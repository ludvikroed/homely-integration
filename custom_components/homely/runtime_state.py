"""Helpers for Homely runtime state, freshness, and observability."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from homeassistant.util import dt as dt_util

from .models import HomelyConfigEntry, HomelyRuntimeData


@dataclass(frozen=True)
class WebSocketStateSnapshot:
    """A lightweight snapshot of websocket connection state."""

    connected: bool
    status: str
    reason: str | None


@dataclass(frozen=True)
class WebSocketConnectionState:
    """Normalized websocket status used by sensors and diagnostics."""

    connected: bool
    reported_status: str
    effective_status: str
    reason: str | None
    status_mismatch: bool


WEBSOCKET_STATUS_OPTIONS = {
    "not_initialized",
    "connecting",
    "connected",
    "disconnected",
    "unknown",
}


def current_runtime_data(entry: HomelyConfigEntry) -> HomelyRuntimeData | None:
    """Return runtime data for an entry when it is still loaded."""
    return getattr(entry, "runtime_data", None)


def cached_location_data(runtime_data: HomelyRuntimeData) -> dict[str, Any] | None:
    """Return the last successful location payload when available."""
    last_data = runtime_data.last_data
    if not isinstance(last_data, dict) or not last_data:
        return None
    return last_data


def websocket_is_connected(runtime_data: HomelyRuntimeData) -> bool:
    """Return whether the current websocket looks connected."""
    return websocket_object_is_connected(runtime_data.websocket)


def websocket_object_is_connected(websocket: Any | None) -> bool:
    """Return whether a websocket object looks connected.

    Socket.IO can report the namespace-level ``connected`` flag as false while the
    underlying Engine.IO transport is still alive and actively delivering events.
    Treat either signal as connected to avoid tearing down healthy sessions.
    """
    if websocket is None:
        return False

    is_connected = getattr(websocket, "is_connected", None)
    if callable(is_connected):
        try:
            if bool(is_connected()):
                return True
        except Exception:
            pass

    socket = getattr(websocket, "socket", None)
    if socket is None:
        return False

    try:
        if bool(getattr(socket, "connected")):
            return True
    except Exception:
        pass

    engineio_client = getattr(socket, "eio", None)
    try:
        return str(getattr(engineio_client, "state", "")).lower() == "connected"
    except Exception:
        return False


def normalize_websocket_status(value: Any) -> str:
    """Convert internal websocket labels to stable enum states."""
    if not isinstance(value, str):
        return "unknown"

    normalized = value.strip().lower().replace(" ", "_")
    return normalized if normalized in WEBSOCKET_STATUS_OPTIONS else "unknown"


def reported_websocket_status(runtime_data: HomelyRuntimeData) -> str:
    """Return the latest websocket status reported by runtime state."""
    status = normalize_websocket_status(runtime_data.ws_status)
    if status in {"connected", "disconnected", "connecting"}:
        return status

    websocket = runtime_data.websocket
    if websocket is None:
        return "not_initialized"

    websocket_status = normalize_websocket_status(getattr(websocket, "status", None))
    if websocket_status != "unknown":
        return websocket_status

    return "connected" if websocket_is_connected(runtime_data) else "disconnected"


def websocket_state_snapshot(runtime_data: HomelyRuntimeData) -> WebSocketStateSnapshot:
    """Return websocket status details for diagnostics and logs."""
    websocket = runtime_data.websocket
    if websocket is None:
        return WebSocketStateSnapshot(
            connected=False,
            status="Not initialized",
            reason=None,
        )

    status = getattr(websocket, "status", None) or "Unknown"
    reason = getattr(websocket, "status_reason", None)
    return WebSocketStateSnapshot(
        connected=websocket_is_connected(runtime_data),
        status=str(status),
        reason=reason if reason is None else str(reason),
    )


def websocket_connection_state(
    runtime_data: HomelyRuntimeData,
) -> WebSocketConnectionState:
    """Return a normalized websocket state for UI and diagnostics."""
    reported_status = reported_websocket_status(runtime_data)
    websocket = runtime_data.websocket
    connected = websocket_is_connected(runtime_data) if websocket is not None else False

    if websocket is None:
        effective_status = "not_initialized"
    elif connected:
        effective_status = "connected"
    elif reported_status in {"connecting", "not_initialized"}:
        effective_status = reported_status
    elif reported_status == "unknown":
        effective_status = "disconnected"
    else:
        effective_status = "disconnected"

    return WebSocketConnectionState(
        connected=connected,
        reported_status=reported_status,
        effective_status=effective_status,
        reason=runtime_data.ws_status_reason,
        status_mismatch=reported_status != effective_status,
    )


def websocket_state_context(runtime_data: HomelyRuntimeData) -> str:
    """Return compact websocket state for diagnostics logs."""
    snapshot = websocket_state_snapshot(runtime_data)
    return (
        f"websocket_connected={snapshot.connected} "
        f"websocket_status={snapshot.status} "
        f"websocket_reason={snapshot.reason}"
    )


def update_runtime_websocket_state(runtime_data: HomelyRuntimeData) -> None:
    """Mirror the current websocket object's state into runtime fields."""
    snapshot = websocket_state_snapshot(runtime_data)
    runtime_data.ws_status = snapshot.status
    runtime_data.ws_status_reason = snapshot.reason
    if (
        snapshot.status == "Disconnected"
        and snapshot.reason
        and snapshot.reason != "manual disconnect"
    ):
        runtime_data.last_disconnect_reason = snapshot.reason


