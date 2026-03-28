"""Tests for Homely repairs flows."""

from __future__ import annotations

from custom_components.homely.repairs import async_create_fix_flow
from tests.common import build_config_entry


async def test_async_create_fix_flow_raises_for_missing_location_issue(hass):
    """Missing-location issues should not expose a fix flow."""
    entry = build_config_entry()
    entry.add_to_hass(hass)

    try:
        await async_create_fix_flow(
            hass,
            f"configured_location_missing_{entry.entry_id}",
            {"entry_id": entry.entry_id},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError")


async def test_async_create_fix_flow_raises_for_unknown_issue(hass):
    """Unknown repair ids should raise a clear error."""
    try:
        await async_create_fix_flow(hass, "unknown_issue", {"entry_id": "missing"})
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError")
