# Pecron Monitor HA App

A [Home Assistant](https://www.home-assistant.io/) app that monitors and
controls Pecron portable power stations. It runs
[pecron-monitor](https://github.com/attractify-logan/pecron-monitor) and creates
MQTT discovery entities for several units: battery, power, voltage, AC and DC
output switches and more, over your local network, the Pecron cloud or both.

> **Unofficial project.** Not affiliated with, endorsed by or supported by
> Pecron. The app is experimental.

## Install

[![Open your Home Assistant instance and show the add app repository dialog with this repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fjrwagz%2Fpecron-monitor-ha-app)

1. Install and start the **Mosquitto broker** app and set up the **MQTT**
   integration.
2. Click the button above, or go to **Settings > Apps > Install app**, open the
   menu, choose **Repositories** and add
   `https://github.com/jrwagz/pecron-monitor-ha-app`.
3. Install **Pecron Monitor HA App**.
4. Follow the [documentation](pecron_monitor_ha_app/DOCS.md) to configure it.
   Local access needs extra preparation on a computer.

Supported architectures: `amd64` and `aarch64`.

## Credits

This app is a wrapper around
[pecron-monitor](https://github.com/attractify-logan/pecron-monitor) by
attractify-logan and contributors, which does all the device communication. See
the [third-party notices](pecron_monitor_ha_app/THIRD_PARTY_NOTICES.md). This
repository is under the [MIT License](LICENSE).

## Development

CI uses Python 3.14. From the repository root, set up an environment, install
the pinned pecron-monitor library and run the tests:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
tests/install_library.sh
pytest
```

Linters (`tests/shellcheck.sh` needs
[ShellCheck](https://www.shellcheck.net/) installed):

```bash
ruff check .
ruff format --check .
yamllint --strict .
tests/shellcheck.sh
```

The smoke test runs a built image against a throwaway MQTT broker. It needs only
Docker and uses no real devices or accounts:

```bash
docker build -t pecron-app pecron_monitor_ha_app
tests/smoke/run.sh pecron-app
```

[CI](.github/workflows/ci.yaml) runs these and a few more checks. To try changes
on Home Assistant, see
[testing a local copy](RELEASING.md#testing-a-local-copy-on-home-assistant). To
publish a version, see [RELEASING.md](RELEASING.md).
