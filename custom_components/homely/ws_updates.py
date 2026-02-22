"""Helpers for applying websocket events to cached Homely data."""
from __future__ import annotations

from typing import Any


def ensure_alarm_root(data_dict: dict[str, Any]) -> dict[str, Any]:
    """Ensure location alarm structure exists and return alarm state dict."""
    features = data_dict.setdefault("features", {})
    alarm_feature = features.setdefault("alarm", {})
    states = alarm_feature.setdefault("states", {})
    return states.setdefault("alarm", {})


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
    device = next((d for d in devices if d.get("id") == device_id), None)
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

        features = device.setdefault("features", {})
        feature_dict = features.setdefault(feature, {})
        states = feature_dict.setdefault("states", {})
        state = states.setdefault(state_name, {})

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
    event_type = event_data.get("type")
    payload = event_data.get("data")
    if not isinstance(payload, dict):
        payload = event_data.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    result: dict[str, Any] = {
        "event_type": event_type,
        "updated": False,
        "device_id": payload.get("deviceId"),
        "changes": [],
    }

    if event_type == "alarm-state-changed":
        alarm_state = payload.get("state")
        alarm_state_dict = ensure_alarm_root(data_dict)
        alarm_state_dict["value"] = alarm_state
        data_dict["alarmState"] = alarm_state
        result["updated"] = True
        result["alarm_state"] = alarm_state
        return result

    if event_type == "device-state-changed":
        changes = apply_device_state_changes(data_dict, payload)
        result["updated"] = bool(changes)
        result["changes"] = changes
        return result

    return result
