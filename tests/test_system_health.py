"""Tests for system health support."""
from __future__ import annotations

from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState

from custom_components.homely.models import HomelyRuntimeData
from custom_components.homely.system_health import system_health_info
from tests.common import LOCATION_ID, build_config_entry, copy_location_data


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
    config_entry._state = ConfigEntryState.LOADED

    info = await system_health_info(hass)

    assert info["entries"] >= 1
    assert info["entry_1"]["location_id"] == LOCATION_ID
    assert info["entry_1"]["ws_status"] == "Connected"
    assert info["entry_1"]["api_available"] is True
    assert info["entry_1"]["tracked_devices"] == 2
