# Homely Integration Documentation

This file contains practical details for users who want more information about this integration than just the README file

## API coverage and missing devices

The integration aims to support all devices and sensors exposed by the Homely API.

Not every device shown in the Homely app is exposed through the API. If Homely does not expose a device or sensor, the integration cannot add it in Home Assistant. Some vendor-specific devices, such as the Namron Smart Plug 16A, are known examples.

The Homely API is read-only for now. Many users have contacted Homely by email to ask whether write access is planned, but the replies have varied. Based on those replies, it currently seems that Homely does not have plans to add write access.

If a device is missing, or a device only shows partial data, use the [Missing device or sensor issue form](https://github.com/ludvikroed/homely-integration/issues/new?template=missing_sensors_devices.yml).

When Homely adds or removes devices on a home, the integration reloads the config entry automatically. New devices can then appear automatically. Devices that disappear from the API are not deleted automatically.

## Supported device types

All Frient devices should be supported. Most locks and other devices shown in the Homely app should also be available. Some vendor-specific devices, such as the Namron Smart Plug 16A, are currently not exposed through the API and therefore cannot be supported. The goal is to support all devices and sensors available through the Homely API, but sadly not every device shown in the Homely app is necessarily available through that API.
If a device is missing, or a device is present but missing sensors, please use the Missing device or sensor issue form.
The Homely API is read-only for now. Many users have contacted Homely by email to ask whether direct device control is planned, but the responses have varied. Based on those replies, it currently seems that Homely does not have plans to add direct device control.

| Device type | Typical entities |
| --- | --- |
| Home | Alarm status, WebSocket status, Battery status, Online |
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

Advanced runtime settings such as polling interval and WebSocket behavior live in the integration **Options** flow, not in the initial login step.

## Key states and values

### Alarm states

Possible alarm states shown in Home Assistant:

- `disarmed`
- `armed_home`
- `armed_away`
- `armed_night`
- `arming`
- `triggered`

### Battery status

`Status of batteries` is `on` when at least one device reports a low or defective battery. It is `off` when no battery problem is detected.

### WebSocket status

The WebSocket status sensor can show:

- `Not initialized`
- `Connecting`
- `Connected`
- `Disconnected`

When available, `reason` shows the current websocket reason and `last_disconnect_reason` keeps the latest disconnect reason after reconnect.

## Reauthentication

If Homely rejects stored credentials, Home Assistant can start a reauthentication flow for the integration.

- Open the repair or reauthentication prompt in Home Assistant
- Enter updated Homely credentials
- The config entry reloads with the new credentials

## Remove stale devices

If Homely stops reporting a device, you can remove it manually in Home Assistant:
1. Go to **Settings** → **Devices & Services** → **Homely**.
2. Open the stale device.
3. Click **Delete device**.

The integration only allows deleting Homely devices that are no longer present in the latest API data. The home device itself is protected and cannot be deleted.

## Polling and WebSocket behavior

- `Enable WebSocket = on` and `Polling while WebSocket is connected = on`:
  Polling continues at the configured interval, and WebSocket provides live updates.
- `Enable WebSocket = on` and `Polling while WebSocket is connected = off`:
  Polling pauses while WebSocket is connected. If WebSocket disconnects, the integration requests an immediate refresh and then continues polling until WebSocket reconnects.
- `Enable WebSocket = off`:
  Polling-only mode.

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
