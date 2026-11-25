"""The check command and the supervising runner (pecron_app.runner)."""

import io
import json
import os
import re
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

from pecron_app import runner as runner_mod
from pecron_app.broker import MqttSettings, MqttUnavailable
from pecron_app.runner import Runner, check

FAKE = str(Path(__file__).parent / "fake_monitor.py")
AUTH_KEY = "c2VjcmV0LWF1dGgta2V5IQ=="
TOKEN = "supervisor-token-secret"
TSL = {"ac_switch_hm": {"id": 40, "type": "BOOL", "access": "RW"}}


def options(**overrides):
    o = {
        "connection_mode": "Automatic",
        "account": {"email": "me@example.com", "password": "account-pw-secret", "region": "na"},
        "devices": [
            {
                "model": "F3000LFP",
                "product_key": "pk",
                "device_key": "a1b2c3d4e5f6",
                "lan_ip": "192.0.2.10",
                "auth_key": AUTH_KEY,
            }
        ],
        "polling": {"poll_interval": 70},
        "mqtt": {"host": "broker", "password": "mqtt-pw-secret"},
        "energy": {},
        "restore_outputs_after_shutdown": {"enabled": False},
        "log_level": "info",
    }
    o.update(overrides)
    return o


class Env:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.options_path = tmp_path / "options.json"
        self.setup_path = tmp_path / "pecron-setup.yaml"
        self.config_path = tmp_path / "pecron-monitor.yaml"
        self.plan_path = tmp_path / "plan.json"
        self.stream = io.StringIO()
        self.write_options(options())
        self.write_setup({"a1b2c3d4e5f6": TSL})

    def write_options(self, opts):
        self.options_path.write_text(json.dumps(opts))

    def write_setup(self, tsl_by_key):
        import yaml

        devices = [{"device_key": k, "tsl_cache": v} for k, v in tsl_by_key.items()]
        self.setup_path.write_text(yaml.safe_dump({"devices": devices}))

    def plan(self, *runs):
        self.plan_path.write_text(json.dumps(list(runs)))

    @property
    def starts(self):
        counter = Path(str(self.plan_path) + ".n")
        return int(counter.read_text()) if counter.exists() else 0

    @property
    def child_args(self):
        return json.loads(Path(str(self.plan_path) + ".args").read_text())

    def runner(self, **kw):
        return Runner(
            options_path=str(self.options_path),
            setup_path=str(self.setup_path),
            config_path=str(self.config_path),
            command=[sys.executable, FAKE],
            environ={
                "FAKE_PLAN": str(self.plan_path),
                "SUPERVISOR_TOKEN": TOKEN,
                "PATH": os.environ["PATH"],
                "PECRON_APP_VERSION": "1.2.3",
            },
            stream=self.stream,
            **kw,
        )

    @property
    def out(self):
        return self.stream.getvalue()


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


class Waits:
    """Replaces Runner.stopping: records delays, stops after `limit` waits."""

    def __init__(self, limit):
        self.limit = limit
        self.delays = []
        self._set = False

    def is_set(self):
        return self._set

    def set(self):
        self._set = True

    def wait(self, delay):
        self.delays.append(delay)
        if len(self.delays) >= self.limit:
            self._set = True
        return self._set


def run_with_waits(r, limit):
    r.stopping = Waits(limit)
    assert r.run() == 0
    return r.stopping.delays


def retry_lines(out):
    return re.findall(r"WARNING Retry (\d+) in (\d+) s", out)


# --- backoff ---------------------------------------------------------------


def test_backoff_sequence_and_retry_on_any_exit_code(env):
    env.plan({"exit": 0}, {"exit": 3})
    delays = run_with_waits(env.runner(), 9)
    assert delays == [5, 10, 20, 40, 80, 160, 300, 300, 300]
    assert env.starts == 9
    assert "pecron-monitor exited with code 0" in env.out
    assert "pecron-monitor exited with code 3" in env.out
    assert retry_lines(env.out)[:3] == [("1", "5"), ("2", "10"), ("3", "20")]


