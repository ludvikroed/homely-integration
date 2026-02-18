# Homely Alarm Integration for Home Assistant

A Home Assistant integration that connects your Homely alarm system with Home Assistant using the Homely api, providing real-time monitoring your alarm and most of your connected devices available through the API.

## Installation & Setup

### Via HACS (Recommended)

1. Open HACS in Home Assistant
2. Search for "Homely" and click "Download"
3. Restart Home Assistant

> **Note**: Not in yet HACS default? Add as a [custom repository](https://my.home-assistant.io/redirect/hacs_repository/?repository=https%3A%2F%2Fgithub.com%2Fludvikroed%2Fhomely-integration%3Ftab%3Dreadme-ov-file&owner=Ludvikroed&category=integration)

### Manual Installation

1. Download the [latest release](https://github.com/ludvikroed/homely-integration/releases)
2. Extract and copy the `homely` folder to `/config/custom_components/homely/`
3. Restart Home Assistant

### Configure

1. Go to **Settings** → **Devices & Services** → **"+ Add Integration"**
2. Search for **"Homely Alarm"**
3. Enter your Homely account credentials (username and password)
4. Click **"Submit"**

> **Multiple Homes?** Add the integration once per home using home ID 0, 1, 2, etc.

## Advanced Configuration

- **Polling interval**: Adjust API polling frequency shown in seconds (backup for websockets)
- **Multiple homes**: Add integration for each home ID (0, 1, 2...)
- **WebSocket toggle**: Enable/disable instant updates

---

## Troubleshooting steps:

- Verify your Homely username and password are correct
- Check the home ID. This is 0 if you only have one Homely home
- Websockets might take 10-30 seconds to connect
- Enable debugging (shown above) and check HA logs

If you can't resolve your problem, please open an issue.

### Enable Debug Logging

To troubleshoot issues or monitor WebSocket and API activity, go to the Homely integration, three dots in the upper right corner and select "Enable debug logging"

Then check the logs under **Settings** → **System** → **Logs**.

---

## Supported Devices

### Fully Supported:
- Alarm status
- Temperature sensors
- Motion detectors
- Door/window sensors
- Smoke detectors
- Water leak sensors
- Smart plugs (status monitoring)
- HAN meter (energy consumption/production)

### Not Supported
- Yale Doorman (not available via API)
- Some vendor specific devices
- Direct device control (The Homely API is read-only)

> **Note**: This integration is not tested with all devices supported through the Homely API. Please open an issue if you are missing devices or features.

### Battery Status
The integration provides a sensor called `Status of batteries` that shows the overall battery health for most devices. If any device reports a battery as low or defective, the sensor state will be `Defective`. If all batteries are healthy, the sensor state will be `Healthy`.

---

## Contributing

Contributions welcome! [Report bugs or suggest features](https://github.com/ludvikroed/homely-integration/issues).

> ⭐ If you find this integration useful, please consider giving it a star on [GitHub](https://github.com/ludvikroed/homely-integration)!

## About

**License**: MIT License - see [LICENSE](LICENSE)

**Created by**: [Ludvik](https://github.com/ludvikroed) | Inspired by [Homely MQTT Add-on](https://github.com/haugeSander/Homely-HA-Addon)

**Disclaimer**: Unofficial project, not affiliated with Homely. Relies on Homely's cloud API which may change.

---
