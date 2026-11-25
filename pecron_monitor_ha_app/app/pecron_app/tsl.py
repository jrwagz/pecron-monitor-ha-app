"""Import each device's tsl_cache from the user's pecron-monitor setup file.

The file (written by ``pecron-monitor --setup``) may also hold the account
password and auth keys: only ``devices[].device_key`` and
``devices[].tsl_cache`` are read, and no file content is ever echoed.
"""

from __future__ import annotations

import yaml

from .config import ConfigError, normalize_device_key, setup_file_location


def _fail(problem: str) -> ConfigError:
    return ConfigError([f"Setup file {setup_file_location()}: {problem}"])


def _valid_tsl(tsl: object) -> bool:
    if not isinstance(tsl, dict) or not tsl:
        return False
    for entry in tsl.values():
        if not isinstance(entry, dict):
            return False
        entry_id = entry.get("id")
        if not isinstance(entry_id, int) or isinstance(entry_id, bool):
            return False
        if "type" not in entry or "access" not in entry:
            return False
    return True


def load_tsl(path: str) -> dict[str, dict]:
    """Return ``{device_key.lower(): tsl_cache}``; ``{}`` if the file is absent."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise _fail(f"cannot be read ({e.strerror}).") from None
    except UnicodeDecodeError:
        raise _fail("is not UTF-8 text.") from None
    except yaml.YAMLError as e:
        # The exception text embeds a snippet of the file: report the position only.
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise _fail(f"is not valid YAML{where}.") from None

    devices = data.get("devices") if isinstance(data, dict) else None
    if not isinstance(devices, list):
        raise _fail("has no devices list. Use the file written by pecron-monitor --setup.")

    result: dict[str, dict] = {}
    seen: set[str] = set()
    for index, device in enumerate(devices, start=1):
        if not isinstance(device, dict) or not isinstance(device.get("device_key"), str):
            raise _fail(
                f"devices entry {index} has no text device_key. Put the key in quotes, "
                'e.g. device_key: "123456789012".'
            )
        key = device["device_key"].strip().lower()
        shown = normalize_device_key(device["device_key"])
        if key in seen:
            raise _fail(f"device key {shown} is listed more than once.")
        seen.add(key)
        if device.get("tsl_cache") is None:
            continue  # the wizard writes no tsl_cache when the TSL fetch failed
        if not _valid_tsl(device["tsl_cache"]):
            raise _fail(
                f"the tsl_cache of device key {shown} is not valid. "
                "Each entry needs an integer id, a type and an access value; run "
                "pecron-monitor --setup again to regenerate it."
            )
        result[key] = device["tsl_cache"]
    return result
