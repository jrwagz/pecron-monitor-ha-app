"""Validate the app options and translate them into the library's config.

Everything here is a pure function except ``load_options`` and
``write_config``. Nothing here may log or print the options or the generated
config: both hold secrets.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import os
import re
import tempfile
from collections.abc import Mapping
from typing import Any

import yaml

from .broker import MqttSettings

AUTOMATIC = "Automatic"
LOCAL_ONLY = "Local only"
CLOUD_ONLY = "Cloud only"
CLOUD_REST_ONLY = "Cloud REST only"
MODES = (AUTOMATIC, LOCAL_ONLY, CLOUD_ONLY, CLOUD_REST_ONLY)

LIBRARY_CONFIG_PATH = "/data/pecron-monitor.yaml"
SETUP_FILE_NAME = "pecron-setup.yaml"

DEFAULT_POLL_INTERVAL = 70
CLOUD_MIN_POLL_INTERVAL = 63
DEFAULT_STALE_AFTER = 600

HIDDEN_HINT = (
    'It may be hidden: enable "Show unused optional configuration options" '
    "at the top of the Configuration tab."
)

# UI labels from translations/en.yaml (tests keep the two in sync).
LABELS = {
    "connection_mode": "Connection mode",
    "account.email": "Email",
    "account.password": "Password",
    "devices": "Devices",
    "devices.model": "Model",
    "devices.product_key": "Product key",
    "devices.device_key": "Device key",
    "devices.lan_ip": "LAN IP address",
    "devices.auth_key": "Local auth key",
    "devices.ble": "Bluetooth",
    "devices.ble_address": "Bluetooth address",
    "polling.poll_interval": "Poll interval",
    "mqtt.stale_after": "Unavailable after",
    "restore_outputs_after_shutdown": "Restore outputs after shutdown",
}

# Option groups copied to the library config. Values are (option, library key).
_POLLING_KEYS = (
    "poll_interval",
    "cloud_retry_interval",
    "mqtt_reconnect_interval",
    "high_freq_warmup_seconds",
)
_HA_KEYS = (
    ("mqtt", "discovery_prefix"),
    ("mqtt", "clear_discovery_on_startup"),
    ("mqtt", "retry_interval"),
    ("mqtt", "stale_after"),
    ("energy", "energy_sensors"),
    ("energy", "energy_max_gap_seconds"),
)
# Strings that keep surrounding whitespace: passwords may legitimately have it.
_UNTRIMMED = {("account", "password"), ("mqtt", "password")}

_HEX12 = re.compile(r"[0-9A-Fa-f]{12}")


class ConfigError(Exception):
    """Invalid configuration. Carries every error and any warnings found."""

    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        self.errors = list(errors)
        self.warnings = list(warnings or [])
        super().__init__("\n".join(self.errors))


def normalize_device_key(key: str) -> str:
    """Upper-case a 12-hex-character device key; leave anything else as is.

    Cloud messages are matched on the key and the setup wizard upper-cases it,
    so logs, TSL matching and the generated config all use this form.
    """
    key = key.strip()
    return key.upper() if _HEX12.fullmatch(key) else key


def load_options(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        options = json.load(f)
    if not isinstance(options, dict):
        raise ConfigError([f"{path} does not contain a JSON object."])
    return options


def app_config_folder(environ: Mapping[str, str]) -> str:
    """User-visible name of this app's config folder (under /addon_configs)."""
    hostname = environ.get("HOSTNAME", "")
    if hostname.endswith("-pecron-monitor-ha-app"):
        return hostname.replace("-", "_")
    return "the folder ending in `_pecron_monitor_ha_app`"


def known_models() -> list[str]:
    import constants  # the library's module, imported lazily

    return sorted(set(constants.BATTERY_CAPACITY_WH) | set(constants.LOCAL_READ_TIMEOUT_OVERRIDES))


def _trim(options: dict) -> None:
    """Strip whitespace from string options in place, except passwords."""
    for group, value in options.items():
        if isinstance(value, str):
            options[group] = value.strip()
        elif isinstance(value, dict):
            for key, inner in value.items():
                if isinstance(inner, str) and (group, key) not in _UNTRIMMED:
                    value[key] = inner.strip()
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    for key, inner in item.items():
                        if isinstance(inner, str):
                            item[key] = inner.strip()


