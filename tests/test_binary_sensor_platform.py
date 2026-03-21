"""Tests for binary sensor platform behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.homely.binary_sensor import (
    PARALLEL_UPDATES,
    HomelyBinarySensor,
    HomelyDeviceOnlineSensor,
    _coerce_bool,
    async_setup_entry,
)
from custom_components.homely.models import HomelyRuntimeData
from custom_components.homely.sensors.discover import discover_device_sensors
from tests.common import LOCATION_ID, build_config_entry


def test_binary_sensor_platform_declares_parallel_updates():
    """Coordinator-driven binary sensor platform should set PARALLEL_UPDATES to 0."""
    assert PARALLEL_UPDATES == 0


def test_coerce_bool_handles_common_values():
    """Bool coercion should normalize values from the API."""
    assert _coerce_bool(True) is True
    assert _coerce_bool(1) is True
    assert _coerce_bool(0) is False
    assert _coerce_bool(2) is None
    assert _coerce_bool("open") is True
    assert _coerce_bool("closed") is False
    assert _coerce_bool("maybe") is None


def test_binary_sensor_and_online_sensor_read_runtime_values(location_data):
    """Binary entities should use the latest coordinator data."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True

    motion_device = location_data["devices"][0]
    discovered = discover_device_sensors(motion_device)
    alarm_config = next(
        sensor for sensor in discovered if sensor["device_suffix"] == "alarm"
    )
    motion_entity = HomelyBinarySensor(coordinator, motion_device, alarm_config)
    online_entity = HomelyDeviceOnlineSensor(coordinator, motion_device)

    assert motion_entity.is_on is False
    assert motion_entity.available is True
    assert online_entity.is_on is True
    assert online_entity.available is True
    assert online_entity.entity_registry_enabled_default is False

    coordinator.data["devices"][0]["features"]["alarm"]["states"]["alarm"]["value"] = (
        True
    )
    coordinator.data["devices"][0]["online"] = False
    assert motion_entity.is_on is True
    assert motion_entity.available is False
    assert online_entity.is_on is False
    assert online_entity.available is True


def test_binary_sensor_invert_logic_for_door_state(location_data):
    """Door sensors should invert closed/open values correctly."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True

    lock_device = location_data["devices"][2]
    discovered = discover_device_sensors(lock_device)
    door_config = next(
        sensor for sensor in discovered if sensor["device_suffix"] == "door"
    )
    entity = HomelyBinarySensor(coordinator, lock_device, door_config)

    assert entity.is_on is False
    coordinator.data["devices"][2]["features"]["report"]["states"]["doorclosed"][
        "value"
    ] = False
    assert entity.is_on is True


def test_binary_sensor_returns_false_for_unparseable_or_missing_values(location_data):
    """Binary sensors should fail closed on missing or non-bool values."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True

    motion_device = location_data["devices"][0]
    discovered = discover_device_sensors(motion_device)
    alarm_config = next(
        sensor for sensor in discovered if sensor["device_suffix"] == "alarm"
    )
    entity = HomelyBinarySensor(coordinator, motion_device, alarm_config)

    coordinator.data["devices"][0]["features"]["alarm"]["states"]["alarm"]["value"] = (
        "maybe"
    )
    assert entity.is_on is False

    coordinator.data = {"devices": []}
    assert entity.available is False
    assert entity.is_on is False


def test_online_sensor_becomes_unavailable_when_device_disappears(location_data):
    """Connectivity sensor should remain available offline, but not if the device is gone."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True

    motion_device = location_data["devices"][0]
    entity = HomelyDeviceOnlineSensor(coordinator, motion_device)

    coordinator.data["devices"][0]["online"] = False
    assert entity.available is True
    assert entity.is_on is False

    coordinator.data = {"devices": []}
    assert entity.available is False
    assert entity.is_on is False


def test_binary_sensor_falls_back_to_name_and_config_category(location_data):
    """Binary sensors without translation keys should still expose a readable fallback name."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True

    motion_device = location_data["devices"][0]
    sensor_config = {
        "path": "features.alarm.states.sensitivitylevel.value",
        "name": "custom_mode",
        "device_suffix": "custom_mode",
        "entity_category": "config",
    }
    entity = HomelyBinarySensor(coordinator, motion_device, sensor_config)

    assert entity.name == "Custom Mode"
    assert entity.entity_category is not None


async def test_binary_sensor_async_setup_entry_creates_entities(hass, location_data):
    """Platform setup should create discovered binary sensors, online sensors and aggregate sensor."""
    config_entry = build_config_entry()
    config_entry.runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )
    collected = []

    await async_setup_entry(hass, config_entry, collected.extend)

    unique_ids = {entity.unique_id for entity in collected}
    assert "70b9db72-5c00-4316-9ffa-ac7bf60fcb47_alarm" in unique_ids
    assert "70b9db72-5c00-4316-9ffa-ac7bf60fcb47_online" in unique_ids
    assert f"location_{LOCATION_ID}_any_battery_problem" in unique_ids


async def test_binary_sensor_async_setup_entry_handles_sparse_device_lists(
    hass, location_data
):
    """Binary sensor setup should ignore malformed device collections gracefully."""
    config_entry = build_config_entry()
    config_entry.runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data={"name": "JF23", "devices": {}}),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data={"name": "JF23", "devices": {}},
    )
    collected = []

    await async_setup_entry(hass, config_entry, collected.extend)

    assert [entity.unique_id for entity in collected] == [
        f"location_{LOCATION_ID}_any_battery_problem"
    ]

    config_entry.runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(
            data={"name": "JF23", "devices": ["broken", location_data["devices"][0]]}
        ),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data={"name": "JF23", "devices": ["broken", location_data["devices"][0]]},
    )
    collected = []

    await async_setup_entry(hass, config_entry, collected.extend)

    unique_ids = {entity.unique_id for entity in collected}
    assert "70b9db72-5c00-4316-9ffa-ac7bf60fcb47_alarm" in unique_ids
    assert "70b9db72-5c00-4316-9ffa-ac7bf60fcb47_online" in unique_ids
    assert f"location_{LOCATION_ID}_any_battery_problem" in unique_ids
