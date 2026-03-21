"""Config flow for Homely Alarm integration."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr, entity_registry as er

from homely.client import HomelyClient

from .const import (
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
from .entity_ids import battery_problem_unique_id
from .models import HomelyConfigEntry

_LOGGER = logging.getLogger(__name__)


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


async def fetch_locations_for_entry(
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Fetch locations for an existing config entry."""
    username = str(entry.data.get(CONF_USERNAME, ""))
    password = str(entry.data.get(CONF_PASSWORD, ""))
    locations, _access_token, reason = await _fetch_locations_for_credentials(
        hass,
        username,
        password,
    )
    return locations, reason


def _snapshot_entry_registries(
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
) -> tuple[list[er.RegistryEntry], list[dr.DeviceEntry]]:
    """Capture current entity/device registry entries for later cleanup."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    return (
        list(er.async_entries_for_config_entry(entity_registry, entry.entry_id)),
        list(dr.async_entries_for_config_entry(device_registry, entry.entry_id)),
    )


def _entity_unique_id_matches_current_entry(
    unique_id: str | None,
    location_id: str | None,
    active_device_ids: Iterable[str],
) -> bool:
    """Return whether an entity unique id belongs to the current location."""
    if not unique_id:
        return False

    if location_id is not None and unique_id in {
        f"location_{location_id}_alarm_panel",
        f"location_{location_id}_websocket_status",
        battery_problem_unique_id(location_id),
    }:
        return True

    return any(unique_id.startswith(f"{device_id}_") for device_id in active_device_ids)


def _device_entry_matches_current_entry(
    device_entry: dr.DeviceEntry,
    location_id: str | None,
    active_device_ids: set[str],
) -> bool:
    """Return whether a device registry entry belongs to the current location."""
    identifiers: Iterable[tuple[str, str]] = device_entry.identifiers
    for identifier_domain, identifier in identifiers:
        if identifier_domain != DOMAIN:
            continue

        identifier_str = str(identifier)
        if location_id is not None and identifier_str == f"location_{location_id}":
            return True
        if identifier_str in active_device_ids:
            return True

    return False


def cleanup_stale_entry_registries(
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    previous_entities: list[er.RegistryEntry],
    previous_devices: list[dr.DeviceEntry],
) -> None:
    """Remove stale registry objects after a successful reconfigure.

    We only clean up registry entries that no longer belong to the current
    location. This avoids deleting the old registry state before the new setup
    has been proven to work.
    """
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    runtime_data = getattr(entry, "runtime_data", None)
    current_location_id = _normalize_location_id(
        getattr(runtime_data, "location_id", None)
    )
    active_device_ids = {
        str(device_id)
        for device_id in getattr(runtime_data, "tracked_device_ids", set())
    }

    for entity_entry in previous_entities:
        if current_location_id is None or not _entity_unique_id_matches_current_entry(
            getattr(entity_entry, "unique_id", None),
            current_location_id,
            active_device_ids,
        ):
            try:
                entity_registry.async_remove(entity_entry.entity_id)
            except KeyError:
                continue

    for device_entry in previous_devices:
        if current_location_id is None or not _device_entry_matches_current_entry(
            device_entry,
            current_location_id,
            active_device_ids,
        ):
            try:
                device_registry.async_remove_device(device_entry.id)
            except KeyError:
                continue


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


async def reconfigure_entry_location(
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    location: dict[str, Any],
) -> str | None:
    """Switch an entry to a different location safely."""
    normalized_location_id = _normalize_location_id(location.get("locationId"))
    if normalized_location_id is None:
        return "invalid_location"

    previous_entities, previous_devices = _snapshot_entry_registries(hass, entry)

    unload_ok = await hass.config_entries.async_unload(entry.entry_id)
    if not unload_ok:
        return "cannot_reconfigure"

    previous_data = dict(entry.data)
    previous_title = entry.title
    previous_unique_id = entry.unique_id
    updated_data = dict(entry.data)
    updated_data[CONF_LOCATION_ID] = normalized_location_id
    hass.config_entries.async_update_entry(
        entry,
        title=_location_name(location),
        data=updated_data,
        unique_id=normalized_location_id,
    )

    setup_ok = await hass.config_entries.async_setup(entry.entry_id)
    if not setup_ok:
        hass.config_entries.async_update_entry(
            entry,
            title=previous_title,
            data=previous_data,
            unique_id=previous_unique_id,
        )
        restore_ok = await hass.config_entries.async_setup(entry.entry_id)
        if not restore_ok:
            _LOGGER.error(
                "Failed to restore previous Homely configuration after reconfigure failure"
            )
        return "cannot_reconfigure"

    cleanup_stale_entry_registries(hass, entry, previous_entities, previous_devices)

    return None


class HomelyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Homely Alarm."""

    VERSION = 2

    _pending_username: str | None = None
    _pending_password: str | None = None
    _pending_locations: list[dict[str, Any]] | None = None
    _reauth_entry: config_entries.ConfigEntry | None = None
    _reconfigure_locations: list[dict[str, Any]] | None = None

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

    @staticmethod
    def _build_location_schema(locations: list[dict[str, Any]]) -> vol.Schema:
        """Build schema for selecting a location."""
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
                ),
            }
        )

    def _clear_pending_user_selection(self) -> None:
        """Reset transient state for multi-step user flow."""
        self._pending_username = None
        self._pending_password = None
        self._pending_locations = None

    def _clear_pending_reconfigure_selection(self) -> None:
        """Reset transient state for reconfigure flow."""
        self._reconfigure_locations = None

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

    async def _create_entry_for_location(
        self,
        *,
        username: str,
        password: str,
        location: dict[str, Any],
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

        return self.async_create_entry(
            title=_location_name(location),
            data={
                CONF_USERNAME: username,
                CONF_PASSWORD: password,
                CONF_LOCATION_ID: normalized_location_id,
            },
            options={
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                CONF_ENABLE_WEBSOCKET: DEFAULT_ENABLE_WEBSOCKET,
                CONF_POLL_WHEN_WEBSOCKET: DEFAULT_POLL_WHEN_WEBSOCKET,
            },
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

            self._pending_username = username
            self._pending_password = password
            self._pending_locations = locations
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
            selected_location_id = _normalize_location_id(
                user_input.get(CONF_LOCATION_ID)
            )
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

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle switching this entry to another location on the same account."""
        if self.source == config_entries.SOURCE_RECONFIGURE:
            entry: config_entries.ConfigEntry[Any] | None = (
                self._get_reconfigure_entry()
            )
        else:
            entry_id = self.context.get("entry_id")
            entry = (
                self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
            )

        if entry is None:
            return self.async_abort(reason="unknown")

        errors: dict[str, str] = {}

        if user_input is None or self._reconfigure_locations is None:
            locations, reason = await fetch_locations_for_entry(self.hass, entry)
            if reason == "invalid_auth":
                return self.async_abort(reason="reauth_required")
            if reason:
                return self.async_abort(reason=reason)
            if not locations:
                return self.async_abort(reason="no_homes")
            self._reconfigure_locations = locations

        locations = self._reconfigure_locations
        if not locations:
            return self.async_abort(reason="unknown")

        if user_input is not None:
            selected_location_id = _normalize_location_id(
                user_input.get(CONF_LOCATION_ID)
            )
            location = _find_location_by_id(locations, selected_location_id)
            if location is None:
                errors[CONF_LOCATION_ID] = "invalid_location"
            elif self._is_duplicate_location(
                selected_location_id,
                ignore_entry_id=entry.entry_id,
            ):
                self._clear_pending_reconfigure_selection()
                return self.async_abort(reason="already_configured")
            else:
                current_location_id = _normalize_location_id(
                    entry.data.get(CONF_LOCATION_ID)
                )
                if selected_location_id == current_location_id:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        title=_location_name(location),
                    )
                    self._clear_pending_reconfigure_selection()
                    return self.async_abort(reason="reconfigure_successful")

                reason = await reconfigure_entry_location(self.hass, entry, location)
                self._clear_pending_reconfigure_selection()
                if reason is None:
                    return self.async_abort(reason="reconfigure_successful")
                return self.async_abort(reason=reason)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._build_location_schema(locations),
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
