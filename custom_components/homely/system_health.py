"""System health support for Homely."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from typing import Any

from homeassistant.components import system_health
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_loaded_integration

from homely.client import BASE_URL

from .const import CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET, DOMAIN
from .models import HomelyRuntimeData
from .runtime_state import cache_age_seconds, websocket_connection_state


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register system health callbacks."""
    register.async_register_info(
        system_health_info,
        manage_url="https://github.com/ludvikroed/homely-integration/blob/main/documentation.md",
    )


def _safe_sdk_version() -> str:
    """Return installed python-homely version when available."""
    try:
        return package_version("python-homely")
    except PackageNotFoundError:
        return "unknown"


def _loaded_runtime_entries(hass: HomeAssistant) -> list[Any]:
    """Return Homely entries that currently expose runtime data."""
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]


def _last_successful_api_poll_age(runtime_data: HomelyRuntimeData) -> int | None:
    """Return age in seconds of the last successful API poll."""
    from .runtime_state import monotonic_age_seconds

    return monotonic_age_seconds(runtime_data.last_successful_poll_monotonic)


def _runtime_entry_summaries(entries: list[ConfigEntry]) -> dict[str, Any]:
    """Summarize runtime state across loaded Homely entries."""
    runtime_entries: list[HomelyRuntimeData] = [entry.runtime_data for entry in entries]

    total_devices = sum(len(runtime.tracked_device_ids) for runtime in runtime_entries)
    api_available_count = sum(1 for runtime in runtime_entries if runtime.api_available)
    live_update_states: list[str] = []
    websocket_connected_count = 0
    websocket_enabled_count = sum(
        1
        for entry in entries
        if bool(
            entry.options.get(
                CONF_ENABLE_WEBSOCKET,
                entry.data.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET),
            )
        )
    )
    for entry in entries:
        websocket_enabled = bool(
            entry.options.get(
                CONF_ENABLE_WEBSOCKET,
                entry.data.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET),
            )
        )
        if not websocket_enabled:
            live_update_states.append(f"{entry.title}: disabled")
            continue

        websocket_state = websocket_connection_state(entry.runtime_data)
        if websocket_state.connected:
            websocket_connected_count += 1

        state_label = websocket_state.effective_status
        if websocket_state.status_mismatch:
            state_label = (
                f"{state_label} (reported {websocket_state.reported_status})"
            )
        live_update_states.append(f"{entry.title}: {state_label}")

    cache_ages = [
        age
        for runtime in runtime_entries
        if (age := cache_age_seconds(runtime)) is not None
    ]
    last_poll_ages = [
        age
        for runtime in runtime_entries
        if (age := _last_successful_api_poll_age(runtime)) is not None
    ]

    return {
        "loaded_entries": len(entries),
        "total_devices": total_devices,
        "entries_with_api_available": api_available_count,
        "entries_with_live_updates_enabled": websocket_enabled_count,
        "entries_with_live_updates_connected": websocket_connected_count,
        "live_update_states": "; ".join(live_update_states) or "none",
        "oldest_cached_data_age_seconds": max(cache_ages) if cache_ages else None,
        "oldest_successful_api_poll_age_seconds": (
            max(last_poll_ages) if last_poll_ages else None
        ),
    }


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Return system health information for Homely."""
    integration = async_get_loaded_integration(hass, DOMAIN)
    entries = hass.config_entries.async_entries(DOMAIN)
    loaded_entries = _loaded_runtime_entries(hass)

    entry_titles = ", ".join(entry.title for entry in loaded_entries) or "none"
    summary = _runtime_entry_summaries(loaded_entries)

    return {
        "integration_version": integration.version,
        "sdk_version": _safe_sdk_version(),
        "api_endpoint_reachable": system_health.async_check_can_reach_url(
            hass,
            BASE_URL,
        ),
        "configured_entries": len(entries),
        "loaded_entries": summary["loaded_entries"],
        "loaded_entry_titles": entry_titles,
        "total_devices": summary["total_devices"],
        "entries_with_api_available": summary["entries_with_api_available"],
        "entries_with_live_updates_enabled": summary[
            "entries_with_live_updates_enabled"
        ],
        "entries_with_live_updates_connected": summary[
            "entries_with_live_updates_connected"
        ],
        "live_update_states": summary["live_update_states"],
        "oldest_cached_data_age_seconds": summary["oldest_cached_data_age_seconds"],
        "oldest_successful_api_poll_age_seconds": summary[
            "oldest_successful_api_poll_age_seconds"
        ],
    }
