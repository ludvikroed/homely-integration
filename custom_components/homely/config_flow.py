"""Config flow for Homely Alarm integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homely.client import HomelyClient

from .const import (
    CONF_PENDING_IMPORT_LOCATIONS,
    CONF_ENABLE_WEBSOCKET,
    CONF_HOME_ID,
    CONF_LOCATION_ID,
    CONF_PASSWORD,
    CONF_POLL_WHEN_WEBSOCKET,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_ENABLE_WEBSOCKET,
    DEFAULT_HOME_ID,
    DEFAULT_POLL_WHEN_WEBSOCKET,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .models import HomelyConfigEntry

_LOGGER = logging.getLogger(__name__)
LOCATION_SELECTION_ALL = "__all_locations__"


def _redact(data: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive keys before logging."""
    redacted = dict(data)
    if CONF_USERNAME in redacted:
        redacted[CONF_USERNAME] = "***"
    if CONF_PASSWORD in redacted:
        redacted[CONF_PASSWORD] = "***"
    return redacted


def _normalize_location_id(location_id: Any) -> str | None:
    """Convert location id to stable string value."""
    if location_id is None:
        return None
    return str(location_id)


def _entry_home_id(entry: config_entries.ConfigEntry) -> int:
    """Read legacy home index from entry options/data with fallback."""
    try:
        return int(
            entry.options.get(
                CONF_HOME_ID,
                entry.data.get(CONF_HOME_ID, DEFAULT_HOME_ID),
            )
        )
    except (TypeError, ValueError):
        return DEFAULT_HOME_ID


def _location_name(location: dict[str, Any]) -> str:
    """Return a human-friendly location name."""
    name = str(location.get("name") or "").strip()
    if name:
        return name

    gateway_serial = str(location.get("gatewayserial") or "").strip()
    if gateway_serial:
        return f"Homely {gateway_serial}"

    normalized_location_id = _normalize_location_id(location.get("locationId"))
    if normalized_location_id:
        return f"Homely {normalized_location_id[:8]}"

    return "Homely"


def _location_label(location: dict[str, Any], *, duplicate_names: set[str]) -> str:
    """Return a selector label for a location."""
    base_name = _location_name(location)
    if base_name not in duplicate_names:
        return base_name

    gateway_serial = str(location.get("gatewayserial") or "").strip()
    if gateway_serial:
        return f"{base_name} ({gateway_serial})"

    normalized_location_id = _normalize_location_id(location.get("locationId"))
    if normalized_location_id:
        return f"{base_name} ({normalized_location_id[:8]})"

    return base_name


