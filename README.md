# Homely Alarm Integration for Home Assistant

<p>
  <a href="https://www.home-assistant.io/integrations/"><img src="https://img.shields.io/badge/Home%20Assistant-Integration-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white" alt="Home Assistant"></a>
  <a href="https://hacs.xyz/"><img src="https://img.shields.io/badge/HACS-Default-41BDF5?style=for-the-badge" alt="HACS"></a>
  <a href="https://github.com/ludvikroed/homely-integration/actions/workflows/validate.yaml"><img src="https://img.shields.io/github/actions/workflow/status/ludvikroed/homely-integration/validate.yaml?style=for-the-badge&label=HACS%20Validation" alt="HACS Validation"></a>
  <a href="https://github.com/ludvikroed/homely-integration/actions/workflows/hassfest.yaml"><img src="https://img.shields.io/github/actions/workflow/status/ludvikroed/homely-integration/hassfest.yaml?style=for-the-badge&label=Hassfest" alt="Hassfest"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/ludvikroed/homely-integration?style=for-the-badge" alt="License"></a>
</p>

A Home Assistant integration that connects your Homely alarm system to Home Assistant using the Homely API, providing read-only, real-time monitoring of your alarm and supported devices.

## Installation & Setup

#### Via HACS (Recommended)
Make sure [HACS](https://hacs.xyz/) is installed.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ludvikroed&repository=homely-integration&category=integration)

Click **Download**, then restart Home Assistant.

#### Manual Installation
Download the latest release, copy the `homely` folder to `/config/custom_components/homely/`, then restart Home Assistant and configure the integration.

#### Configure

1. Go to **Settings** → **Devices & Services** → **"+ Add Integration"**
2. Search for **"Homely"**
3. Enter your Homely account credentials (username and password)
4. If your account has multiple Homely homes, choose either **Add all homes** or one specific home from the dropdown
5. Finish setup

`Add all homes` creates one config entry per available home. Homes that are already configured are skipped automatically.

⭐ If you find this integration useful, please consider giving it a star on [GitHub](https://github.com/ludvikroed/homely-integration)! ⭐

#### Advanced Configuration

After setup, open the integration options to adjust:

- **Polling interval**: Adjust API polling frequency in seconds as a backup for WebSocket updates
  Default is 180 seconds and the minimum is 30 seconds.
- **WebSocket toggle**: Enable or disable instant updates
- **Polling while WebSocket is connected**: Optional. If disabled, API polling pauses while WebSocket is connected and resumes automatically if the WebSocket disconnects

For deeper details and value references, including sensor status values, see [documentation.md](documentation.md).

If Homely adds or removes devices on a location, the integration detects the topology change and reloads the entry automatically. New devices can then appear without manual reconfiguration. Devices that disappear from the API are not deleted automatically.

---

### Troubleshooting

- Verify your Homely username and password are correct
- If your account has multiple locations, make sure the correct location was selected during setup
- Enable debugging (shown below) and check HA logs
- If a device or sensor is present but does not work as expected, please use the [Bug report form](https://github.com/ludvikroed/homely-integration/issues/new?template=bug_report.yml)

If you can't resolve your problem, please [open a GitHub issue](https://github.com/ludvikroed/homely-integration/issues/new/choose) and choose the matching form.

If a device is missing, or a device is present but missing sensors, use the [Missing device or sensor issue form](https://github.com/ludvikroed/homely-integration/issues/new?template=missing_sensors_devices.yml).

##### Enable Debug Logging

To troubleshoot issues or monitor WebSocket and API activity, open the Homely integration, click the three dots in the upper-right corner, and select **Enable debug logging**. You can also add this to your `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.homely: debug
```

Then check the logs under **Settings** → **System** → **Logs**.

---

## Supported Devices

The integration aims to support all devices and sensors exposed by the Homely API. In practice, Frient devices should generally be well supported, and Yale Doorman and similar locks should also work when their states are available through the API.

Not every device shown in the Homely app is necessarily exposed through the API. If Homely does not expose a device or a sensor, the integration cannot add it in Home Assistant. Some vendor-specific devices, such as the Namron Smart Plug 16A, are known examples.

The Homely API is currently read-only, so this integration focuses on monitoring and status in Home Assistant rather than direct device control.

- Alarm status is supported
- Frient devices should generally be supported
- Yale Doorman and similar locks should generally work when exposed through the API
- Direct device control is not available because the Homely API is read-only

For a support matrix and more detail about device coverage, API limitations, and known gaps, see [documentation.md](documentation.md).

If a device is missing, or a device is present but missing sensors, please use the [Missing device or sensor issue form](https://github.com/ludvikroed/homely-integration/issues/new?template=missing_sensors_devices.yml).

---

## Contributing

Contributions are welcome. You can [report bugs or suggest features](https://github.com/ludvikroed/homely-integration/issues), or submit a pull request.

Before opening a PR, run:

- `python -m ruff check custom_components tests`
- `pytest`
- `python -m mypy --config-file mypy.ini -p custom_components.homely`

## About

**Created by**: [Ludvik](https://github.com/ludvikroed) | Inspired by [Homely MQTT Add-on](https://github.com/haugeSander/Homely-HA-Addon)

**Disclaimer**: Unofficial project, not affiliated with Homely. Relies on Homely's cloud API which may change.

**License**: MIT License - see [LICENSE](LICENSE)