def cached_data_grace_seconds(scan_interval: int) -> int:
    """Return grace period for cached polling data when websocket is unavailable."""
    return max(60, min(scan_interval, 300))


def tracked_api_device_ids(
    entry_data: HomelyRuntimeData | None,
) -> tuple[bool, set[str]]:
    """Return current Homely device ids from coordinator/cache with availability flag."""
    if entry_data is None:
        return False, set()

    coordinator_data: Any = entry_data.coordinator.data
    data = coordinator_data if isinstance(coordinator_data, dict) else entry_data.last_data
    devices = data.get("devices")
    if not isinstance(devices, list):
        return False, set()

    tracked_ids = {
        str(device_id)
        for device in devices
        if isinstance(device, dict) and (device_id := device.get("id")) is not None
    }
    return True, tracked_ids


def device_id_snapshot(data: dict[str, Any] | None) -> set[str]:
    """Return device ids from a Homely payload."""
    if not isinstance(data, dict):
        return set()

    devices = data.get("devices")
    if not isinstance(devices, list):
        return set()

    return {
        str(device_id)
        for device in devices
        if isinstance(device, dict) and (device_id := device.get("id")) is not None
    }


def monotonic_age_seconds(last_monotonic: float | None) -> int | None:
    """Return age in seconds for a monotonic timestamp."""
    if last_monotonic is None or last_monotonic <= 0:
        return None
    return max(0, int(monotonic() - last_monotonic))


def record_successful_poll(runtime_data: HomelyRuntimeData, at: float | None = None) -> None:
    """Record a successful polling refresh and data activity timestamp."""
    timestamp = monotonic() if at is None else at
    runtime_data.last_successful_poll_monotonic = timestamp
    runtime_data.last_data_activity_monotonic = timestamp
    runtime_data.last_successful_poll_at = dt_util.utcnow()


def record_websocket_event(
    runtime_data: HomelyRuntimeData,
    event_type: str,
    *,
    update_data_activity: bool = False,
    at: float | None = None,
) -> None:
    """Record the most recent websocket event and optional data activity."""
    timestamp = monotonic() if at is None else at
    runtime_data.last_websocket_event_monotonic = timestamp
    runtime_data.last_websocket_event_at = dt_util.utcnow()
    runtime_data.last_websocket_event_type = event_type
    if update_data_activity:
        runtime_data.last_data_activity_monotonic = timestamp


def cache_age_seconds(runtime_data: HomelyRuntimeData) -> int | None:
    """Return age of the freshest cached Homely data."""
    return monotonic_age_seconds(runtime_data.last_data_activity_monotonic)


def runtime_observability_snapshot(runtime_data: HomelyRuntimeData) -> dict[str, Any]:
    """Return structured runtime observability fields for diagnostics."""
    websocket_state = websocket_connection_state(runtime_data)
    return {
        "api_available": runtime_data.api_available,
        "ws_status": runtime_data.ws_status,
        "ws_status_reason": runtime_data.ws_status_reason,
        "last_disconnect_reason": runtime_data.last_disconnect_reason,
        "websocket_connected": websocket_state.connected,
        "websocket_effective_status": websocket_state.effective_status,
        "websocket_reported_status": websocket_state.reported_status,
        "websocket_status_mismatch": websocket_state.status_mismatch,
        "tracked_devices": len(runtime_data.tracked_device_ids),
        "last_successful_poll_age_seconds": monotonic_age_seconds(
            runtime_data.last_successful_poll_monotonic
        ),
        "last_websocket_event_age_seconds": monotonic_age_seconds(
            runtime_data.last_websocket_event_monotonic
        ),
        "last_websocket_event_type": runtime_data.last_websocket_event_type,
        "cache_age_seconds": cache_age_seconds(runtime_data),
    }
