"""Importing tsl_cache from the setup file (pecron_app.tsl) and its validation rules."""

import copy
import os
from pathlib import Path

import pytest
import yaml

from pecron_app import config as cfg
from pecron_app.broker import MqttSettings
from pecron_app.config import ConfigError
from pecron_app.tsl import load_tsl

WIZARD = Path(__file__).parent / "fixtures" / "setup-wizard.yaml"
WIZARD_DATA = yaml.safe_load(WIZARD.read_text())
F3000_TSL = WIZARD_DATA["devices"][0]["tsl_cache"]
AUTH_KEY = "c2VjcmV0LWF1dGgta2V5IQ=="


def write(tmp_path, data, raw=False):
    path = tmp_path / "pecron-setup.yaml"
    path.write_text(data if raw else yaml.safe_dump(data))
    return str(path)


def load_error(path):
    with pytest.raises(ConfigError) as exc:
        load_tsl(path)
    (message,) = exc.value.errors
    assert "pecron-setup.yaml in the app config folder local_pecron_monitor_ha_app" in message
    return message


def options(mode, devices):
    return {
        "connection_mode": mode,
        "account": {"email": "me@example.com", "password": "pw"},
        "devices": devices,
    }


def device(key="A1B2C3D4E5F6", **extra):
    d = {
        "model": "F3000LFP",
        "product_key": "pk",
        "device_key": key,
        "lan_ip": "192.0.2.10",
        "auth_key": AUTH_KEY,
    }
    d.update(extra)
    return {k: v for k, v in d.items() if v is not None}


# --- load_tsl ------------------------------------------------------------


def test_wizard_file_reads_only_tsl():
    assert load_tsl(str(WIZARD)) == {"a1b2c3d4e5f6": F3000_TSL}


def test_absent_file_is_empty(tmp_path):
    assert load_tsl(str(tmp_path / "missing.yaml")) == {}


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read anything")
def test_unreadable_file(tmp_path):
    path = write(tmp_path, {"devices": []})
    os.chmod(path, 0)
    assert "cannot be read" in load_error(path)


def test_invalid_yaml_reports_position_not_content(tmp_path):
    path = write(tmp_path, "password: hunter2-secret\ndevices: [\n  {a: b\n", raw=True)
    message = load_error(path)
    assert "line" in message and "column" in message
    assert "hunter2" not in message and "{a" not in message


@pytest.mark.parametrize("data", [{"email": "x"}, {"devices": {"a": 1}}, ["devices"], None])
def test_no_devices_list(tmp_path, data):
    assert "no devices list" in load_error(write(tmp_path, data))


def test_device_entry_not_a_mapping(tmp_path):
    assert "quotes" in load_error(write(tmp_path, {"devices": ["a1b2c3d4e5f6"]}))


def test_numeric_device_key_must_be_quoted(tmp_path):
    path = write(tmp_path, "devices:\n  - device_key: 123456789012\n", raw=True)
    assert "quotes" in load_error(path)


def test_duplicate_keys_case_insensitive(tmp_path):
    data = {"devices": [{"device_key": "a1b2c3d4e5f6"}, {"device_key": "A1B2C3D4E5F6"}]}
    assert "more than once" in load_error(write(tmp_path, data))


def test_missing_tsl_cache_means_no_tsl(tmp_path):
    data = {"devices": [{"device_key": "a1b2c3d4e5f6"}, {"device_key": "b", "tsl_cache": None}]}
    assert load_tsl(write(tmp_path, data)) == {}


@pytest.mark.parametrize(
    "tsl",
    [
        {},
        [],
        "x",
        {"ac": "x"},
        {"ac": {"id": "40", "type": "BOOL", "access": "RW"}},
        {"ac": {"id": True, "type": "BOOL", "access": "RW"}},
        {"ac": {"id": 40, "access": "RW"}},
        {"ac": {"id": 40, "type": "BOOL"}},
    ],
)
def test_invalid_tsl_names_device(tmp_path, tsl):
    data = {"devices": [{"device_key": "a1b2c3d4e5f6", "tsl_cache": tsl}]}
    assert "A1B2C3D4E5F6" in load_error(write(tmp_path, data))


