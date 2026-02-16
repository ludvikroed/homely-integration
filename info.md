# Homely Alarm Integration

Connect your Homely alarm system with Home Assistant for real-time monitoring and control.

## Features

- **Easy Setup** - Simple installation via HACS with config flow
- **Device Monitoring** - Automatic discovery of sensors (temperature, motion, door/window)
- **Battery Monitoring** - Track battery levels for all wireless devices
- **Multi-Location Support** - Support for multiple Homely homes
- **Real-time Updates** - WebSocket connection for instant status updates

## Supported Devices

### Security Sensors
- Door/window contact sensors
- Motion detectors (PIR sensors)
- Smoke/fire detectors
- Flood/water leak sensors
- Tamper detection

### Environmental Sensors
- Temperature sensors

### Energy Monitoring (HAN-compatible devices)
- Energy consumption (kWh)
- Energy production (kWh)
- Energy demand (kWh)

### Diagnostic & Status
- Signal strength (RSSI/dBm)
- Network link address
- Battery voltage
- Battery low warnings
- Battery defect alerts

## Configuration

After installation, go to **Settings** → **Devices & Services** → **Add Integration** and search for "Homely Alarm".

You'll need:
- Working homely alarm system
- Your Homely account email
- Your Homely account password

For more details, see the [full documentation](https://github.com/ludvikroed/homely-integration).
