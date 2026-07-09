# Homely Integration Documentation

Looking for installation, setup, and the short overview? See [README.md](README.md).

This file contains practical details for users who want more information than the README gives.

## API coverage and missing devices

The integration aims to support all devices and sensors exposed by the Homely API.

Not every device shown in the Homely app is exposed through the API. If Homely does not expose a device or sensor, the integration cannot add it in Home Assistant. Some vendor-specific devices, such as the Namron Smart Plug 16A, are known examples.

The Homely API is read-only for now, so this integration focuses on monitoring and status in Home Assistant.

If a device is missing, or a device only shows partial data, use the [Missing device or sensor issue form](https://github.com/ludvikroed/homely-integration/issues/new?template=missing_sensors_devices.yml).

When Homely adds or removes devices on a home, the integration reloads the config entry automatically. New devices can then appear automatically. Devices that disappear from the API are not deleted automatically.

## Supported device types

All Frient devices should be supported. Most locks and other devices shown in the Homely app should also be available. Some vendor-specific devices, such as the Namron Smart Plug 16A, are currently not exposed through the API and therefore cannot be supported. The goal is to support all devices and sensors available through the Homely API, but not every device shown in the Homely app is necessarily available through that API.
If a device is missing, or a device is present but missing sensors, please use the Missing device or sensor issue form.
Direct device control is not available because the Homely API is read-only.

| Device type | Typical entities |
| --- | --- |
| Home | Alarm status, WebSocket status, Last cloud API poll, Battery status |
| Frient motion sensors | Motion, Temperature, Battery low, Online |
| Frient door/window sensors | Contact, Temperature, Battery low, Online |
| Frient smoke detectors | Fire, Tamper, Temperature, Battery low, Online |
| Frient flood alarms | Flood, Temperature, Battery low, Online |
| Frient HAN meters | Consumption, Production, Demand, Metering Check, Online |
| Most locks | Lock, Door, Low battery, Jammed, Online |

## Location selection

The config flow now selects locations by the actual Homely location name returned by the API.

- If your account has only one location, it is selected automatically during setup.
- If your account has multiple locations, Home Assistant shows one location dropdown.
- The dropdown includes an `Add all homes` option together with the available individual locations.
- If you choose `Add all homes`, the integration creates the first entry during setup and then adds the remaining available locations automatically.
- `Add all homes` creates one config entry per available location.
- Locations that are already configured are skipped automatically.
- The integration prevents adding the same location twice.
- If you want to use a different location later, remove the existing entry and add the integration again for the desired location.
- Runtime behavior such as WebSocket and API polling is fixed by the integration and is not changed after setup.

## Key states and values

### Alarm states

Possible alarm states shown in Home Assistant:

- `disarmed`
- `armed_home`
- `armed_away`
- `armed_night`
- `arming`
- `triggered`

The alarm entity can also expose attributes from the last known `DISARMED` event:

- `last_disarmed_by`
- `last_disarmed_at`
- `last_disarmed_user_id`
- `last_disarmed_event_id`
- `last_disarmed_device_id`

These values are only available after Homely has sent a disarm event that includes user information.

### Battery status

`Status of batteries` is `on` when at least one device reports a low or defective battery. It is `off` when no battery problem is detected. The sensor can use cached device data when the API is temporarily unavailable.

### WebSocket status

The WebSocket status sensor can show:

- `Not initialized`
- `Connecting`
- `Connected`
- `Disconnected`

When available, `reason` shows the current websocket reason and `last_disconnect_reason` keeps the latest disconnect reason after reconnect.

### API poll status

The `Last cloud API poll` sensor shows the result of the most recent REST API poll:

- `not_run`
- `success`
- `failed`
- `failed_<code>`, for example `failed_429` or `failed_503`
- `unknown`

Attributes can include `status_code`, `last_error_code`, `detail`, `last_poll_at`, `next_retry_at`, `retry_delay_seconds`, and `retry_status_code`.

## Remove stale devices

If Homely stops reporting a device, you can remove it manually in Home Assistant:
1. Go to **Settings** → **Devices & Services** → **Homely**.
2. Open the stale device.
3. Click **Delete device**.

The integration only allows deleting Homely devices that are no longer present in the latest API data. The home device itself is protected and cannot be deleted.

## Polling and WebSocket behavior

WebSocket live updates are always enabled. The integration does not expose settings for turning WebSocket off or changing the polling interval after setup.

The Homely cloud API is polled:

- during startup
- once every 6 hours
- after a WebSocket failure if the WebSocket does not reconnect quickly

When WebSocket disconnects, the integration first asks the WebSocket client to reconnect. It waits briefly before polling the API, so short disconnects do not cause unnecessary polling.

If an API poll fails, the integration schedules a new API poll with backoff: 3 minutes, 10 minutes, 30 minutes, 1 hour, 2 hours, then 6 hours. The `Last cloud API poll` sensor shows the planned retry time in its attributes.

## API outage handling

The `/home` REST endpoint is the source of full device and battery data. Alarm changes are delivered by WebSocket as `alarm-state-changed` events.

**Alarm status without the API:**

- Alarm state is delivered by WebSocket, so it can keep updating even while the REST API is unavailable.
- The last alarm state is saved to disk and restored on restart, so after a Home Assistant restart it shows the **last known status right away** — you do not need to wait for a new event.
- It is only blank (`unknown`) on the very first setup, before any alarm event has been received. In that case, arm or disarm the alarm once to populate it.
- The WebSocket only sends *changes* (no initial snapshot). If the alarm changes while Home Assistant is off, the shown value can be briefly out of date until the next alarm event corrects it.
- If Homely includes user information when the alarm is disarmed, the alarm entity attributes show who last disarmed it.

**What is limited while the API is down:**

- Per-device sensors rely on the latest device snapshot from the API or cache. A fresh install with no cached data may have no per-device entities until the API works.
- Battery status can keep using cached data, but it cannot learn new battery changes until the API reports fresh device data.
- The **Last cloud API poll** sensor shows the result of the latest REST poll, while the **WebSocket status** sensor shows the live-update connection.

## Contributing

Contributions are very welcome, and I really appreciate everyone who takes the time to help improve this integration.

### Reporting issues

If something does not work as expected, please open a GitHub issue and choose the matching form:

- [Bug report form](https://github.com/ludvikroed/homely-integration/issues/new?template=bug_report.yml)
- [Missing device or sensor issue form](https://github.com/ludvikroed/homely-integration/issues/new?template=missing_sensors_devices.yml)
- [All issue forms](https://github.com/ludvikroed/homely-integration/issues/new/choose)

##### Ideas and contributions

If you have an idea, a feature request, or something that should be improved, please open a GitHub issue.

##### Pull requests

Before opening a pull request, run:

- `python -m ruff check custom_components tests`
- `pytest`
- `python -m mypy --config-file mypy.ini -p custom_components.homely`
