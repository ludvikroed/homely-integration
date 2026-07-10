"""Helpers for applying websocket events to cached Homely data."""

from __future__ import annotations

from typing import Any

from .runtime_state import LAST_DISARMED_CACHE_KEY


def _normalize_event_type(event_type: Any) -> str | None:
    """Normalize websocket event type names to kebab-case."""
    if not isinstance(event_type, str):
        return None
    normalized = event_type.strip().lower().replace("_", "-")
    return normalized or None


def _ensure_nested_dict(parent: dict[str, Any], key: str) -> dict[str, Any]:
    """Ensure a nested value exists and is a dict."""
    existing = parent.get(key)
    if isinstance(existing, dict):
        return existing

    created: dict[str, Any] = {}
    parent[key] = created
    return created


def ensure_alarm_root(data_dict: dict[str, Any]) -> dict[str, Any]:
    """Ensure location alarm structure exists and return alarm state dict."""
    features = _ensure_nested_dict(data_dict, "features")
    alarm_feature = _ensure_nested_dict(features, "alarm")
    states = _ensure_nested_dict(alarm_feature, "states")
    return _ensure_nested_dict(states, "alarm")


def _event_type_and_payload(event_data: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Return normalized event type and payload from known websocket shapes."""
    raw_event_type = event_data.get("type") or event_data.get("event")
    payload = event_data.get("data")
    if not isinstance(payload, dict):
        payload = event_data.get("payload")

    args = event_data.get("args")
    if isinstance(args, list):
        for item in args:
            if not isinstance(item, dict):
                continue
            arg_type = item.get("type") or item.get("event")
            arg_payload = item.get("data")
            if isinstance(arg_payload, dict):
                raw_event_type = arg_type or raw_event_type
                payload = arg_payload
                break

    return _normalize_event_type(raw_event_type), payload if isinstance(payload, dict) else {}


def _last_disarmed_details(payload: dict[str, Any]) -> dict[str, Any]:
    """Build stable metadata for the last disarm event."""
    return {
        "user_name": payload.get("userName"),
        "user_id": payload.get("userId"),
        "timestamp": payload.get("timestamp"),
        "event_id": payload.get("eventId"),
        "device_id": payload.get("deviceId"),
    }


def apply_device_state_changes(
    data_dict: dict[str, Any],
    event_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply device-state-changed payload directly to cached data.

    Returns a list describing each applied change.
    """
    device_id = event_payload.get("deviceId")
    if not device_id:
        return []

    devices = data_dict.get("devices", [])
    if not isinstance(devices, list):
        return []
    device = next(
        (
            item
            for item in devices
            if isinstance(item, dict) and item.get("id") == device_id
        ),
        None,
    )
    if not isinstance(device, dict):
        return []

    changes = event_payload.get("changes")
    if not isinstance(changes, list) or not changes:
        single_change = event_payload.get("change")
        changes = [single_change] if isinstance(single_change, dict) else []

    applied_changes: list[dict[str, Any]] = []
    for change in changes:
        if not isinstance(change, dict):
            continue

        feature = change.get("feature")
        state_name = change.get("stateName")
        if not feature or not state_name:
            continue

        value = change.get("value")
        last_updated = change.get("lastUpdated")

        features = _ensure_nested_dict(device, "features")
        feature_dict = _ensure_nested_dict(features, str(feature))
        states = _ensure_nested_dict(feature_dict, "states")
        state = _ensure_nested_dict(states, str(state_name))

        old_value = state.get("value")
        state["value"] = value
        if last_updated is not None:
            state["lastUpdated"] = last_updated

        applied_changes.append(
            {
                "device_id": device_id,
                "feature": feature,
                "state_name": state_name,
                "old_value": old_value,
                "value": value,
            }
        )

    return applied_changes


def apply_websocket_event_to_data(
    data_dict: dict[str, Any],
    event_data: dict[str, Any],
) -> dict[str, Any]:
    """Apply a websocket event to cached data and return update details."""
    event_type, payload = _event_type_and_payload(event_data)

    result: dict[str, Any] = {
        "event_type": event_type,
        "updated": False,
        "device_id": payload.get("deviceId"),
        "changes": [],
    }

    if event_type == "alarm-state-changed":
        alarm_state = payload.get("state")
        if alarm_state is None:
            alarm_state = payload.get("alarmState")
        if alarm_state is not None:
            alarm_state_dict = ensure_alarm_root(data_dict)
            alarm_state_dict["value"] = alarm_state
            data_dict["alarmState"] = alarm_state
            if str(alarm_state).upper() == "DISARMED":
                last_disarmed = _last_disarmed_details(payload)
                data_dict[LAST_DISARMED_CACHE_KEY] = last_disarmed
                result["last_disarmed"] = last_disarmed
        result["updated"] = alarm_state is not None
        result["alarm_state"] = alarm_state
        return result

    if event_type == "device-state-changed":
        changes = apply_device_state_changes(data_dict, payload)
        result["updated"] = bool(changes)
        result["changes"] = changes
        return result

    return result
