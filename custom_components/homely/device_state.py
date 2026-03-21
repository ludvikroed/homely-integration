"""Helpers for looking up Homely devices in coordinator payloads."""

from __future__ import annotations

from typing import Any


def get_current_device(
    data: dict[str, Any] | None,
    device_id: str,
) -> dict[str, Any] | None:
    """Return the latest device payload from coordinator data."""
    if not isinstance(data, dict):
        return None

    devices = data.get("devices", [])
    if not isinstance(devices, list):
        return None

    for device in devices:
        if not isinstance(device, dict):
            continue
        if str(device.get("id")) == device_id:
            return device

    return None


def is_device_available(device: dict[str, Any] | None) -> bool:
    """Return whether a device should be considered available."""
    if not device:
        return False

    online = device.get("online")
    return True if online is None else bool(online)
