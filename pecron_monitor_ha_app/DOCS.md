# Pecron Monitor HA App

Monitor and control Pecron portable power stations in Home Assistant. The app
runs [pecron-monitor](https://github.com/attractify-logan/pecron-monitor)
v0.8.4 and creates MQTT discovery entities for each of your units.

This is an unofficial community project. It is not affiliated with, endorsed by
or supported by Pecron.

> **The AC Output and DC Output switches act on the real unit straight away.**
> Turning an output off cuts the power to whatever is plugged into it. To try a
> switch, use an output with nothing connected.

## Prerequisites

- Home Assistant with Apps (Home Assistant OS), on `amd64` or `aarch64`.
- An MQTT broker. Install the **Mosquitto broker** app (**Settings > Apps >
  Install app**), start it, then add the **MQTT** integration that Home
  Assistant offers under **Settings > Devices & services**.
- A Pecron account with a password. If you sign in with Google or Apple, set a
  password in the Pecron app first.
- Every unit connected to your Wi-Fi. If you use the local network (Automatic
  with a LAN IP address, or Local only), give each unit a fixed address with a
  DHCP reservation in your router.

## Which mode, and what you need

| | Automatic | Local only | Cloud only | Cloud REST only |
|---|---|---|---|---|
| Talks to | Pecron cloud, plus your network for devices with a LAN IP address | Your network only, never the cloud | Cloud MQTT and REST | Cloud REST |
| Email and password | Required | Not used | Required | Required |
| Model, product key, device key | Required | Required | Required | Required |
| LAN IP address | Optional | Required | Not used | Not used |
| Local auth key | Optional; needed to start without internet | Required | Not used | Not used |
| Smallest poll interval | 63 s | 5 s | 63 s | 63 s |
| Setup wizard | Recommended if you use a LAN IP address | Required | Not needed | Not needed |
| Setup file | Recommended if you use a LAN IP address | Required | Not needed | Not needed |
| AC and DC switches | Yes | Yes | Yes | Yes |
| Selects (charging power, UPS threshold) | While the cloud is reachable | No | Yes | Yes |
| Restore outputs after shutdown | Yes | No | Yes | No |

**Who can skip the setup wizard:** anyone using **Cloud only** or **Cloud REST
only**, and **Automatic** users without LAN IP addresses. Automatic users with
LAN IP addresses can also skip it (the app fetches the local auth key from the
cloud), but read [the risk](#risk-of-automatic-mode-without-the-setup-file)
first. **Local only** users cannot skip it.

**Finding the keys without the wizard:**

- `device_key`: in the Pecron app, open the device, then **Settings (gear) >
  Device Info > Device Key** (some app versions say **Device Code**). It is
  usually 12 hexadecimal characters.
- `product_key`: see the [model table](#models-and-product-keys).
- `auth_key`: only the setup wizard gives you this (in the file it writes).

### Quick start: Automatic or cloud

1. Meet the [prerequisites](#prerequisites).
2. In Home Assistant, open **Settings > Apps > Install app**, open the menu at
   the top right, choose **Repositories** and add
   `https://github.com/jrwagz/pecron-monitor-ha-app`.
3. Install **Pecron Monitor HA App**.
4. Optional, for Automatic with LAN IP addresses: run the
   [setup wizard](#setup-wizard-on-your-computer) on your computer.
5. On the app's **Configuration** tab, choose the **Connection mode**, enter
   your email, password and region, and add one entry per unit under
   **Devices** with model, product key and device key. For local access also
   enter the LAN IP address and, if you ran the wizard, the local auth key
   (enable **Show unused optional configuration options** if you do not see
   them). Save.
6. Start the app.
7. If you ran the wizard: place the [setup file](#setup-file) in the app config
   folder and restart the app.
8. Open the **Log** tab and wait for the line that starts `Ready: entities are
   under Settings > Devices & services > MQTT`. Values appear once each device
   responds.

### Quick start: fast local polling

1. Meet the [prerequisites](#prerequisites), including a DHCP reservation for
   each unit.
2. Run the [setup wizard](#setup-wizard-on-your-computer) on your computer and
   prepare the [setup file](#setup-file). Keep each device's `device_key`,
   `product_key` and `auth_key` at hand.
3. In Home Assistant, open **Settings > Apps > Install app**, open the menu at
   the top right, choose **Repositories** and add
   `https://github.com/jrwagz/pecron-monitor-ha-app`.
4. Install **Pecron Monitor HA App**.
5. On the **Configuration** tab, set **Connection mode** to **Local only**, set
   **Poll interval** to 10, set the region, and add each unit with model,
   product key, device key, LAN IP address and local auth key (enable **Show
   unused optional configuration options** if you do not see the last two).
   Save.
6. Start the app once. It stops with an error saying there is no `tsl_cache`.
   This is expected, and this first start creates the app config folder.
7. [Place the setup file](#placing-the-file) in that folder.
8. Start the app again and wait on the **Log** tab for the line that starts
   `Ready: entities are under Settings > Devices & services > MQTT`. Values
   appear once each device responds.

A poll interval of 10 does not mean an update every 10 seconds; see
[reporting cadence](#reporting-cadence).

## Setup wizard (on your computer)

The wizard is part of pecron-monitor. It logs in to your Pecron account and
writes a file holding each device's keys and its list of controls
(`tsl_cache`). Run it on a computer, not on Home Assistant. It needs Python 3.9
or newer and internet access.

These install commands were tested on macOS and on Debian-based Linux (the
`python:3.12-slim` container), both with Python 3.12:

```bash
mkdir pecron-setup
cd pecron-setup
python3 -m venv venv
source venv/bin/activate
pip install https://github.com/attractify-logan/pecron-monitor/archive/refs/tags/v0.8.4.tar.gz
pecron-monitor --version
```

On Windows (not tested), use `py -m venv venv` and `venv\Scripts\activate` in
place of the `python3` and `source` lines.

The last command should print `pecron-monitor 0.8.4`. Then run the wizard:

```bash
pecron-monitor --setup
```

| Prompt | Answer |
|---|---|
| `Pecron account email:` | Your account email |
| `Pecron account password:` | Your password (nothing is shown while you type) |
| `Region [na]:` | `na`, `eu` or `cn`; Enter for `na` |
| `Select devices to monitor ... [1,2]:` | Enter for all devices |
| `Device Key (or press Enter to finish):` | Only if devices are entered by hand: type a device key; press Enter when done |
| `Choose [1]:` and `Select [1-N]` | Only when entering by hand: Enter auto-detects the model; pick from the list if asked |
| `Scan for devices on WiFi LAN? [Y/n]:` | `n`, or Enter to have it search for your units' IP addresses |
| `Enter LAN IP for ...` | The unit's IP address, or Enter to skip (the app takes addresses from its own options) |
| `Scan for devices via Bluetooth? [Y/n]:` | `n` (only shown if Bluetooth support is installed) |
| `Poll interval in seconds [70]:` | Enter |
| `Low battery alert threshold % [20]:` | Enter |
| `Enable Telegram alerts? [y/N]:` | Enter (no) |
| `Enable Home Assistant MQTT bridge? [y/N]:` | Enter (no) |
| `Install as a systemd service ...? [y/N]:` | Enter (no); only shown on Linux with systemd |

Check that each device shows a TSL line with a number of properties and a
successful encryption key. The file is written inside the virtual environment;
the wizard prints the full path after `Config saved to`, typically
`venv/lib/python3.X/site-packages/config.yaml`. The local auth key is not shown
on screen: read it from `auth_key` in that file. The wizard may ask the cloud
for a new auth key, so after running it again, check that **Local auth key** in
the app still matches.

> **Warning: do not start the monitor on your computer with this file.** The
> wizard writes an example rule, "Low battery — turn off AC", that switches AC
> output off at 10 % battery. The app never uses it, but `pecron-monitor` on
> your computer does. Ignore the wizard's closing suggestions to run
> `pecron-monitor` or `pecron-monitor --ac on`. Open `config.yaml` and replace
> the whole `rules:` block with `rules: []`.

### How the file maps to app options

| Key in `config.yaml` | App option |
|---|---|
| `email` | `account.email` |
| `password` | `account.password` |
| `region` | `account.region` |
| `devices[].name` | `devices.model` (see the [model table](#models-and-product-keys)) |
| `devices[].product_key` | `devices.product_key` |
| `devices[].device_key` | `devices.device_key` |
| `devices[].lan_ip` | `devices.lan_ip` |
| `devices[].auth_key` | `devices.auth_key` |
| `devices[].tsl_cache` | No option; delivered in the setup file |
| `poll_interval` | `polling.poll_interval` |
| `alerts`, `rules`, `rule_state`, `homeassistant`, `restore_outputs_after_shutdown` | Not read by the app; use its options and Home Assistant automations |

## Setup file

The app reads only `devices[].device_key` and `devices[].tsl_cache` from the
setup file. Its name must be exactly `pecron-setup.yaml`.

The wizard's complete `config.yaml` works. **Trimming it is recommended**,
because the file is included in Home Assistant backups and the full version
holds your password and auth keys. Keep only this structure, leaving each
`tsl_cache` block exactly as the wizard wrote it, with its indentation:

```yaml
devices:
  - device_key: "AABBCCDDEEFF"
    tsl_cache:
      # ... the wizard's entries for this device ...
  - device_key: "001122334455"
    tsl_cache:
      # ... the wizard's entries for this device ...
```

Keep device keys in quotes. Run the wizard again and replace the file after a
firmware update of a unit.

### Placing the file

The app config folder is created when the app first starts, even if that start
ends with a configuration error. Start the app once, then copy the file into the
folder whose name ends in `_pecron_monitor_ha_app`. Using the Samba share app:

1. Install **Samba share** (**Settings > Apps > Install app**).
2. On its **Configuration** tab set a username and password, save, and start it.
3. On your computer, connect to the `app_configs` share: in Windows File
   Explorer open `\\homeassistant.local\app_configs`; in macOS Finder use **Go >
   Connect to Server** with `smb://homeassistant.local/app_configs`. Use your
   Home Assistant's address if that name does not work. Older versions of the
   app call the share `addon_configs`.
4. Open the folder ending in `_pecron_monitor_ha_app` and copy your file there
   as `pecron-setup.yaml` (check that no `.txt` was appended).
5. Restart Pecron Monitor HA App. The log shows `TSL from the setup file` for
   each device it found.

If you already use the **Terminal & SSH** app, the same folder is under
`/app_configs/` (`/addon_configs/` in older versions).

### Risk of Automatic mode without the setup file

If every device has a LAN IP address and a local auth key, Automatic mode can
start while the Pecron cloud is unreachable. A device without a `tsl_cache` then
gets default controls taken from another model: **entities may be wrong and
switches may control the wrong output** until the app restarts with the cloud
reachable or the setup file in place. Place the setup file to avoid this. If you
are in that state, do not use the switches.

## Options

Optional settings are hidden until you enable **Show unused optional
configuration options**. A dash means no default. Restart the app after saving.

| Option | Name in the UI | Default | What it does |
|---|---|---|---|
| `connection_mode` | Connection mode | `Automatic` | `Automatic`, `Local only`, `Cloud only` or `Cloud REST only`; see [modes](#which-mode-and-what-you-need) |
| `account` | Pecron account | | Your Pecron app login |
| `account.email` | Email | empty | Required except in Local only |
| `account.password` | Password | empty | Required except in Local only |
| `account.region` | Region | `na` | `na` North America, `eu` Europe, `cn` China; read in every mode |
| `devices` | Devices | none | One entry per unit; at least one |
| `devices.model` | Model | required | Model name as in the [model table](#models-and-product-keys), case-sensitive |
| `devices.product_key` | Product key | required | Product key of the model |
| `devices.device_key` | Device key | required | Key of this unit; 12-hex keys are converted to upper case |
| `devices.lan_ip` | LAN IP address | – | IP address or hostname of the unit; required in Local only |
| `devices.auth_key` | Local auth key | – | From the wizard's file; required in Local only. Ignored without a LAN IP address |
| `devices.ble` | Bluetooth | – | Not supported; ignored with a warning |
| `devices.ble_address` | Bluetooth address | – | Not supported; ignored with a warning |
| `polling` | Polling | | Reading and retry timing |
| `polling.poll_interval` | Poll interval | `70` | Seconds between readings. Minimum 63, or 5 in Local only |
| `polling.cloud_retry_interval` | Cloud retry interval | `300` | Seconds between attempts to reach the cloud again after an Automatic-mode fallback to local |
| `polling.mqtt_reconnect_interval` | Cloud MQTT reconnect interval | `60` | Seconds between cloud MQTT reconnect attempts |
| `polling.high_freq_warmup_seconds` | High-frequency warm-up | `60` | Seconds of high-frequency reporting requested at startup (Automatic, Cloud only); `0` disables |
| `mqtt` | Home Assistant MQTT broker | `{}` | Leave empty to use the Mosquitto app automatically |
| `mqtt.host` | Broker host | automatic | Another broker; port then defaults to 1883 with no credentials |
| `mqtt.port` | Broker port | automatic | Plain TCP port |
| `mqtt.username` | Broker username | automatic | Overrides the username |
| `mqtt.password` | Broker password | automatic | Overrides the password |
| `mqtt.discovery_prefix` | Discovery prefix | `homeassistant` | MQTT discovery prefix Home Assistant listens on |
| `mqtt.clear_discovery_on_startup` | Clear discovery on startup | `true` | Clear and republish discovery messages at startup |
| `mqtt.retry_interval` | Broker retry interval | `60` | Seconds between broker reconnect attempts |
| `mqtt.stale_after` | Unavailable after | `600` | Seconds without a reading before a device shows unavailable; at least three poll intervals |
| `energy` | Energy | | Derived energy sensors |
| `energy.energy_sensors` | Energy sensors | `false` | Add AC input, AC output and DC output kWh sensors computed from power readings (approximate) |
| `energy.energy_max_gap_seconds` | Maximum gap | `1800` | Longest gap between readings that is still counted |
| `restore_outputs_after_shutdown` | Restore outputs after shutdown | | See the warning below |
| `restore_outputs_after_shutdown.enabled` | Enabled | `false` | Turn output restore on |
| `restore_outputs_after_shutdown.shutdown_threshold_pct` | Shutdown threshold | `10` | Battery % at or below which going offline counts as a low-battery shutdown |
| `restore_outputs_after_shutdown.shutdown_threshold_voltage` | Shutdown voltage threshold | – | Battery voltage that also counts as a low-battery shutdown |
| `restore_outputs_after_shutdown.minimum_offline_seconds` | Minimum offline time | `120` | Shorter outages are ignored |
| `restore_outputs_after_shutdown.retry_interval_seconds` | Restore retry interval | `30` | Seconds between restore attempts |
| `restore_outputs_after_shutdown.retry_timeout_seconds` | Restore timeout | `600` | When to stop trying |
| `restore_outputs_after_shutdown.snapshot_max_age_seconds` | Snapshot maximum age | `86400` | Older saved states are discarded |
| `log_level` | Log level | `info` | `trace`, `debug`, `info`, `notice`, `warning`, `error` or `fatal`; `trace` and `debug` add the library's detailed output |

> **Output restore switches real outputs.** After a unit comes back, the app
> sets AC and DC to the saved state. That can turn an output **off** as well as
> on, and a switch state that was never read is saved as off.

### Models and product keys

From the pecron-monitor v0.8.4 documentation. Product keys differ between
sources, so **the value the setup wizard gives you is authoritative**.
Automatic and the cloud modes correct a wrong product key from your account's
device list; **Local only does not check or correct it**. A wrong device key is
never corrected.

| Model | Product key | Model | Product key |
|---|---|---|---|
| E300LFP | `p11u2Q` | E2400LFP | `p11tf9` |
| C300LFP Mini | `p11uXh` | E2400LFP ADJ | `p11vB4` |
| E500LFP | `p11uFC` | E3600 | `p11tUC` |
| E600LFP | `p11umP` | E3600LFP | `p11wV4` |
| E800LFP | `p11uXR` | E3800LFP | `p11uJn` |
| E1000LFP | `p11vxg` | F1000LFP | `p11vWw` |
| E1500LFP | `p11u2b` | F3000LFP | `p11uAG` |
| E2000LFP | `p11usc` | F5000LFP | `p11vwW` |
| E2200LFP | `p11t8R` | WB12200 | `p11vGo` |

In Automatic and Local only, C300LFP Mini, E800LFP, E2200LFP, E2400LFP ADJ and
WB12200 produce a "not a model the library knows" warning even when typed
correctly.

## Limitations

- **Broker:** plain TCP only, no TLS.
- **One instance per broker:** the MQTT client id (`pecron_ha_bridge`) and the
  topics are fixed. Do not run a second Pecron bridge on the same broker.
- **Selects need the cloud:** `AC Charging Power Setting` and `UPS Charge
  Threshold` (the app has no number entities; each select appears only on models
  that have the control) are sent through the cloud. In Local only, or while
  Automatic has fallen back to local, they still appear but a change does not
  stick: Home Assistant goes back to the old value. The only log message is
  `Cannot send control`, at debug level. If the cloud is lost while the app is
  already running, you may instead see `set_device_property_rest request failed`,
  possibly followed by a `Sent ... via CLOUD MQTT` line although nothing arrived.
- **No LAN discovery** (enter LAN IP addresses yourself) and **no Bluetooth**.
- **Restore outputs after shutdown** works only with cloud MQTT connected
  (Automatic or Cloud only).
- **No rules or alerts:** use Home Assistant automations. Example (replace the
  entity ID with your own):

  ```yaml
  alias: Pecron low battery
  triggers:
    - trigger: numeric_state
      entity_id: sensor.pecron_f1000lfp_aabbccddeeff_battery_soc
      below: 20
  actions:
    - action: persistent_notification.create
      data:
        title: Pecron battery low
        message: "Battery is at {{ trigger.to_state.state }} %."
  ```

### Reporting cadence

Measured with pecron-monitor v0.8.4 run from a computer (not yet with this app),
local connection, poll interval 10, two F1000LFP and one F3000LFP:

| Setup | Time between readings of a device (median) |
|---|---|
| Three devices in one process (how this app runs) | 25 s |
| One device per process | 15 to 16 s |

A local read took about 5 s, the poll interval was added after it, and devices in
one process were read one after another. Expect roughly the poll interval plus
5 s per device. Intervals below 10 and other models were not measured.

Cloud reporting cadence was not measured. pecron-monitor's source notes that
without high-frequency reporting, new data may arrive only about every 20
minutes, however often it is requested.

### Cloud quota

Pecron limits cloud polling **per account**; pecron-monitor puts the limit at
roughly 1280 polls a day. Plan as if every device's poll counts, along with
anything else using the account. Automatic mode also sends a cloud request for
each device on every poll, including devices read locally. With several devices,
raise the poll interval (about 70 s per device, so 210 s for three) and keep
**Unavailable after** at three times that or more.

## Troubleshooting

Start on the app's **Log** tab. Configuration errors begin with `The
configuration is invalid. Fix the following and restart the app:` and the app
stays stopped until you fix them. `<device>` below stands for text such as
`Device 1 (F1000LFP, device key AABBCCDDEEFF)`.

### Configuration errors

| Message | What to do |
|---|---|
| `Cannot read the app options (...)` or `... does not contain a JSON object.` | Save the options again on the Configuration tab and restart |
| `Connection mode must be one of: ...` | Choose a listed mode |
| `No devices are configured. ...` | Add a device under **Devices**, save, start |
| `Email (Pecron account) is required in ... mode.` / `Password (Pecron account) is required in ... mode.` | Enter it, or use Local only |
| `Poll interval is ... s, below the minimum of 63 s for ... mode.` | Use 70 or more; only Local only allows less |
| `<device>: Model is empty.` / `Product key is empty.` / `Device key is empty.` | Fill in the field |
| `<device>: Device key ... is also used by ...` | List each unit once (case does not matter) |
| `<device>: LAN IP address is required in Local only mode.` / `Local auth key is required in Local only mode.` | Enter it; enable **Show unused optional configuration options** if hidden |
| `<device>: Local auth key is not valid base64.` | Copy `auth_key` again, completely, from the wizard's file |
| `<device>: no tsl_cache for this device in pecron-setup.yaml ...` | Local only: [place the setup file](#placing-the-file) containing this device, then start again. In Automatic this is only a warning; see [the risk](#risk-of-automatic-mode-without-the-setup-file) |

A broken setup file stops the app in every mode. These messages begin with
`Setup file pecron-setup.yaml in the app config folder ...:`. Fix the file, or
delete it if your mode does not need it.

| Message | What to do |
|---|---|
| `cannot be read (...)` | Replace the file; check it is a normal file |
| `is not UTF-8 text.` | Save it as plain UTF-8 text |
| `is not valid YAML at line ...` | Fix the indentation or syntax there, or copy the wizard's file again |
| `has no devices list.` | Use the file written by `pecron-monitor --setup` |
| `devices entry ... has no text device_key.` | Give each entry a `device_key` in quotes |
| `device key ... is listed more than once.` | Remove the duplicate entry |
| `the tsl_cache of device key ... is not valid.` | Run the wizard again and copy the block unchanged |

MQTT broker settings:

| Message | What to do |
|---|---|
| `No MQTT broker: Broker host is empty and the Home Assistant Supervisor is not available ...` | Set **Broker host** |
| `The Home Assistant MQTT service only offers a TLS connection ...` | Set **Broker host** and **Broker port** to a plain TCP listener |
| `The Home Assistant MQTT service is not available (...)`, `... could not be read (...)` or `... returned an unexpected response.` | Install and start Mosquitto broker, or set **Broker host**. The app keeps retrying |

### A switch or select goes back to its old value

- A select in Local only or during a cloud outage: expected; see
  [Limitations](#limitations).
- A switch: look for `Write to ... not confirmed` or, at debug level, `Cannot
  send control` and `Local connect failed`. Wait about a minute before trying
  again. In testing from a computer, one command sent about 18 s after the
  previous one had no effect and logged nothing at the default level.
- Check the unit itself before assuming what an output is doing.

### Wrong password or region

- Cloud only, Cloud REST only, and Automatic when not every device has a LAN IP
  address and auth key: the log shows `Login failed (code ...)`, then `The
  Pecron login was rejected: check Email, Password and Region under Pecron
  account.` and the app retries every 300 s.
- Automatic with local details for every device: the app **keeps running** on
  the local network and logs `Cloud login failed (...), falling back to offline
  mode`, then `Cloud retry failed: ...`. An unreachable cloud produces the same
  messages; the text in brackets says which. Correct the options and restart.

### Wrong local auth key

The log shows `Login rejected (result=...)` for the local connection. Copy
`auth_key` for that device again, running the wizard again if necessary.

### A device never gets values or stays unavailable

`No reading from ... marking it unavailable in Home Assistant` names the device.

- Local: set **Log level** to `debug`, restart and look for `Local connect
  failed`. Check that the unit is on, the LAN IP address is right (use a DHCP
  reservation) and Home Assistant can reach that network.
- Cloud: look for `not found or not bound` (check the device key; that device
  gets no entities), `OFFLINE (device may not be connected to WiFi/internet)`
  (check the unit in the Pecron app) or `No valid devices found`. A `code 4007`
  warning ("device is not bound") can be ignored while data still arrives.
- `code 4026` or `Insufficient resources`: the [cloud quota](#cloud-quota) is
  used up. Raise the poll interval and restart; the limit resets at 00:00 UTC.
- Devices that flap between values and unavailable: raise **Unavailable after**.

### No entities at all (broker refuses the credentials)

A broker that rejects the username or password produces **no error message**. Set
**Log level** to `info` or more detailed and restart. If there is no `Home
Assistant MQTT bridge connected` line, no `Ready:` line and no entities, check
**Broker username** and **Broker password**, or clear the `mqtt` options to use
Mosquitto automatically.

`Cannot connect to MQTT broker at ...` means the broker could not be reached;
check that it is running and that host and port are right.

### Entities flap and the broker keeps disconnecting

Repeated `Home Assistant MQTT bridge disconnected` and `connected` lines usually
mean a second Pecron bridge uses the same broker, such as the old community app
or `pecron-monitor` on another computer. Stop one of them.

### Restarts and retries

- Configuration errors stop the app. It does not retry.
- If pecron-monitor exits, or Home Assistant's MQTT service is not available,
  the app logs the reason and `Retry N in ... s`. Delays grow through 5, 10, 20,
  40, 80, 160 and 300 s, and start over after a run of 10 minutes or more. A
  rejected login waits 300 s straight away.
- `Unexpected error:` followed by a traceback stops the app. Please report it,
  after [removing private data](#security-and-privacy).

### Running diagnostics from your computer

1. Stop the app.
2. In the `pecron-setup` folder, activate the environment again (`source
   venv/bin/activate`).
3. **Make sure `config.yaml` there says `rules: []`.** With the wizard's example
   rule, a diagnostic run can switch AC output off.
4. Run `pecron-monitor --diagnose` (login, device check and a short data test)
   or `pecron-monitor --controls` (lists the controls of each device). Both need
   the cloud.
5. Start the app again.

Their output is not redacted. Do not run plain `pecron-monitor`, `--ac`, `--dc`,
`--control` or `--probe-control` for troubleshooting.

## Removing a device and uninstalling

To remove one device:

1. Delete its entry under **Devices**, save and restart the app.
2. Open **Settings > Devices & services > MQTT**, open the device `Pecron
   <model> (<device key>)`, and delete it from its menu.

Also remove its block from `pecron-setup.yaml` to avoid a warning. The app needs
at least one device; to remove the last one, uninstall.

To uninstall:

1. Stop the app and uninstall it. Its private data is deleted. The app config
   folder, including `pecron-setup.yaml`, is **kept** unless you enable **Also
   delete the app's configuration folder** in the dialog.
2. Delete each Pecron device under **Settings > Devices & services > MQTT**.
3. Delete any copies of `config.yaml` or `pecron-setup.yaml` on your computer.

## Migrating from the old community app

This is for users of
[Pecron Monitor Streamer](https://github.com/mat1990dj/ha-apps/tree/main/pecron_monitor).

1. Create a Home Assistant backup and note the entity IDs your dashboards and
   automations use.
2. **Stop the old app and turn off its Start on boot.** Both apps use the same
   MQTT client id, so they must not run together.
3. Install this app and configure it:

   | Old option | New option |
   |---|---|
   | `pecron_account.username` | `account.email` |
   | `pecron_account.password`, `.region` | `account.password`, `account.region` |
   | `device_information.device_name` | `devices.model` (use the real model name) |
   | `device_information.product_key`, `.device_key`, `.auth_key`, `.lan_ip` | `devices.product_key`, `.device_key`, `.auth_key`, `.lan_ip` |
   | `device_information.connection_mode` | `connection_mode` |
   | `mqtt_settings` | Leave `mqtt` empty to use Mosquitto |

4. Start it and verify: the `Ready:` line, current values for each unit, and
   your dashboards and automations. Review automations that switch outputs before
   enabling them on new entities.
5. To roll back, stop this app (turn off its Start on boot) and start the old one
   again.
6. When you are satisfied, uninstall the old app.

**Device keys are upper-cased.** A 12-hex device key typed in lower case in the
old app yields **new entity IDs** here: update dashboards and automations. The
old lower-case device remains under MQTT; delete it once you no longer need to
roll back. Whether other entity IDs carry over has not been measured yet.

## Security and privacy

- Home Assistant backups include the app options, the setup file and the app's
  private data, which holds a generated configuration with your password and
  keys. Protect your backups.
- In the app log, your email, passwords and auth keys are replaced with `***`.
  **Device keys are not redacted.** Before posting a log, also remove device
  keys (they appear in entity names and topics), IP addresses and the account
  user id after `Logged in as`. Review debug logs especially carefully: they
  include raw device and cloud data.
- Never post `config.yaml` or `pecron-setup.yaml`.

## Credits

All device communication is done by
[pecron-monitor](https://github.com/attractify-logan/pecron-monitor) by
attractify-logan and contributors.
