import pytest


@pytest.fixture(autouse=True)
def _hostname(monkeypatch):
    """Messages name the app config folder, which is derived from the host name."""
    monkeypatch.setenv("HOSTNAME", "local-pecron-monitor-ha-app")
