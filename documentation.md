# Homely Integration Documentation

This document describes the integration's entities, runtime behavior, recovery mechanisms, and known limitations. See [README.md](README.md) for installation and initial setup.

## Setup and multiple homes

The config flow authenticates with Homely and retrieves the homes available to the account.

- An account with one home is configured directly.
- An account with multiple homes shows a home selector.
- **Add all homes** creates one config entry per home and skips homes that are already configured.
- Duplicate config entries for the same Homely location are prevented.
- To replace a configured home with a different one, remove the old config entry and run setup again.

WebSocket and API behavior is managed by the integration and has no user-configurable polling options.

## Devices and entities

The integration creates entities from the features included in each Homely API device payload. Entity availability therefore varies by device model, firmware, and what Homely exposes for the account.

Typical coverage includes:

| Device or service | Entities that may be created |
| --- | --- |
| Homely home | Alarm control panel, Battery problem, Live update connection status, Last cloud API poll |
| Motion sensor | Motion, Temperature, Battery low |
| Door/window sensor | Contact, Temperature, Battery low |
| Smoke detector | Fire, Tamper, Temperature, Battery low |
| Flood alarm | Flood, Temperature, Battery low |
| HAN meter | Consumption, Production, Demand, Metering check |
| Compatible lock | Lock state, Door, Low battery, Jammed, Error code, Language, Sound volume |

An **Online** diagnostic binary sensor is also created for each API device. Other diagnostic entities can include battery voltage, link quality, network address, battery defect, and metering check.

