"""Settings for the Home Assistant MQTT broker."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MqttSettings:
    host: str
    port: int = 1883
    username: str = ""
    password: str = field(default="", repr=False)
