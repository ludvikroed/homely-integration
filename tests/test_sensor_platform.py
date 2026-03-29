"""Tests for sensor platform behavior."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

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
    coordinator.last_update_success = True

    han_device = location_data["devices"][4]
    discovered = discover_device_sensors(han_device)
    consumption = next(
        sensor for sensor in discovered if sensor["device_suffix"] == "consumption"
    )
    entity = HomelySensor(coordinator, han_device, consumption)

    assert entity.native_value == 769.67


def test_motion_sensitivity_sensor_exposes_config_value(location_data):
    """Motion sensors should expose the configured sensitivity level."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True

    motion_device = location_data["devices"][0]
    discovered = discover_device_sensors(motion_device)
    sensitivity = next(
        sensor for sensor in discovered if sensor["device_suffix"] == "sensitivitylevel"
    )
    entity = HomelySensor(coordinator, motion_device, sensitivity)

    assert entity.native_value == 1
    assert entity.entity_category is None


def test_lock_info_sensors_expose_language_and_sound(location_data):
    """Yale lock info sensors should expose readable configuration values."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True

    lock_device = location_data["devices"][2]
    discovered = discover_device_sensors(lock_device)
    by_suffix = {sensor["device_suffix"]: sensor for sensor in discovered}

    sound_volume_entity = HomelySensor(
        coordinator, lock_device, by_suffix["soundvolume"]
    )
    language_entity = HomelySensor(coordinator, lock_device, by_suffix["language"])

    assert sound_volume_entity.native_value == "low"
    assert language_entity.native_value == "en"
    assert sound_volume_entity.options == ["muted", "low", "high"]
    assert language_entity.options == ["no", "en", "sv", "da"]
    assert sound_volume_entity.entity_category is None
    assert language_entity.entity_category is None

    coordinator.data["devices"][2]["features"]["lock"]["states"]["soundvolume"][
        "value"
    ] = 2
    coordinator.data["devices"][2]["features"]["lock"]["states"]["language"][
        "value"
    ] = "sv"
    assert sound_volume_entity.native_value == "high"
    assert language_entity.native_value == "sv"

    coordinator.data["devices"][2]["features"]["lock"]["states"]["soundvolume"][
        "value"
    ] = 9
    coordinator.data["devices"][2]["features"]["lock"]["states"]["language"][
        "value"
    ] = "fi"
    assert sound_volume_entity.native_value == "9"
    assert language_entity.native_value == "fi"
    assert "9" in sound_volume_entity.options
    assert "fi" in language_entity.options


def test_sensor_entity_returns_raw_value_without_transform(location_data):
    """Sensors without transforms should return the raw state value."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True

    motion_device = location_data["devices"][0]
    sensor_config = {
        "path": "features.temperature.states.temperature.value",
        "name": "temperature",
        "device_suffix": "temperature",
    }
    entity = HomelySensor(coordinator, motion_device, sensor_config)

    assert entity.native_value == 21.8


def test_sensor_entity_uses_diagnostic_defaults_and_correct_link_quality_unit(
    location_data,
):
    """Diagnostic sensors should avoid UI spam and use correct units."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True

    motion_device = location_data["devices"][0]
    discovered = discover_device_sensors(motion_device)
    link_quality = next(
        sensor
        for sensor in discovered
        if sensor["device_suffix"] == "networklinkstrength"
    )
    battery_voltage = next(
        sensor for sensor in discovered if sensor["device_suffix"] == "battery_voltage"
    )

    link_quality_entity = HomelySensor(coordinator, motion_device, link_quality)
    battery_voltage_entity = HomelySensor(coordinator, motion_device, battery_voltage)

    assert link_quality_entity.native_unit_of_measurement == "%"
    assert link_quality_entity.entity_registry_enabled_default is False
    assert battery_voltage_entity.entity_registry_enabled_default is False


def test_sensor_entity_handles_transform_errors_gracefully(location_data):
    """Broken transforms should fall back to raw values instead of crashing."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True
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
    coordinator.last_update_success = True
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
    assert entity.available is False
    assert entity.native_value is None


def test_sensor_entity_becomes_unavailable_when_device_is_offline(location_data):
    """Device-bound sensors should be unavailable when the device is offline."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True

    motion_device = location_data["devices"][0]
    sensor_config = {
        "path": "features.temperature.states.temperature.value",
        "name": "temperature",
        "device_suffix": "temperature",
    }
    entity = HomelySensor(coordinator, motion_device, sensor_config)

    assert entity.available is True

    coordinator.data["devices"][0]["online"] = False
    assert entity.available is False


def test_sensor_entity_ignores_config_category(location_data):
    """Plain sensors should not expose config entity category."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True
    motion_device = location_data["devices"][0]
    sensor_config = {
        "path": "features.alarm.states.sensitivitylevel.value",
        "name": "sensitivitylevel",
        "device_suffix": "sensitivitylevel",
        "entity_category": "config",
    }

    entity = HomelySensor(coordinator, motion_device, sensor_config)
    assert entity.entity_category is None


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
        last_disconnect_reason="network error: boom",
    )
    config_entry.runtime_data = runtime_data

    entity = HomelyWebSocketStatusSensor(
        runtime_data.coordinator, hass, config_entry, LOCATION_ID
    )
    assert entity.native_value == "connected"
    assert entity.extra_state_attributes == {
        "reason": "event received",
        "last_disconnect_reason": "network error: boom",
    }
    assert entity.entity_registry_enabled_default is False
    assert "connected" in entity.options

    runtime_data.ws_status = ""
    runtime_data.websocket = SimpleNamespace(is_connected=lambda: False)
    assert entity.native_value == "disconnected"

    runtime_data.websocket = None
    assert entity.native_value == "not_initialized"
    runtime_data.ws_status_reason = ""
    assert entity.extra_state_attributes == {
        "last_disconnect_reason": "network error: boom"
    }


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

    entity = HomelyWebSocketStatusSensor(
        runtime_data.coordinator, hass, config_entry, LOCATION_ID
    )

    assert entity.native_value == "disabled"
    assert "disabled" in entity.options