The table lists common examples, not a fixed compatibility guarantee. A device shown in the Homely app may be missing from the API or expose only some features. The integration cannot create a device or entity for data that Homely does not provide. Use the [Missing device or sensor form](https://github.com/ludvikroed/homely-integration/issues/new?template=missing_sensors_devices.yml) and attach diagnostics when coverage is incomplete.

### Read-only behavior

The available Homely API is read-only. Alarm and lock entities report state, but commands to arm, disarm, lock, or unlock are not supported. Automations can use the reported states as triggers and conditions.

### Battery problem

The home-level **Battery problem** binary sensor is `on` when any device reports a low or defective battery, including compatible locks that report `lowbat`. It is `off` when known battery states report no problem and `unknown` when the snapshot contains no usable battery state. Cached device data can keep the last known result available during a temporary API outage.

## Alarm state and event metadata

The alarm control panel maps Homely states to these Home Assistant states:

- `disarmed`
- `armed_home`
- `armed_away`
- `armed_night`
- `arming`
- `triggered`

When Homely includes user information in completed arm or disarm events, the alarm entity may expose:

- `last_armed_by`
- `last_armed_user_id`
- `last_armed_at`
- `last_armed_device_id`
- `last_disarmed_by`
- `last_disarmed_user_id`
- `last_disarmed_at`
- `last_disarmed_device_id`

These attributes are event metadata and are stored with the cached alarm state. They are not guaranteed to be present, and events sent while Home Assistant is offline cannot be recovered unless Homely includes the same information in a later event.

## WebSocket and API synchronization

WebSocket live updates are always enabled. Alarm changes and supported device-state changes are applied as events arrive. The WebSocket is the primary source of live state changes.

The Homely `/home` endpoint provides the complete location and device snapshot. It is requested:

- during startup
- every 24 hours
- after a WebSocket failure when the connection does not recover quickly

An existing installation with a valid cached snapshot loads entities from cache without waiting for the startup `/home` request to finish. The request starts immediately in the background and replaces cached values when it succeeds.

On first setup without cache, the integration waits for the initial `/home` request to finish. If the request fails, the integration can still load location-level alarm and diagnostic entities in WebSocket-only mode. Device entities are added after a later successful full snapshot.

When the WebSocket disconnects, the integration requests a reconnect first. An API fallback is delayed briefly so short disconnects do not cause unnecessary `/home` requests.

### API failures and retry schedule

After an API error, retries use this backoff schedule:

- 3 minutes
- 10 minutes
- 30 minutes
- 1 hour
- 2 hours
- 6 hours

Transient API, rate-limit, and network failures use valid cached data when possible. A malformed or incomplete payload is not accepted as a valid device snapshot.

### State after downtime

WebSocket events are not a replayable history. If state changes while Home Assistant is offline, cached values can be briefly out of date after restart. The startup `/home` synchronization reconciles the current alarm and device snapshot when the endpoint is available.

During an API outage:

- WebSocket alarm and device events can continue updating supported values indefinitely.
- The last valid snapshot remains available from cache without an age-based expiry.
- New or removed devices cannot be reconciled until a valid full snapshot arrives.
- A new installation without cache may have no device entities.
- If both the API and WebSocket are unavailable, entities keep their last known values. Use the diagnostic status sensors and cache age to determine whether those values may be stale.

## Diagnostic status entities

The Homely home device includes two always-available diagnostic sensors.

### Live update connection status

State values:

- `not_initialized`
- `connecting`
- `connected`
- `disconnected`
- `unknown`

Home Assistant translates these values in the UI. Attributes can include:

- `reason`: current WebSocket status reason
- `reported_status`: SDK-reported status when it differs from effective transport state
- `last_disconnect_reason`: latest retained disconnect reason

### Last cloud API poll

State values:

- `not_run`
- `success`
- `failed`
- `failed_<code>`, such as `failed_429`, `failed_439`, or `failed_503`
- `unknown`

Attributes can include:

- `last_poll_at`
- `status_code`
- `last_error_code`
- `detail`
- `next_retry_at`
- `retry_status_code`
- `retry_delay_seconds`

The WebSocket status and API poll status are separate. A failed API poll does not mean live updates are disconnected, and a disconnected WebSocket does not necessarily mean the API is unavailable.

## Device additions, removals, and Repairs

When a valid snapshot contains new devices, the integration saves the snapshot before reloading the config entry so the corresponding entities can be created.

A missing device is not accepted from a single snapshot. The same removal must appear in two consecutive valid snapshots. API errors, invalid payloads, and cache fallback do not count as confirmation.

After confirmation:

- The stale Home Assistant device is kept for manual review and removal.
- One warning appears under **Settings > System > Repairs** for the affected Homely home.
- The Repair lists stale device names.
- The Repair closes if the device returns, is deleted from Home Assistant, or the Homely config entry is removed.

To delete a confirmed stale device:

1. Go to **Settings > Devices & services > Homely**.
2. Open the stale device.
3. Select **Delete device**.

The integration blocks deletion of devices that are still present in the current accepted snapshot. The virtual Homely home device is also protected.

## Reauthentication after a password change

If Homely explicitly rejects the stored email address or password, Home Assistant starts its standard reauthentication flow. Open the reauthentication notification from the Homely integration or Repairs dashboard, enter the updated credentials, and submit the form. The integration validates that the configured Homely home is still available before saving the new credentials and reloading.

Temporary connection failures do not start reauthentication; the integration keeps cached data and retries instead.

## Troubleshooting and diagnostics

### Enable debug logging

Use **Enable debug logging** from the Homely integration menu, or add:

```yaml
logger:
  default: info
  logs:
    custom_components.homely: debug
    homely: debug
```

The `homely` logger includes SDK and WebSocket details. Restart Home Assistant after changing YAML logger configuration.

### Download diagnostics

Open **Settings > Devices & services > Homely**, select the affected config entry, open its menu, and download diagnostics. Diagnostics include runtime health and the latest available API snapshot with selected identifiers redacted. Review the file before sharing it because device state and names may still be present.

System Health also reports integration and SDK versions, loaded entries, API availability, WebSocket status, device counts, and cache/poll age.

### Report an issue

- [Setup or login problem](https://github.com/ludvikroed/homely-integration/issues/new?template=setup_or_login_problem.yml)
- [Missing device or sensor](https://github.com/ludvikroed/homely-integration/issues/new?template=missing_sensors_devices.yml)
- [Bug report](https://github.com/ludvikroed/homely-integration/issues/new?template=bug_report.yml)
- [Feature request](https://github.com/ludvikroed/homely-integration/issues/new?template=feature_request.yml)

Include the integration version, Home Assistant version, relevant logs, and diagnostics where appropriate.

## Known limitations

- The integration depends on Homely cloud services and is not suitable for fully local operation.
- Direct alarm and lock control is unavailable.
- WebSocket events that occurred while Home Assistant was offline are not replayed.
- Device and entity coverage is limited to data exposed by the Homely API.
- API or WebSocket behavior can change independently of this project.
