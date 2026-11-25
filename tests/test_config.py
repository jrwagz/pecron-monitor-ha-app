"""Validation and library config generation (pecron_app.config)."""

import copy
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from pecron_app import config as cfg
from pecron_app.broker import MqttSettings
from pecron_app.config import ConfigError

APP = Path(__file__).resolve().parent.parent / "pecron_monitor_ha_app"
MQTT = MqttSettings("core-mosquitto", 1883, "addons", "brokerpw")
AUTH_KEY = "c2VjcmV0LWF1dGgta2V5IQ=="  # base64 of "secret-auth-key!"


def device(**overrides):
    d = {
        "model": "F3000LFP",
        "product_key": "pk123",
        "device_key": "a1b2c3d4e5f6",
        "lan_ip": "192.168.1.50",
        "auth_key": AUTH_KEY,
    }
    d.update(overrides)
    return {k: v for k, v in d.items() if v is not None}


def options(mode="Automatic", devices=None, **groups):
    o = {
        "connection_mode": mode,
        "account": {"email": "me@example.com", "password": "pw", "region": "na"},
        "devices": [device()] if devices is None else devices,
        "polling": {"poll_interval": 70},
        "mqtt": {},
        "energy": {"energy_sensors": False},
        "restore_outputs_after_shutdown": {"enabled": False},
        "log_level": "info",
    }
    for group, value in groups.items():
        o[group] = value
    return o


def errors_of(opts, tsl=None):
    with pytest.raises(ConfigError) as exc:
        cfg.validate(opts, tsl)
    return exc.value.errors


def one(messages, needle):
    matches = [m for m in messages if needle in m]
    assert len(matches) == 1, (needle, messages)
    return matches[0]


# --- validation errors -----------------------------------------------------


def test_valid_options_have_no_warnings():
    assert cfg.validate(options(), None) == []


def test_no_devices():
    msg = one(errors_of(options(devices=[])), "No devices")
    assert "Configuration tab" in msg
    assert "pecron-setup.yaml" not in msg


def test_no_devices_local_only_names_setup_file_and_folder():
    msg = one(errors_of(options("Local only", devices=[])), "No devices")
    assert "pecron-setup.yaml" in msg
    assert "local_pecron_monitor_ha_app" in msg


@pytest.mark.parametrize(
    "field,label",
    [
        ("model", "Model"),
        ("product_key", "Product key"),
        ("device_key", "Device key"),
    ],
)
def test_blank_device_fields(field, label):
    one(errors_of(options(devices=[device(**{field: "   "})])), f"{label} is empty")


def test_duplicate_device_key_case_insensitive():
    devices = [device(), device(device_key="A1B2C3D4E5F6", lan_ip="192.168.1.51")]
    msg = one(errors_of(options(devices=devices)), "also used by")
    assert "Device 2" in msg and "Device 1" in msg


@pytest.mark.parametrize("mode", ["Automatic", "Cloud only", "Cloud REST only"])
@pytest.mark.parametrize("key,label", [("email", "Email"), ("password", "Password")])
def test_account_required_outside_local_only(mode, key, label):
    o = options(mode)
    o["account"][key] = ""
    one(errors_of(o), f"{label} (Pecron account) is required")


def test_account_not_required_in_local_only():
    o = options("Local only", account={})
    assert cfg.validate(o, None) == []


@pytest.mark.parametrize("mode", ["Automatic", "Cloud only", "Cloud REST only"])
def test_poll_interval_minimum_in_cloud_modes(mode):
    o = options(mode, polling={"poll_interval": 62}, mqtt={"stale_after": 600})
    msg = one(errors_of(o), "Poll interval")
    assert "63" in msg and "70" in msg and "Local only" in msg


def test_short_poll_interval_allowed_in_local_only():
    assert cfg.validate(options("Local only", polling={"poll_interval": 5}), None) == []


@pytest.mark.parametrize(
    "field,label", [("lan_ip", "LAN IP address"), ("auth_key", "Local auth key")]
)
def test_local_only_requires_lan_ip_and_auth_key(field, label):
    msg = one(errors_of(options("Local only", devices=[device(**{field: ""})])), label)
    assert "Show unused optional configuration options" in msg