def test_backoff_resets_after_long_run(env):
    env.plan({"exit": 1}, {"exit": 1}, {"exit": 1, "sleep": 0.4}, {"exit": 1})
    delays = run_with_waits(env.runner(reset_after=0.3), 4)
    assert delays == [5, 10, 5, 10]


def test_mqtt_unavailable_is_retried(env, monkeypatch):
    calls = []

    def flaky(options, environ):
        calls.append(1)
        if len(calls) < 3:
            raise MqttUnavailable("The Home Assistant MQTT service is not available (HTTP 400).")
        return MqttSettings("broker")

    monkeypatch.setattr(runner_mod, "resolve_mqtt", flaky)
    env.plan({"exit": 1})
    delays = run_with_waits(env.runner(), 3)
    assert delays == [5, 10, 20]
    assert env.out.count("MQTT service is not available") == 2
    assert env.starts == 1


def test_config_error_exits_without_child(env):
    env.write_options(options(devices=[]))
    env.plan({"exit": 0})
    assert env.runner().run() == 1
    assert "No devices are configured" in env.out
    assert env.starts == 0


def test_setup_file_error_exits(env):
    env.setup_path.write_text("devices: [")
    assert env.runner().run() == 1
    assert "not valid YAML" in env.out


def test_child_gets_args_env_and_config(env):
    env.plan({"exit": 1})
    run_with_waits(env.runner(), 1)
    args = env.child_args
    assert args["args"] == [
        "--config",
        str(env.config_path),
        "--homeassistant",
        "--no-ble",
    ]
    assert args["env"]["PYTHONUNBUFFERED"] == "1"
    assert args["env"]["PECRON_STATE_PATH"] == "/data/pecron-restore.json"
    assert args["env"]["PECRON_ENERGY_STATE_PATH"] == "/data/pecron-energy.json"
    assert args["env"]["PECRON_RULE_STATE_PATH"] == "/data/pecron-rules.json"
    assert oct(env.config_path.stat().st_mode & 0o777) == "0o600"


def test_banner_once_per_container_start(env):
    env.plan({"exit": 1})
    run_with_waits(env.runner(), 3)
    assert env.out.count("Pecron Monitor HA App 1.2.3, pecron-monitor ") == 1
    assert env.out.count("Connection mode: Automatic; devices: F3000LFP (A1B2C3D4E5F6)") == 1


# --- stopping --------------------------------------------------------------


def _stop_later(r, after):
    threading.Timer(after, r.stop).start()


def test_stop_during_run_terminates_child(env):
    env.plan({"sleep": 30})
    r = env.runner()
    _stop_later(r, 0.5)
    started = time.monotonic()
    assert r.run() == 0
    assert time.monotonic() - started < 5
    assert "Bridge offline published" in env.out
    assert "Retry" not in env.out


def test_stop_kills_child_ignoring_sigterm(env):
    env.plan({"sleep": 30, "on_term": "ignore"})
    r = env.runner(stop_grace=0.5)
    _stop_later(r, 0.5)
    started = time.monotonic()
    assert r.run() == 0
    assert time.monotonic() - started < 5


def test_stop_during_delay_exits_at_once(env):
    env.plan({"exit": 1})
    r = env.runner(delays=(30,))
    _stop_later(r, 0.5)
    started = time.monotonic()
    assert r.run() == 0
    assert time.monotonic() - started < 5
    assert env.starts == 1


@pytest.mark.parametrize("phase", ["run", "delay"])
def test_real_sigterm(env, phase):
    env.plan({"sleep": 30} if phase == "run" else {"exit": 1})
    r = env.runner(delays=(30,))
    previous = signal.signal(signal.SIGTERM, r.stop)
    try:
        threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGTERM)).start()
        started = time.monotonic()
        assert r.run() == 0
        assert time.monotonic() - started < 5
    finally:
        signal.signal(signal.SIGTERM, previous)


# --- output ----------------------------------------------------------------


def test_redaction_of_app_and_library_output(env):
    env.plan(
        {
            "exit": 1,
            "lines": [
                "12:00:00 INFO login me@example.com / account-pw-secret",
                f"12:00:00 INFO key {AUTH_KEY} broker mqtt-pw-secret token {TOKEN}",
            ],
        }
    )
    run_with_waits(env.runner(), 1)
    for secret in ("me@example.com", "account-pw-secret", AUTH_KEY, "mqtt-pw-secret", TOKEN):
        assert secret not in env.out
    assert "login *** / ***" in env.out


