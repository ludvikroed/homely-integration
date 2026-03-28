"""Repairs support for Homely."""

from __future__ import annotations

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a repairs flow for Homely issues."""
    raise ValueError(f"Unknown Homely repair issue: {issue_id}")
