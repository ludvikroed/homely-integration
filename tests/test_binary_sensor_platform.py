"""Tests for binary sensor platform behavior."""
from __future__ import annotations

import builtins
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

    motion_device = location_data["devices"][0]
    discovered = discover_device_sensors(motion_device)
    alarm_config = next(sensor for sensor in discovered if sensor["device_suffix"] == "alarm")
    motion_entity = HomelyBinarySensor(coordinator, motion_device, alarm_config)
    online_entity = HomelyDeviceOnlineSensor(coordinator, motion_device)

    assert motion_entity.is_on is False
    assert online_entity.is_on is True
    assert online_entity.entity_registry_enabled_default is False

    coordinator.data["devices"][0]["features"]["alarm"]["states"]["alarm"]["value"] = True
    coordinator.data["devices"][0]["online"] = False
    assert motion_entity.is_on is True
    assert online_entity.is_on is False


def test_binary_sensor_invert_logic_for_door_state(location_data):
    """Door sensors should invert closed/open values correctly."""
    coordinator = MagicMock()
    coordinator.data = location_data

    lock_device = location_data["devices"][2]
    discovered = discover_device_sensors(lock_device)
    door_config = next(sensor for sensor in discovered if sensor["device_suffix"] == "door")
    entity = HomelyBinarySensor(coordinator, lock_device, door_config)

    assert entity.is_on is False
    coordinator.data["devices"][2]["features"]["report"]["states"]["doorclosed"]["value"] = False
    assert entity.is_on is True


def test_binary_sensor_returns_false_for_unparseable_or_missing_values(location_data):
    """Binary sensors should fail closed on missing or non-bool values."""
    coordinator = MagicMock()
    coordinator.data = location_data

    motion_device = location_data["devices"][0]
    discovered = discover_device_sensors(motion_device)
    alarm_config = next(sensor for sensor in discovered if sensor["device_suffix"] == "alarm")
    entity = HomelyBinarySensor(coordinator, motion_device, alarm_config)

    coordinator.data["devices"][0]["features"]["alarm"]["states"]["alarm"]["value"] = "maybe"
    assert entity.is_on is False

    coordinator.data = {"devices": []}
    assert entity.is_on is False


async def test_binary_sensor_async_setup_entry_tolerates_missing_aggregate_import(hass, location_data):
    """Platform setup should still work if the aggregate battery helper cannot import."""
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
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name.endswith("all_batteries_healthy"):
            raise ImportError
        return original_import(name, *args, **kwargs)

    from unittest.mock import patch

    with patch("builtins.__import__", side_effect=_fake_import):
        await async_setup_entry(hass, config_entry, collected.extend)

    unique_ids = {entity.unique_id for entity in collected}
    assert f"location_{LOCATION_ID}_any_battery_problem" not in unique_ids


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