def test_service_mqtt_password_redacted(env, monkeypatch):
    monkeypatch.setattr(
        runner_mod,
        "resolve_mqtt",
        lambda o, e: MqttSettings("core-mosquitto", 1883, "addons", "svc-secret"),
    )
    env.plan({"exit": 1, "lines": ["12:00:00 ERROR auth svc-secret failed"]})
    run_with_waits(env.runner(), 1)
    assert "svc-secret" not in env.out


def test_level_filter_with_continuations(env):
    env.write_options(options(log_level="warning"))
    env.plan(
        {
            "exit": 1,
            "lines": [
                "pre-log print line",
                "12:00:00 INFO hidden info",
                "hidden continuation of info",
                "12:00:00 WARNING shown warning",
                "  shown continuation of warning",
                "12:00:00 DEBUG hidden debug",
                "Traceback (most recent call last):",
                "  hidden frame",
                "ValueError: hidden traceback end",
                "12:00:00 ERROR shown error",
            ],
        }
    )
    run_with_waits(env.runner(), 1)
    out = env.out
    for shown in ("pre-log print line", "shown warning", "shown continuation", "shown error"):
        assert shown in out
    assert "hidden" not in out
    assert "Retry 1 in 5 s" in out  # retry lines always print
    assert "Pecron Monitor HA App" not in out  # INFO app lines are filtered too


@pytest.mark.parametrize(
    "level,shown",
    [
        ("notice", ["WARNING", "ERROR"]),
        ("fatal", []),
        ("error", ["ERROR"]),
        ("debug", ["DEBUG", "INFO", "WARNING", "ERROR"]),
    ],
)
def test_library_level_mapping(env, level, shown):
    env.write_options(options(log_level=level))
    env.plan(
        {
            "exit": 1,
            "lines": [f"12:00:00 {lvl} lib-{lvl}" for lvl in ("DEBUG", "INFO", "WARNING", "ERROR")]
            + ["12:00:00 CRITICAL lib-CRITICAL"],
        }
    )
    run_with_waits(env.runner(), 1)
    for lvl in ("DEBUG", "INFO", "WARNING", "ERROR"):
        assert (f"lib-{lvl}" in env.out) is (lvl in shown)
    assert "lib-CRITICAL" in env.out


def test_last_error_line_in_retry_message(env):
    env.write_options(options(log_level="fatal"))
    env.plan(
        {
            "exit": 1,
            "lines": [
                "12:00:00 ERROR first",
                "12:00:00 ERROR socket closed",
                "12:00:00 INFO later info",
            ],
        },
        {
            "exit": 1,
            "lines": [
                "12:00:00 ERROR earlier",
                "Traceback (most recent call last):",
                '  File "x.py", line 1',
                "OSError: disk gone",
            ],
        },
        {"exit": 0},
    )
    run_with_waits(env.runner(), 3)
    assert "exited with code 1; last error: socket closed" in env.out
    assert "exited with code 1; last error: OSError: disk gone" in env.out
    assert re.search(r"exited with code 0\n", env.out)


def test_login_rejected(env):
    env.plan(
        {
            "exit": 1,
            "lines": [
                "Traceback (most recent call last):",
                '  File "cloud_api.py", line 58, in login',
                "RuntimeError: Login failed (code 4011): bad password",
            ],
        }
    )
    delays = run_with_waits(env.runner(), 2)
    assert delays == [300, 300]
    assert "Pecron login was rejected: check Email, Password and Region" in env.out
    assert retry_lines(env.out)[0] == ("1", "300")


def test_login_rejected_not_after_fallbacks(env):
    env.plan(
        {
            "exit": 1,
            "lines": [
                "12:00:00 WARNING Login failed (code 5000) on primary domain, trying fallback",
                "12:00:00 WARNING Cloud login failed (Login failed (code 4011): x), falling back "
                "to offline mode",
                "12:00:00 ERROR Something unrelated crashed",
            ],
        }
    )
    delays = run_with_waits(env.runner(), 1)
    assert delays == [5]
    assert "login was rejected" not in env.out


