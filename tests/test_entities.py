"""Tests for entity-specific behavior."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock

from homeassistant.components.alarm_control_panel.const import AlarmControlPanelState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType

from custom_components.homely.alarm_control_panel import (
    PARALLEL_UPDATES as ALARM_PARALLEL_UPDATES,
    HomelyAlarmPanel,
    async_setup_entry as alarm_async_setup_entry,
)
from custom_components.homely.all_batteries_healthy import (
    HomelyAllBatteriesHealthySensor,
    _is_true,
)
from custom_components.homely.lock import (
    PARALLEL_UPDATES as LOCK_PARALLEL_UPDATES,
    HomelyLock,
    async_setup_entry as lock_async_setup_entry,
    _coerce_bool,
    _is_lock_device,
)
from custom_components.homely.models import HomelyRuntimeData
from custom_components.homely.sensor import HomelySensor, HomelyWebSocketStatusSensor
from custom_components.homely.sensors.discover import discover_device_sensors
from tests.common import LOCATION_ID, build_config_entry


def test_alarm_panel_maps_known_alarm_states(location_data):
    """Alarm entity should map API states to Home Assistant states."""
    coordinator = MagicMock()
    coordinator.data = location_data
    entity = HomelyAlarmPanel(coordinator, LOCATION_ID)

    assert entity.alarm_state is AlarmControlPanelState.DISARMED

    coordinator.data["alarmState"] = "ARMED_AWAY"
    assert entity.alarm_state is AlarmControlPanelState.ARMED_AWAY

    coordinator.data["alarmState"] = "ARMED_PARTLY"
    assert entity.alarm_state is AlarmControlPanelState.ARMED_HOME

    coordinator.data["alarmState"] = "ARMED_AWAY_PENDING"
    assert entity.alarm_state is AlarmControlPanelState.ARMING


def test_alarm_panel_uses_nested_fallback_and_handles_unknown_state(location_data):
    """Alarm entity should fall back to nested data and ignore unknown states."""
    coordinator = MagicMock()
    nested_only = deepcopy(location_data)
    nested_only.pop("alarmState", None)
    nested_only["features"] = {"alarm": {"states": {"alarm": {"value": "TRIGGERED"}}}}
    coordinator.data = nested_only
    entity = HomelyAlarmPanel(coordinator, LOCATION_ID)

    assert entity.alarm_state is AlarmControlPanelState.TRIGGERED

    coordinator.data["features"]["alarm"]["states"]["alarm"]["value"] = "SOMETHING_NEW"
    assert entity.alarm_state is None

    assert entity.alarm_state is None


def test_location_level_entities_use_service_device_type(hass, location_data):
    """Virtual location entities should be registered as service devices."""
    coordinator = MagicMock()
    coordinator.data = location_data
    config_entry = build_config_entry()
    config_entry.runtime_data = HomelyRuntimeData(
        coordinator=coordinator,
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )

    alarm_entity = HomelyAlarmPanel(coordinator, LOCATION_ID)
    battery_entity = HomelyAllBatteriesHealthySensor(coordinator, "JF23", LOCATION_ID)
    websocket_entity = HomelyWebSocketStatusSensor(
        coordinator, hass, config_entry, LOCATION_ID
    )

    assert alarm_entity.device_info["entry_type"] is DeviceEntryType.SERVICE
    assert battery_entity.device_info["entry_type"] is DeviceEntryType.SERVICE
    assert websocket_entity.device_info["entry_type"] is DeviceEntryType.SERVICE


def test_alarm_and_lock_platforms_declare_parallel_updates():
    """Coordinator-driven alarm and lock platforms should set PARALLEL_UPDATES to 0."""
    assert ALARM_PARALLEL_UPDATES == 0
    assert LOCK_PARALLEL_UPDATES == 0


async def test_alarm_panel_async_setup_entry_adds_entity(hass, location_data):
    """Alarm platform setup should add exactly one location entity."""
    config_entry = build_config_entry()
    config_entry.runtime_data = HomelyRuntimeData(
        coordinator=MagicMock(data=location_data),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )
    collected = []

    await alarm_async_setup_entry(hass, config_entry, collected.extend)

    assert len(collected) == 1
    assert collected[0].unique_id == f"location_{LOCATION_ID}_alarm_panel"
    assert collected[0].name is None


def test_lock_entity_reads_state_and_extra_attributes(location_data):
    """Lock entity should expose read-only state and metadata from report states."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True
    lock_device = location_data["devices"][2]
    entity = HomelyLock(coordinator, lock_device)

    assert entity.available is True
    assert entity.name is None
    assert entity.is_locked is True
    assert entity.is_jammed is False
    assert entity.extra_state_attributes == {
        "event": "DOORLOCK_MANUAL_LOCK",
        "door_closed": True,
        "low_battery": False,
        "part_of_alarm": False,
        "lock_model": "Doorman V2x",
        "error_code": "Success",
    }


