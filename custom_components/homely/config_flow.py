"""Config flow for Homely Alarm integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

_LOGGER = logging.getLogger(__name__)

from .const import (
    CONF_HOME_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
    CONF_ENABLE_WEBSOCKET,
    DEFAULT_HOME_ID,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_ENABLE_WEBSOCKET,
    DOMAIN,
)
from .api import fetch_token, get_location_id, get_data


class HomelyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Homely Alarm."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HomelyOptionsFlow:
        """Get the options flow for this handler."""
        return HomelyOptionsFlow()

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
            
            # Get the location name (default to 0 if not specified)
            home_id = user_input.get(CONF_HOME_ID, DEFAULT_HOME_ID)
            try:
                location_item = location_response[home_id]
                location_id = location_item["locationId"]
                
                # Fetch location data to get the name
                location_data = await get_data(self.hass, access_token, location_id)
                location_name = location_data.get("name", f"Homely Alarm {home_id}") if location_data else f"Homely Alarm {home_id}"
            except (KeyError, IndexError, TypeError):
                location_name = f"Homely Alarm {home_id}"
            
            # Store home_id in data even if not provided by user
            user_input[CONF_HOME_ID] = home_id
            
            return self.async_create_entry(
                title=location_name,
                data=user_input,
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_HOME_ID, default=DEFAULT_HOME_ID): vol.Coerce(int),
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=10)
                ),
                vol.Optional(CONF_ENABLE_WEBSOCKET, default=DEFAULT_ENABLE_WEBSOCKET): bool,
            }
        )

        return self.async_show_form(step_id="user", data_schema=data_schema)


class HomelyOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Homely Alarm."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        try:
            _LOGGER.debug("Options flow init called with user_input: %s", user_input)
            
            if user_input is not None:
                _LOGGER.debug("Saving options: %s", user_input)
                return self.async_create_entry(title="", data=user_input)

            # Get current options or use defaults
            _LOGGER.debug("Config entry data: %s", self.config_entry.data)
            _LOGGER.debug("Config entry options: %s", self.config_entry.options)
            
            home_id = self.config_entry.options.get(
                CONF_HOME_ID,
                self.config_entry.data.get(CONF_HOME_ID, DEFAULT_HOME_ID)
            )
            scan_interval = self.config_entry.options.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
            )
            enable_websocket = self.config_entry.options.get(
                CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET
            )
            
            _LOGGER.debug(
                "Options values: home_id=%s, scan_interval=%s, enable_websocket=%s",
                home_id, scan_interval, enable_websocket
            )

            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Optional(
                            CONF_HOME_ID,
                            default=home_id,
                        ): vol.Coerce(int),
                        vol.Optional(
                            CONF_SCAN_INTERVAL,
                            default=scan_interval,
                        ): vol.All(vol.Coerce(int), vol.Range(min=10)),
                        vol.Optional(
                            CONF_ENABLE_WEBSOCKET,
                            default=enable_websocket,
                        ): bool,
                    }
                ),
            )
        except Exception as err:
            _LOGGER.error("Error in options flow: %s", err, exc_info=True)
            return self.async_abort(reason="unknown")
