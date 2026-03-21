"""Repairs support for Homely."""

from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .config_flow import (
    HomelyConfigFlow,
    _find_location_by_id,
    _location_name,
    _normalize_location_id,
    fetch_locations_for_entry,
    is_duplicate_location_configured,
    reconfigure_entry_location,
)
from .models import HomelyConfigEntry


class MissingLocationRepairFlow(RepairsFlow):
    """Repair flow for entries whose configured location is no longer available."""

    def __init__(self, entry: HomelyConfigEntry) -> None:
        """Initialize the repair flow."""
        self.entry = entry
        self._locations: list[dict[str, Any]] | None = None

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Start the repair flow."""
        return await self.async_step_select_location(user_input)

    async def async_step_select_location(
        self,
        user_input: dict[str, str] | None = None,
    ) -> FlowResult:
        """Select a replacement location for this entry."""
        errors: dict[str, str] = {}

        if self._locations is None:
            locations, reason = await fetch_locations_for_entry(self.hass, self.entry)
            if reason == "invalid_auth":
                return self.async_abort(reason="reauth_required")
            if reason:
                errors["base"] = reason
            elif not locations:
                errors["base"] = "no_homes"
            else:
                self._locations = locations

        if user_input is not None and self._locations is not None:
            selected_location_id = _normalize_location_id(user_input.get("location_id"))
            location = _find_location_by_id(self._locations, selected_location_id)
            if location is None:
                errors["location_id"] = "invalid_location"
            elif is_duplicate_location_configured(
                self.hass,
                selected_location_id,
                ignore_entry_id=self.entry.entry_id,
            ):
                return self.async_abort(reason="already_configured")
            else:
                current_location_id = _normalize_location_id(
                    self.entry.data.get("location_id")
                )
                if selected_location_id == current_location_id:
                    self.hass.config_entries.async_update_entry(
                        self.entry,
                        title=_location_name(location),
                    )
                    return self.async_create_entry(data={})

                reason = await reconfigure_entry_location(
                    self.hass, self.entry, location
                )
                if reason is None:
                    return self.async_create_entry(data={})
                return self.async_abort(reason=reason)

        return self.async_show_form(
            step_id="select_location",
            data_schema=HomelyConfigFlow._build_location_schema(self._locations or []),
            errors=errors,
            description_placeholders={"entry_title": self.entry.title},
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a repairs flow for Homely issues."""
    assert data is not None
    entry_id = data.get("entry_id")
    assert isinstance(entry_id, str)

    if issue_id.startswith("configured_location_missing_") and (
        entry := hass.config_entries.async_get_entry(entry_id)
    ):
        return MissingLocationRepairFlow(entry)

    raise ValueError(f"Unknown Homely repair issue: {issue_id}")
