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
from .api import fetch_token_with_reason, get_location_id, get_data


def _redact(data: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive keys before logging."""
    redacted = dict(data)
    if CONF_USERNAME in redacted:
        redacted[CONF_USERNAME] = "***"
    if CONF_PASSWORD in redacted:
        redacted[CONF_PASSWORD] = "***"
    return redacted


async def _fetch_locations_for_credentials(
    hass,
    username: str,
    password: str,
) -> tuple[list[dict[str, Any]] | None, str | None, str | None]:
    """Authenticate and fetch account locations."""
    response, reason = await fetch_token_with_reason(hass, username, password)
    if not response:
        return None, None, reason or "cannot_connect"

    access_token = response.get("access_token")
    if not access_token:
        return None, None, "invalid_auth"

    locations = await get_location_id(hass, access_token)
    if locations is None:
        return None, None, "cannot_connect"
    if not locations:
        return None, access_token, "no_homes"
    return locations, access_token, None


class HomelyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Homely Alarm."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HomelyOptionsFlow:
        """Get the options flow for this handler."""
        return HomelyOptionsFlow()

    @staticmethod
    def _build_user_schema(defaults: dict[str, Any] | None = None):
        """Build user-step schema."""
        from homeassistant.helpers import selector

        default_values = defaults or {}
        return vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME,
                    default=default_values.get(CONF_USERNAME, ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
                ),
                vol.Required(
                    CONF_PASSWORD,
                    default=default_values.get(CONF_PASSWORD, ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Optional(
                    CONF_HOME_ID,
                    default=default_values.get(CONF_HOME_ID, DEFAULT_HOME_ID),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=0,
                    )
                ),
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=default_values.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=10,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional(
                    CONF_ENABLE_WEBSOCKET,
                    default=default_values.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET),
                ): selector.BooleanSelector(),
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            input_values = dict(user_input)

            # Get the location name (default to 0 if not specified)
            try:
                home_id = int(user_input.get(CONF_HOME_ID, DEFAULT_HOME_ID))
            except (TypeError, ValueError):
                errors[CONF_HOME_ID] = "invalid_home_id"
                return self.async_show_form(step_id="user", data_schema=self._build_user_schema(input_values), errors=errors)

            try:
                scan_interval = int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
                if scan_interval < 10:
                    raise ValueError
            except (TypeError, ValueError):
                errors[CONF_SCAN_INTERVAL] = "invalid_scan_interval"
                return self.async_show_form(step_id="user", data_schema=self._build_user_schema(input_values), errors=errors)

            location_response, access_token, reason = await _fetch_locations_for_credentials(
                self.hass,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            if reason or not location_response:
                errors["base"] = reason or "cannot_connect"
                return self.async_show_form(step_id="user", data_schema=self._build_user_schema(input_values), errors=errors)

            if home_id < 0 or home_id >= len(location_response):
                errors[CONF_HOME_ID] = "invalid_home_id"
                return self.async_show_form(step_id="user", data_schema=self._build_user_schema(input_values), errors=errors)
            enable_websocket = user_input.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET)

            location_item = location_response[home_id]
            location_id = location_item.get("locationId")

            # Fetch location data to get the name
            location_data = None
            if location_id is not None and access_token:
                location_data = await get_data(self.hass, access_token, location_id)
            location_name = (
                location_data.get("name", f"Homely Alarm {home_id}")
                if isinstance(location_data, dict)
                else f"Homely Alarm {home_id}"
            )

            entry_data = dict(user_input)
            entry_data[CONF_HOME_ID] = home_id
            entry_data[CONF_SCAN_INTERVAL] = scan_interval
            entry_data[CONF_ENABLE_WEBSOCKET] = bool(enable_websocket)

            return self.async_create_entry(
                title=location_name,
                data=entry_data,
            )

        return self.async_show_form(step_id="user", data_schema=self._build_user_schema(), errors=errors)


class HomelyOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Homely Alarm."""

    @staticmethod
    def _build_options_schema(
        home_id: int,
        scan_interval: int,
        enable_websocket: bool,
    ) -> vol.Schema:
        """Build options schema with supplied defaults."""
        return vol.Schema(
            {
                vol.Optional(CONF_HOME_ID, default=home_id): vol.Coerce(int),
                vol.Optional(CONF_SCAN_INTERVAL, default=scan_interval): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=10),
                ),
                vol.Optional(CONF_ENABLE_WEBSOCKET, default=enable_websocket): bool,
            }
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        try:
            if user_input is not None:
                _LOGGER.debug(
                    "Options flow submitted with data=%s",
                    _redact(dict(user_input)),
                )
            else:
                _LOGGER.debug("Options flow opened")

            # Get current options or use defaults
            _LOGGER.debug("Config entry data: %s", _redact(dict(self.config_entry.data)))
            _LOGGER.debug("Config entry options: %s", dict(self.config_entry.options))

            home_id = int(self.config_entry.options.get(
                CONF_HOME_ID,
                self.config_entry.data.get(CONF_HOME_ID, DEFAULT_HOME_ID)
            ))
            scan_interval = int(self.config_entry.options.get(
                CONF_SCAN_INTERVAL,
                self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ))
            enable_websocket = self.config_entry.options.get(
                CONF_ENABLE_WEBSOCKET,
                self.config_entry.data.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET)
            )

            if user_input is not None:
                errors: dict[str, str] = {}

                try:
                    home_id = int(user_input.get(CONF_HOME_ID, home_id))
                except (TypeError, ValueError):
                    errors[CONF_HOME_ID] = "invalid_home_id"

                try:
                    scan_interval = int(user_input.get(CONF_SCAN_INTERVAL, scan_interval))
                    if scan_interval < 10:
                        raise ValueError
                except (TypeError, ValueError):
                    errors[CONF_SCAN_INTERVAL] = "invalid_scan_interval"

                enable_websocket = bool(user_input.get(CONF_ENABLE_WEBSOCKET, enable_websocket))

                if not errors:
                    username = self.config_entry.data.get(CONF_USERNAME)
                    password = self.config_entry.data.get(CONF_PASSWORD)
                    if not username or not password:
                        errors["base"] = "invalid_auth"
                    else:
                        location_response, _access_token, reason = await _fetch_locations_for_credentials(
                            self.hass,
                            username,
                            password,
                        )
                        if reason or not location_response:
                            errors["base"] = reason or "cannot_connect"
                        elif home_id < 0 or home_id >= len(location_response):
                            errors[CONF_HOME_ID] = "invalid_home_id"

                if errors:
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._build_options_schema(home_id, scan_interval, enable_websocket),
                        errors=errors,
                    )

                user_input[CONF_HOME_ID] = home_id
                user_input[CONF_SCAN_INTERVAL] = scan_interval
                user_input[CONF_ENABLE_WEBSOCKET] = enable_websocket
                _LOGGER.debug("Saving options: %s", dict(user_input))
                return self.async_create_entry(title="", data=user_input)

            _LOGGER.debug(
                "Options values: home_id=%s, scan_interval=%s, enable_websocket=%s",
                home_id, scan_interval, enable_websocket
            )

            return self.async_show_form(
                step_id="init",
                data_schema=self._build_options_schema(home_id, scan_interval, enable_websocket),
            )
        except Exception as err:
            _LOGGER.error("Error in options flow: %s", err, exc_info=True)
            return self.async_abort(reason="unknown")