def test_lock_helper_functions_cover_bool_and_device_detection(location_data):
    """Lock helpers should classify common bool values and lock payloads."""
    assert _coerce_bool(True) is True
    assert _coerce_bool(0) is False
    assert _coerce_bool(2) is None
    assert _coerce_bool("locked") is True
    assert _coerce_bool("unlock") is False
    assert _coerce_bool("maybe") is None

    assert _is_lock_device(location_data["devices"][2]) is True
    assert _is_lock_device(location_data["devices"][0]) is False

    report_only_lock = {
        "id": "lock-2",
        "modelName": "Yale mystery",
        "features": {
            "report": {
                "states": {
                    "locked": {"value": True},
                    "lockmodel": {"value": "Doorman"},
                }
            }
        },
    }
    assert _is_lock_device(report_only_lock) is True

    report_only_yale = {
        "id": "lock-3",
        "modelName": "Yale sensor",
        "features": {"report": {"states": {"locked": {"value": True}}}},
    }
    assert _is_lock_device(report_only_yale) is True


async def test_lock_entity_handles_missing_device_and_unsupported_commands(
    location_data,
):
    """Lock entity should degrade safely and reject control commands."""
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True
    lock_device = deepcopy(location_data["devices"][2])
    entity = HomelyLock(coordinator, lock_device)

    coordinator.data = {"devices": []}
    assert entity.available is False
    assert entity.is_locked is None
    assert entity.is_jammed is None
    assert entity.extra_state_attributes == {}

    try:
        await entity.async_lock()
    except HomeAssistantError:
        pass
    else:
        raise AssertionError("Expected HomeAssistantError")


async def test_lock_async_setup_entry_and_fallback_fields(hass, location_data):
    """Lock platform should discover locks and use fallback report fields."""
    config_entry = build_config_entry()
    config_entry.runtime_data = HomelyRuntimeData(
        coordinator=MagicMock(data=location_data),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )
    collected = []

    await lock_async_setup_entry(hass, config_entry, collected.extend)

    assert len(collected) == 1
    entity = collected[0]

    fallback_lock = deepcopy(location_data["devices"][2])
    fallback_lock["features"]["lock"]["states"]["state"]["value"] = None
    fallback_lock["features"]["report"]["states"]["broken"] = {"value": True}
    fallback_lock["features"]["report"]["states"]["Broken"]["value"] = None
    fallback_lock["online"] = None
    entity.coordinator.last_update_success = True
    entity.coordinator.data = {"devices": [fallback_lock]}

    assert entity.available is True
    assert entity.is_locked is True
    assert entity.is_jammed is True

    try:
        await entity.async_unlock()
    except HomeAssistantError:
        pass
    else:
        raise AssertionError("Expected HomeAssistantError")


