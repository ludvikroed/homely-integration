# Homely Alarm Integration for Home Assistant

<p>
  <a href="https://www.home-assistant.io/integrations/"><img src="https://img.shields.io/badge/Home%20Assistant-Integration-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white" alt="Home Assistant"></a>
  <a href="https://hacs.xyz/"><img src="https://img.shields.io/badge/HACS-Default-41BDF5?style=for-the-badge" alt="HACS"></a>
  <a href="https://github.com/ludvikroed/homely-integration/actions/workflows/validate.yaml"><img src="https://img.shields.io/github/actions/workflow/status/ludvikroed/homely-integration/validate.yaml?style=for-the-badge&label=HACS%20Validation" alt="HACS Validation"></a>
  <a href="https://github.com/ludvikroed/homely-integration/actions/workflows/hassfest.yaml"><img src="https://img.shields.io/github/actions/workflow/status/ludvikroed/homely-integration/hassfest.yaml?style=for-the-badge&label=Hassfest" alt="Hassfest"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/ludvikroed/homely-integration?style=for-the-badge" alt="License"></a>
</p>

Unofficial Home Assistant integration for Homely alarm systems with real-time WebSocket updates and periodic API synchronization.

The integration is read-only. It monitors alarm, lock, sensor, battery, and connection states but cannot arm, disarm, lock, or unlock devices.

See [documentation.md](documentation.md) for runtime behavior, entity details, API limitations, Repairs, reauthentication, and troubleshooting.

## Features

- Live alarm and device-state updates through WebSocket events
- Device discovery and periodic reconciliation through the Homely `/home` API
- Alarm control panel and state-only lock entities
- Automatic sensors based on the features Homely exposes for each device
- Multiple Homely homes, including an **Add all homes** setup option
- Cached state during restarts and temporary API outages
- Diagnostic entities, System Health information, downloadable diagnostics, and Repairs for confirmed stale devices

## Installation

### HACS (recommended)

Make sure [HACS](https://hacs.xyz/) is installed.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ludvikroed&repository=homely-integration&category=integration)

Open the repository in HACS, select **Download**, and restart Home Assistant.

### Manual installation

1. Download the latest release.
2. Copy `custom_components/homely` to `/config/custom_components/homely`.
3. Restart Home Assistant.

## Setup

1. Go to **Settings > Devices & services**.
2. Select **Add integration** and search for **Homely**.
3. Enter the email address and password for your Homely account.
4. If the account has multiple homes, select one home or **Add all homes**.

Each home is created as a separate config entry. Homes that are already configured are skipped.

## Troubleshooting

Start by checking:

- The Homely email address and password are correct.
- The expected home was selected during setup if you have multiple homes.
- The integration is updated to the latest available version.
- **Live update connection status** and **Last cloud API poll** on the Homely home device.
- **Settings > System > Logs** for Homely errors.

To enable debug logging from YAML:

```yaml
logger:
  default: info
  logs:
    custom_components.homely: debug
    homely: debug
```

You can also select **Enable debug logging** from the integration menu. Download diagnostics from the affected Homely config entry when reporting missing devices or entities. Review diagnostic files before sharing them.

Use the matching issue form:

- [Setup or login problem](https://github.com/ludvikroed/homely-integration/issues/new?template=setup_or_login_problem.yml)
- [Missing device or sensor](https://github.com/ludvikroed/homely-integration/issues/new?template=missing_sensors_devices.yml)
- [Bug report](https://github.com/ludvikroed/homely-integration/issues/new?template=bug_report.yml)
- [Feature request](https://github.com/ludvikroed/homely-integration/issues/new?template=feature_request.yml)

## Device support

Entities are created from the features present in the Homely API payload. Common Frient sensors, HAN meters, Yale Doorman, and similar locks are supported when Homely exposes the required data.

A device visible in the Homely app may still be absent or incomplete in the API. The integration cannot add data that Homely does not expose. See the [detailed device and entity coverage](documentation.md#devices-and-entities) before reporting a missing device.

## Contributing

Contributions are welcome. Before opening a pull request, run:

- `python -m ruff check custom_components tests`
- `pytest`
- `python -m mypy --config-file mypy.ini -p custom_components.homely`

## About

- **Created by:** [Ludvik](https://github.com/ludvikroed)
- **Inspired by:** [Homely MQTT Add-on](https://github.com/haugeSander/Homely-HA-Addon)
- **License:** [MIT](LICENSE)

This project is not affiliated with Homely. It relies on Homely cloud services and APIs, which may change.
