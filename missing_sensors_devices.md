# Missing Sensors or Devices

Before reporting a missing device or sensor, make sure you are using the latest version of the integration.

Use this guide if:
- a device is missing completely from Home Assistant
- a device is present, but expected sensors are missing

## Why this happens

The integration can only create entities from data exposed by the Homely API.

That means one of these is usually true:
- the device is available in the API, but this integration does not map all of its states yet
- the device or sensor is not exposed by the Homely API at all

## What to send

For missing devices or missing sensors, diagnostics is usually all I need.

1. Open the Homely integration in Home Assistant.
2. Download the diagnostics file for the affected entry.
3. Open a GitHub issue and attach the diagnostics file.
4. Include a short description of what is missing.

Issue tracker: <https://github.com/ludvikroed/homely-integration/issues>

## What to write in the issue

- Device name as shown in Homely or Home Assistant
- Device type/model if known
- Whether the whole device is missing, or only some sensors
- What entities you get now
- What entities or sensors you expected
- Which Homely location/entry the issue applies to
- Integration version and Home Assistant version

## About debug logging

You normally do **not** need debug logging for this kind of issue.

Debug logging is only useful if diagnostics is not enough, or if the problem is more about setup, login, or websocket behavior than missing devices/sensors.
