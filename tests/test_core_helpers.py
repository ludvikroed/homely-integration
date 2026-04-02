"""Tests for helper logic in __init__ and ws_updates."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from custom_components.homely.__init__ import (
    _ctx,
    _get_alarm_state,
    _json_debug,
    _log_startup_device_payloads,
    _set_alarm_state,
    _tracked_api_device_ids,
    async_migrate_entry,
)
from custom_components.homely.device_state import (
    get_current_device,
    is_device_available,
)
from custom_components.homely.models import HomelyRuntimeData
from custom_components.homely.models import get_entry_runtime_data
from custom_components.homely.runtime_state import (
    reported_websocket_status,
    record_successful_poll,
    record_websocket_event,
    runtime_observability_snapshot,
    tracked_api_device_ids,
    update_runtime_websocket_state,
    websocket_connection_state,
    websocket_is_connected,
    websocket_state_context,
    websocket_state_snapshot,
)
from custom_components.homely.sensors import _as_float, _wh_to_kwh
from custom_components.homely.ws_updates import (
    _normalize_event_type,
    apply_device_state_changes,
    apply_websocket_event_to_data,
    ensure_alarm_root,
)
from tests.common import LOCATION_ID, build_config_entry


def test_init_helper_functions_and_tracked_ids(location_data):
    """Helper functions should normalize alarm data and tracked device ids."""
    assert _ctx("entry", "loc", "dev") == "entry_id=entry location_id=loc device_id=dev"
    assert _ctx("entry", LOCATION_ID, location_data["devices"][0]["id"]) == (
        "entry_id=entry "
        f"location_id={LOCATION_ID[:8]}... "
        f"device_id={location_data['devices'][0]['id'][:8]}..."
    )
    assert _json_debug({"a": 1}) == '{"a":1}'
    assert _get_alarm_state(location_data) == "DISARMED"

    location_data.pop("alarmState")
    assert _get_alarm_state(location_data) is None
    _set_alarm_state(location_data, "ARMED_AWAY")
    assert location_data["alarmState"] == "ARMED_AWAY"
    assert (
        location_data["features"]["alarm"]["states"]["alarm"]["value"] == "ARMED_AWAY"
    )

    runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )
    has_snapshot, device_ids = _tracked_api_device_ids(runtime_data)
    assert has_snapshot is True
    assert "70b9db72-5c00-4316-9ffa-ac7bf60fcb47" in device_ids


def test_ws_update_helpers_apply_alarm_and_device_changes(location_data):
    """Websocket helper primitives should mutate cached structures safely."""
    assert _normalize_event_type("device_state_changed") == "device-state-changed"
    assert _normalize_event_type(None) is None

    root = ensure_alarm_root({})
    assert root == {}

    changes = apply_device_state_changes(
        location_data,
        {
            "deviceId": location_data["devices"][0]["id"],
            "change": {
                "feature": "battery",
                "stateName": "low",
                "value": True,
            },
        },
    )

    assert changes[0]["old_value"] is False
    assert (
        location_data["devices"][0]["features"]["battery"]["states"]["low"]["value"]
        is True
    )

    unsupported = apply_websocket_event_to_data(location_data, {"type": "unsupported"})
    assert unsupported["updated"] is False


def test_models_and_sensor_helper_edge_cases():
    """Runtime model and sensor helper utilities should handle error cases."""
    try:
        get_entry_runtime_data(SimpleNamespace(runtime_data=None, entry_id="entry-1"))
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError")

    assert _as_float("2.5") == 2.5
    assert _as_float("bad") is None
    assert _as_float(None) is None
    assert _wh_to_kwh(1234) == 1.234
    assert _wh_to_kwh("bad") == "bad"

    class _Unserializable:
        pass

    assert _json_debug(_Unserializable()).startswith("<")
    assert _get_alarm_state(None) is None


def test_device_state_helpers_handle_sparse_payloads(location_data):
    """Device lookup helpers should tolerate malformed data and keep availability simple."""
    motion_device = location_data["devices"][0]

    assert get_current_device(None, motion_device["id"]) is None
    assert get_current_device({"devices": {}}, motion_device["id"]) is None
    assert (
        get_current_device({"devices": ["broken", motion_device]}, motion_device["id"])
        == motion_device
    )
    assert get_current_device({"devices": [{"id": "other"}]}, motion_device["id"]) is None

    assert is_device_available(None) is False
    assert is_device_available({}) is False
    assert is_device_available({"id": motion_device["id"], "online": None}) is True
    assert is_device_available({"id": motion_device["id"], "online": False}) is False


def test_tracked_device_ids_handle_missing_snapshots():
    """Tracked device helper should tolerate empty or malformed runtime data."""
    assert _tracked_api_device_ids(None) == (False, set())

    runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=None),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data={},
    )
    assert _tracked_api_device_ids(runtime_data) == (False, set())
    runtime_data.coordinator.data = "bad"
    assert _tracked_api_device_ids(runtime_data) == (False, set())


def test_runtime_state_helpers_handle_broken_websocket_and_manual_disconnect(
    location_data,
):
    """Runtime websocket helpers should stay safe around broken socket state."""
    runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )

    def _raise_runtime_error() -> bool:
        raise RuntimeError("boom")

    runtime_data.websocket = SimpleNamespace(
        is_connected=_raise_runtime_error,
        status="Disconnected",
        status_reason="manual disconnect",
    )

    assert websocket_is_connected(runtime_data) is False
    snapshot = websocket_state_snapshot(runtime_data)
    assert snapshot.connected is False
    assert snapshot.status == "Disconnected"
    assert snapshot.reason == "manual disconnect"

    update_runtime_websocket_state(runtime_data)
    assert runtime_data.ws_status == "Disconnected"
    assert runtime_data.ws_status_reason == "manual disconnect"
    assert runtime_data.last_disconnect_reason is None
    assert websocket_state_context(runtime_data) == (
        "websocket_connected=False "
        "websocket_status=Disconnected "
        "websocket_reason=manual disconnect"
    )


def test_runtime_state_connection_state_prefers_effective_socket_connection(
    location_data,
):
    """Reported Connected should not override a disconnected socket."""
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
    runtime_data.websocket = SimpleNamespace(is_connected=lambda: False, status="Connected")

    assert reported_websocket_status(runtime_data) == "connected"

    websocket_state = websocket_connection_state(runtime_data)
    assert websocket_state.connected is False
    assert websocket_state.reported_status == "connected"
    assert websocket_state.effective_status == "disconnected"
    assert websocket_state.status_mismatch is True

    observability = runtime_observability_snapshot(runtime_data)
    assert observability["websocket_connected"] is False
    assert observability["websocket_effective_status"] == "disconnected"
    assert observability["websocket_reported_status"] == "connected"
    assert observability["websocket_status_mismatch"] is True


def test_runtime_state_record_helpers_update_observability_snapshot(location_data):
    """Runtime observability helpers should reflect recorded poll and websocket events."""
    runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data="bad"),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
        tracked_device_ids={"dev-1", "dev-2"},
    )

    has_snapshot, device_ids = tracked_api_device_ids(runtime_data)
    assert has_snapshot is True
    assert len(device_ids) == len(location_data["devices"])

    record_successful_poll(runtime_data, at=100.0)
    record_websocket_event(
        runtime_data,
        "device-state-changed",
        update_data_activity=True,
        at=105.0,
    )

    snapshot = runtime_observability_snapshot(runtime_data)
    assert snapshot["tracked_devices"] == 2
    assert snapshot["last_websocket_event_type"] == "device-state-changed"
    assert snapshot["last_successful_poll_age_seconds"] is not None
    assert snapshot["last_websocket_event_age_seconds"] is not None
    assert snapshot["cache_age_seconds"] is not None
    assert runtime_data.last_successful_poll_at is not None
    assert runtime_data.last_websocket_event_at is not None
    assert runtime_data.last_data_activity_monotonic == 105.0


def test_log_startup_device_payloads_handles_missing_devices(caplog):
    """Startup debug logging should not crash on partial payloads."""
    with caplog.at_level(logging.DEBUG):
        _log_startup_device_payloads({"devices": ["broken"]}, "entry-1", LOCATION_ID)
        _log_startup_device_payloads({}, "entry-1", LOCATION_ID)
        _log_startup_device_payloads({"devices": [{}]}, "entry-1", LOCATION_ID)

    assert "device payload #1 is not an object" in caplog.text
    assert "devices list missing" in caplog.text
    assert "Startup API payload #1" in caplog.text


async def test_async_migrate_entry_rejects_future_versions(hass):
    """Future config entry versions should be rejected explicitly."""
    config_entry = build_config_entry(version=3)
    config_entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, config_entry) is False