def _location_options(locations: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Return selector options for location choice."""
    names = [_location_name(location) for location in locations]
    duplicate_names = {name for name in names if names.count(name) > 1}

    options: list[tuple[str, str]] = []
    for location in locations:
        normalized_location_id = _normalize_location_id(location.get("locationId"))
        if normalized_location_id is None:
            continue
        options.append(
            (
                normalized_location_id,
                _location_label(location, duplicate_names=duplicate_names),
            )
        )
    return options


def _find_location_by_id(
    locations: list[dict[str, Any]],
    location_id: str | None,
) -> dict[str, Any] | None:
    """Find a location item by location id."""
    if location_id is None:
        return None
    for location in locations:
        if _normalize_location_id(location.get("locationId")) == location_id:
            return location
    return None


def _entry_options() -> dict[str, Any]:
    """Return default options for newly created entries."""
    return {
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_ENABLE_WEBSOCKET: DEFAULT_ENABLE_WEBSOCKET,
        CONF_POLL_WHEN_WEBSOCKET: DEFAULT_POLL_WHEN_WEBSOCKET,
    }


def _coerce_scan_interval(value: Any, default: int = DEFAULT_SCAN_INTERVAL) -> int:
    """Return a valid scan interval with safe fallback."""
    try:
        return max(30, int(value))
    except (TypeError, ValueError):
        return default


def _get_client(hass: HomeAssistant) -> HomelyClient:
    """Build a Homely SDK client bound to Home Assistant's shared session."""
    return HomelyClient(async_get_clientsession(hass))


async def fetch_token_with_reason(
    hass: HomeAssistant,
    username: str,
    password: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch credentials through the SDK client."""
    return await _get_client(hass).fetch_token_with_reason(username, password)


async def get_location_id(
    hass: HomeAssistant,
    token: str,
) -> list[dict[str, Any]] | None:
    """Fetch account locations through the SDK client."""
    return await _get_client(hass).get_locations(token)


async def get_data(
    hass: HomeAssistant,
    token: str,
    location_id: str | int,
) -> dict[str, Any] | None:
    """Fetch location data through the SDK client."""
    return await _get_client(hass).get_home_data(token, location_id)


async def _fetch_locations_for_credentials(
    hass: HomeAssistant,
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


def is_duplicate_location_configured(
    hass: HomeAssistant,
    location_id: str | None,
    *,
    ignore_entry_id: str | None = None,
) -> bool:
    """Check whether a location is already configured for this domain."""
    if location_id is None:
        return False

    for entry in hass.config_entries.async_entries(DOMAIN):
        if ignore_entry_id is not None and entry.entry_id == ignore_entry_id:
            continue

        existing_location = _normalize_location_id(entry.data.get(CONF_LOCATION_ID))
        if existing_location == location_id:
            return True
        if entry.unique_id == location_id:
            return True

    return False
class HomelyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Homely Alarm."""

    VERSION = 2

    _pending_username: str | None = None
    _pending_password: str | None = None
    _pending_locations: list[dict[str, Any]] | None = None
    _reauth_entry: config_entries.ConfigEntry | None = None

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HomelyOptionsFlow:
        """Get the options flow for this handler."""
        return HomelyOptionsFlow()

    @staticmethod
    def _build_user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
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
            }
        )

    def _build_location_schema(
        self,
        locations: list[dict[str, Any]],
    ) -> vol.Schema:
        """Build schema for selecting a location."""
        from homeassistant.helpers import selector

        options: list[selector.SelectOptionDict] = []
        if len(locations) > 1:
            options.append(
                selector.SelectOptionDict(
                    value=LOCATION_SELECTION_ALL,
                    label="Add all homes",
                )
            )

        options.extend(
            selector.SelectOptionDict(value=value, label=label)
            for value, label in _location_options(locations)
        )
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

    def _clear_pending_user_selection(self) -> None:
        """Reset transient state for multi-step user flow."""
        self._pending_username = None
        self._pending_password = None
        self._pending_locations = None

    def _is_duplicate_location(
        self,
        location_id: str | None,
        *,
        ignore_entry_id: str | None = None,
    ) -> bool:
        """Check whether a location is already configured."""
        return is_duplicate_location_configured(
            self.hass,
            location_id,
            ignore_entry_id=ignore_entry_id,
        )

    def _available_locations(
        self,
        locations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return locations that can still be added."""
        return [
            location
            for location in locations
            if _normalize_location_id(location.get("locationId")) is not None
            and not self._is_duplicate_location(
                _normalize_location_id(location.get("locationId"))
            )
        ]

    async def _create_entry_for_location(
        self,
        *,
        username: str,
        password: str,
        location: dict[str, Any],
        pending_import_locations: list[dict[str, str]] | None = None,
    ) -> ConfigFlowResult:
        """Create a config entry for the selected location."""
        normalized_location_id = _normalize_location_id(location.get("locationId"))
        if normalized_location_id is None:
            return self.async_abort(reason="invalid_location")

        if self._is_duplicate_location(normalized_location_id):
            return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(normalized_location_id)
        self._abort_if_unique_id_configured()

        self._clear_pending_user_selection()

        entry_data = {
            CONF_USERNAME: username,
            CONF_PASSWORD: password,
            CONF_LOCATION_ID: normalized_location_id,
        }
        if pending_import_locations:
            entry_data[CONF_PENDING_IMPORT_LOCATIONS] = pending_import_locations

        return self.async_create_entry(
            title=_location_name(location),
            data=entry_data,
            options=_entry_options(),
        )

    async def _create_entries_for_all_locations(
        self,
        *,
        username: str,
        password: str,
        locations: list[dict[str, Any]],
    ) -> ConfigFlowResult:
        """Create entries for all currently unconfigured locations."""
        unconfigured_locations = self._available_locations(locations)
        if not unconfigured_locations:
            self._clear_pending_user_selection()
            return self.async_abort(reason="already_configured")

        primary_location, *remaining_locations = unconfigured_locations
        pending_import_locations = [
            {
                CONF_LOCATION_ID: str(location["locationId"]),
                "title": _location_name(location),
            }
            for location in remaining_locations
            if location.get("locationId") is not None
        ]
        return await self._create_entry_for_location(
            username=username,
            password=password,
            location=primary_location,
            pending_import_locations=pending_import_locations,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            input_values = dict(user_input)
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            locations, _access_token, reason = await _fetch_locations_for_credentials(
                self.hass,
                username,
                password,
            )
            if reason or not locations:
                errors["base"] = reason or "cannot_connect"
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._build_user_schema(input_values),
                    errors=errors,
                )

            if len(locations) == 1:
                return await self._create_entry_for_location(
                    username=username,
                    password=password,
                    location=locations[0],
                )

            available_locations = self._available_locations(locations)
            if not available_locations:
                return self.async_abort(reason="already_configured")

            self._pending_username = username
            self._pending_password = password
            self._pending_locations = available_locations
            return await self.async_step_select_location()

        return self.async_show_form(
            step_id="user",
            data_schema=self._build_user_schema(),
            errors=errors,
        )

    async def async_step_select_location(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle location selection for accounts with multiple locations."""
        errors: dict[str, str] = {}
        locations = self._pending_locations
        username = self._pending_username
        password = self._pending_password

        if not locations or username is None or password is None:
            return self.async_abort(reason="unknown")

        if user_input is not None:
            selected_location_id = user_input.get(CONF_LOCATION_ID)
            if selected_location_id == LOCATION_SELECTION_ALL:
                return await self._create_entries_for_all_locations(
                    username=username,
                    password=password,
                    locations=locations,
                )

            selected_location_id = _normalize_location_id(selected_location_id)
            location = _find_location_by_id(locations, selected_location_id)
            if location is None:
                errors[CONF_LOCATION_ID] = "invalid_location"
            else:
                return await self._create_entry_for_location(
                    username=username,
                    password=password,
                    location=location,
                )

        return self.async_show_form(
            step_id="select_location",
            data_schema=self._build_location_schema(locations),
            errors=errors,
        )

    async def async_step_import(
        self,
        import_data: dict[str, Any],
    ) -> ConfigFlowResult:
        """Create additional entries scheduled internally by the user flow."""
        location_id = _normalize_location_id(import_data.get(CONF_LOCATION_ID))
        username = str(import_data.get(CONF_USERNAME, ""))
        password = str(import_data.get(CONF_PASSWORD, ""))
        if location_id is None:
            return self.async_abort(reason="invalid_location")
        if not username or not password:
            return self.async_abort(reason="invalid_auth")

        title = str(import_data.get("title") or "").strip() or f"Homely {location_id[:8]}"
        return await self._create_entry_for_location(
            username=username,
            password=password,
            location={
                "locationId": location_id,
                "name": title,
            },
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> ConfigFlowResult:
        """Handle a reauth flow."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Confirm reauthentication with updated credentials."""
        errors: dict[str, str] = {}
        reauth_entry = self._reauth_entry
        if reauth_entry is None:
            return self.async_abort(reason="unknown")

        defaults = {
            CONF_USERNAME: reauth_entry.data.get(CONF_USERNAME, ""),
            CONF_PASSWORD: "",
        }

        if user_input is not None:
            input_values = dict(user_input)
            locations, _access_token, reason = await _fetch_locations_for_credentials(
                self.hass,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            current_location_id = _normalize_location_id(
                reauth_entry.data.get(CONF_LOCATION_ID)
            )
            if reason or not locations:
                errors["base"] = reason or "cannot_connect"
            elif _find_location_by_id(locations, current_location_id) is None:
                errors["base"] = "invalid_location"
            else:
                updated_data = dict(reauth_entry.data)
                updated_data[CONF_USERNAME] = user_input[CONF_USERNAME]
                updated_data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates=updated_data,
                )

            defaults.update(input_values)

        from homeassistant.helpers import selector

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=defaults.get(CONF_USERNAME, ""),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.EMAIL
                        )
                    ),
                    vol.Required(
                        CONF_PASSWORD,
                        default=defaults.get(CONF_PASSWORD, ""),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                }
            ),
            errors=errors,
        )

class HomelyOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Homely Alarm."""

    @staticmethod
    def _build_options_schema(
        scan_interval: int,
        enable_websocket: bool,
        poll_when_websocket: bool,
    ) -> vol.Schema:
        """Build options schema with supplied defaults."""
        from homeassistant.helpers import selector

        return vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=scan_interval,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=30,
                        unit_of_measurement="seconds",
                    )
                ),
                vol.Optional(
                    CONF_ENABLE_WEBSOCKET,
                    default=enable_websocket,
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_POLL_WHEN_WEBSOCKET,
                    default=poll_when_websocket,
                ): selector.BooleanSelector(),
            }
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage advanced runtime options."""
        scan_interval = _coerce_scan_interval(
            self.config_entry.options.get(
                CONF_SCAN_INTERVAL,
                self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )
        )
        enable_websocket = bool(
            self.config_entry.options.get(
                CONF_ENABLE_WEBSOCKET,
                self.config_entry.data.get(
                    CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET
                ),
            )
        )
        poll_when_websocket = bool(
            self.config_entry.options.get(
                CONF_POLL_WHEN_WEBSOCKET,
                self.config_entry.data.get(
                    CONF_POLL_WHEN_WEBSOCKET,
                    DEFAULT_POLL_WHEN_WEBSOCKET,
                ),
            )
        )

        if user_input is not None:
            errors: dict[str, str] = {}

            raw_scan_interval = user_input.get(CONF_SCAN_INTERVAL, scan_interval)
            try:
                scan_interval = int(raw_scan_interval)
                if scan_interval < 30:
                    raise ValueError
            except (TypeError, ValueError):
                errors[CONF_SCAN_INTERVAL] = "invalid_scan_interval"
                scan_interval = _coerce_scan_interval(raw_scan_interval, scan_interval)

            enable_websocket = bool(
                user_input.get(CONF_ENABLE_WEBSOCKET, enable_websocket)
            )
            poll_when_websocket = bool(
                user_input.get(CONF_POLL_WHEN_WEBSOCKET, poll_when_websocket)
            )

            if errors:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._build_options_schema(
                        scan_interval,
                        enable_websocket,
                        poll_when_websocket,
                    ),
                    errors=errors,
                )

            return self.async_create_entry(
                title="",
                data={
                    CONF_SCAN_INTERVAL: scan_interval,
                    CONF_ENABLE_WEBSOCKET: enable_websocket,
                    CONF_POLL_WHEN_WEBSOCKET: poll_when_websocket,
                },
            )

        return self.async_show_form(
            step_id="init",
            data_schema=self._build_options_schema(
                scan_interval,
                enable_websocket,
                poll_when_websocket,
            ),
        )
