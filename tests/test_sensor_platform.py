"""Tests for sensor platform behavior."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.homely.models import HomelyRuntimeData
from custom_components.homely.sensor import (
    PARALLEL_UPDATES,
    HomelySensor,
    HomelyWebSocketStatusSensor,
    async_setup_entry,
)
from custom_components.homely.const import CONF_ENABLE_WEBSOCKET
from custom_components.homely.sensors.discover import discover_device_sensors
from tests.common import LOCATION_ID, build_config_entry


def test_sensor_platform_declares_parallel_updates():
    """Coordinator-driven sensor platform should set PARALLEL_UPDATES to 0."""
    assert PARALLEL_UPDATES == 0


def test_sensor_entity_reads_transformed_values(location_data):
    """Sensor entities should expose transformed runtime values."""
    coordinator = MagicMock()
    coordinator.data = location_data

    han_device = location_data["devices"][4]
    discovered = discover_device_sensors(han_device)
    consumption = next(sensor for sensor in discovered if sensor["device_suffix"] == "consumption")
    entity = HomelySensor(coordinator, han_device, consumption)

    assert entity.native_value == 769.67


def test_sensor_entity_returns_raw_value_without_transform(location_data):
    """Sensors without transforms should return the raw state value."""
    coordinator = MagicMock()
    coordinator.data = location_data

    motion_device = location_data["devices"][0]
    sensor_config = {
        "path": "features.temperature.states.temperature.value",
        "name": "temperature",
        "device_suffix": "temperature",
    }
    entity = HomelySensor(coordinator, motion_device, sensor_config)

    assert entity.native_value == 21.8


def test_sensor_entity_uses_diagnostic_defaults_and_correct_link_quality_unit(location_data):
    """Diagnostic sensors should avoid UI spam and use correct units."""
    coordinator = MagicMock()
    coordinator.data = location_data

    motion_device = location_data["devices"][0]
    discovered = discover_device_sensors(motion_device)
    link_quality = next(sensor for sensor in discovered if sensor["device_suffix"] == "networklinkstrength")
    battery_voltage = next(sensor for sensor in discovered if sensor["device_suffix"] == "battery_voltage")

    link_quality_entity = HomelySensor(coordinator, motion_device, link_quality)
    battery_voltage_entity = HomelySensor(coordinator, motion_device, battery_voltage)

    assert link_quality_entity.native_unit_of_measurement == "%"
    assert link_quality_entity.entity_registry_enabled_default is False
    assert battery_voltage_entity.entity_registry_enabled_default is False


def test_sensor_entity_handles_transform_errors_gracefully(location_data):
    """Broken transforms should fall back to raw values instead of crashing."""
    coordinator = MagicMock()
    coordinator.data = location_data
    motion_device = location_data["devices"][0]
    sensor_config = {
        "path": "features.temperature.states.temperature.value",
        "name": "temperature",
        "device_suffix": "temperature",
        "transform_value": lambda value: (_ for _ in ()).throw(ValueError("bad")),
    }

    entity = HomelySensor(coordinator, motion_device, sensor_config)
    assert entity.native_value == 21.8


def test_sensor_entity_handles_missing_devices_and_type_errors(location_data):
    """Sensors should handle missing devices and transform type errors safely."""
    coordinator = MagicMock()
    coordinator.data = location_data
    motion_device = location_data["devices"][0]
    sensor_config = {
        "path": "features.temperature.states.temperature.value",
        "name": "temperature",
        "device_suffix": "temperature",
        "transform_value": lambda value: (_ for _ in ()).throw(TypeError("bad")),
    }

    entity = HomelySensor(coordinator, motion_device, sensor_config)
    assert entity.native_value == 21.8

    coordinator.data = {"devices": []}
    assert entity.native_value is None


def test_sensor_entity_supports_config_category(location_data):
    """Config-category sensors should map to the proper HA entity category."""
    coordinator = MagicMock()
    coordinator.data = location_data
    motion_device = location_data["devices"][0]
    sensor_config = {
        "path": "features.alarm.states.sensitivitylevel.value",
        "name": "sensitivitylevel",
        "device_suffix": "sensitivitylevel",
        "entity_category": "config",
    }

    entity = HomelySensor(coordinator, motion_device, sensor_config)
    assert entity.entity_category is not None


def test_websocket_status_sensor_uses_runtime_data(hass, location_data):
    """WebSocket status sensor should read status and reason from runtime state."""
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})
    runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
        ws_status="Connected",
        ws_status_reason="event received",
    )
    config_entry.runtime_data = runtime_data

    entity = HomelyWebSocketStatusSensor(runtime_data.coordinator, hass, config_entry, LOCATION_ID)
    assert entity.native_value == "Connected"
    assert entity.extra_state_attributes == {"reason": "event received"}
    assert entity.entity_registry_enabled_default is False
    assert "Connected" in entity.options

    runtime_data.ws_status = ""
    runtime_data.websocket = SimpleNamespace(is_connected=lambda: False)
    assert entity.native_value == "Disconnected"

    runtime_data.websocket = None
    assert entity.native_value == "Not initialized"
    runtime_data.ws_status_reason = ""
    assert entity.extra_state_attributes is None


def test_websocket_status_sensor_reports_disabled_when_websocket_is_off(
    hass,
    location_data,
):
    """Status sensor should expose Disabled when websocket support is turned off."""
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: False})
    runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
        ws_status="Connected",
        ws_status_reason=None,
    )
    config_entry.runtime_data = runtime_data

    entity = HomelyWebSocketStatusSensor(runtime_data.coordinator, hass, config_entry, LOCATION_ID)

    assert entity.native_value == "Disabled"
    assert "Disabled" in entity.options


async def test_sensor_async_setup_entry_creates_ws_status_and_device_sensors(hass, location_data):
    """Sensor platform setup should create status sensor and discovered sensors."""
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
    assert f"location_{LOCATION_ID}_websocket_status" in unique_ids
    assert "70b9db72-5c00-4316-9ffa-ac7bf60fcb47_temperature" in unique_ids
    assert "1d6d0206-bfcc-4c8b-83f1-c23d7270fe9f_consumption" in unique_ids


async def test_websocket_status_sensor_registers_and_unregisters_listeners(hass, location_data):
    """Status sensor should manage listener lifecycle cleanly."""
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})
    runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )
    config_entry.runtime_data = runtime_data
    entity = HomelyWebSocketStatusSensor(runtime_data.coordinator, hass, config_entry, LOCATION_ID)

    with (
        patch.object(CoordinatorEntity, "async_added_to_hass", AsyncMock(return_value=None)),
        patch.object(CoordinatorEntity, "async_will_remove_from_hass", AsyncMock(return_value=None)),
        patch.object(entity, "async_schedule_update_ha_state"),
    ):
        await entity.async_added_to_hass()
        assert len(runtime_data.ws_status_listeners) == 1
        await entity.async_will_remove_from_hass()
        assert runtime_data.ws_status_listeners == []


async def test_websocket_status_sensor_listener_triggers_state_update(hass, location_data):
    """Registered websocket status listeners should schedule state writes."""
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})
    runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )
    config_entry.runtime_data = runtime_data
    entity = HomelyWebSocketStatusSensor(runtime_data.coordinator, hass, config_entry, LOCATION_ID)
    entity.hass = hass
    entity.entity_id = "sensor.test"

    with (
        patch.object(CoordinatorEntity, "async_added_to_hass", AsyncMock(return_value=None)),
        patch.object(entity, "async_schedule_update_ha_state") as schedule_mock,
    ):
        await entity.async_added_to_hass()
        runtime_data.ws_status_listeners[0]()

    assert schedule_mock.call_count >= 2


async def test_websocket_status_sensor_handles_missing_listener_storage(hass, location_data):
    """Broken runtime listener storage should not crash add/remove hooks."""
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})
    runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )
    config_entry.runtime_data = runtime_data
    entity = HomelyWebSocketStatusSensor(runtime_data.coordinator, hass, config_entry, LOCATION_ID)
    entity._runtime_data = SimpleNamespace(ws_status="Connected")

    with (
        patch.object(CoordinatorEntity, "async_added_to_hass", AsyncMock(return_value=None)),
        patch.object(CoordinatorEntity, "async_will_remove_from_hass", AsyncMock(return_value=None)),
    ):
        await entity.async_added_to_hass()
        await entity.async_will_remove_from_hass()


def test_websocket_status_sensor_handles_unknown_runtime_state(hass, location_data):
    """Status sensor should return Unknown on broken runtime access."""
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})
    runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )
    config_entry.runtime_data = runtime_data
    entity = HomelyWebSocketStatusSensor(runtime_data.coordinator, hass, config_entry, LOCATION_ID)

    entity._runtime_data = SimpleNamespace()
    assert entity.native_value == "Unknown"
    assert entity.extra_state_attributes is None
