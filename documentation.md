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

## WebSocket status sensor values

The WebSocket status sensor can show:

- `Not initialized`
- `Connecting`
- `Connected`
- `Disconnected`

When available, the `reason` attribute contains the latest disconnect/connect reason.

## Polling and WebSocket behavior

- WebSocket applies supported updates directly to cached data for fast state updates.
- Polling still runs at your configured interval as fallback and data consistency check.
- If WebSocket disconnects, reconnect attempts run continuously every 5 minutes.
