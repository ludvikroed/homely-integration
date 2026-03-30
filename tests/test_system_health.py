"""Tests for Homely system health."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.homely.const import CONF_ENABLE_WEBSOCKET, CONF_LOCATION_ID
from custom_components.homely.models import HomelyRuntimeData
from custom_components.homely.system_health import async_register, system_health_info
from tests.common import LOCATION_ID, SECOND_LOCATION_ID, build_config_entry, copy_location_data


async def test_system_health_info_summarizes_entries(hass):
    """System health should expose useful aggregate runtime information."""
    entry_one = build_config_entry(
        options={CONF_ENABLE_WEBSOCKET: True},
        unique_id=LOCATION_ID,
    )
    entry_one.add_to_hass(hass)
    data_one = copy_location_data()
    data_one["name"] = "JF23"
    runtime_one = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=data_one),
        access_token="access-1",
        refresh_token="refresh-1",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=data_one,
        tracked_device_ids={"dev-1", "dev-2"},
        api_available=True,
        last_successful_poll_monotonic=time.monotonic() - 20,
        last_data_activity_monotonic=time.monotonic() - 15,
    )
    runtime_one.websocket = SimpleNamespace(is_connected=lambda: True)
    entry_one.runtime_data = runtime_one

    entry_two = build_config_entry(
        data_overrides={CONF_LOCATION_ID: SECOND_LOCATION_ID},
        options={CONF_ENABLE_WEBSOCKET: False},
        unique_id=SECOND_LOCATION_ID,
    )
    entry_two.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry_two, title="Cabin")
    data_two = copy_location_data()
    data_two["name"] = "Cabin"
    runtime_two = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=data_two),
        access_token="access-2",
        refresh_token="refresh-2",
        expires_at=0,
        location_id=SECOND_LOCATION_ID,
        last_data=data_two,
        tracked_device_ids={"dev-3"},
        api_available=False,
        last_successful_poll_monotonic=time.monotonic() - 120,
        last_data_activity_monotonic=time.monotonic() - 45,
    )
    entry_two.runtime_data = runtime_two

    with (
        patch(
            "custom_components.homely.system_health.async_get_loaded_integration",
            return_value=SimpleNamespace(version="1.4.4-beta"),
        ),
        patch(
            "custom_components.homely.system_health._safe_sdk_version",
            return_value="0.1.2",
        ),
        patch(
            "custom_components.homely.system_health.system_health.async_check_can_reach_url",
            AsyncMock(return_value="ok"),
        ),
    ):
        info = await system_health_info(hass)

    assert info["integration_version"] == "1.4.4-beta"
    assert info["sdk_version"] == "0.1.2"
    assert await info["api_endpoint_reachable"] == "ok"
    assert info["configured_entries"] == 2
    assert info["loaded_entries"] == 2
    assert info["loaded_entry_titles"] == "JF23, Cabin"
    assert info["total_devices"] == 3
    assert info["entries_with_api_available"] == 1
    assert info["entries_with_live_updates_enabled"] == 1
    assert info["entries_with_live_updates_connected"] == 1
    assert info["oldest_cached_data_age_seconds"] is not None
    assert info["oldest_successful_api_poll_age_seconds"] is not None


async def test_system_health_registers_manage_url(hass):
    """System health registration should expose a management URL."""
    register = SimpleNamespace(async_register_info=MagicMock())

    async_register(hass, register)

    register.async_register_info.assert_called_once()
    assert (
        register.async_register_info.call_args.kwargs["manage_url"]
        == "https://github.com/ludvikroed/homely-integration/blob/main/documentation.md"
    )
