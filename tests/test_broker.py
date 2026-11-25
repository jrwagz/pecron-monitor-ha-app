"""MQTT broker settings from manual options or the Supervisor service."""

import io
import json
import logging
from urllib.error import HTTPError, URLError

import pytest

from pecron_app import broker
from pecron_app.broker import MqttSettings, MqttUnavailable, resolve_mqtt
from pecron_app.config import ConfigError

TOKEN = "supervisor-token-secret"
ENV = {"SUPERVISOR_TOKEN": TOKEN}
SERVICE = {
    "addon": "core_mosquitto",
    "host": "core-mosquitto",
    "port": 1883,
    "ssl": False,
    "protocol": "3.1.1",
    "username": "addons",
    "password": "service-password-secret",
}


class Response(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body if isinstance(body, bytes) else json.dumps(body).encode())
        self.status = status


@pytest.fixture
def http(monkeypatch):
    """Stub urlopen; record requests. Set .result to a body, Response or exception."""

    class Stub:
        result = {"result": "ok", "data": SERVICE}
        requests = []

        def __call__(self, request, timeout):
            self.requests.append((request, timeout))
            if isinstance(self.result, Exception):
                raise self.result
            if isinstance(self.result, Response):
                return self.result
            return Response(self.result)

    stub = Stub()
    stub.requests = []
    monkeypatch.setattr(broker, "urlopen", stub)
    return stub


def opts(**mqtt):
    return {"mqtt": mqtt}


def test_manual_host_uses_no_service(http):
    settings = resolve_mqtt(opts(host="broker.lan"), ENV)
    assert settings == MqttSettings("broker.lan", 1883, "", "")
    assert http.requests == []


def test_manual_host_with_all_fields(http):
    settings = resolve_mqtt(opts(host="b", port=1884, username="u", password="p"), {})
    assert settings == MqttSettings("b", 1884, "u", "p")
    assert http.requests == []


def test_service_settings(http):
    assert resolve_mqtt({}, ENV) == MqttSettings(
        "core-mosquitto", 1883, "addons", "service-password-secret"
    )
    (request, timeout) = http.requests[0]
    assert request.full_url == "http://supervisor/services/mqtt"
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert timeout == 10


def test_service_with_overrides(http):
    settings = resolve_mqtt(opts(port=1884, username="me", password="mine"), ENV)
    assert settings == MqttSettings("core-mosquitto", 1884, "me", "mine")


def test_service_without_credentials(http):
    data = {k: v for k, v in SERVICE.items() if k not in ("username", "password")}
    http.result = {"result": "ok", "data": data}
    assert resolve_mqtt({}, ENV) == MqttSettings("core-mosquitto", 1883, "", "")


@pytest.mark.parametrize(
    "error",
    [
        HTTPError(broker.SERVICE_URL, 400, "Bad Request", {}, None),
        URLError("Name does not resolve"),
        TimeoutError("timed out"),
        ConnectionResetError(),
    ],
)
def test_service_unavailable_is_retryable(http, error):
    http.result = error
    with pytest.raises(MqttUnavailable) as exc:
        resolve_mqtt({}, ENV)
    assert "Mosquitto" in str(exc.value) and "Broker host" in str(exc.value)


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        {"result": "ok"},
        {"result": "ok", "data": {"port": 1883}},
        {"result": "ok", "data": {"host": "h", "port": "1883"}},
    ],
)
def test_malformed_response_is_retryable(http, body):
    http.result = Response(body)
    with pytest.raises(MqttUnavailable):
        resolve_mqtt({}, ENV)


def test_non_200_is_retryable(http):
    http.result = Response({"result": "ok", "data": SERVICE}, status=204)
    with pytest.raises(MqttUnavailable):
        resolve_mqtt({}, ENV)


def test_no_token_and_no_host_is_config_error(http):
    with pytest.raises(ConfigError) as exc:
        resolve_mqtt({}, {})
    assert "Broker host" in str(exc.value)
    assert http.requests == []


def test_ssl_service_is_config_error(http):
    http.result = {"result": "ok", "data": {**SERVICE, "ssl": True}}
    with pytest.raises(ConfigError) as exc:
        resolve_mqtt({}, ENV)
    assert "Broker port" in str(exc.value)


def test_secrets_never_logged_or_in_errors(http, caplog):
    caplog.set_level(logging.DEBUG)
    resolve_mqtt({}, ENV)
    resolve_mqtt(opts(password="manual-password-secret"), ENV)
    resolve_mqtt(opts(host="h", password="manual-password-secret"), ENV)
    messages = [r.getMessage() for r in caplog.records]
    assert any("core-mosquitto:1883" in m for m in messages)
    for error in (HTTPError(broker.SERVICE_URL, 401, "Unauthorized", {}, None), URLError("x")):
        http.result = error
        with pytest.raises(MqttUnavailable) as exc:
            resolve_mqtt({}, ENV)
        messages.append(str(exc.value))
    http.result = {"result": "ok", "data": {**SERVICE, "ssl": True}}
    with pytest.raises(ConfigError) as exc:
        resolve_mqtt({}, ENV)
    messages.append(str(exc.value))
    text = "\n".join(messages)
    for secret in (TOKEN, "service-password-secret", "manual-password-secret"):
        assert secret not in text


def test_settings_repr_hides_password():
    assert "pw-secret" not in repr(MqttSettings("h", 1, "u", "pw-secret"))
