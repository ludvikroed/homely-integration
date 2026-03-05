# Missing Sensors or Devices

Use this guide when:
- a device is visible in Home Assistant, but you only get `Online/Connect true/false` and miss expected sensors
- a device is missing completely from Home Assistant

## Why this happens

The integration creates entities based on fields available in Homely API payloads.  
If a device model has states/features we do not map yet, you may only see connectivity.

It may also happen that Homely API does not expose all device types or sensor values yet.  
Even so, the goal for this integration is to support everything the API exposes, and expand support as API data allows.

## What to do

1. Enable debug logging for Homely.
2. Restart Home Assistant (important).
   - Startup payload logging runs once on first API fetch after restart.
3. Open logs and find startup dump lines:
   - `Startup API payload for '<device name>' ...`
   - If your device is not present in this startup list, it is most likely not available through Homely API.
4. Copy the full payload block for the affected device(s).
5. Open a GitHub issue and include the data.

If a full device is missing in Home Assistant:
- Follow the same steps above.
- In the issue, also write the device name/type you expected to see, and that it was missing completely.

Issue tracker: <https://github.com/ludvikroed/homely-integration/issues>

## Debug logging

You can use integration debug toggle, or YAML:

Go to the Homely integration, click the three dots in the top-right corner, and select "Enable debug logging".  
Or add this to your `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.homely: debug
```

## What to include in your issue

- Device name as shown in Homely/Home Assistant (example: `Yale Doorman by entrance`)
- Device type/model (if known)
- What entities you get now (example: only `Online` / `Connect`)
- What entities/sensors you expected
- Full startup payload block from logs for that device
- Integration version and Home Assistant version
- If you use multiple homes: `Home index` value

## Example from logs

```text
2026-03-05 08:45:13.714 DEBUG (MainThread) [custom_components.homely] Startup API payload for 'Smoke Alarm Example' entry_id=01KEXAMPLEENTRY123456789AB location_id=11111111-2222-4333-8444-555555555555 device_id=aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee
{
  "features": {
    "alarm": {
      "states": {
        "fire": {
          "lastUpdated": "2025-04-11T18:15:04.315Z",
          "value": false
        }
      }
    },
    "battery": {
      "states": {
        "low": {
          "lastUpdated": "2025-04-11T18:15:04.314Z",
          "value": false
        },
        "voltage": {
          "lastUpdated": "2026-02-27T11:51:20.919Z",
          "value": 3
        }
      }
    },
    "diagnostic": {
      "states": {
        "networklinkaddress": {
          "lastUpdated": "2025-09-20T06:52:25.125Z",
          "value": "0015BC00EXAMPLE1"
        },
        "networklinkstrength": {
          "lastUpdated": "2026-03-05T06:58:51.161Z",
          "value": 98
        }
      }
    },
    "temperature": {
      "states": {
        "temperature": {
          "lastUpdated": "2026-03-05T07:18:47.248Z",
          "value": 17.9
        }
      }
    }
  },
  "id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
  "location": "Floor X - Example Room",
  "modelId": "99999999-8888-4777-8666-555555555555",
  "modelName": "Intelligent Smoke Alarm",
  "name": "Smoke Alarm Example",
  "online": true,
  "serialNumber": "SERIAL-EXAMPLE-0001"
}
```

## Privacy note

Do not share tokens/passwords.  
It is usually safe to share device payloads, but remove personal labels if you prefer.
