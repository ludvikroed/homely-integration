"""Shared test data and helpers for Homely tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homely.const import (
    CONF_ENABLE_WEBSOCKET,
    CONF_HOME_ID,
    CONF_LOCATION_ID,
    CONF_PASSWORD,
    CONF_POLL_WHEN_WEBSOCKET,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_HOME_ID,
    DEFAULT_POLL_WHEN_WEBSOCKET,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

USERNAME = "user@example.com"
PASSWORD = "super-secret"
LOCATION_ID = "32cd1f1d-6065-4878-bb1f-ed1aeca5a244"
SECOND_LOCATION_ID = "11111111-2222-3333-4444-555555555555"

TOKEN_RESPONSE = {
    "access_token": "access-token",
    "refresh_token": "refresh-token",
    "expires_in": 3600,
}

LOCATION_RESPONSE = [
    {
        "locationId": LOCATION_ID,
        "name": "JF23",
    },
    {
        "locationId": SECOND_LOCATION_ID,
        "name": "Cabin",
    },
]

LOCATION_DATA: dict[str, Any] = {
    "locationId": LOCATION_ID,
    "gatewayserial": "0200000140008079",
    "name": "JF23",
    "alarmState": "DISARMED",
    "devices": [
        {
            "id": "70b9db72-5c00-4316-9ffa-ac7bf60fcb47",
            "name": "Bevegelse stue",
            "serialNumber": "0015BC001A10CD0A",
            "location": "Floor 2 - Living room",
            "online": True,
            "modelName": "Alarm Motion Sensor 2",
            "features": {
                "setup": {
                    "states": {
                        "appledenable": {"value": False},
                        "errledenable": {"value": True},
                    }
                },
                "alarm": {
                    "states": {
                        "alarm": {"value": False},
                        "tamper": {"value": False},
                        "sensitivitylevel": {"value": 1},
                    }
                },
                "temperature": {
                    "states": {
                        "temperature": {"value": 21.8},
                    }
                },
                "battery": {
                    "states": {
                        "low": {"value": False},
                        "defect": {"value": False},
                        "voltage": {"value": 2.9},
                    }
                },
                "diagnostic": {
                    "states": {
                        "networklinkstrength": {"value": 100},
                        "networklinkaddress": {"value": "0015BC004100A513"},
                    }
                },
            },
        },
        {
            "id": "d74041f7-ad3b-45ac-95c4-f98548d11f4d",
            "name": "Røyk foreldre",
            "serialNumber": "0015BC0031031967",
            "location": "Floor 3 - Soverom foreldre",
            "online": True,
            "modelName": "Intelligent Smoke Alarm",
            "features": {
                "alarm": {
                    "states": {
                        "fire": {"value": False},
                    }
                },
                "temperature": {
                    "states": {
                        "temperature": {"value": 18.4},
                    }
                },
                "battery": {
                    "states": {
                        "low": {"value": False},
                        "voltage": {"value": 3.0},
                    }
                },
                "diagnostic": {
                    "states": {
                        "networklinkstrength": {"value": 100},
                        "networklinkaddress": {"value": "0015BC004100A513"},
                    }
                },
            },
        },
        {
            "id": "6c120e85-e8d5-49ac-abc0-baa29f9243b7",
            "name": "Lås treningsrom",
            "serialNumber": "680AE2FFFE6B9A9E",
            "location": "Floor 1 - Treningsrom",
            "online": True,
            "modelName": "Yale Doorman V2N",
            "features": {
                "lock": {
                    "states": {
                        "state": {"value": True},
                        "soundvolume": {"value": 1},
                        "language": {"value": "en"},
                    }
                },
                "report": {
                    "states": {
                        "event": {"value": "DOORLOCK_MANUAL_LOCK"},
                        "errorcode": {"value": "Success"},
                        "locked": {"value": True},
                        "Broken": {"value": False},
                        "doorclosed": {"value": True},
                        "lowbat": {"value": False},
                        "securesensor": {"value": False},
                        "lockmodel": {"value": "Doorman V2x"},
                        "partofalarm": {"value": False},
                    }
                },
            },
        },
        {
            "id": "a8034720-2a17-4b2a-95f4-eec910cdeddf",
            "name": "Flood Alarm",
            "serialNumber": "0015BC0033001BFC",
            "location": "",
            "online": True,
            "modelName": "Flood Alarm",
            "features": {
                "alarm": {
                    "states": {
                        "flood": {"value": False},
                    }
                },
                "temperature": {
                    "states": {
                        "temperature": {"value": 22.8},
                    }
                },
                "battery": {
                    "states": {
                        "low": {"value": False},
                        "voltage": {"value": 2.9},
                    }
                },
                "diagnostic": {
                    "states": {
                        "networklinkstrength": {"value": 83},
                        "networklinkaddress": {"value": "0015BC002C102E91"},
                    }
                },
            },
        },
        {
            "id": "1d6d0206-bfcc-4c8b-83f1-c23d7270fe9f",
            "name": "HAN plug",
            "serialNumber": "0015BC001B024D94",
            "location": "Floor 1 - Entrance",
            "online": True,
            "modelName": "EMI Norwegian HAN",
            "features": {
                "metering": {
                    "states": {
                        "summationdelivered": {"value": 769670},
                        "summationreceived": {"value": 0},
                        "demand": {"value": 105},
                        "check": {"value": False},
                    }
                },
                "diagnostic": {
                    "states": {
                        "networklinkstrength": {"value": 98},
                        "networklinkaddress": {"value": "0015BC002C102E91"},
                    }
                },
            },
        },
    ],
}

UPDATED_LOCATION_DATA: dict[str, Any] = deepcopy(LOCATION_DATA)
UPDATED_LOCATION_DATA["alarmState"] = "ARMED_AWAY"
UPDATED_LOCATION_DATA["devices"][0]["features"]["temperature"]["states"]["temperature"][
    "value"
] = 22.4


def copy_location_data() -> dict[str, Any]:
    """Return a deep copy of the standard location payload."""
    return deepcopy(LOCATION_DATA)


def copy_updated_location_data() -> dict[str, Any]:
    """Return a deep copy of the updated location payload."""
    return deepcopy(UPDATED_LOCATION_DATA)


def build_config_entry(
    *,
    data_overrides: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    unique_id: str | None = LOCATION_ID,
    version: int = 2,
    include_default_options: bool = True,
) -> MockConfigEntry:
    """Create a config entry matching the Homely integration defaults."""
    data = {
        CONF_USERNAME: USERNAME,
        CONF_PASSWORD: PASSWORD,
        CONF_LOCATION_ID: LOCATION_ID,
    }
    if data_overrides:
        data.update(data_overrides)

    default_options: dict[str, Any] = {}
    if include_default_options:
        default_options = {
            CONF_HOME_ID: DEFAULT_HOME_ID,
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_ENABLE_WEBSOCKET: False,
            CONF_POLL_WHEN_WEBSOCKET: DEFAULT_POLL_WHEN_WEBSOCKET,
        }
    if options is not None:
        default_options.update(options)

    return MockConfigEntry(
        domain=DOMAIN,
        title="JF23",
        data=data,
        options=default_options,
        unique_id=unique_id,
        version=version,
    )