def test_auth_key_must_be_base64():
    msg = one(errors_of(options(devices=[device(auth_key="not base64!")])), "base64")
    assert "not base64!" not in msg


def test_all_errors_collected_with_warnings():
    o = options(polling={"poll_interval": 10}, devices=[device(model="", ble=True)])
    o["account"]["email"] = ""
    with pytest.raises(ConfigError) as exc:
        cfg.validate(o, None)
    assert len(exc.value.errors) == 3
    assert any("Bluetooth" in w for w in exc.value.warnings)


# --- warnings --------------------------------------------------------------


def test_poll_interval_close_to_minimum_warns():
    one(cfg.validate(options(polling={"poll_interval": 65}), None), "close to the cloud minimum")


def test_ble_warns():
    one(cfg.validate(options(devices=[device(ble_address="AA:BB")]), None), "not supported")


@pytest.mark.parametrize("mode", ["Local only", "Cloud REST only"])
def test_restore_without_cloud_mqtt_warns(mode):
    o = options(mode, restore_outputs_after_shutdown={"enabled": True})
    one(cfg.validate(o, None), "no effect")


def test_restore_with_cloud_mqtt_is_quiet():
    o = options("Cloud only", restore_outputs_after_shutdown={"enabled": True})
    assert cfg.validate(o, None) == []


def test_stale_after_below_three_polls_warns():
    one(cfg.validate(options(polling={"poll_interval": 300}), None), "Unavailable after is 600")
    one(cfg.validate(options(mqtt={"stale_after": 200}), None), "Unavailable after is 200")


def test_automatic_auth_key_without_lan_ip_warns():
    msg = one(cfg.validate(options(devices=[device(lan_ip=None)]), None), "local transport")
    assert AUTH_KEY not in msg


def test_device_key_not_hex12_warns():
    one(cfg.validate(options(devices=[device(device_key="abc")]), None), "12 hexadecimal")


def test_invalid_dotted_ip_warns_but_hostname_is_fine():
    one(cfg.validate(options(devices=[device(lan_ip="192.168.1.300")]), None), "IPv4")
    assert cfg.validate(options(devices=[device(lan_ip="pecron.lan")]), None) == []


@pytest.mark.parametrize("mode", ["Local only", "Automatic"])
def test_unknown_model_warns_with_list(mode):
    msg = one(cfg.validate(options(mode, devices=[device(model="f3000lfp")]), None), "not a model")
    assert "F1000LFP" in msg and "F3000LFP" in msg


def test_unknown_model_quiet_in_cloud_modes():
    assert cfg.validate(options("Cloud only", devices=[device(model="X9")]), None) == []


def test_messages_name_device_by_model_and_normalized_key():
    msg = one(cfg.validate(options(devices=[device(ble=True)]), None), "not supported")
    assert msg.startswith("Device 1 (F3000LFP, device key A1B2C3D4E5F6)")


def test_messages_never_contain_secrets():
    o = options(devices=[device(auth_key="bad key!", ble=True)], polling={"poll_interval": 1})
    o["account"]["password"] = "hunter2-secret"
    with pytest.raises(ConfigError) as exc:
        cfg.validate(o, None)
    for message in exc.value.errors + exc.value.warnings:
        assert "hunter2-secret" not in message and "bad key!" not in message


# --- normalization ---------------------------------------------------------


def test_validate_trims_strings_but_not_passwords():
    o = options(devices=[device(model=" F3000LFP ", auth_key=f" {AUTH_KEY} ")])
    o["account"].update(email=" me@example.com ", password=" pw ")
    o["mqtt"] = {"host": " broker ", "password": " mpw "}
    cfg.validate(o, None)
    assert o["devices"][0]["model"] == "F3000LFP"
    assert o["devices"][0]["auth_key"] == AUTH_KEY
    assert o["account"]["email"] == "me@example.com"
    assert o["account"]["password"] == " pw "
    assert o["mqtt"] == {"host": "broker", "password": " mpw "}


def test_missing_groups_get_defaults():
    o = {"connection_mode": "Local only", "devices": [device()]}
    assert cfg.validate(o, None) == []
    assert o["account"]["region"] == "na"
    assert o["polling"]["poll_interval"] == 70


