"""Diagnostics support for Homely."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .models import HomelyConfigEntry, get_entry_runtime_data
from .runtime_state import runtime_observability_snapshot

_ENTRY_REDACT_KEYS = {
    "access_token",
    "refresh_token",
    "gatewayId",
    "username",
    "password",
    "locationId",
    "location_id",
    "unique_id",
}

_API_DUMP_REDACT_KEYS = {
    "gatewayserial",
    "rootLocationId",
    "serialNumber",
    "locationId",
    "location_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime_data = get_entry_runtime_data(entry)
    api_dump: Any = runtime_data.coordinator.data
    if not isinstance(api_dump, dict):
        api_dump = runtime_data.last_data if isinstance(runtime_data.last_data, dict) else None

    diagnostics = {
        "entry": async_redact_data(
            {
                "entry_id": entry.entry_id,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            _ENTRY_REDACT_KEYS,
        ),
        "runtime": {
            "location_id": "**REDACTED**",
            "coordinator_last_update_success": runtime_data.coordinator.last_update_success,
            "observability": runtime_observability_snapshot(runtime_data),
            "api_dump": (
                async_redact_data(api_dump, _API_DUMP_REDACT_KEYS)
                if isinstance(api_dump, dict)
                else api_dump
            ),
        },
    }

    return diagnostics
