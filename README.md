# Homely Alarm Integration for Home Assistant

A custom Home Assistant integration that connects your Homely alarm system with Home Assistant, providing real-time monitoring of your alarm and connected devices.

---

## Features

- **Easy Setup** - Simple installation via HACS, no add-ons or MQTT required
- **Device Monitoring** - Automatic discovery of most of your connected sensors (temperature, motion, door/window, etc.)
- **Battery Monitoring** - Track battery levels for all wireless devices
- **Multi-Location Support** - Support for multiple Homely locations/homes
- **WebSocket Status Sensor** - Monitor connection health

---

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Search for "Homely"
3. Click "Download"
4. Restart Home Assistant
5. Go to **Settings** → **Devices & Services**
6. Click **"+ Add Integration"**
7. Search for "Homely" and configure with your credentials

> **Note**: If the integration is not yet available in HACS default repository, you can add it as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories/) using `https://github.com/ludvikroed/homely-integration`

### Manual Installation

1. Download the latest release from [GitHub](https://github.com/ludvikroed/homely-integration/releases)
2. Extract the `homely` folder from the archive
3. Copy the `homely` folder to your Home Assistant's `custom_components` directory
   - Path: `/config/custom_components/homely/`
4. Restart Home Assistant

---

## Configuration

### Setup via UI

1. Go to **Settings** → **Devices & Services**
2. Click **"+ Add Integration"**
3. Search for **"Homely Alarm"**
4. Enter your credentials:
   - **Username**: Your Homely account email
   - **Password**: Your Homely account password
   - **Home ID**: Use `0` for your first/only home
5. Click **"Submit"**

> **Multiple Homes?** If you have multiple locations in your Homely account, add the integration once for each location. First add with Home ID `0`, then add the integration again with Home ID `1`, etc.

The integration will automatically:
- Authenticate with the Homely API
- Fetch your location name and use it as the integration title
- Create entities for your alarm panel
- Discover all connected devices and create appropriate sensors
- Establish a WebSocket connection for real-time updates

---

## Entities Created

### Alarm Control Panel

- **Entity**: `alarm_control_panel.<location_name>_alarm`
- **States**: 
  - `disarmed` - Alarm is off
  - `armed_away` - Full alarm activation
  - `armed_home` - Home mode (partial activation)
  - `arming` - Countdown/pending state
  - `triggered` - Alarm has been triggered

### Sensors

Automatically discovered based on your connected devices:

- **Temperature Sensors** - Current temperature readings
- **Signal Strength** - Device connectivity status (RSSI)
- **Battery Levels** - Battery percentage for wireless devices
- **Device States** - Custom sensors based on device capabilities

### Binary Sensors

- **Door/Window Sensors** - Open/closed state
- **Motion Sensors** - Motion detected/clear
- **Battery Low Warnings** - Low battery alerts
- **Device Alerts** - Various device-specific alerts

### Diagnostic Sensors

- **WebSocket Status** - Connection state (`connected`, `disconnected`, `reconnecting`)
- Shows connection health

---

## Advanced Configuration

### Enable Debug Logging

To troubleshoot issues or monitor WebSocket activity, add to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.homely: debug
    custom_components.homely.websocket: debug
    custom_components.homely.api: debug
```

Then restart Home Assistant and check the logs under **Settings** → **System** → **Logs**.


## WebSocket Integration

This integration uses WebSocket for real-time updates, with polling every 2 minutes as a fallback for redundancy if the WebSocket connection fails.

---

## Troubleshooting

### Integration Won't Load

**Symptoms**: Integration fails during setup

**Solutions**:
- Verify your Homely username and password are correct

### WebSocket Not Connecting

**Symptoms**: Updates take 2 minutes instead of being instant

**Check**:
```yaml
# Look for these log messages:
# "WebSocket connection established"
# "WebSocket connected"
# "WebSocket connection failed"
```

---

## Supported Devices

This integration supports all devices accessible through the Homely API:

### Fully Supported

- Temperature sensors
- Motion detectors (PIR)
- Door/window sensors (magnetic contacts)
- Smoke detectors
- Water leak sensors
- Smart plugs (status monitoring)
- Wireless devices with battery reporting
- Alarm control panel

> **Note**: I have only tested the smoke detector, alarm control panel, door sensors, and motion sensors. Please open an issue if you encounter problems with other device types.

### Not Supported

- Yale Doorman (not available via API)
- Direct device control (read-only integration)
- Some proprietary vendor-specific devices

> **Note**: This is a monitoring integration. Device control (e.g., turning on/off switches) is not currently supported by the Homely API.

---

## Contributing

Contributions are welcome! 

### Reporting Bugs

1. Check if the issue already exists in [Issues](https://github.com/ludvikroed/homely-integration/issues)
2. Create a new issue with:
   - Home Assistant version
   - Integration version
   - Detailed description of the problem
   - Relevant log entries (with sensitive data removed)

### Suggesting Features

Open an issue with the `enhancement` label and describe:
- The feature you'd like to see
- Why it would be useful
- How it might work

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Disclaimer

This is an unofficial community project and is not affiliated with, endorsed by, or connected to Homely. 

The integration relies on Homely's cloud API, which may change. While efforts are made to keep the integration working, functionality may break if Homely modifies their API.

---

## Credits

- Created by [Ludvik](https://github.com/ludvikroed)
- Inspired by the [Homely MQTT Add-on](https://github.com/haugeSander/Homely-HA-Addon) by haugeSander

---

## Star History

If you find this integration useful, please consider giving it a star on GitHub!

---