"""System health support for Homely."""
from __future__ import annotations

from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_ENABLE_WEBSOCKET,
    CONF_POLL_WHEN_WEBSOCKET,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)
from .models import get_entry_runtime_data


def _location_hint(value: str | None) -> str | None:
    """Return a shortened location identifier for system health output."""
    if value is None:
        return None
    if len(value) <= 8:
        return value
    return f"{value[:8]}..."


@callback
def async_register(
    hass: HomeAssistant,
    register: system_health.SystemHealthRegistration,
) -> None:
    """Register system health callbacks."""
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Return system health details for Homely."""
    entries = hass.config_entries.async_entries(DOMAIN)
    info: dict[str, Any] = {
        "entries": len(entries),
    }

    for index, entry in enumerate(entries, start=1):
        runtime = getattr(entry, "runtime_data", None)
        entry_key = f"entry_{index}"
        entry_info: dict[str, Any] = {
            "state": entry.state.value,
            "location_id": _location_hint(entry.data.get("location_id")),
            "scan_interval": entry.options.get(CONF_SCAN_INTERVAL),
            "enable_websocket": entry.options.get(CONF_ENABLE_WEBSOCKET),
            "poll_when_websocket": entry.options.get(CONF_POLL_WHEN_WEBSOCKET),
        }

        if runtime is not None:
            runtime_data = get_entry_runtime_data(entry)
            entry_info.update(
                {
                    "api_available": runtime_data.api_available,
                    "ws_status": runtime_data.ws_status,
                    "ws_status_reason": runtime_data.ws_status_reason,
                    "tracked_devices": len(runtime_data.tracked_device_ids),
                }
            )

        info[entry_key] = entry_info

    return info