def _apply_defaults(options: dict) -> None:
    options.setdefault("connection_mode", AUTOMATIC)
    for group in ("account", "polling", "mqtt", "energy", "restore_outputs_after_shutdown"):
        if not isinstance(options.get(group), dict):
            options[group] = {}
    if not isinstance(options.get("devices"), list):
        options["devices"] = []
    options["account"].setdefault("region", "na")
    options["polling"].setdefault("poll_interval", DEFAULT_POLL_INTERVAL)
    options["restore_outputs_after_shutdown"].setdefault("enabled", False)
    options.setdefault("log_level", "info")


def _device_name(index: int, device: dict) -> str:
    """How messages refer to a device: its position, model and device key."""
    parts = []
    if device.get("model"):
        parts.append(device["model"])
    if device.get("device_key"):
        parts.append(f"device key {normalize_device_key(device['device_key'])}")
    detail = f" ({', '.join(parts)})" if parts else ""
    return f"Device {index + 1}{detail}"


def _is_base64(value: str) -> bool:
    try:
        base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return False
    return True


def validate(options: dict, tsl: dict | None) -> list[str]:
    """Check the options; return warnings or raise ConfigError.

    Normalizes ``options`` in place: trims strings (not passwords) and fills
    defaults. ``tsl`` is the result of ``tsl.load_tsl`` or None when the
    setup file could not be read, in which case TSL rules are skipped.
    """
    _trim(options)
    _apply_defaults(options)
    errors: list[str] = []
    warnings: list[str] = []

    mode = options["connection_mode"]
    if mode not in MODES:
        errors.append(f"{LABELS['connection_mode']} must be one of: {', '.join(MODES)}.")
    uses_cloud = mode != LOCAL_ONLY
    account = options["account"]
    devices = options["devices"]
    poll = options["polling"]["poll_interval"]
    folder = app_config_folder(os.environ)

    if not devices:
        msg = (
            "No devices are configured. Open the Configuration tab, add a device under "
            f"{LABELS['devices']}, save, and start the app."
        )
        if mode == LOCAL_ONLY:
            msg += (
                f" For Local only, also place {SETUP_FILE_NAME} in the app config folder "
                f"{folder}, which now exists."
            )
        errors.append(msg)

    if uses_cloud:
        for key in ("email", "password"):
            if not account.get(key):
                errors.append(
                    f"{LABELS['account.' + key]} (Pecron account) is required in {mode} mode. "
                    "Enter it, or set Connection mode to Local only."
                )
        if poll < CLOUD_MIN_POLL_INTERVAL:
            errors.append(
                f"{LABELS['polling.poll_interval']} is {poll} s, below the minimum of "
                f"{CLOUD_MIN_POLL_INTERVAL} s for {mode} mode. Use 70 s (recommended); "
                "only Local only allows less."
            )
        elif poll < DEFAULT_POLL_INTERVAL:
            warnings.append(
                f"{LABELS['polling.poll_interval']} is {poll} s, close to the cloud minimum of "
                f"{CLOUD_MIN_POLL_INTERVAL} s. 70 s (recommended) leaves headroom."
            )

    stale_after = options["mqtt"].get("stale_after", DEFAULT_STALE_AFTER)
    if stale_after < 3 * poll:
        warnings.append(
            f"{LABELS['mqtt.stale_after']} is {stale_after} s, less than three times the "
            f"{LABELS['polling.poll_interval']} of {poll} s: entities may flap to unavailable. "
            f"Set it to at least {3 * poll} s."
        )

    if options["restore_outputs_after_shutdown"].get("enabled") and mode in (
        LOCAL_ONLY,
        CLOUD_REST_ONLY,
    ):
        warnings.append(
            f"{LABELS['restore_outputs_after_shutdown']} has no effect in {mode} mode: "
            "it needs cloud MQTT (Automatic or Cloud only)."
        )

    models = known_models() if mode in (LOCAL_ONLY, AUTOMATIC) else []
    seen: dict[str, str] = {}
    for index, device in enumerate(devices):
        name = _device_name(index, device)
        for field in ("model", "product_key", "device_key"):
            if not device.get(field):
                errors.append(f"{name}: {LABELS['devices.' + field]} is empty. Enter it.")

        key = device.get("device_key", "")
        if key:
            folded = key.lower()
            if folded in seen:
                errors.append(
                    f"{name}: {LABELS['devices.device_key']} {normalize_device_key(key)} is "
                    f"also used by {seen[folded]}. Each device must be listed once."
                )
            else:
                seen[folded] = name
            if not _HEX12.fullmatch(key):
                warnings.append(
                    f"{name}: {LABELS['devices.device_key']} is not 12 hexadecimal characters. "
                    "Check it against Device Info in the Pecron app."
                )

        lan_ip = device.get("lan_ip")
        auth_key = device.get("auth_key")
        if mode == LOCAL_ONLY:
            for field, value in (("lan_ip", lan_ip), ("auth_key", auth_key)):
                if not value:
                    errors.append(
                        f"{name}: {LABELS['devices.' + field]} is required in Local only mode. "
                        f"Enter it in the device entry. {HIDDEN_HINT}"
                    )
        if auth_key and not _is_base64(auth_key):
            errors.append(
                f"{name}: {LABELS['devices.auth_key']} is not valid base64. Copy it again "
                "from the pecron-monitor setup wizard output."
            )
        if mode == AUTOMATIC and auth_key and not lan_ip:
            warnings.append(
                f"{name}: {LABELS['devices.auth_key']} is set but {LABELS['devices.lan_ip']} "
                "is empty, so local transport is disabled for this device. Enter the LAN IP "
                f"address to use it. {HIDDEN_HINT}"
            )
        if lan_ip and re.fullmatch(r"[0-9.]+", lan_ip):
            try:
                ipaddress.IPv4Address(lan_ip)
            except ValueError:
                warnings.append(
                    f"{name}: {LABELS['devices.lan_ip']} {lan_ip} is not a valid IPv4 address."
                )
        if device.get("ble") or device.get("ble_address"):
            warnings.append(
                f"{name}: {LABELS['devices.ble']} and {LABELS['devices.ble_address']} are not "
                "supported in this version and are ignored."
            )
        if models and device.get("model") and device["model"] not in models:
            warnings.append(
                f"{name}: {LABELS['devices.model']} {device['model']} is not a model the library "
                f"knows (case-sensitive). Known models: {', '.join(models)}."
            )

    if errors:
        raise ConfigError(errors, warnings)
    return warnings


