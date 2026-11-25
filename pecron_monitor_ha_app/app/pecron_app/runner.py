"""Check the configuration and run pecron-monitor under supervision.

``check`` runs once per container start (s6 oneshot) and reports every error
and warning. ``run`` (s6 longrun) regenerates the library config, starts
``pecron-monitor`` as a child, relays its output redacted and level-filtered,
and restarts it with increasing delays until asked to stop.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Mapping, Sequence
from importlib import metadata
from typing import TextIO

from . import config as cfg
from .broker import MqttUnavailable, resolve_mqtt
from .config import ConfigError, normalize_device_key
from .tsl import load_tsl

OPTIONS_PATH = "/data/options.json"
SETUP_PATH = "/config/" + cfg.SETUP_FILE_NAME
STATE_FILES = {
    "PECRON_STATE_PATH": "/data/pecron-restore.json",
    "PECRON_ENERGY_STATE_PATH": "/data/pecron-energy.json",
    "PECRON_RULE_STATE_PATH": "/data/pecron-rules.json",
}

DELAYS = (5, 10, 20, 40, 80, 160, 300)
RESET_AFTER = 600  # a child that ran this long starts the delays over
STOP_GRACE = 10  # seconds the child gets after SIGTERM before SIGKILL

READY_MARKER = "Published Home Assistant discovery configs"
LOGIN_REJECTED_MARKER = "Login failed (code"

# Option log_level -> lowest Python level shown. "notice" has no Python
# equivalent: library lines then behave as at "warning".
THRESHOLDS = {
    "trace": logging.DEBUG,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}
_LIBRARY_LINE = re.compile(r"^\d\d:\d\d:\d\d (DEBUG|INFO|WARNING|ERROR|CRITICAL) (.*)$")


class Output:
    """Writes app and library lines in one format, redacted and level-filtered."""

    def __init__(self, log_level: str = "info", stream: TextIO | None = None):
        self.threshold = THRESHOLDS.get(log_level, logging.INFO)
        self.stream = stream or sys.stdout
        self.secrets: list[str] = []
        self._show_unlevelled = True  # decision of the previous library line

    def add_secrets(self, *values: str | None) -> None:
        # Also the trimmed form: validate() trims email and auth keys before the
        # library sees (and may log) them.
        new = {form for v in values if v for form in (v, v.strip()) if form} | set(self.secrets)
        # Longest first, so a secret containing another is replaced whole.
        self.secrets = sorted(new, key=len, reverse=True)

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "***")
        return text

    def _write(self, line: str) -> None:
        self.stream.write(self.redact(line) + "\n")
        self.stream.flush()

    def log(self, level: int, message: str, always: bool = False) -> None:
        if always or level >= self.threshold:
            stamp = time.strftime("%H:%M:%S")
            self._write(f"{stamp} {logging.getLevelName(level)} {message}")

    def info(self, message: str) -> None:
        self.log(logging.INFO, message)

    def warning(self, message: str, always: bool = False) -> None:
        self.log(logging.WARNING, message, always)

    def error(self, message: str) -> None:
        self.log(logging.ERROR, message, always=True)

    def new_child(self) -> None:
        """Unlevelled lines before a new child's first levelled line are shown."""
        self._show_unlevelled = True

    def library(self, line: str) -> None:
        match = _LIBRARY_LINE.match(line)
        if match:
            self._show_unlevelled = logging.getLevelName(match[1]) >= self.threshold
        if self._show_unlevelled:
            self._write(line)


class _OutputHandler(logging.Handler):
    """Routes the package's ``logging`` calls (e.g. in broker) through Output."""

    def __init__(self, output: Output):
        super().__init__()
        self.output = output

    def emit(self, record: logging.LogRecord) -> None:
        self.output.log(record.levelno, record.getMessage())


def _attach_logging(output: Output) -> None:
    logger = logging.getLogger("pecron_app")
    logger.handlers[:] = [_OutputHandler(output)]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False


def _secrets(options: dict, environ: Mapping[str, str]) -> list[str | None]:
    account = options.get("account") or {}
    devices = options.get("devices") or []
    return [
        account.get("email"),
        account.get("password"),
        (options.get("mqtt") or {}).get("password"),
        environ.get("SUPERVISOR_TOKEN"),
        *(d.get("auth_key") for d in devices if isinstance(d, dict)),
    ]


