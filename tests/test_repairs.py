"""Tests for Homely repairs flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.homely.const import CONF_LOCATION_ID
from custom_components.homely.repairs import async_create_fix_flow
from tests.common import LOCATION_ID, SECOND_LOCATION_ID, PASSWORD, USERNAME, build_config_entry


async def test_async_create_fix_flow_missing_location_shows_selector(hass):
    """Missing-location issues should allow selecting a replacement location."""
    entry = build_config_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.homely.repairs._fetch_locations_for_credentials",
        AsyncMock(
            return_value=(
                [
                    {"locationId": LOCATION_ID, "name": "JF23"},
                    {"locationId": SECOND_LOCATION_ID, "name": "Cabin"},
                ],
                "token",
                None,
            )
        ),
    ):
        flow = await async_create_fix_flow(
            hass,
            f"configured_location_missing_{entry.entry_id}",
            {"entry_id": entry.entry_id},
        )
        result = await flow.async_step_init()

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_location"


async def test_async_create_fix_flow_missing_location_updates_entry_and_reloads(hass):
    """Selecting a replacement location should update and reload the entry."""
    entry = build_config_entry()
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.homely.repairs._fetch_locations_for_credentials",
            AsyncMock(
                return_value=(
                    [
                        {"locationId": SECOND_LOCATION_ID, "name": "Cabin"},
                    ],
                    "token",
                    None,
                )
            ),
        ),
        patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload,
    ):
        flow = await async_create_fix_flow(
            hass,
            f"configured_location_missing_{entry.entry_id}",
            {"entry_id": entry.entry_id},
        )
        result = await flow.async_step_select_location(
            {CONF_LOCATION_ID: SECOND_LOCATION_ID}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_LOCATION_ID] == SECOND_LOCATION_ID
    assert entry.unique_id == SECOND_LOCATION_ID
    assert entry.title == "Cabin"
    schedule_reload.assert_called_once_with(entry.entry_id)


async def test_async_create_fix_flow_missing_location_requires_reauth(hass):
    """Repair flow should abort cleanly when stored credentials no longer work."""
    entry = build_config_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.homely.repairs._fetch_locations_for_credentials",
        AsyncMock(return_value=(None, None, "invalid_auth")),
    ):
        flow = await async_create_fix_flow(
            hass,
            f"configured_location_missing_{entry.entry_id}",
            {"entry_id": entry.entry_id},
        )
        result = await flow.async_step_init()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_required"


async def test_async_create_fix_flow_raises_for_unknown_issue(hass):
    """Unknown repair ids should raise a clear error."""
    try:
        await async_create_fix_flow(hass, "unknown_issue", {"entry_id": "missing"})
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError")
