"""Runtime models for the Homely integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from time import monotonic
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .websocket import HomelyWebSocket


@dataclass
class HomelyRuntimeData:
    """Runtime state for a loaded Homely config entry."""

    coordinator: DataUpdateCoordinator[dict[str, Any]]
    access_token: str
    refresh_token: str
    expires_at: float
    location_id: str
    last_data: dict[str, Any]
    websocket: HomelyWebSocket | None = None
    ws_status: str = "Not initialized"
    ws_status_reason: str | None = None
    last_disconnect_reason: str | None = None
    ws_status_listeners: list[Callable[[], None]] = field(default_factory=list)
    ws_disconnect_refresh_monotonic: float = 0.0
    ws_watchdog_reconnect_monotonic: float = 0.0
    ws_watchdog_last_warning_monotonic: float = 0.0
    ws_watchdog_last_reason: str | None = None
    ws_watchdog_last_action_at: datetime | None = None
    ws_watchdog_recovery_history_monotonic: list[float] = field(default_factory=list)
    last_successful_poll_monotonic: float = field(default_factory=monotonic)
    last_data_activity_monotonic: float = field(default_factory=monotonic)
    last_successful_poll_at: datetime | None = None
    last_websocket_event_monotonic: float | None = None
    last_websocket_event_at: datetime | None = None
    last_websocket_event_type: str | None = None
    last_ws_event_details: dict[str, Any] | None = None
    api_available: bool = True
    tracked_device_ids: set[str] = field(default_factory=set)
    topology_reload_pending: bool = False
    force_api_refresh_once: bool = False
    partner_code: int | str | None = None


type HomelyConfigEntry = ConfigEntry[HomelyRuntimeData]


def get_entry_runtime_data(entry: HomelyConfigEntry) -> HomelyRuntimeData:
    """Return runtime data for a loaded config entry."""
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        raise ValueError(f"Config entry {entry.entry_id} is not loaded")
    return cast(HomelyRuntimeData, runtime_data)
