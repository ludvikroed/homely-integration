"""Tests for discovery helpers and websocket update mapping."""

from __future__ import annotations

from custom_components.homely.sensors.discover import (
    _get_value_by_path,
    _resolve_path_and_value,
    _transform_value,
    discover_device_sensors,
)
from custom_components.homely.ws_updates import (
    apply_device_state_changes,
    apply_websocket_event_to_data,
)


def test_get_value_by_path_reads_nested_values(location_data):
    """Nested paths should resolve correctly and missing keys return None."""
    motion_sensor = location_data["devices"][0]

    assert (
        _get_value_by_path(
            motion_sensor,
            "features.temperature.states.temperature.value",
        )
        == 21.8
    )
    assert (
        _get_value_by_path(motion_sensor, "features.temperature.states.missing.value")
        is None
    )
    assert _get_value_by_path([], "features.temperature") is None


def test_discovery_helpers_cover_invalid_paths_and_transform_errors(location_data):
    """Discovery helpers should handle malformed configs safely."""
    motion_sensor = location_data["devices"][0]

    path, value = _resolve_path_and_value(
        motion_sensor,
        {"paths": [None, "features.temperature.states.temperature.value"]},
    )
    assert path == "features.temperature.states.temperature.value"
    assert value == 21.8

    path, value = _resolve_path_and_value(motion_sensor, {"path": None})
    assert path is None
    assert value is None

    assert (
        _transform_value(
            {"transform_value": lambda _value: (_ for _ in ()).throw(TypeError("bad"))},
            5,
        )
        == 5
    )


def test_discover_device_sensors_resolves_motion_lock_flood_and_han_paths(
    location_data,
):
    """Discovery should expose realistic sensors from sample payloads."""
    motion_sensor = location_data["devices"][0]
    lock_device = location_data["devices"][2]
    flood_device = location_data["devices"][3]
    han_device = location_data["devices"][4]

    motion_discovered = discover_device_sensors(motion_sensor)
    discovered_suffixes = {sensor["device_suffix"] for sensor in motion_discovered}
    assert {
        "alarm",
        "sensitivitylevel",
        "tamper",
        "temperature",
        "battery_low",
        "battery_voltage",
    } <= discovered_suffixes

    alarm_sensor = next(
        sensor for sensor in motion_discovered if sensor["device_suffix"] == "alarm"
    )
    assert alarm_sensor["resolved_name"] == "motion"
    assert alarm_sensor["resolved_device_class"] == "motion"
    assert motion_discovered[
        next(
            index
            for index, sensor in enumerate(motion_discovered)
            if sensor["device_suffix"] == "sensitivitylevel"
        )
    ]["value"] == 1

    lock_discovered = discover_device_sensors(lock_device)
    lock_suffixes = {sensor["device_suffix"] for sensor in lock_discovered}
    jammed_sensor = next(
        sensor for sensor in lock_discovered if sensor["device_suffix"] == "jammed"
    )
    sound_volume_sensor = next(
        sensor for sensor in lock_discovered if sensor["device_suffix"] == "soundvolume"
    )
    language_sensor = next(
        sensor for sensor in lock_discovered if sensor["device_suffix"] == "language"
    )
    assert jammed_sensor["path"] == "features.report.states.Broken.value"
    assert sound_volume_sensor["value"] == "low"
    assert language_sensor["value"] == "en"
    assert {
        "error_code",
        "language",
        "soundvolume",
    } <= lock_suffixes

    flood_discovered = discover_device_sensors(flood_device)
    assert "flood" in {sensor["device_suffix"] for sensor in flood_discovered}

    han_discovered = discover_device_sensors(han_device)
    han_by_suffix = {sensor["device_suffix"]: sensor for sensor in han_discovered}
    assert {"consumption", "production", "demand", "metering_check"} <= set(
        han_by_suffix
    )
    assert han_by_suffix["consumption"]["value"] == 769.67
    assert han_by_suffix["demand"]["value"] == 105


def test_apply_websocket_event_updates_alarm_state(location_data):
    """Alarm websocket events should update both top-level and nested alarm state."""
    result = apply_websocket_event_to_data(
        location_data,
        {"type": "alarm_state_changed", "data": {"state": "ARMED_AWAY"}},
    )

    assert result["event_type"] == "alarm-state-changed"
    assert result["updated"] is True
    assert location_data["alarmState"] == "ARMED_AWAY"
    assert (
        location_data["features"]["alarm"]["states"]["alarm"]["value"] == "ARMED_AWAY"
    )


def test_apply_websocket_event_updates_device_state(location_data):
    """Device websocket events should update the matching cached state."""
    result = apply_websocket_event_to_data(
        location_data,
        {
            "type": "device_state_changed",
            "data": {
                "deviceId": location_data["devices"][0]["id"],
                "changes": [
                    {
                        "feature": "temperature",
                        "stateName": "temperature",
                        "value": 22.1,
                    }
                ],
            },
        },
    )

    assert result["event_type"] == "device-state-changed"
    assert result["updated"] is True
    assert result["changes"][0]["old_value"] == 21.8
    assert (
        location_data["devices"][0]["features"]["temperature"]["states"]["temperature"][
            "value"
        ]
        == 22.1
    )


def test_ws_updates_handle_invalid_payload_shapes(location_data):
    """Websocket update helpers should ignore malformed payloads."""
    assert apply_device_state_changes(location_data, {}) == []
    assert apply_device_state_changes({"devices": {}}, {"deviceId": "dev"}) == []
    assert apply_device_state_changes(location_data, {"deviceId": "missing"}) == []

    result = apply_websocket_event_to_data(
        location_data, {"type": "device_state_changed", "data": None}
    )
    assert result["updated"] is False


def test_apply_device_state_changes_skips_bad_change_items_and_keeps_last_updated(
    location_data,
):
    """Device websocket updates should ignore malformed changes and preserve timestamps."""
    result = apply_device_state_changes(
        location_data,
        {
            "deviceId": location_data["devices"][0]["id"],
            "changes": [
                "broken",
                {"feature": "temperature"},
                {"stateName": "temperature"},
                {
                    "feature": "temperature",
                    "stateName": "temperature",
                    "value": 19.4,
                    "lastUpdated": "2026-03-18T08:15:00Z",
                },
            ],
        },
    )

    assert len(result) == 1
    assert result[0]["old_value"] == 21.8
    assert (
        location_data["devices"][0]["features"]["temperature"]["states"]["temperature"][
            "value"
        ]
        == 19.4
    )
    assert (
        location_data["devices"][0]["features"]["temperature"]["states"]["temperature"][
            "lastUpdated"
        ]
        == "2026-03-18T08:15:00Z"
    )
