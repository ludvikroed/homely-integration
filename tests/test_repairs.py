"""Tests for Homely repairs flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.homely.repairs import (
    MissingLocationRepairFlow,
    async_create_fix_flow,
)
from custom_components.homely.const import CONF_LOCATION_ID
from tests.common import LOCATION_ID, SECOND_LOCATION_ID, build_config_entry


async def test_async_create_fix_flow_returns_missing_location_flow(hass):
    """Homely should expose a repair flow for missing configured locations."""
    entry = build_config_entry()
    entry.add_to_hass(hass)

    flow = await async_create_fix_flow(
        hass,
        f"configured_location_missing_{entry.entry_id}",
        {"entry_id": entry.entry_id},
    )

    assert isinstance(flow, MissingLocationRepairFlow)


async def test_missing_location_repair_flow_shows_location_picker(hass):
    """Repair flow should let the user pick a replacement location."""
    entry = build_config_entry()
    entry.add_to_hass(hass)
    flow = MissingLocationRepairFlow(entry)
    flow.hass = hass

    with patch(
        "custom_components.homely.repairs.fetch_locations_for_entry",
        AsyncMock(
            return_value=(
                [
                    {"locationId": LOCATION_ID, "name": "Home"},
                    {"locationId": SECOND_LOCATION_ID, "name": "Cabin"},
                ],
                None,
            )
        ),
    ):
        result = await flow.async_step_init()

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_location"


async def test_missing_location_repair_flow_reconfigures_entry(hass):
    """Repair flow should switch the entry to the selected replacement location."""
    entry = build_config_entry()
    entry.add_to_hass(hass)
    flow = MissingLocationRepairFlow(entry)
    flow.hass = hass

    with (
        patch(
            "custom_components.homely.repairs.fetch_locations_for_entry",
            AsyncMock(
                return_value=(
                    [
                        {"locationId": LOCATION_ID, "name": "Home"},
                        {"locationId": SECOND_LOCATION_ID, "name": "Cabin"},
                    ],
                    None,
                )
            ),
        ),
        patch(
            "custom_components.homely.repairs.reconfigure_entry_location",
            AsyncMock(return_value=None),
        ) as mock_reconfigure,
    ):
        await flow.async_step_init()
        result = await flow.async_step_select_location(
            {CONF_LOCATION_ID: SECOND_LOCATION_ID}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    mock_reconfigure.assert_awaited_once()


async def test_missing_location_repair_flow_aborts_when_reauth_is_needed(hass):
    """Repair flow should direct the user to reauth when credentials are invalid."""
    entry = build_config_entry()
    entry.add_to_hass(hass)
    flow = MissingLocationRepairFlow(entry)
    flow.hass = hass

    with patch(
        "custom_components.homely.repairs.fetch_locations_for_entry",
        AsyncMock(return_value=(None, "invalid_auth")),
    ):
        result = await flow.async_step_init()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_required"


async def test_missing_location_repair_flow_rejects_duplicate_target_location(hass):
    """Repair flow should not allow selecting a location already configured elsewhere."""
    entry = build_config_entry()
    entry.add_to_hass(hass)
    other_entry = build_config_entry(
        data_overrides={CONF_LOCATION_ID: SECOND_LOCATION_ID},
        unique_id=SECOND_LOCATION_ID,
    )
    other_entry.add_to_hass(hass)
    flow = MissingLocationRepairFlow(entry)
    flow.hass = hass

    with patch(
        "custom_components.homely.repairs.fetch_locations_for_entry",
        AsyncMock(
            return_value=(
                [
                    {"locationId": LOCATION_ID, "name": "Home"},
                    {"locationId": SECOND_LOCATION_ID, "name": "Cabin"},
                ],
                None,
            )
        ),
    ):
        await flow.async_step_init()
        result = await flow.async_step_select_location(
            {CONF_LOCATION_ID: SECOND_LOCATION_ID}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_missing_location_repair_flow_surfaces_connection_errors_in_form(hass):
    """Repair flow should stay on the form for transient connection problems."""
    entry = build_config_entry()
    entry.add_to_hass(hass)
    flow = MissingLocationRepairFlow(entry)
    flow.hass = hass

    with patch(
        "custom_components.homely.repairs.fetch_locations_for_entry",
        AsyncMock(return_value=(None, "cannot_connect")),
    ):
        result = await flow.async_step_init()

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_missing_location_repair_flow_rejects_invalid_selected_location(hass):
    """Repair flow should keep the user on the form for unknown locations."""
    entry = build_config_entry()
    entry.add_to_hass(hass)
    flow = MissingLocationRepairFlow(entry)
    flow.hass = hass

    with patch(
        "custom_components.homely.repairs.fetch_locations_for_entry",
        AsyncMock(
            return_value=(
                [
                    {"locationId": LOCATION_ID, "name": "Home"},
                    {"locationId": SECOND_LOCATION_ID, "name": "Cabin"},
                ],
                None,
            )
        ),
    ):
        await flow.async_step_init()
        result = await flow.async_step_select_location(
            {CONF_LOCATION_ID: "missing-location"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_LOCATION_ID: "invalid_location"}


async def test_missing_location_repair_flow_updates_title_for_same_location(hass):
    """Repair flow should allow resolving the issue by keeping the same location id."""
    entry = build_config_entry()
    entry.add_to_hass(hass)
    flow = MissingLocationRepairFlow(entry)
    flow.hass = hass

    with patch(
        "custom_components.homely.repairs.fetch_locations_for_entry",
        AsyncMock(
            return_value=([{"locationId": LOCATION_ID, "name": "Renamed Home"}], None)
        ),
    ):
        await flow.async_step_init()
        result = await flow.async_step_select_location({CONF_LOCATION_ID: LOCATION_ID})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.title == "Renamed Home"


async def test_missing_location_repair_flow_aborts_when_reconfigure_fails(hass):
    """Repair flow should abort with a user-facing reason if switching location fails."""
    entry = build_config_entry()
    entry.add_to_hass(hass)
    flow = MissingLocationRepairFlow(entry)
    flow.hass = hass

    with (
        patch(
            "custom_components.homely.repairs.fetch_locations_for_entry",
            AsyncMock(
                return_value=(
                    [
                        {"locationId": LOCATION_ID, "name": "Home"},
                        {"locationId": SECOND_LOCATION_ID, "name": "Cabin"},
                    ],
                    None,
                )
            ),
        ),
        patch(
            "custom_components.homely.repairs.reconfigure_entry_location",
            AsyncMock(return_value="cannot_reconfigure"),
        ),
    ):
        await flow.async_step_init()
        result = await flow.async_step_select_location(
            {CONF_LOCATION_ID: SECOND_LOCATION_ID}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_reconfigure"


async def test_async_create_fix_flow_raises_for_unknown_issue(hass):
    """Unknown repair ids should raise a clear error."""
    try:
        await async_create_fix_flow(hass, "unknown_issue", {"entry_id": "missing"})
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError")