def test_normalize_device_key():
    assert cfg.normalize_device_key(" a1b2c3d4e5f6 ") == "A1B2C3D4E5F6"
    assert cfg.normalize_device_key("not-hex-key") == "not-hex-key"


def test_app_config_folder():
    assert cfg.app_config_folder({"HOSTNAME": "a0d7b954-pecron-monitor-ha-app"}) == (
        "a0d7b954_pecron_monitor_ha_app"
    )
    assert "_pecron_monitor_ha_app" in cfg.app_config_folder({"HOSTNAME": "laptop"})


def test_labels_match_translations():
    tr = yaml.safe_load((APP / "translations" / "en.yaml").read_text())["configuration"]
    for path, label in cfg.LABELS.items():
        group, _, key = path.partition(".")
        entry = tr[group]
        if key:
            entry = entry["fields"][key]
        assert entry["name"] == label, path


# --- library config --------------------------------------------------------


def build(mode, **kw):
    o = options(mode, **kw)
    cfg.validate(o, None)
    return o, cfg.build_library_config(o, MQTT, None)


def test_automatic_config():
    o, c = build("Automatic")
    assert c == {
        "email": "me@example.com",
        "password": "pw",
        "region": "na",
        "devices": [
            {
                "name": "F3000LFP",
                "product_key": "pk123",
                "device_key": "A1B2C3D4E5F6",
                "lan_ip": "192.168.1.50",
                "auth_key": AUTH_KEY,
            }
        ],
        "poll_interval": 70,
        "homeassistant": {
            "enabled": True,
            "mqtt_host": "core-mosquitto",
            "mqtt_port": 1883,
            "mqtt_user": "addons",
            "mqtt_password": "brokerpw",
            "energy_sensors": False,
        },
        "restore_outputs_after_shutdown": {"enabled": False},
    }
    assert cfg.library_args(o) == [
        "--config",
        "/data/pecron-monitor.yaml",
        "--homeassistant",
        "--no-ble",
    ]


def test_local_only_config_omits_account():
    o, c = build("Local only")
    assert "email" not in c and "password" not in c
    assert c["region"] == "na"
    assert c["devices"][0]["auth_key"] == AUTH_KEY
    assert cfg.library_args(o)[-1] == "--local"


@pytest.mark.parametrize(
    "mode,flag", [("Cloud only", "--nolocal"), ("Cloud REST only", "--rest-only")]
)
def test_cloud_modes_omit_local_fields(mode, flag):
    o, c = build(mode)
    assert "lan_ip" not in c["devices"][0] and "auth_key" not in c["devices"][0]
    assert c["email"] == "me@example.com"
    assert cfg.library_args(o)[-1] == flag


def test_automatic_auth_key_without_lan_ip_omitted():
    _, c = build("Automatic", devices=[device(lan_ip=None)])
    assert "auth_key" not in c["devices"][0]


@pytest.mark.parametrize("level,verbose", [("trace", True), ("debug", True), ("info", False)])
def test_verbose_flag(level, verbose):
    o = options(log_level=level)
    assert ("--verbose" in cfg.library_args(o)) is verbose


def test_unset_and_empty_options_omitted():
    o = options(devices=[device(lan_ip="", ble=True, ble_address="AA")])
    o["mqtt"] = {"discovery_prefix": "", "stale_after": 900}
    o["restore_outputs_after_shutdown"] = {"enabled": True, "shutdown_threshold_voltage": None}
    cfg.validate(o, None)
    c = cfg.build_library_config(o, MqttSettings("h", 1883), None)
    d = c["devices"][0]
    assert set(d) == {"name", "product_key", "device_key"}
    assert c["homeassistant"] == {
        "enabled": True,
        "mqtt_host": "h",
        "mqtt_port": 1883,
        "stale_after": 900,
        "energy_sensors": False,
    }
    assert c["restore_outputs_after_shutdown"] == {"enabled": True}
    for key in ("alerts", "rules", "rule_state", "cloud_retry_interval"):
        assert key not in c


