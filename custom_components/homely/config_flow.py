"""Config flow for Homely Alarm integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_HOME_ID, CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .api import fetch_token, get_location_id, get_data


class HomelyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Homely Alarm."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            # Authenticate and get location name
            response = await fetch_token(
                self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            
            if not response:
                return self.async_abort(reason="cannot_connect")
            
            access_token = response.get("access_token")
            if not access_token:
                return self.async_abort(reason="invalid_auth")
            
            # Get locations
            location_response = await get_location_id(self.hass, access_token)
            if not location_response:
                return self.async_abort(reason="cannot_connect")
            
            # Get the location name
            home_id = user_input[CONF_HOME_ID]
            try:
                location_item = location_response[home_id]
                location_id = location_item["locationId"]
                
                # Fetch location data to get the name
                location_data = await get_data(self.hass, access_token, location_id)
                location_name = location_data.get("name", f"Homely Alarm {home_id}") if location_data else f"Homely Alarm {home_id}"
            except (KeyError, IndexError, TypeError):
                location_name = f"Homely Alarm {home_id}"
            
            return self.async_create_entry(
                title=location_name,
                data=user_input,
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_HOME_ID): vol.Coerce(int),
            }
        )

        return self.async_show_form(step_id="user", data_schema=data_schema)
