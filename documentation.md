# Homely Integration Documentation

This file contains practical details for users who want more than quick setup.

## Home index

`Home index` selects which home in your Homely account is used by this config entry.

- `0` = first home
- `1` = second home
- `2` = third home

If you have multiple homes, add one integration entry per home index.

## Battery status values

### Per-device battery sensors

Battery values come from each device's battery feature.

- `battery_low`: boolean (`true`/`false`)
- `battery_defect`: boolean (`true`/`false`)
- `battery_voltage`: numeric value (voltage), if provided by API

`true` on `battery_low` or `battery_defect` means that device has a battery issue.

### Aggregate battery sensor

The integration creates a location-level sensor named `Status of batteries`.

- Home Assistant state `on` = at least one device reports low/defective battery
- Home Assistant state `off` = no low/defective battery detected
- Extra attribute `status = "Defective"` when state is `on`
- Extra attribute `status = "Healthy"` when state is `off`

## Alarm state values

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

Practical lock-related binary sensors are also exposed when present in API data:

- `Door` (`device_class: door`) from `features.report.states.doorclosed` (mapped so `on = open`)
- `Low Battery` (`device_class: battery`) from `features.report.states.lowbat`
- `Jammed` (`device_class: problem`) from `features.report.states.Broken/broken`

## WebSocket status sensor values

The WebSocket status sensor can show:

- `Not initialized`
- `Connecting`
- `Connected`
- `Disconnected`

When available, the `reason` attribute contains the latest disconnect/connect reason.

### Remove Stale Devices

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
