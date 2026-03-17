"""Runtime models for the Homely integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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
    ws_status_listeners: list[Callable[[], None]] = field(default_factory=list)
    ws_disconnect_refresh_monotonic: float = 0.0
    api_available: bool = True
    tracked_device_ids: set[str] = field(default_factory=set)
    topology_reload_pending: bool = False


def get_entry_runtime_data(entry: ConfigEntry) -> HomelyRuntimeData:
    """Return runtime data for a loaded config entry."""
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None:
        raise ValueError(f"Config entry {entry.entry_id} is not loaded")
    return runtime_data