def _device_label(device: dict) -> str:
    return f"{device.get('model', '?')} ({normalize_device_key(device.get('device_key', ''))})"


def _open(options_path: str, environ: Mapping[str, str], stream: TextIO | None):
    """Load the options and set up output at their log level; None if unreadable."""
    try:
        options = cfg.load_options(options_path)
    except (OSError, ValueError, ConfigError) as e:
        Output(stream=stream).error(f"Cannot read the app options ({type(e).__name__}).")
        return None
    output = Output(options.get("log_level", "info"), stream)
    output.add_secrets(*_secrets(options, environ))
    _attach_logging(output)
    return output, options


def _load_tsl(setup_path: str) -> tuple[dict | None, list[str]]:
    """Load the setup file; return (tsl or None, file errors)."""
    try:
        return load_tsl(setup_path), []
    except ConfigError as e:
        return None, e.errors


def _report_errors(output: Output, errors: Sequence[str]) -> None:
    output.error("The configuration is invalid. Fix the following and restart the app:")
    for message in errors:
        output.error(f"- {message}")


def check(
    options_path: str = OPTIONS_PATH,
    setup_path: str = SETUP_PATH,
    environ: Mapping[str, str] = os.environ,
    stream: TextIO | None = None,
) -> int:
    """Validate everything once and print all errors and warnings. Returns the exit code."""
    opened = _open(options_path, environ, stream)
    if opened is None:
        return 1
    output, options = opened
    try:
        return _check(output, options, setup_path)
    except Exception:
        _report_crash(output)
        return 1


def _report_crash(output: Output) -> None:
    output.error("Unexpected error:")
    for line in traceback.format_exc().splitlines():
        output.error(line)


def _check(output: Output, options: dict, setup_path: str) -> int:
    tsl, errors = _load_tsl(setup_path)
    warnings: list[str] = []
    try:
        warnings = cfg.validate(options, tsl)
    except ConfigError as e:
        errors += e.errors
        warnings = e.warnings
    for message in warnings:
        output.warning(message)
    if errors:
        _report_errors(output, errors)
        return 1

    for device in options["devices"]:
        props = (tsl or {}).get(device["device_key"].lower())
        label = _device_label(device)
        if props:
            output.info(f"{label}: TSL from the setup file, {len(props)} properties")
        else:
            output.info(f"{label}: no TSL in the setup file")
    return 0