def test_keys_are_lower_cased(tmp_path):
    data = {"devices": [{"device_key": " A1B2C3D4E5F6 ", "tsl_cache": F3000_TSL}]}
    assert load_tsl(write(tmp_path, data)) == {"a1b2c3d4e5f6": F3000_TSL}


# --- validate with TSL ---------------------------------------------------


def test_local_only_requires_tsl():
    with pytest.raises(ConfigError) as exc:
        cfg.validate(options("Local only", [device("0A0B0C0D0E0F")]), {})
    (message,) = exc.value.errors
    assert "no tsl_cache" in message and "pecron-monitor --setup" in message
    assert "local_pecron_monitor_ha_app" in message


def test_local_only_matches_tsl_case_insensitively():
    assert cfg.validate(options("Local only", [device("a1b2c3d4e5f6")]), {"a1b2c3d4e5f6": {}}) == []


def test_automatic_without_tsl_warns_with_consequence():
    (warning,) = cfg.validate(options("Automatic", [device()]), {})
    assert "default controls" in warning and "wrong output" in warning


def test_automatic_cloud_only_device_needs_no_tsl():
    assert cfg.validate(options("Automatic", [device(lan_ip=None, auth_key=None)]), {}) == []


@pytest.mark.parametrize("mode", ["Cloud only", "Cloud REST only"])
def test_cloud_modes_need_no_tsl(mode):
    assert cfg.validate(options(mode, [device()]), {}) == []


def test_tsl_none_skips_tsl_rules():
    assert cfg.validate(options("Local only", [device()]), None) == []


def test_unmatched_file_devices_warn():
    tsl = {"a1b2c3d4e5f6": {}, "0a0b0c0d0e0f": {}}
    (warning,) = cfg.validate(options("Local only", [device()]), tsl)
    assert "0A0B0C0D0E0F" in warning and "A1B2C3D4E5F6" not in warning


def test_wizard_secrets_and_rules_do_not_reach_library_config():
    tsl = load_tsl(str(WIZARD))
    o = options("Local only", [device()])
    cfg.validate(o, tsl)
    c = cfg.build_library_config(o, MqttSettings("h", 1883), tsl)
    text = yaml.safe_dump(c)
    for leaked in ("someone@example.com", "not-a-real-password", "alerts", "rules", "telegram"):
        assert leaked not in text
    assert c["devices"][0]["tsl_cache"] == F3000_TSL


def library_monitor(tmp_path, monkeypatch, setup_data):
    monitor = pytest.importorskip("monitor")
    for var in ("PECRON_STATE_PATH", "PECRON_ENERGY_STATE_PATH", "PECRON_RULE_STATE_PATH"):
        monkeypatch.setenv(var, str(tmp_path / var))
    tsl = load_tsl(write(tmp_path, setup_data))
    o = options("Local only", [device()])
    cfg.validate(o, tsl)
    m = monitor.PecronMonitor(
        copy.deepcopy(cfg.build_library_config(o, MqttSettings("h", 1), tsl)), no_ble=True
    )
    m.skip_local_setup = True
    m._build_devices_from_config()
    return m


def test_library_uses_imported_tsl_as_controls(tmp_path, monkeypatch):
    m = library_monitor(tmp_path, monkeypatch, WIZARD_DATA)
    assert m.devices[0]["controls"] == F3000_TSL


class RecordingTransport:
    """Stands in for the library's LocalTransport; records writes, sends nothing."""

    connected = False

    def __init__(self):
        self.writes = []

    def connect(self):
        self.connected = True
        return True

    def disconnect(self):
        self.connected = False

    def send_control(self, control_id, value, ctrl_type, verify=True):
        self.writes.append((control_id, value, ctrl_type))
        return True


def test_switch_command_writes_the_imported_control_id(tmp_path, monkeypatch):
    data = copy.deepcopy(WIZARD_DATA)
    tsl = data["devices"][0]["tsl_cache"]
    tsl["ac_switch_hm"]["id"] = 99  # the library default is 40
    m = library_monitor(tmp_path, monkeypatch, data)
    key = m.devices[0]["device_key"]
    transport = m.local_transports[key] = RecordingTransport()

    m._ha_command(key, "ac", "garbled")
    assert transport.writes == []

    m._ha_command(key, "ac", "ON")
    assert transport.writes == [(99, True, "BOOL")]
