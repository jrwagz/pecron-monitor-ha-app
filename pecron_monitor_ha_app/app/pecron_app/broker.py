"""Settings for the Home Assistant MQTT broker.

Manual ``mqtt.host`` wins; otherwise the Supervisor's MQTT service (granted by
``services: mqtt:need``) supplies host, port and credentials, and any manual
port, username or password overrides the matching value. Credentials and the
Supervisor token are never logged or put in messages.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import ConfigError

log = logging.getLogger(__name__)

SERVICE_URL = "http://supervisor/services/mqtt"
DEFAULT_PORT = 1883
TIMEOUT = 10

_INSTALL_HINT = (
    "Install and start the Mosquitto broker app, or set Broker host under Home Assistant "
    "MQTT broker in the Configuration tab."
)


@dataclass(frozen=True)
class MqttSettings:
    host: str
    port: int = DEFAULT_PORT
    username: str = ""
    password: str = field(default="", repr=False)


class MqttUnavailable(Exception):
    """The Supervisor MQTT service could not be used right now (retryable)."""


def _unavailable(problem: str) -> MqttUnavailable:
    return MqttUnavailable(f"The Home Assistant MQTT service {problem}. {_INSTALL_HINT}")


def _fetch_service(token: str) -> dict:
    request = Request(SERVICE_URL, headers={"Authorization": f"Bearer {token}"})
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                raise _unavailable(f"is not available (HTTP {response.status})")
            body = json.load(response)
    except URLError as e:  # includes HTTPError for non-2xx responses
        detail = f"HTTP {e.code}" if hasattr(e, "code") else type(e).__name__
        raise _unavailable(f"is not available ({detail})") from None
    except (OSError, ValueError) as e:  # timeouts, resets, invalid JSON
        raise _unavailable(f"could not be read ({type(e).__name__})") from None
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) or not data.get("host") or not isinstance(data.get("port"), int):
        raise _unavailable("returned an unexpected response")
    return data


def resolve_mqtt(options: dict, environ: Mapping[str, str]) -> MqttSettings:
    manual = options.get("mqtt") or {}
    if manual.get("host"):
        settings = MqttSettings(
            host=manual["host"],
            port=manual.get("port") or DEFAULT_PORT,
            username=manual.get("username") or "",
            password=manual.get("password") or "",
        )
        log.info("MQTT broker: manual settings, %s:%d", settings.host, settings.port)
        return settings

    token = environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise ConfigError(
            [
                "No MQTT broker: Broker host is empty and the Home Assistant Supervisor is not "
                "available to provide one. Set Broker host under Home Assistant MQTT broker."
            ]
        )

    data = _fetch_service(token)
    if data.get("ssl"):
        raise ConfigError(
            [
                "The Home Assistant MQTT service only offers a TLS connection, which this app does "
                "not support. Set Broker host and Broker port under Home Assistant MQTT broker "
                "to a plain TCP listener."
            ]
        )
    settings = MqttSettings(
        host=data["host"],
        port=manual.get("port") or data["port"],
        username=manual.get("username") or data.get("username") or "",
        password=manual.get("password") or data.get("password") or "",
    )
    overridden = [k for k in ("port", "username", "password") if manual.get(k)]
    note = f" (overridden: {', '.join(overridden)})" if overridden else ""
    log.info(
        "MQTT broker: Home Assistant MQTT service%s, %s:%d", note, settings.host, settings.port
    )
    return settings