def test_ready_line_once_per_child_start(env):
    marker = "12:00:00 INFO Published Home Assistant discovery configs"
    env.plan({"exit": 1, "lines": [marker, marker]})
    run_with_waits(env.runner(), 2)
    assert env.out.count("Ready: entities are under Settings > Devices & services > MQTT") == 2
    assert "Pecron F3000LFP (A1B2C3D4E5F6)" in env.out


# --- check -----------------------------------------------------------------


def run_check(env):
    return check(str(env.options_path), str(env.setup_path), {}, env.stream)


def test_check_ok_logs_tsl_per_device(env):
    opts = options()
    opts["devices"].append({**opts["devices"][0], "device_key": "0a0b0c0d0e0f"})
    env.write_options(opts)
    assert run_check(env) == 0
    assert "INFO F3000LFP (A1B2C3D4E5F6): TSL from the setup file, 1 properties" in env.out
    assert "INFO F3000LFP (0A0B0C0D0E0F): no TSL in the setup file" in env.out
    assert "WARNING Device 2" in env.out  # Automatic without TSL


def test_check_reports_file_and_option_errors_together(env):
    env.setup_path.write_text("devices: [")
    env.write_options(options(polling={"poll_interval": 10}, log_level="fatal"))
    assert run_check(env) == 1
    assert "not valid YAML" in env.out
    assert "Poll interval is 10 s" in env.out
    assert "account-pw-secret" not in env.out


def test_check_unreadable_options(env):
    env.options_path.write_text("{not json")
    assert run_check(env) == 1
    assert "Cannot read the app options" in env.out


# --- contract with the pinned library ----------------------------------------


def test_library_still_logs_the_markers():
    pytest.importorskip("monitor")
    import cloud_api
    import ha_discovery

    assert runner_mod.READY_MARKER in Path(ha_discovery.__file__).read_text()
    assert runner_mod.LOGIN_REJECTED_MARKER in Path(cloud_api.__file__).read_text()


# --- review regressions ------------------------------------------------------


def test_trimmed_secrets_are_redacted(env):
    opts = options()
    opts["account"]["email"] = "  me@example.com "
    opts["devices"][0]["auth_key"] = f" {AUTH_KEY}  "
    env.write_options(opts)
    env.plan({"exit": 1, "lines": [f"12:00:00 INFO login me@example.com key {AUTH_KEY}"]})
    run_with_waits(env.runner(), 1)
    assert "me@example.com" not in env.out and AUTH_KEY not in env.out


def test_unlevelled_lines_shown_at_start_of_each_child(env):
    env.write_options(options(log_level="info"))
    env.plan(
        {"exit": 1, "lines": ["12:00:00 DEBUG filtered", "filtered continuation"]},
        {"exit": 1, "lines": ["Traceback (most recent call last):", "ImportError: boom"]},
    )
    run_with_waits(env.runner(), 2)
    assert "filtered" not in env.out
    assert "ImportError: boom" in env.out


def test_print_after_traceback_is_not_the_last_error(env):
    env.plan(
        {
            "exit": 1,
            "lines": [
                "Traceback (most recent call last):",
                "OSError: disk gone",
                "Goodbye from print",
            ],
        }
    )
    run_with_waits(env.runner(), 1)
    assert "last error: OSError: disk gone" in env.out


def test_stop_during_broker_lookup_logs_no_retry(env, monkeypatch):
    r = env.runner()

    def slow(options, environ):
        r._stop()
        raise MqttUnavailable("service gone")

    monkeypatch.setattr(runner_mod, "resolve_mqtt", slow)
    assert r.run() == 0
    assert "Retry" not in env.out


def test_unexpected_error_is_reported_redacted(env, monkeypatch):
    def boom(config, path):
        raise OSError(f"cannot write with {AUTH_KEY}")

    monkeypatch.setattr(runner_mod.cfg, "write_config", boom)
    assert env.runner().run() == 1
    assert "ERROR Unexpected error:" in env.out
    assert "OSError: cannot write with ***" in env.out