def _put(target: dict, key: str, value: Any) -> None:
    """Set ``target[key]`` unless the value is unset or an empty string."""
    if value is not None and value != "":
        target[key] = value


def build_library_config(options: dict, mqtt: MqttSettings, tsl: dict | None) -> dict:
    """Translate validated options into the library's YAML config."""
    mode = options["connection_mode"]
    account = options["account"]
    config: dict[str, Any] = {}

    if mode != LOCAL_ONLY:  # email/password are not read in --local mode
        _put(config, "email", account.get("email"))
        _put(config, "password", account.get("password"))
    config["region"] = account.get("region", "na")

    devices = []
    for option in options["devices"]:
        device_key = normalize_device_key(option["device_key"])
        device: dict[str, Any] = {}
        _put(device, "name", option.get("model"))
        _put(device, "product_key", option.get("product_key"))
        device["device_key"] = device_key
        # Upstream ignores --nolocal in long-running mode: omitting the local
        # fields is what keeps the cloud modes off the local transport.
        if mode in (AUTOMATIC, LOCAL_ONLY):
            _put(device, "lan_ip", option.get("lan_ip"))
            # Without lan_ip an auth_key makes the library scan the container's
            # own network for the device, which can never succeed.
            if option.get("lan_ip"):
                _put(device, "auth_key", option.get("auth_key"))
        if tsl and device_key.lower() in tsl:
            device["tsl_cache"] = tsl[device_key.lower()]
        devices.append(device)
    config["devices"] = devices

    for key in _POLLING_KEYS:
        _put(config, key, options["polling"].get(key))

    ha: dict[str, Any] = {"enabled": True}
    _put(ha, "mqtt_host", mqtt.host)
    _put(ha, "mqtt_port", mqtt.port)
    _put(ha, "mqtt_user", mqtt.username)
    _put(ha, "mqtt_password", mqtt.password)
    for group, key in _HA_KEYS:
        _put(ha, key, options[group].get(key))
    config["homeassistant"] = ha

    restore: dict[str, Any] = {}
    for key, value in options["restore_outputs_after_shutdown"].items():
        _put(restore, key, value)
    config["restore_outputs_after_shutdown"] = restore
    return config


def library_args(options: dict) -> list[str]:
    args = ["--config", LIBRARY_CONFIG_PATH, "--homeassistant", "--no-ble"]
    args += {
        AUTOMATIC: [],
        LOCAL_ONLY: ["--local"],
        CLOUD_ONLY: ["--nolocal"],  # no effect upstream in long-running mode; see above
        CLOUD_REST_ONLY: ["--rest-only"],
    }[options["connection_mode"]]
    if options.get("log_level") in ("trace", "debug"):
        args.append("--verbose")
    return args


def write_config(config: dict, path: str) -> None:
    """Write the config atomically, readable only by the owner (0600)."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".pecron-monitor-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
