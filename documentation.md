# Homely Integration Documentation

This file contains practical details for users who want more than quick setup.

## API coverage and missing devices

Some devices that are fully supported in the Homely app may still be missing in Home Assistant if Homely does not expose them through the API. In other cases, the device may be available through the API, but the integration may not map all available states yet.

If a device is missing, or a device only shows partial data, follow [missing_sensors_devices.md](missing_sensors_devices.md).

When Homely adds or removes devices on a location, the integration detects the topology change and reloads the config entry automatically so the entity list stays in sync.

## Location selection

The config flow now selects locations by the actual Homely location name returned by the API.

- If your account has only one location, it is selected automatically during setup.
- If your account has multiple locations, Home Assistant shows a location picker.
- Add the integration multiple times, once per location, if you want more than one location in Home Assistant.
- The integration prevents adding the same location twice.
- Use **Reconfigure** if you want to switch an existing entry to a different location on the same account. The integration clears the old entry registry bindings before reloading, so stale entities from the previous location are not kept.

Advanced runtime settings such as polling interval and WebSocket behavior live in the integration **Options** flow, not in the initial login step.

## Battery status values

### Per-device battery sensors

Battery values come from each device's battery feature.

- `battery_low`: boolean (`true`/`false`)
- `battery_defect`: boolean (`true`/`false`)
- `battery_voltage`: numeric value (voltage), if provided by API

`true` on `battery_low` or `battery_defect` means that device has a battery issue.

### Aggregate battery sensor

The integration creates a location-level binary sensor named `Status of batteries`.

- Home Assistant state `on` = at least one device reports low/defective battery
- Home Assistant state `off` = no low/defective battery detected
- Extra attribute `status = "Defective"` when state is `on`
- Extra attribute `status = "Healthy"` when state is `off`
- Some lock devices, such as Yale Doorman, report battery state through `features.report.states.lowbat`

## Alarm state values

The alarm entity reflects the current alarm status reported by the API. Alarm control commands are not currently sent through this integration.

Possible alarm states shown in Home Assistant:

- `disarmed`
- `armed_home`
- `armed_away`
- `armed_night`
- `arming`
- `triggered`

## Lock support (Yale Doorman and similar)

Lock devices that expose `features.lock.states.state.value` are created as Home Assistant lock entities.

- `locked` when value is `true`
- `unlocked` when value is `false`

The lock entity is currently read-only (no lock/unlock command is sent to Homely).

When available, the lock entity may also expose extra attributes such as:

- `door_closed`
- `low_battery`
- `part_of_alarm`
- `lock_model`
- `error_code`

Practical lock-related binary sensors are also exposed when present in API data:

- `Door` (`device_class: door`) from `features.report.states.doorclosed` (mapped so `on = open`)
- `Low Battery` (`device_class: battery`) from `features.report.states.lowbat`
- `Jammed` (`device_class: problem`) from `features.report.states.Broken/broken`

Additional lock/config sensors may be exposed when available:

- `Error Code`

## Flood alarm support

Flood alarms are exposed from `features.alarm.states.flood` and can also provide:

- temperature
- battery status
- diagnostic link sensors

## HAN meter support

HAN devices such as `EMI Norwegian HAN` expose:

- `Consumption` from `summationdelivered`, converted from Wh to kWh
- `Production` from `summationreceived`, converted from Wh to kWh
- `Demand` from `demand`, shown in W
- `Metering Check`
- diagnostic link sensors

## WebSocket status sensor values

The WebSocket status sensor can show:

- `Not initialized`
- `Connecting`
- `Connected`
- `Disconnected`

When available, the `reason` attribute contains the latest disconnect/connect reason.

## Reauthentication

If Homely rejects stored credentials, Home Assistant can start a reauthentication flow for the integration.

- Open the repair or reauthentication prompt in Home Assistant
- Enter updated Homely credentials
- The config entry reloads with the new credentials

## Diagnostics

The integration exposes diagnostics data for support and debugging.

- credentials and tokens are redacted
- device ids, serial numbers, and location identifiers are redacted
- websocket status, cache age, last successful poll age, and last websocket event are included in sanitized form

## System health

The integration exposes Home Assistant system health information for each loaded Homely entry, including:

- config entry state
- scan interval and WebSocket-related options
- API availability
- WebSocket status and last reason
- whether the WebSocket is currently connected
- age of the last successful poll
- age and type of the last websocket event
- cache age for the latest data the integration is serving
- tracked device count

## Documentation status

- `manifest.json` currently points to this repository's `documentation.md`, because the official Home Assistant docs page is not live yet.
- The submission-ready Home Assistant documentation draft lives in [`homely.markdown`](homely.markdown).
- Importable automation blueprints that match the draft examples live in [`blueprints/automation/homely`](blueprints/automation/homely).

## Remove stale devices

If Homely stops reporting a device, you can remove it manually in Home Assistant:
1. Go to **Settings** → **Devices & Services** → **Homely**.
2. Open the stale device.
3. Click **Delete device**.

The integration only allows deleting device-level Homely devices that are no longer present in the latest API data. Location-level Homely devices are protected and cannot be deleted.

## Polling and WebSocket behavior

- WebSocket applies supported updates directly to cached data for fast state updates.
- Reconnect attempts run continuously every 5 minutes when disconnected.

Behavior depends on your options:

- `Enable WebSocket = on` and `Polling while WebSocket is connected = on`:
  Polling continues at configured interval, and WebSocket gives extra real-time updates.
- `Enable WebSocket = on` and `Polling while WebSocket is connected = off`:
  Polling pauses while WebSocket is connected. If WebSocket disconnects, the integration requests an immediate refresh and then continues normal polling until WebSocket reconnects at configured interval.
- `Enable WebSocket = off`:
  Polling-only mode.

### Should polling stay on when WebSocket is on?

- Keep polling `on` if you want periodic full refresh in addition to live events.
  This can be useful if some device data changes are not always pushed as WebSocket events, or if you prefer extra safety against missed events.
- Set polling `off` if you want lower API traffic and mostly real-time updates from WebSocket only.
  This is typically fine when WebSocket events cover your use case well.

Practical tradeoff: `on` = more robust consistency, `off` = less API load.