async def test_runtime_timestamp_sensors_use_runtime_data(hass, location_data):
    """Runtime timestamp sensors should expose the latest poll and websocket times."""
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})
    last_poll_at = dt_util.utcnow()
    last_ws_at = last_poll_at + timedelta(seconds=5)
    runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
        last_successful_poll_at=last_poll_at,
        last_websocket_event_at=last_ws_at,
        last_websocket_event_type="device-state-changed",
    )
    config_entry.runtime_data = runtime_data
    collected = []

    await async_setup_entry(hass, config_entry, collected.extend)

    by_unique_id = {entity.unique_id: entity for entity in collected}
    assert (
        by_unique_id[f"location_{LOCATION_ID}_last_successful_poll"].native_value
        == last_poll_at
    )
    websocket_message = by_unique_id[f"location_{LOCATION_ID}_last_websocket_message"]
    assert websocket_message.native_value == last_ws_at
    assert websocket_message.icon == "mdi:message-outline"
    assert websocket_message.extra_state_attributes == {
        "event_type": "device-state-changed"
    }


async def test_sensor_async_setup_entry_creates_ws_status_and_device_sensors(
    hass, location_data
):
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
    assert f"location_{LOCATION_ID}_last_successful_poll" in unique_ids
    assert f"location_{LOCATION_ID}_last_websocket_message" in unique_ids
    assert "70b9db72-5c00-4316-9ffa-ac7bf60fcb47_sensitivitylevel" in unique_ids
    assert "70b9db72-5c00-4316-9ffa-ac7bf60fcb47_temperature" in unique_ids
    assert "6c120e85-e8d5-49ac-abc0-baa29f9243b7_soundvolume" in unique_ids
    assert "6c120e85-e8d5-49ac-abc0-baa29f9243b7_language" in unique_ids
    assert "1d6d0206-bfcc-4c8b-83f1-c23d7270fe9f_consumption" in unique_ids


async def test_sensor_async_setup_entry_handles_sparse_device_lists(
    hass, location_data
):
    """Sensor setup should ignore malformed device collections gracefully."""
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
        f"location_{LOCATION_ID}_websocket_status",
        f"location_{LOCATION_ID}_last_successful_poll",
        f"location_{LOCATION_ID}_last_websocket_message",
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
    assert f"location_{LOCATION_ID}_websocket_status" in unique_ids
    assert f"location_{LOCATION_ID}_last_successful_poll" in unique_ids
    assert f"location_{LOCATION_ID}_last_websocket_message" in unique_ids
    assert "70b9db72-5c00-4316-9ffa-ac7bf60fcb47_sensitivitylevel" in unique_ids
    assert "70b9db72-5c00-4316-9ffa-ac7bf60fcb47_temperature" in unique_ids


async def test_websocket_status_sensor_registers_and_unregisters_listeners(
    hass, location_data
):
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
    entity = HomelyWebSocketStatusSensor(
        runtime_data.coordinator, hass, config_entry, LOCATION_ID
    )

    with (
        patch.object(
            CoordinatorEntity, "async_added_to_hass", AsyncMock(return_value=None)
        ),
        patch.object(
            CoordinatorEntity,
            "async_will_remove_from_hass",
            AsyncMock(return_value=None),
        ),
        patch.object(entity, "async_schedule_update_ha_state"),
    ):
        await entity.async_added_to_hass()
        assert len(runtime_data.ws_status_listeners) == 1
        await entity.async_will_remove_from_hass()
        assert runtime_data.ws_status_listeners == []


async def test_websocket_status_sensor_listener_triggers_state_update(
    hass, location_data
):
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
    entity = HomelyWebSocketStatusSensor(
        runtime_data.coordinator, hass, config_entry, LOCATION_ID
    )
    entity.hass = hass
    entity.entity_id = "sensor.test"

    with (
        patch.object(
            CoordinatorEntity, "async_added_to_hass", AsyncMock(return_value=None)
        ),
        patch.object(entity, "async_schedule_update_ha_state") as schedule_mock,
    ):
        await entity.async_added_to_hass()
        runtime_data.ws_status_listeners[0]()

    assert schedule_mock.call_count >= 2


async def test_websocket_status_sensor_handles_missing_listener_storage(
    hass, location_data
):
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
    entity = HomelyWebSocketStatusSensor(
        runtime_data.coordinator, hass, config_entry, LOCATION_ID
    )
    entity._runtime_data = SimpleNamespace(ws_status="Connected")

    with (
        patch.object(
            CoordinatorEntity, "async_added_to_hass", AsyncMock(return_value=None)
        ),
        patch.object(
            CoordinatorEntity,
            "async_will_remove_from_hass",
            AsyncMock(return_value=None),
        ),
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
    entity = HomelyWebSocketStatusSensor(
        runtime_data.coordinator, hass, config_entry, LOCATION_ID
    )

    entity._runtime_data = SimpleNamespace()
    assert entity.native_value == "unknown"
    assert entity.extra_state_attributes is None
