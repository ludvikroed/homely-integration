"""Tests for Homely repairs flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.homely.const import CONF_LOCATION_ID, CONF_PASSWORD
from custom_components.homely.repairs import async_create_fix_flow
from tests.common import LOCATION_ID, SECOND_LOCATION_ID, build_config_entry


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


async def test_async_create_fix_flow_missing_location_requires_stored_credentials(hass):
    """Repair flow should ask for reauth when stored credentials are unavailable."""
    entry = build_config_entry(data_overrides={CONF_PASSWORD: ""})
    entry.add_to_hass(hass)

    with patch(
        "custom_components.homely.repairs._fetch_locations_for_credentials",
        AsyncMock(),
    ) as fetch_locations:
        flow = await async_create_fix_flow(
            hass,
            f"configured_location_missing_{entry.entry_id}",
            {"entry_id": entry.entry_id},
        )
        result = await flow.async_step_init()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_required"
    fetch_locations.assert_not_called()


async def test_async_create_fix_flow_missing_location_aborts_when_no_homes_exist(hass):
    """Repair flow should explain when no replacement homes are available."""
    entry = build_config_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.homely.repairs._fetch_locations_for_credentials",
        AsyncMock(return_value=([], "token", None)),
    ):
        flow = await async_create_fix_flow(
            hass,
            f"configured_location_missing_{entry.entry_id}",
            {"entry_id": entry.entry_id},
        )
        result = await flow.async_step_init()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_homes"


async def test_async_create_fix_flow_missing_location_rejects_invalid_selection(hass):
    """Repair flow should keep the form open for invalid manual selections."""
    entry = build_config_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.homely.repairs._fetch_locations_for_credentials",
        AsyncMock(
            return_value=(
                [{"locationId": SECOND_LOCATION_ID, "name": "Cabin"}],
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
        result = await flow.async_step_select_location(
            {CONF_LOCATION_ID: "does-not-exist"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_location"
    assert result["errors"] == {CONF_LOCATION_ID: "invalid_location"}


async def test_async_create_fix_flow_missing_location_aborts_when_only_duplicates_remain(
    hass,
):
    """Repair flow should stop when every available home is already configured."""
    entry = build_config_entry()
    entry.add_to_hass(hass)
    duplicate_entry = build_config_entry(
        data_overrides={CONF_LOCATION_ID: SECOND_LOCATION_ID},
        unique_id=SECOND_LOCATION_ID,
    )
    duplicate_entry.add_to_hass(hass)

    with patch(
        "custom_components.homely.repairs._fetch_locations_for_credentials",
        AsyncMock(
            return_value=(
                [{"locationId": SECOND_LOCATION_ID, "name": "Cabin"}],
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

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_async_create_fix_flow_missing_location_detects_duplicate_on_submit(hass):
    """Repair flow should abort if another entry claims the selected home before submit."""
    entry = build_config_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.homely.repairs._fetch_locations_for_credentials",
        AsyncMock(
            return_value=(
                [{"locationId": SECOND_LOCATION_ID, "name": "Cabin"}],
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
        initial_result = await flow.async_step_init()

        duplicate_entry = build_config_entry(
            data_overrides={CONF_LOCATION_ID: SECOND_LOCATION_ID},
            unique_id=SECOND_LOCATION_ID,
        )
        duplicate_entry.add_to_hass(hass)

        submit_result = await flow.async_step_select_location(
            {CONF_LOCATION_ID: SECOND_LOCATION_ID}
        )

    assert initial_result["type"] is FlowResultType.FORM
    assert submit_result["type"] is FlowResultType.ABORT
    assert submit_result["reason"] == "already_configured"


async def test_async_create_fix_flow_raises_for_unknown_issue(hass):
    """Unknown repair ids should raise a clear error."""
    try:
        await async_create_fix_flow(hass, "unknown_issue", {"entry_id": "missing"})
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError")
