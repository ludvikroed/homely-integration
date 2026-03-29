"""The Homely Alarm integration."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .api import (
    clear_last_refresh_token_result,
    fetch_refresh_token,
    fetch_token_with_reason,
    get_last_refresh_token_result,
    get_data,
    get_data_with_status,
    get_location_id,
)
from .coordinator_runtime import build_async_update_data
from .const import (
    CONF_ENABLE_WEBSOCKET,
    CONF_HOME_ID,
    CONF_LOCATION_ID,
    CONF_PASSWORD,
    CONF_PENDING_IMPORT_LOCATIONS,
    CONF_POLL_WHEN_WEBSOCKET,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_ENABLE_WEBSOCKET,
    DEFAULT_HOME_ID,
    DEFAULT_POLL_WHEN_WEBSOCKET,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPTION_KEYS,
)
from .logging_helpers import (
    _ctx,
    _json_debug,
    _log_identifier,
    _log_startup_device_payloads as _log_startup_device_payloads_impl,
    _redact_for_debug_logging,
)
from .models import HomelyConfigEntry, HomelyRuntimeData
from .runtime_state import (
    cached_data_grace_seconds,
    current_runtime_data,
    device_id_snapshot,
    record_successful_poll,
    tracked_api_device_ids,
)
from .websocket import HomelyWebSocket
from .websocket_runtime import (
    async_init_websocket,
    build_device_topology_change_handler,
    register_internet_available_listener,
    register_websocket_connected_poll_fallback,
)
from .ws_updates import apply_websocket_event_to_data

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.ALARM_CONTROL_PANEL,
    Platform.LOCK,
]
_LOGGER = logging.getLogger(__name__)


def _cached_data_grace_seconds(scan_interval: int) -> int:
    """Compatibility wrapper for cache-grace helper tests."""
    return cached_data_grace_seconds(scan_interval)


def _device_id_snapshot(data: dict[str, Any] | None) -> set[str]:
    """Compatibility wrapper for device-id snapshot helper tests."""
    return device_id_snapshot(data)


def _tracked_api_device_ids(
    entry_data: HomelyRuntimeData | None,
) -> tuple[bool, set[str]]:
    """Compatibility wrapper for active-device snapshot helper tests."""
    return tracked_api_device_ids(entry_data)


def _log_startup_device_payloads(
    data: dict[str, Any],
    entry_id: str,
    location_id: str | int,
) -> None:
    """Compatibility wrapper for startup payload logging helper tests."""
    _log_startup_device_payloads_impl(_LOGGER, data, entry_id, location_id)


def _missing_location_issue_id(entry_id: str) -> str:
    """Return the repair issue id for a missing configured location."""
    return f"configured_location_missing_{entry_id}"


def _create_missing_location_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    location_identifier: str,
) -> None:
    """Create a repair issue when the configured location is unavailable."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        _missing_location_issue_id(entry.entry_id),
        data={"entry_id": entry.entry_id},
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="configured_location_missing",
        translation_placeholders={
            "entry_title": entry.title,
            "location": location_identifier,
        },
    )


def _delete_missing_location_issue(hass: HomeAssistant, entry_id: str) -> None:
    """Delete the missing-location repair issue for an entry."""
    ir.async_delete_issue(hass, DOMAIN, _missing_location_issue_id(entry_id))


def _get_alarm_state(data: dict[str, Any] | None) -> Any:
    """Return location alarm state, preferring top-level API field."""
    if not isinstance(data, dict):
        return None

    top_level = data.get("alarmState")
    if top_level is not None:
        return top_level

    return (
        data.get("features", {})
        .get("alarm", {})
        .get("states", {})
        .get("alarm", {})
        .get("value")
    )


def _set_alarm_state(data: dict[str, Any], alarm_state: Any) -> None:
    """Write location alarm state to both top-level and nested feature path."""
    data["alarmState"] = alarm_state
    features = data.setdefault("features", {})
    alarm_feature = features.setdefault("alarm", {})
    states = alarm_feature.setdefault("states", {})
    alarm_state_dict = states.setdefault("alarm", {})
    alarm_state_dict["value"] = alarm_state


def _pending_import_locations(
    entry: ConfigEntry,
) -> list[dict[str, str]]:
    """Return sanitized pending multi-location imports from entry data."""
    pending_imports = entry.data.get(CONF_PENDING_IMPORT_LOCATIONS, [])
    if not isinstance(pending_imports, list):
        return []

    sanitized: list[dict[str, str]] = []
    for item in pending_imports:
        if not isinstance(item, dict):
            continue

        location_id = item.get(CONF_LOCATION_ID)
        if location_id is None:
            continue

        sanitized.append(
            {
                CONF_LOCATION_ID: str(location_id),
                "title": str(item.get("title") or "").strip(),
            }
        )

    return sanitized