class Runner:
    """Supervises one pecron-monitor child at a time."""

    def __init__(
        self,
        options_path: str = OPTIONS_PATH,
        setup_path: str = SETUP_PATH,
        config_path: str = cfg.LIBRARY_CONFIG_PATH,
        command: Sequence[str] = ("pecron-monitor",),
        environ: Mapping[str, str] = os.environ,
        stream: TextIO | None = None,
        delays: Sequence[float] = DELAYS,
        reset_after: float = RESET_AFTER,
        stop_grace: float = STOP_GRACE,
    ):
        self.options_path = options_path
        self.setup_path = setup_path
        self.config_path = config_path
        self.command = list(command)
        self.environ = dict(environ)
        self.delays = delays
        self.reset_after = reset_after
        self.stop_grace = stop_grace
        self.output = Output(stream=stream)
        self.stopping = threading.Event()
        # Read by the signal handler: no lock, it could interrupt its holder.
        self._child: subprocess.Popen | None = None
        self._bannered = False  # version banner: once per container start

    # --- signals ---------------------------------------------------------

    def stop(self, *_args) -> None:
        """Signal handler: stop the child (SIGTERM, SIGKILL after the grace) and exit.

        Runs on a thread: Event.set() takes a lock the interrupted main thread
        may be holding inside Event.wait().
        """
        threading.Thread(target=self._stop, daemon=True).start()

    def _stop(self) -> None:
        self.stopping.set()
        child = self._child
        if child is not None and child.poll() is None:
            child.terminate()
            timer = threading.Timer(self.stop_grace, self._kill, args=(child,))
            timer.daemon = True
            timer.start()

    @staticmethod
    def _kill(child: subprocess.Popen) -> None:
        if child.poll() is None:
            child.kill()

    # --- main loop -------------------------------------------------------

    def _prepare(self) -> tuple[dict, list[str]]:
        """Load, validate, resolve the broker, write the library config."""
        options = cfg.load_options(self.options_path)
        self.output.add_secrets(*_secrets(options, self.environ))
        tsl, errors = _load_tsl(self.setup_path)
        try:
            cfg.validate(options, tsl)  # pecron-check already printed the warnings
        except ConfigError as e:
            raise ConfigError(errors + e.errors) from None
        if errors:
            raise ConfigError(errors)
        if not self._bannered:
            self._banner(options)
            self._bannered = True
        mqtt = resolve_mqtt(options, self.environ)
        self.output.add_secrets(mqtt.password)
        cfg.write_config(cfg.build_library_config(options, mqtt, tsl), self.config_path)
        return options, cfg.library_args(options, self.config_path)

    def _banner(self, options: dict) -> None:
        try:
            library = metadata.version("pecron-monitor")
        except metadata.PackageNotFoundError:
            library = "unknown"
        app = self.environ.get("PECRON_APP_VERSION", "dev")
        devices = ", ".join(_device_label(d) for d in options["devices"])
        self.output.info(f"Pecron Monitor HA App {app}, pecron-monitor {library}")
        self.output.info(f"Connection mode: {options['connection_mode']}; devices: {devices}")

    def _start_child(self, args: list[str]) -> subprocess.Popen:
        env = {**self.environ, "PYTHONUNBUFFERED": "1", **STATE_FILES}
        self._child = subprocess.Popen(
            [*self.command, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            env=env,
        )
        if self.stopping.is_set():  # a signal arrived before _child was set
            self._stop()
        return self._child

    def _relay(self, child: subprocess.Popen, options: dict) -> str | None:
        """Relay child output until EOF; return its last error line (redacted)."""
        last_error = None
        in_traceback = False
        ready = False
        self.output.new_child()
        assert child.stdout is not None
        for raw in child.stdout:
            line = raw.rstrip("\n")
            match = _LIBRARY_LINE.match(line)
            if match:
                in_traceback = False
                if match[1] in ("ERROR", "CRITICAL"):
                    last_error = match[2]
            elif line.startswith("Traceback (most recent call last)"):
                in_traceback = True
            elif in_traceback and line and not line[0].isspace():
                last_error = line  # the exception line ends the traceback
                in_traceback = False
            self.output.library(line)
            if not ready and READY_MARKER in line:
                ready = True
                names = ", ".join(f"Pecron {_device_label(d)}" for d in options["devices"])
                self.output.info(
                    "Ready: entities are under Settings > Devices & services > MQTT, on devices "
                    f"named {names}. Values appear once each device responds."
                )
        child.wait()
        return self.output.redact(last_error) if last_error else None

    def run(self) -> int:
        opened = _open(self.options_path, self.environ, self.output.stream)
        if opened is None:
            return 1
        self.output = opened[0]
        try:
            return self._loop()
        except Exception:
            _report_crash(self.output)
            return 1

    def _loop(self) -> int:
        step = 0  # index into the delays
        retry = 0  # retries since the last reset, for the log
        while not self.stopping.is_set():
            ran_for = 0.0
            try:
                options, args = self._prepare()
            except ConfigError as e:
                _report_errors(self.output, e.errors)
                return 1
            except MqttUnavailable as e:
                cause = str(e)
                login_rejected = False
            else:
                if self.stopping.is_set():
                    break
                started = time.monotonic()
                child = self._start_child(args)
                last_error = self._relay(child, options)
                ran_for = time.monotonic() - started
                code = child.returncode
                cause = (
                    f"pecron-monitor was killed by signal {-code}"
                    if code < 0
                    else f"pecron-monitor exited with code {code}"
                )
                if last_error:
                    cause += f"; last error: {last_error}"
                login_rejected = bool(last_error and LOGIN_REJECTED_MARKER in last_error)
                if login_rejected:
                    cause += (
                        ". The Pecron login was rejected: check Email, Password and Region "
                        "under Pecron account."
                    )

            if self.stopping.is_set():
                break
            if ran_for >= self.reset_after:
                step = retry = 0
            if login_rejected:  # retrying soon cannot help
                step = len(self.delays) - 1
            delay = self.delays[min(step, len(self.delays) - 1)]
            step += 1
            retry += 1
            self.output.warning(cause, always=True)
            self.output.warning(f"Retry {retry} in {delay:g} s", always=True)
            if self.stopping.wait(delay):
                break
        return 0


def run() -> int:
    runner = Runner()
    signal.signal(signal.SIGTERM, runner.stop)
    signal.signal(signal.SIGINT, runner.stop)
    return runner.run()
