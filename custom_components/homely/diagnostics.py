"""Diagnostics support for Homely."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .models import get_entry_runtime_data

_REDACT_KEYS = {
    "access_token",
    "refresh_token",
    "username",
    "password",
    "name",
    "location",
    "gatewayserial",
    "serialNumber",
    "networklinkaddress",
    "id",
    "deviceId",
    "locationId",
    "location_id",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime_data = get_entry_runtime_data(entry)

    diagnostics = {
        "entry": {
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "runtime": {
            "location_id": runtime_data.location_id,
            "ws_status": runtime_data.ws_status,
            "ws_status_reason": runtime_data.ws_status_reason,
            "coordinator_last_update_success": runtime_data.coordinator.last_update_success,
            "data": runtime_data.coordinator.data or runtime_data.last_data,
        },
    }

    return async_redact_data(diagnostics, _REDACT_KEYS)
