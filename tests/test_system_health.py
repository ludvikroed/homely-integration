"""Tests for system health support."""

from __future__ import annotations

import time
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState

from custom_components.homely.models import HomelyRuntimeData
from custom_components.homely.system_health import async_register, system_health_info
from tests.common import LOCATION_ID, build_config_entry, copy_location_data


def test_system_health_helpers_cover_registration():
    """System health helper functions should stay predictable."""
    register = SimpleNamespace(
        async_register_info=lambda callback: setattr(register, "callback", callback)
    )

    async_register(None, register)

    assert register.callback is system_health_info


async def test_system_health_reports_entry_runtime_details(hass):
    """System health should expose useful runtime details per entry."""
    config_entry = build_config_entry()
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=copy_location_data()),
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=copy_location_data(),
        ws_status="Connected",
        ws_status_reason="ready",
        api_available=True,
        tracked_device_ids={"device-1", "device-2"},
    )
    config_entry.runtime_data.last_successful_poll_monotonic = time.monotonic() - 12
    config_entry.runtime_data.last_websocket_event_monotonic = time.monotonic() - 5
    config_entry.runtime_data.last_websocket_event_type = "device-state-changed"
    config_entry._state = ConfigEntryState.LOADED

    info = await system_health_info(hass)

    assert info["entries"] >= 1
    assert info["entry_1"]["ws_status"] == "Connected"
    assert info["entry_1"]["api_available"] is True
    assert info["entry_1"]["tracked_devices"] == 2
    assert info["entry_1"]["last_successful_poll_age_seconds"] is not None
    assert info["entry_1"]["last_websocket_event_age_seconds"] is not None
    assert info["entry_1"]["last_websocket_event_type"] == "device-state-changed"
    assert info["entry_1"]["cache_age_seconds"] is not None