def _clear_pending_import_locations(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Remove internal pending-import metadata after scheduling."""
    if CONF_PENDING_IMPORT_LOCATIONS not in entry.data:
        return

    updated_data = dict(entry.data)
    updated_data.pop(CONF_PENDING_IMPORT_LOCATIONS, None)
    hass.config_entries.async_update_entry(entry, data=updated_data)


def _schedule_pending_location_imports(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Schedule config flows for additional unconfigured locations."""
    pending_imports = _pending_import_locations(entry)
    if not pending_imports:
        return

    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    if not username or not password:
        _clear_pending_import_locations(hass, entry)
        return

    existing_location_ids = {
        str(existing_entry.data.get(CONF_LOCATION_ID))
        for existing_entry in hass.config_entries.async_entries(DOMAIN)
        if existing_entry.entry_id != entry.entry_id
        and existing_entry.data.get(CONF_LOCATION_ID) is not None
    }

    for pending in pending_imports:
        location_id = pending[CONF_LOCATION_ID]
        if location_id in existing_location_ids:
            continue

        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_IMPORT},
                data={
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                    CONF_LOCATION_ID: location_id,
                    "title": pending["title"],
                },
            )
        )
        existing_location_ids.add(location_id)

    _clear_pending_import_locations(hass, entry)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to newer structure."""
    if entry.version > 2:
        _LOGGER.error("Unsupported config entry version %s", entry.version)
        return False

    if entry.version == 1:
        new_data = dict(entry.data)
        new_options = dict(entry.options)
        for key in OPTION_KEYS:
            if key in new_data and key not in new_options:
                new_options[key] = new_data.pop(key)

        new_unique_id = entry.unique_id
        location_id = new_data.get(CONF_LOCATION_ID)
        if new_unique_id is None and location_id is not None:
            new_unique_id = str(location_id)

        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            options=new_options,
            unique_id=new_unique_id,
            version=2,
        )
        _LOGGER.info(
            "Migrated Homely config entry to version 2 entry_id=%s", entry.entry_id
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: HomelyConfigEntry) -> bool:
    """Set up Homely Alarm from a config entry."""
    entry_id = entry.entry_id
    _LOGGER.debug("Setting up Homely Alarm entry entry_id=%s", entry_id)
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    if not username or not password:
        raise ConfigEntryAuthFailed("Homely credentials are missing")

    response, reason = await fetch_token_with_reason(
        hass,
        username,
        password,
    )

    if not response:
        if reason == "invalid_auth":
            raise ConfigEntryAuthFailed("Invalid Homely username or password")
        raise ConfigEntryNotReady("Failed to fetch Homely token")

    access_token_str = response.get("access_token")
    refresh_token_str = response.get("refresh_token")
    expires_in = response.get("expires_in")
    if not access_token_str or not refresh_token_str:
        raise ConfigEntryNotReady("Token response missing required fields")
    if not expires_in:
        raise ConfigEntryNotReady("Token response missing expires_in")
    try:
        expires_in_seconds = int(expires_in)
    except (TypeError, ValueError) as err:
        raise ConfigEntryNotReady("Token response has invalid expires_in") from err
    _LOGGER.debug(
        "Initial token acquired entry_id=%s access_expires_in_s=%s refresh_margin_s=60",
        entry_id,
        expires_in_seconds,
    )

    # Resolve location id for this entry. Prefer stored location_id and fall back
    # to legacy home_id-based entries created before multi-step location selection.
    location_response = await get_location_id(hass, access_token_str)
    if not location_response:
        raise ConfigEntryNotReady("Failed to fetch Homely locations")
    location_id = None
    configured_location_id = entry.data.get(CONF_LOCATION_ID)
    if configured_location_id is not None:
        configured_location_id = str(configured_location_id)
        for location_item in location_response:
            candidate_location_id = location_item.get("locationId")
            if (
                candidate_location_id is not None
                and str(candidate_location_id) == configured_location_id
            ):
                location_id = candidate_location_id
                break
        if location_id is None:
            _create_missing_location_issue(hass, entry, configured_location_id)
            raise ConfigEntryNotReady(
                f"Configured location_id={configured_location_id} is not available"
            )
    else:
        home_id = int(
            entry.options.get(
                CONF_HOME_ID,
                entry.data.get(CONF_HOME_ID, DEFAULT_HOME_ID),
            )
        )
        _LOGGER.debug("Using legacy home_id=%s entry_id=%s", home_id, entry_id)
        try:
            location_item = location_response[home_id]
            location_id = location_item["locationId"]
        except (KeyError, IndexError, TypeError) as err:
            _LOGGER.debug(
                "Failed to find location_id for home_id=%s entry_id=%s: %s",
                home_id,
                entry_id,
                err,
            )
            _create_missing_location_issue(hass, entry, str(home_id))
            raise ConfigEntryNotReady(
                f"Configured home_id={home_id} is not available"
            ) from err

        _LOGGER.debug(
            "Resolved legacy home_id=%s to location_id=%s entry_id=%s",
            home_id,
            location_id,
            entry_id,
        )

    _delete_missing_location_issue(hass, entry_id)

    normalized_location_id = str(location_id)
    if (
        entry.unique_id != normalized_location_id
        or entry.data.get(CONF_LOCATION_ID) != normalized_location_id
    ):
        updated_data = dict(entry.data)
        updated_data[CONF_LOCATION_ID] = normalized_location_id
        hass.config_entries.async_update_entry(
            entry,
            data=updated_data,
            unique_id=normalized_location_id,
        )
        _LOGGER.debug(
            "Updated config entry with location_id/unique_id entry_id=%s location_id=%s",
            entry_id,
            normalized_location_id,
        )

    data = await get_data(hass, access_token_str, location_id)
    if not data:
        raise ConfigEntryNotReady("Failed to fetch Homely location data")
    initial_alarm_state = _get_alarm_state(data)
    if initial_alarm_state is not None:
        _set_alarm_state(data, initial_alarm_state)
    _log_startup_device_payloads(data, entry_id, location_id)

    def _runtime_data() -> HomelyRuntimeData | None:
        """Return runtime data only while the entry is still loaded."""
        return current_runtime_data(entry)

    scan_interval = int(
        entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
    )
    enable_websocket = entry.options.get(
        CONF_ENABLE_WEBSOCKET,
        entry.data.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET),
    )
    poll_when_websocket = bool(
        entry.options.get(
            CONF_POLL_WHEN_WEBSOCKET,
            entry.data.get(CONF_POLL_WHEN_WEBSOCKET, DEFAULT_POLL_WHEN_WEBSOCKET),
        )
    )

    _LOGGER.debug(
        "Configured polling entry_id=%s location_id=%s scan_interval=%ss websocket=%s",
        entry_id,
        location_id,
        scan_interval,
        enable_websocket,
    )
    _LOGGER.debug(
        "Polling while websocket connected is %s entry_id=%s location_id=%s",
        "enabled" if poll_when_websocket else "disabled",
        entry_id,
        location_id,
    )

    handle_device_topology_change = build_device_topology_change_handler(
        hass=hass,
        entry=entry,
        location_id=location_id,
        logger=_LOGGER,
        runtime_data_getter=_runtime_data,
        ctx=_ctx,
        log_identifier=_log_identifier,
    )
    async_update_data = build_async_update_data(
        hass=hass,
        logger=_LOGGER,
        entry_id=entry_id,
        location_id=location_id,
        username=username,
        password=password,
        scan_interval=scan_interval,
        enable_websocket=bool(enable_websocket),
        poll_when_websocket=poll_when_websocket,
        runtime_data_getter=_runtime_data,
        fetch_refresh_token=lambda runtime_hass, refresh: fetch_refresh_token(
            runtime_hass, refresh
        ),
        fetch_token_with_reason=lambda runtime_hass, runtime_username, runtime_password: fetch_token_with_reason(
            runtime_hass,
            runtime_username,
            runtime_password,
        ),
        get_data_with_status=lambda runtime_hass, token, runtime_location_id: get_data_with_status(
            runtime_hass,
            token,
            runtime_location_id,
        ),
        get_last_refresh_token_result=lambda: get_last_refresh_token_result(),
        clear_last_refresh_token_result=lambda: clear_last_refresh_token_result(),
        get_alarm_state=_get_alarm_state,
        set_alarm_state=_set_alarm_state,
        handle_device_topology_change=handle_device_topology_change,
        ctx=_ctx,
    )
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="homely",
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )
    runtime_data = HomelyRuntimeData(
        coordinator=coordinator,
        access_token=access_token_str,
        refresh_token=refresh_token_str,
        expires_at=time.time() + expires_in_seconds - 60,
        location_id=normalized_location_id,
        last_data=data,
        tracked_device_ids=_device_id_snapshot(data),
    )
    record_successful_poll(runtime_data)
    entry.runtime_data = runtime_data

    if enable_websocket:
        hass.async_create_task(
            async_init_websocket(
                hass=hass,
                entry=entry,
                location_id=location_id,
                logger=_LOGGER,
                runtime_data_getter=_runtime_data,
                coordinator=coordinator,
                enable_websocket=bool(enable_websocket),
                poll_when_websocket=poll_when_websocket,
                websocket_factory=HomelyWebSocket,
                apply_websocket_event=lambda cached_data, event_data: apply_websocket_event_to_data(
                    cached_data,
                    event_data,
                ),
                ctx=_ctx,
                json_debug=_json_debug,
                redact_for_debug_logging=_redact_for_debug_logging,
            )
        )
        _LOGGER.debug(
            "WebSocket initialization scheduled entry_id=%s location_id=%s",
            entry_id,
            location_id,
        )

        try:
            internet_unsub = register_internet_available_listener(
                hass=hass,
                entry=entry,
                location_id=location_id,
                logger=_LOGGER,
                runtime_data_getter=_runtime_data,
            )
            if internet_unsub is None:
                raise RuntimeError("listener registration unavailable")
            entry.async_on_unload(internet_unsub)
        except Exception:
            _LOGGER.debug(
                "Could not register internet_available listener entry_id=%s location_id=%s",
                entry_id,
                location_id,
            )
        if not poll_when_websocket:
            try:
                periodic_poll_unsub = register_websocket_connected_poll_fallback(
                    hass=hass,
                    entry=entry,
                    location_id=location_id,
                    logger=_LOGGER,
                    runtime_data_getter=_runtime_data,
                    coordinator=coordinator,
                    ctx=_ctx,
                )
                if periodic_poll_unsub is None:
                    raise RuntimeError("listener registration unavailable")
                entry.async_on_unload(periodic_poll_unsub)
            except Exception:
                _LOGGER.debug(
                    "Could not register periodic websocket-backed API refresh entry_id=%s location_id=%s",
                    entry_id,
                    location_id,
                )
    else:
        _LOGGER.debug(
            "WebSocket disabled in options entry_id=%s location_id=%s; using polling only",
            entry_id,
            location_id,
        )

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _schedule_pending_location_imports(hass, entry)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.debug(
        "Homely Alarm integration setup completed entry_id=%s location_id=%s",
        entry_id,
        location_id,
    )
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Allow manual deletion of stale Homely devices from the device registry."""
    has_homely_identifier = False
    entry_data = getattr(entry, "runtime_data", None)
    has_snapshot, active_device_ids = _tracked_api_device_ids(entry_data)

    for identifier_domain, identifier in device_entry.identifiers:
        if identifier_domain != DOMAIN:
            continue

        has_homely_identifier = True
        identifier_str = str(identifier)

        # Keep location-level virtual device protected.
        if identifier_str.startswith("location_"):
            _LOGGER.debug(
                "Device removal denied for location device entry_id=%s device_id=%s",
                entry.entry_id,
                identifier_str,
            )
            return False

        if has_snapshot and identifier_str in active_device_ids:
            _LOGGER.debug(
                "Device removal denied for active API device entry_id=%s device_id=%s",
                entry.entry_id,
                identifier_str,
            )
            return False

    if not has_homely_identifier:
        return False

    _LOGGER.debug(
        "Allowing manual removal of stale Homely device entry_id=%s ha_device_id=%s",
        entry.entry_id,
        device_entry.id,
    )
    return True


async def async_reload_entry(hass: HomeAssistant, entry: HomelyConfigEntry) -> None:
    """Reload config entry when options change."""
    _LOGGER.debug("Options changed; reloading entry_id=%s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HomelyConfigEntry) -> bool:
    """Unload a config entry."""
    entry_data = getattr(entry, "runtime_data", None)
    location_id = entry_data.location_id if entry_data is not None else None
    _LOGGER.debug(
        "Unloading Homely Alarm entry entry_id=%s location_id=%s",
        entry.entry_id,
        location_id,
    )
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        ws = entry_data.websocket if entry_data is not None else None
        if ws:
            try:
                await ws.disconnect()
                _LOGGER.debug(
                    "WebSocket disconnected entry_id=%s location_id=%s",
                    entry.entry_id,
                    location_id,
                )
            except Exception as err:
                _LOGGER.error(
                    "Error disconnecting websocket entry_id=%s location_id=%s: %s",
                    entry.entry_id,
                    location_id,
                    err,
                )

        setattr(entry, "runtime_data", None)
        _LOGGER.debug(
            "Homely Alarm integration unloaded entry_id=%s location_id=%s",
            entry.entry_id,
            location_id,
        )
    return unload_ok