def test_all_optional_settings_mapped():
    o = options(
        polling={
            "poll_interval": 70,
            "cloud_retry_interval": 120,
            "mqtt_reconnect_interval": 30,
            "high_freq_warmup_seconds": 0,
        },
        mqtt={
            "discovery_prefix": "ha",
            "clear_discovery_on_startup": False,
            "retry_interval": 15,
            "stale_after": 700,
        },
        energy={"energy_sensors": True, "energy_max_gap_seconds": 900},
        restore_outputs_after_shutdown={
            "enabled": True,
            "shutdown_threshold_pct": 5,
            "shutdown_threshold_voltage": 48.5,
        },
    )
    cfg.validate(o, None)
    c = cfg.build_library_config(o, MQTT, None)
    assert c["cloud_retry_interval"] == 120
    assert c["mqtt_reconnect_interval"] == 30
    assert c["high_freq_warmup_seconds"] == 0
    ha = c["homeassistant"]
    assert (ha["discovery_prefix"], ha["clear_discovery_on_startup"]) == ("ha", False)
    assert (ha["retry_interval"], ha["stale_after"]) == (15, 700)
    assert (ha["energy_sensors"], ha["energy_max_gap_seconds"]) == (True, 900)
    assert c["restore_outputs_after_shutdown"] == {
        "enabled": True,
        "shutdown_threshold_pct": 5,
        "shutdown_threshold_voltage": 48.5,
    }


def test_tsl_attached_by_normalized_key():
    tsl = {"a1b2c3d4e5f6": {"ac_switch_hm": {"id": 40, "type": "BOOL", "access": "RW"}}}
    o = options()
    cfg.validate(o, tsl)
    c = cfg.build_library_config(o, MQTT, tsl)
    assert c["devices"][0]["tsl_cache"] == tsl["a1b2c3d4e5f6"]


# --- writing ---------------------------------------------------------------

AWKWARD = "a\"b'c\\d:e #f\ng — ünï 🔋"


def test_round_trip_awkward_strings(tmp_path):
    o = options(devices=[device(model=AWKWARD)])
    o["account"]["password"] = AWKWARD
    cfg.validate(o, None)
    c = cfg.build_library_config(o, MqttSettings("h", 1883, "u", AWKWARD), None)
    path = tmp_path / "out.yaml"
    cfg.write_config(c, str(path))
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == c


def test_written_file_is_0600_even_over_0644(tmp_path):
    path = tmp_path / "out.yaml"
    path.write_text("old")
    os.chmod(path, 0o644)
    cfg.write_config({"a": 1}, str(path))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert yaml.safe_load(path.read_text()) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["out.yaml"]


def test_config_error_carries_warnings():
    e = ConfigError(["bad"], ["careful"])
    assert e.errors == ["bad"] and e.warnings == ["careful"]
    assert ConfigError(["x"]).warnings == []


def test_load_options(tmp_path):
    path = tmp_path / "options.json"
    path.write_text('{"connection_mode": "Local only"}')
    assert cfg.load_options(str(path)) == {"connection_mode": "Local only"}
    path.write_text("[]")
    with pytest.raises(ConfigError):
        cfg.load_options(str(path))


# --- contract with the pinned library ----------------------------------------

MODES = ["Automatic", "Local only", "Cloud only", "Cloud REST only"]


@pytest.mark.parametrize("mode", MODES)
def test_library_accepts_generated_config(mode, tmp_path, monkeypatch):
    monitor = pytest.importorskip("monitor")
    for var in ("PECRON_STATE_PATH", "PECRON_ENERGY_STATE_PATH", "PECRON_RULE_STATE_PATH"):
        monkeypatch.setenv(var, str(tmp_path / var))
    o, c = build(mode)
    m = monitor.PecronMonitor(copy.deepcopy(c), no_ble=True, rest_only=mode == "Cloud REST only")
    assert m._check_offline_capable() is (mode in ("Automatic", "Local only"))


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("log_level", ["info", "debug"])
def test_library_cli_accepts_flags(mode, log_level, tmp_path):
    pytest.importorskip("pecron_monitor")
    args = cfg.library_args(options(mode, log_level=log_level))
    args[args.index("--config") + 1] = str(tmp_path / "missing.yaml")
    result = subprocess.run(
        [sys.executable, "-c", "import pecron_monitor; pecron_monitor.main()", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, result.stderr
    assert "Config not found" in result.stdout
