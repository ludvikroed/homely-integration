# Homely Alarm Integration for Home Assistant

A custom Home Assistant integration that connects your Homely alarm system with Home Assistant, providing real-time monitoring of your alarm and connected devices available through the Homely API.

---

## Installation & Setup

### Via HACS (Recommended)

1. Open HACS in Home Assistant
2. Search for "Homely" and click "Download"
3. Restart Home Assistant

> **Note**: Not in yet HACS default? Add as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories/): `https://github.com/ludvikroed/homely-integration`

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

---

## Advanced Configuration

- **Polling interval**: Adjust API polling frequency (backup for websockets)
- **Multiple homes**: Add integration for each home ID (0, 1, 2...)
- **WebSocket toggle**: Enable/disable instant updates

### Enable Debug Logging

To troubleshoot issues or monitor WebSocket and API activity, add to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.homely: debug
    custom_components.homely.websocket: debug
    custom_components.homely.api: debug
    custom_components.homely.config_flow: debug
```

Then restart Home Assistant and check the logs under **Settings** → **System** → **Logs**.

---

## Troubleshooting

Please open an issue if you have problems after reading the troubleshooting guide
### Integration Won't Load

- Verify your Homely username and password are correct
- Check the home ID. This is 0 if you only have one Homely home

### WebSocket Not Connecting

**Symptoms**: Updates take 2 minutes instead of being instant

Enable debugging (shown above) and check HA logs for:
```yaml
# Look for these log messages:
# "WebSocket connection established"
# "WebSocket connected"
# "WebSocket connection failed"
```

---

## Supported Devices

### Fully Supported
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
- Direct device control (read-only integration)

> **Note**: This integration is only tested with smoke detectors, alarm panel, door sensors, and motion sensors. Please report issues with other device types if you find any.

---

## Contributing

Contributions welcome! [Report bugs or suggest features](https://github.com/ludvikroed/homely-integration/issues).

> ⭐ If you find this integration useful, please consider giving it a star on [GitHub](https://github.com/ludvikroed/homely-integration)!

---

## About

**License**: MIT License - see [LICENSE](LICENSE)

**Created by**: [Ludvik](https://github.com/ludvikroed) | Inspired by [Homely MQTT Add-on](https://github.com/haugeSander/Homely-HA-Addon)

**Disclaimer**: Unofficial project, not affiliated with Homely. Relies on Homely's cloud API which may change.

---
