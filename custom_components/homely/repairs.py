"""Repairs support for Homely."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .config_flow import (
    _fetch_locations_for_credentials,
    _find_location_by_id,
    _location_name,
    _location_options,
    _normalize_location_id,
    is_duplicate_location_configured,
)
from .const import CONF_LOCATION_ID, CONF_PASSWORD, CONF_USERNAME, DOMAIN

_CONFIGURED_LOCATION_MISSING_PREFIX = "configured_location_missing_"


class MissingLocationRepairFlow(RepairsFlow):
    """Repair flow for replacing a missing configured location."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Store the target config entry."""
        super().__init__()
        self._entry = entry
        self._locations: list[dict[str, Any]] | None = None

    def _build_location_schema(
        self,
        locations: list[dict[str, Any]],
    ) -> vol.Schema:
        """Build a selector for replacement locations."""
        from homeassistant.helpers import selector

        options = [
            selector.SelectOptionDict(value=value, label=label)
            for value, label in _location_options(locations)
        ]
        default_value = options[0]["value"] if options else None
        return vol.Schema(
            {
                vol.Required(
                    CONF_LOCATION_ID,
                    default=default_value,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

    async def _ensure_available_locations(self) -> str | None:
        """Fetch candidate locations for this repair."""
        if self._locations is not None:
            return None

        username = str(self._entry.data.get(CONF_USERNAME, "")).strip()
        password = str(self._entry.data.get(CONF_PASSWORD, ""))
        if not username or not password:
            return "reauth_required"

        locations, _access_token, reason = await _fetch_locations_for_credentials(
            self.hass,
            username,
            password,
        )
        if reason == "invalid_auth":
            return "reauth_required"
        if reason:
            return reason
        if not locations:
            return "no_homes"

        self._locations = [
            location
            for location in locations
            if (location_id := _normalize_location_id(location.get("locationId")))
            is not None
            and not is_duplicate_location_configured(
                self.hass,
                location_id,
                ignore_entry_id=self._entry.entry_id,
            )
        ]
        if not self._locations:
            return "already_configured"

        return None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Start the repair flow."""
        return await self.async_step_select_location(user_input)

    async def async_step_select_location(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user choose a replacement location."""
        setup_error = await self._ensure_available_locations()
        if setup_error is not None:
            return self.async_abort(reason=setup_error)

        assert self._locations is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_location_id = _normalize_location_id(
                user_input.get(CONF_LOCATION_ID)
            )
            location = _find_location_by_id(self._locations, selected_location_id)
            if location is None:
                errors[CONF_LOCATION_ID] = "invalid_location"
            elif is_duplicate_location_configured(
                self.hass,
                selected_location_id,
                ignore_entry_id=self._entry.entry_id,
            ):
                return self.async_abort(reason="already_configured")
            else:
                updated_data = dict(self._entry.data)
                updated_data[CONF_LOCATION_ID] = selected_location_id
                self.hass.config_entries.async_update_entry(
                    self._entry,
                    data=updated_data,
                    unique_id=selected_location_id,
                    title=_location_name(location),
                )
                self.hass.config_entries.async_schedule_reload(self._entry.entry_id)
                return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="select_location",
            data_schema=self._build_location_schema(self._locations),
            errors=errors,
            description_placeholders={"entry_title": self._entry.title},
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a repairs flow for Homely issues."""
    if issue_id.startswith(_CONFIGURED_LOCATION_MISSING_PREFIX):
        entry_id = data.get("entry_id") if isinstance(data, dict) else None
        if not isinstance(entry_id, str):
            entry_id = issue_id.removeprefix(_CONFIGURED_LOCATION_MISSING_PREFIX)
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            raise ValueError(f"Unknown Homely config entry for repair issue: {issue_id}")

        flow = MissingLocationRepairFlow(entry)
        flow.hass = hass
        flow.handler = DOMAIN
        flow.issue_id = issue_id
        flow.data = data
        return flow

    raise ValueError(f"Unknown Homely repair issue: {issue_id}")
