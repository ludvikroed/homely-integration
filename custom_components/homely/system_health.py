"""System health support for Homely."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_ENABLE_WEBSOCKET,
    CONF_POLL_WHEN_WEBSOCKET,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)
from .models import HomelyConfigEntry, get_entry_runtime_data
from .runtime_state import runtime_observability_snapshot


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
        typed_entry = cast(HomelyConfigEntry, entry)
        runtime = getattr(entry, "runtime_data", None)
        entry_key = f"entry_{index}"
        entry_info: dict[str, Any] = {
            "state": entry.state.value,
            "scan_interval": entry.options.get(CONF_SCAN_INTERVAL),
            "enable_websocket": entry.options.get(CONF_ENABLE_WEBSOCKET),
            "poll_when_websocket": entry.options.get(CONF_POLL_WHEN_WEBSOCKET),
        }

        if runtime is not None:
            runtime_data = get_entry_runtime_data(typed_entry)
            entry_info.update(runtime_observability_snapshot(runtime_data))

        info[entry_key] = entry_info

    return info