def test_all_batteries_healthy_sensor_aggregates_battery_problems(location_data):
    """Aggregate battery sensor should turn on when any device reports an issue."""
    coordinator = MagicMock()
    coordinator.data = location_data
    entity = HomelyAllBatteriesHealthySensor(coordinator, "JF23", LOCATION_ID)

    assert entity.is_on is False
    assert entity.extra_state_attributes == {"status": "Healthy"}

    coordinator.data["devices"][2]["features"]["report"]["states"]["lowbat"][
        "value"
    ] = True
    assert entity.is_on is True
    assert entity.extra_state_attributes == {"status": "Defective"}


def test_all_batteries_healthy_sensor_handles_regular_low_and_defect_flags(
    location_data,
):
    """Aggregate battery sensor should also react to normal battery.low/defect states."""
    coordinator = MagicMock()
    coordinator.data = location_data
    entity = HomelyAllBatteriesHealthySensor(coordinator, "JF23", LOCATION_ID)

    coordinator.data["devices"][0]["features"]["battery"]["states"]["low"]["value"] = (
        True
    )
    assert entity.is_on is True
    assert entity.extra_state_attributes == {"status": "Defective"}

    coordinator.data["devices"][0]["features"]["battery"]["states"]["low"]["value"] = (
        False
    )
    coordinator.data["devices"][0]["features"]["battery"]["states"]["defect"][
        "value"
    ] = True
    assert entity.is_on is True
    assert entity.extra_state_attributes == {"status": "Defective"}


def test_all_batteries_healthy_sensor_handles_truthy_values_and_sparse_payloads(
    location_data,
):
    """Aggregate battery sensor should handle known true-like values and skip bad payloads."""
    coordinator = MagicMock()
    coordinator.data = {
        "devices": [
            "not-a-device",
            {"features": None},
            location_data["devices"][0],
        ]
    }
    entity = HomelyAllBatteriesHealthySensor(coordinator, "JF23", LOCATION_ID)

    coordinator.data["devices"][2]["features"]["battery"]["states"]["low"]["value"] = (
        "true"
    )
    assert entity.is_on is True

    coordinator.data["devices"][2]["features"]["battery"]["states"]["low"]["value"] = (
        False
    )
    coordinator.data["devices"][2]["features"]["battery"]["states"]["defect"][
        "value"
    ] = 1
    assert entity.is_on is True


def test_all_batteries_healthy_sensor_handles_malformed_nested_payloads():
    """Aggregate battery sensor should ignore malformed nested battery/report payloads."""
    coordinator = MagicMock()
    coordinator.data = {
        "devices": [
            {"features": {"battery": "bad", "report": "bad"}},
            {
                "features": {
                    "battery": {"states": "bad"},
                    "report": {"states": "bad"},
                }
            },
        ]
    }
    entity = HomelyAllBatteriesHealthySensor(coordinator, "JF23", LOCATION_ID)

    assert entity.is_on is False
    assert entity.extra_state_attributes == {"status": "Healthy"}

    coordinator.data = {"devices": {}}
    assert entity.is_on is False
    assert entity.extra_state_attributes == {"status": "Healthy"}


def test_is_true_supports_common_truthy_values():
    """Battery helper should accept Homely-like bool, numeric and string truthy values."""
    assert _is_true(True) is True
    assert _is_true(1) is True
    assert _is_true("true") is True
    assert _is_true("ON") is True
    assert _is_true(False) is False
    assert _is_true(0) is False
    assert _is_true("false") is False


def test_han_sensor_scales_totals_and_exposes_power(location_data):
    """HAN entities should expose scaled energy totals and watt demand."""
    coordinator = MagicMock()
    coordinator.data = location_data
    han_device = location_data["devices"][4]
    discovered = discover_device_sensors(han_device)

    consumption = next(
        sensor for sensor in discovered if sensor["device_suffix"] == "consumption"
    )
    demand = next(
        sensor for sensor in discovered if sensor["device_suffix"] == "demand"
    )

    consumption_entity = HomelySensor(coordinator, han_device, consumption)
    demand_entity = HomelySensor(coordinator, han_device, demand)

    assert consumption_entity.native_value == 769.67
    assert demand_entity.native_value == 105
