# Homely Alarm Integration for Home Assistant

<p>
  <a href="https://www.home-assistant.io/integrations/"><img src="https://img.shields.io/badge/Home%20Assistant-Integration-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white" alt="Home Assistant"></a>
  <a href="https://hacs.xyz/"><img src="https://img.shields.io/badge/HACS-Default-41BDF5?style=for-the-badge" alt="HACS"></a>
  <a href="https://github.com/ludvikroed/homely-integration/actions/workflows/validate.yaml"><img src="https://img.shields.io/github/actions/workflow/status/ludvikroed/homely-integration/validate.yaml?style=for-the-badge&label=HACS%20Validation" alt="HACS Validation"></a>
  <a href="https://github.com/ludvikroed/homely-integration/actions/workflows/hassfest.yaml"><img src="https://img.shields.io/github/actions/workflow/status/ludvikroed/homely-integration/hassfest.yaml?style=for-the-badge&label=Hassfest" alt="Hassfest"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/ludvikroed/homely-integration?style=for-the-badge" alt="License"></a>
</p>

A Home Assistant integration that connects your Homely alarm system to Home Assistant using the Homely API, providing real-time monitoring of your alarm and supported devices.

## Installation & Setup

### Via HACS (Recommended)
Make sure [HACS](https://hacs.xyz/) is installed.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ludvikroed&repository=homely-integration&category=integration)

Click **Download**, then restart Home Assistant.

### Configure

1. Go to **Settings** → **Devices & Services** → **"+ Add Integration"**
2. Search for **"Homely"**
3. Enter your Homely account credentials (username and password)
4. If your account has multiple Homely locations, choose which location to add
5. Finish setup

> **Multiple locations?** Add the integration multiple times, once per location. 

### Manual Installation
Download the code, copy the `homely` folder to `/config/custom_components/homely/`, then restart Home Assistant and configure the integration.

## Advanced Configuration

After setup, open the integration options to adjust:

- **Polling interval**: Adjust API polling frequency in seconds as a backup for WebSocket updates
  Default is 180 seconds and the minimum is 30 seconds.
- **WebSocket toggle**: Enable or disable instant updates
- **Polling while WebSocket is connected**: Optional. If disabled, API polling pauses while WebSocket is connected and resumes automatically if the WebSocket disconnects

For deeper details and value references, including sensor status values, see [documentation.md](documentation.md).

If Homely adds or removes devices on a location, the integration now detects the topology change and reloads the entry automatically so new entities appear without manual cleanup.

---

## Troubleshooting

- Verify your Homely username and password are correct
- If your account has multiple locations, make sure the correct location was selected during setup
- If you want to move an existing entry to another Homely location, use **Reconfigure** from the integration menu
- WebSocket may take 10-30 seconds to connect
- Enable debugging (shown below) and check HA logs

If you can't resolve your problem, please [open a GitHub issue](https://github.com/ludvikroed/homely-integration/issues/new/choose) and choose the matching form.

If a device is missing, or a device is present but missing sensors, use the [Missing device or sensor issue form](https://github.com/ludvikroed/homely-integration/issues/new?template=missing_sensors_devices.yml).

### Enable Debug Logging

To troubleshoot issues or monitor WebSocket and API activity, open the Homely integration, click the three dots in the upper-right corner, and select **Enable debug logging**. You can also add this to your `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.homely: debug
```

Then check the logs under **Settings** → **System** → **Logs**.

### Diagnostics

The integration supports Home Assistant diagnostics for safer troubleshooting. Diagnostics redact credentials, tokens, serial numbers, and other sensitive identifiers before export.

---

## Supported Devices

### Currently Supported:
- Alarm status
- Yale Doorman lock
- Temperature sensors
- Motion detectors
- Door/window sensors
- Smoke detectors
- Water leak sensors
- Smart plug
- HAN meter

### Not Supported
- Some devices may not yet be available through the Homely API
- Direct device control (Homely API is read-only)

> **Note**: The aim is to support all devices and sensors exposed by the Homely API, but not every device available in the Homely app is necessarily exposed through the API.

---

## Contributing

Contributions are welcome. You can [report bugs or suggest features](https://github.com/ludvikroed/homely-integration/issues), or submit a pull request.

Before opening a PR, run:

- `python -m ruff check custom_components tests`
- `pytest`
- `python -m mypy --config-file mypy.ini -p custom_components.homely`

⭐ If you find this integration useful, please consider giving it a star on [GitHub](https://github.com/ludvikroed/homely-integration)! ⭐

## About

**Created by**: [Ludvik](https://github.com/ludvikroed) | Inspired by [Homely MQTT Add-on](https://github.com/haugeSander/Homely-HA-Addon)

**Disclaimer**: Unofficial project, not affiliated with Homely. Relies on Homely's cloud API which may change.

**License**: MIT License - see [LICENSE](LICENSE)
