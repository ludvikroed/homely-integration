"""The Homely Alarm integration."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.const import Platform
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers import issue_registry as ir

from datetime import timedelta
from .api import (
    fetch_refresh_token,
    fetch_token_with_reason,
    get_data,
    get_data_with_status,
    get_location_id,
)
from .const import (
    CONF_HOME_ID,
    CONF_LOCATION_ID,
    CONF_SCAN_INTERVAL,
    CONF_ENABLE_WEBSOCKET,
    CONF_POLL_WHEN_WEBSOCKET,
    DEFAULT_HOME_ID,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_ENABLE_WEBSOCKET,
    DEFAULT_POLL_WHEN_WEBSOCKET,
    DOMAIN,
    OPTION_KEYS,
)
from .models import HomelyRuntimeData
from .websocket import HomelyWebSocket
from .ws_updates import apply_websocket_event_to_data

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.ALARM_CONTROL_PANEL, Platform.LOCK]
_LOGGER = logging.getLogger(__name__)
_TRANSIENT_HTTP_STATUS = {429, 500, 502, 503, 504}
_LOG_REDACT_KEYS = {
    "deviceId",
    "gatewayserial",
    "id",
    "location",
    "locationId",
    "name",
    "networklinkaddress",
    "serialNumber",
}


def _missing_location_issue_id(entry_id: str) -> str:
    """Return the repair issue id for a missing configured location."""
    return f"configured_location_missing_{entry_id}"


def _create_missing_location_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    location_identifier: str,
) -> None:
    """Create a fixable repair issue when the configured location is unavailable."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        _missing_location_issue_id(entry.entry_id),
        data={"entry_id": entry.entry_id},
        is_fixable=True,
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


def _ctx(entry_id: str, location_id: str | None = None, device_id: str | None = None) -> str:
    """Build consistent structured logging context."""
    context = f"entry_id={entry_id}"
    if location_id is not None:
        context += f" location_id={location_id}"
    if device_id is not None:
        context += f" device_id={device_id}"
    return context


def _json_debug(value: Any) -> str:
    """Return JSON string for debug logging without raising."""
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(value)


def _redact_for_debug_logging(value: Any) -> Any:
    """Return a version of nested payloads suitable for debug logging."""
    if isinstance(value, dict):
        return {
            key: ("**REDACTED**" if key in _LOG_REDACT_KEYS else _redact_for_debug_logging(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_for_debug_logging(item) for item in value]
    return value


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


def _log_startup_device_payloads(
    data: dict[str, Any],
    entry_id: str,
    location_id: str | int,
) -> None:
    """Log full payload per device once during startup when debug logging is enabled."""
    if not _LOGGER.isEnabledFor(logging.DEBUG):
        return

    location_id_str = str(location_id)
    devices = data.get("devices")
    if not isinstance(devices, list):
        _LOGGER.debug(
            "Startup API device dump skipped; devices list missing %s",
            _ctx(entry_id, location_id_str),
        )
        return

    _LOGGER.debug(
        "Startup API device dump begin %s device_count=%s",
        _ctx(entry_id, location_id_str),
        len(devices),
    )

    for index, device in enumerate(devices, start=1):
        if not isinstance(device, dict):
            _LOGGER.debug(
                "Startup API device payload #%s is not an object %s payload=%r",
                index,
                _ctx(entry_id, location_id_str),
                device,
            )
            continue

        device_dump = json.dumps(
            _redact_for_debug_logging(device),
            indent=2,
            ensure_ascii=True,
            sort_keys=True,
        )

        _LOGGER.debug(
            "Startup API payload #%s %s\n%s",
            index,
            _ctx(entry_id, location_id_str),
            device_dump,
        )

    _LOGGER.debug("Startup API device dump complete %s", _ctx(entry_id, location_id_str))


def _tracked_api_device_ids(entry_data: HomelyRuntimeData | None) -> tuple[bool, set[str]]:
    """Return current Homely device ids from coordinator/cache with availability flag."""
    if entry_data is None:
        return False, set()

    data = entry_data.coordinator.data or entry_data.last_data
    if not isinstance(data, dict):
        return False, set()

    devices = data.get("devices")
    if not isinstance(devices, list):
        return False, set()

    tracked_ids = {
        str(device_id)
        for device in devices
        if isinstance(device, dict) and (device_id := device.get("id")) is not None
    }
    return True, tracked_ids


def _device_id_snapshot(data: dict[str, Any] | None) -> set[str]:
    """Return device ids from a Homely payload."""
    if not isinstance(data, dict):
        return set()

    devices = data.get("devices")
    if not isinstance(devices, list):
        return set()

    return {
        str(device_id)
        for device in devices
        if isinstance(device, dict) and (device_id := device.get("id")) is not None
    }


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
        _LOGGER.info("Migrated Homely config entry to version 2 entry_id=%s", entry.entry_id)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Homely Alarm from a config entry."""
    entry_id = entry.entry_id
    _LOGGER.debug("Setting up Homely Alarm entry entry_id=%s", entry_id)
    username = entry.data.get("username")
    password = entry.data.get("password")
    if not username or not password:
        raise ConfigEntryAuthFailed("Homely credentials are missing")

    # Initial login to get tokens
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
            if candidate_location_id is not None and str(candidate_location_id) == configured_location_id:
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
            _LOGGER.error(
                "Failed to find location_id for home_id=%s entry_id=%s: %s",
                home_id,
                entry_id,
                err,
            )
            _create_missing_location_issue(hass, entry, str(home_id))
            raise ConfigEntryNotReady(f"Configured home_id={home_id} is not available") from err

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
    
    # Initial data fetch
    data = await get_data(hass, access_token_str, location_id)
    if not data:
        raise ConfigEntryNotReady("Failed to fetch Homely location data")
    initial_alarm_state = _get_alarm_state(data)
    if initial_alarm_state is not None:
        _set_alarm_state(data, initial_alarm_state)
    _log_startup_device_payloads(data, entry_id, location_id)
    
    runtime_data: HomelyRuntimeData | None = None

    async def _reload_for_device_topology_change() -> None:
        """Reload the entry once when the device list changes."""
        if runtime_data is None:
            return

        try:
            _LOGGER.info(
                "Reloading Homely entry after device topology change %s",
                _ctx(entry_id, location_id),
            )
            await hass.config_entries.async_reload(entry_id)
        finally:
            if runtime_data is not None:
                runtime_data.topology_reload_pending = False

    def _handle_device_topology_change(updated_data: dict[str, Any]) -> None:
        """Detect added or removed devices and schedule a reload when needed."""
        if runtime_data is None:
            return

        updated_ids = _device_id_snapshot(updated_data)
        previous_ids = runtime_data.tracked_device_ids
        if not previous_ids:
            runtime_data.tracked_device_ids = updated_ids
            return

        if updated_ids == previous_ids:
            return

        added = sorted(updated_ids - previous_ids)
        removed = sorted(previous_ids - updated_ids)
        runtime_data.tracked_device_ids = updated_ids

        if runtime_data.topology_reload_pending:
            _LOGGER.debug(
                "Device topology changed again while reload is pending %s added=%s removed=%s",
                _ctx(entry_id, location_id),
                added,
                removed,
            )
            return

        runtime_data.topology_reload_pending = True
        _LOGGER.info(
            "Homely device topology changed %s added=%s removed=%s",
            _ctx(entry_id, location_id),
            added,
            removed,
        )
        hass.async_create_task(_reload_for_device_topology_change())

    # WebSocket callback to update data when events are received
    def on_websocket_data(event_data: dict) -> None:
        """Handle WebSocket data updates and update local cache directly."""
        try:
            if runtime_data is None:
                _LOGGER.debug(
                    "Ignoring websocket callback for unloaded entry %s",
                    _ctx(entry_id, location_id),
                )
                return
            ws_device_id = None
            payload = event_data.get("data") if isinstance(event_data, dict) else None
            if not isinstance(payload, dict):
                payload = event_data.get("payload") if isinstance(event_data, dict) else None
            if isinstance(payload, dict):
                ws_device_id = payload.get("deviceId")
            _LOGGER.debug(
                "WebSocket event payload %s payload=%s",
                _ctx(entry_id, location_id, str(ws_device_id) if ws_device_id is not None else None),
                _json_debug(event_data),
            )
            result = apply_websocket_event_to_data(runtime_data.last_data, event_data)
            event_type = result.get("event_type")
            device_id = result.get("device_id")

            if event_type in ("connect", "disconnect"):
                return

            if event_type == "alarm-state-changed":
                _LOGGER.debug(
                    "Applied websocket alarm update entry_id=%s location_id=%s alarm_state=%s",
                    entry_id,
                    location_id,
                    result.get("alarm_state"),
                )
                if coordinator and result.get("updated"):
                    coordinator.async_update_listeners()
                return

            if event_type == "device-state-changed":
                applied_changes = result.get("changes", [])
                if applied_changes:
                    for change in applied_changes:
                        _LOGGER.debug(
                            "Applied websocket device update entry_id=%s location_id=%s "
                            "device_id=%s feature=%s state=%s value=%s old_value=%s",
                            entry_id,
                            location_id,
                            change.get("device_id"),
                            change.get("feature"),
                            change.get("state_name"),
                            change.get("value"),
                            change.get("old_value"),
                        )
                    if coordinator:
                        coordinator.async_update_listeners()
                else:
                    _LOGGER.debug(
                        "Device websocket event could not be applied directly; "
                        "entry_id=%s location_id=%s device_id=%s",
                        entry_id,
                        location_id,
                        device_id,
                    )
                return

            _LOGGER.debug(
                "Ignoring unsupported websocket event entry_id=%s location_id=%s event_type=%s",
                entry_id,
                location_id,
                event_type,
            )
            
        except Exception as err:
            _LOGGER.error(
                "Unhandled exception in websocket callback %s: %s",
                _ctx(entry_id, location_id),
                err,
                exc_info=True,
            )

    async def init_websocket() -> None:
        """Initialize WebSocket connection."""
        try:
            if runtime_data is None:
                _LOGGER.debug("Skipping websocket init; entry data missing entry_id=%s", entry_id)
                return
            # Define a status callback that updates registered entities immediately
            def _status_callback(status: str, reason: str | None):
                try:
                    if runtime_data is None:
                        return
                    previous_status = runtime_data.ws_status
                    runtime_data.ws_status = status
                    runtime_data.ws_status_reason = reason

                    def _dispatch_status_update() -> None:
                        if runtime_data is None:
                            return
                        for listener in list(runtime_data.ws_status_listeners):
                            try:
                                listener()
                            except Exception as err:
                                _LOGGER.debug(
                                    "ws_status listener callback failed %s: %s",
                                    _ctx(entry_id, location_id),
                                    err,
                                )
                        if coordinator:
                            try:
                                coordinator.async_update_listeners()
                            except Exception as err:
                                _LOGGER.debug(
                                    "coordinator listener update failed %s: %s",
                                    _ctx(entry_id, location_id),
                                    err,
                                )
                            # If polling is disabled while websocket is connected,
                            # request an immediate refresh when websocket disconnects
                            # so fallback polling resumes without waiting for next interval.
                            if (
                                status == "Disconnected"
                                and previous_status != "Disconnected"
                                and enable_websocket
                                and not poll_when_websocket
                                and reason != "manual disconnect"
                            ):
                                try:
                                    last_refresh = runtime_data.ws_disconnect_refresh_monotonic
                                    now_monotonic = time.monotonic()
                                    if now_monotonic - last_refresh < 30:
                                        _LOGGER.debug(
                                            "Skipping immediate refresh due to disconnect debounce %s",
                                            _ctx(entry_id, location_id),
                                        )
                                        return
                                    runtime_data.ws_disconnect_refresh_monotonic = now_monotonic
                                    hass.async_create_task(coordinator.async_request_refresh())
                                    _LOGGER.debug(
                                        "Requested immediate polling refresh after websocket disconnect "
                                        "%s",
                                        _ctx(entry_id, location_id),
                                    )
                                except Exception as err:
                                    _LOGGER.debug(
                                        "Failed to request refresh after websocket disconnect %s: %s",
                                        _ctx(entry_id, location_id),
                                        err,
                                    )

                    hass.loop.call_soon_threadsafe(_dispatch_status_update)
                except Exception as err:
                    _LOGGER.debug(
                        "WebSocket status callback failed %s status=%s reason=%s: %s",
                        _ctx(entry_id, location_id),
                        status,
                        reason,
                        err,
                    )

            ws = HomelyWebSocket(
                entry_id=entry_id,
                location_id=runtime_data.location_id,
                token=runtime_data.access_token,
                on_data_update=on_websocket_data,
                status_update_callback=_status_callback,
            )
            runtime_data.websocket = ws
            runtime_data.ws_status = ws.status
            runtime_data.ws_status_reason = ws.status_reason
            success = await ws.connect()
            if success:
                _LOGGER.debug("WebSocket initial connect succeeded entry_id=%s location_id=%s", entry_id, location_id)
            else:
                _LOGGER.warning(
                    "WebSocket connection failed entry_id=%s location_id=%s. "
                    "Polling continues and reconnect loop retries",
                    entry_id,
                    location_id,
                )
        except KeyError:
            _LOGGER.debug("Skipping websocket init; entry data missing entry_id=%s", entry_id)
        except Exception as err:
            _LOGGER.error("Error initializing websocket entry_id=%s: %s", entry_id, err, exc_info=True)

    async def async_update_data() -> dict:
        """Periodic refresh of location data."""
        if runtime_data is None:
            raise UpdateFailed("Entry data is unavailable during coordinator update")
        access_token = runtime_data.access_token
        refresh_token = runtime_data.refresh_token
        expires_at = runtime_data.expires_at
        poll_started_at = time.monotonic()
        ws = runtime_data.websocket
        ws_connected = bool(ws and ws.is_connected())

        def _mark_api_unavailable(message: str) -> None:
            if runtime_data.api_available:
                runtime_data.api_available = False
                _LOGGER.warning("%s %s", message, _ctx(entry_id, location_id))

        def _mark_api_available() -> None:
            if not runtime_data.api_available:
                runtime_data.api_available = True
                _LOGGER.info(
                    "Homely API is reachable again %s",
                    _ctx(entry_id, location_id),
                )
        
        # Refresh token a bit before it expires
        if time.time() >= expires_at:
            _LOGGER.debug("Token expires soon; refreshing entry_id=%s location_id=%s", entry_id, location_id)
            refresh_response = await fetch_refresh_token(hass, refresh_token)
            if not refresh_response:
                _LOGGER.warning(
                    "Token refresh failed; trying full login entry_id=%s location_id=%s",
                    entry_id,
                    location_id,
                )
                login_response, login_reason = await fetch_token_with_reason(
                    hass,
                    username,
                    password,
                )
                if not login_response:
                    if login_reason == "invalid_auth":
                        raise ConfigEntryAuthFailed(
                            "Stored Homely credentials are no longer valid"
                        )
                    raise UpdateFailed("Failed to refresh token and full login also failed.")
                new_access_token = login_response.get("access_token")
                new_refresh_token = login_response.get("refresh_token") or refresh_token
                new_expires_in = login_response.get("expires_in")
                if not new_access_token or not new_expires_in:
                    raise UpdateFailed("Full login response missing required fields")
                try:
                    new_expires_in_seconds = int(new_expires_in)
                except (TypeError, ValueError):
                    raise UpdateFailed("Full login response has invalid expires_in")
                runtime_data.access_token = new_access_token
                runtime_data.refresh_token = new_refresh_token
                runtime_data.expires_at = time.time() + new_expires_in_seconds - 60
                access_token = new_access_token
                _LOGGER.info(
                    "Token refreshed via full login entry_id=%s location_id=%s "
                    "access_expires_in_s=%s next_refresh_in_s=%s",
                    entry_id,
                    location_id,
                    new_expires_in_seconds,
                    max(new_expires_in_seconds - 60, 0),
                )
            else:
                new_access_token = refresh_response.get("access_token")
                new_refresh_token = refresh_response.get("refresh_token") or refresh_token
                new_expires_in = refresh_response.get("expires_in")
                if not new_access_token or not new_expires_in:
                    raise UpdateFailed("Refresh response missing required fields")
                try:
                    new_expires_in_seconds = int(new_expires_in)
                except (TypeError, ValueError):
                    raise UpdateFailed("Refresh response has invalid expires_in")
                runtime_data.access_token = new_access_token
                runtime_data.refresh_token = new_refresh_token
                runtime_data.expires_at = time.time() + new_expires_in_seconds - 60
                access_token = new_access_token
                _LOGGER.debug(
                    "Token refreshed entry_id=%s location_id=%s "
                    "access_expires_in_s=%s next_refresh_in_s=%s",
                    entry_id,
                    location_id,
                    new_expires_in_seconds,
                    max(new_expires_in_seconds - 60, 0),
                )
            # Update WebSocket token in-place (do not disconnect/reconnect)
            ws = runtime_data.websocket
            if ws is not None:
                try:
                    ws.update_token(new_access_token)
                    _LOGGER.debug(
                        "Updated websocket token in-place (no forced reconnect) entry_id=%s location_id=%s",
                        entry_id,
                        location_id,
                    )
                except Exception as err:
                    _LOGGER.debug(
                        "Failed to update websocket token entry_id=%s location_id=%s: %s",
                        entry_id,
                        location_id,
                        err,
                    )

        # Re-evaluate websocket connectivity right before deciding to skip polling.
        ws = runtime_data.websocket
        ws_connected = bool(ws and ws.is_connected())
        if enable_websocket and ws_connected and not poll_when_websocket:
            if ws is not None:
                runtime_data.ws_status = ws.status
                runtime_data.ws_status_reason = ws.status_reason
            _LOGGER.debug(
                "Polling skipped API request because websocket is connected "
                "entry_id=%s location_id=%s",
                entry_id,
                location_id,
            )
            return runtime_data.last_data

        location_id_value = runtime_data.location_id
        # Fetch latest data
        try:
            updated, status_code = await get_data_with_status(hass, access_token, location_id_value)
            if not updated:
                if status_code in (401, 403):
                    raise ConfigEntryAuthFailed("Homely token is no longer accepted by API")
                if (
                    status_code in _TRANSIENT_HTTP_STATUS
                    and isinstance(runtime_data.last_data, dict)
                    and runtime_data.last_data
                ):
                    _mark_api_unavailable(
                        "Polling API request failed with transient status="
                        f"{status_code}; continuing with cached data"
                    )
                    return runtime_data.last_data
                raise UpdateFailed("Failed to fetch data from API")
            _mark_api_available()
            elapsed_ms = int((time.monotonic() - poll_started_at) * 1000)
            devices = updated.get("devices")
            device_count = len(devices) if isinstance(devices, list) else "unknown"
            _LOGGER.debug(
                "Polling API fetch success entry_id=%s location_id=%s "
                "duration_ms=%s device_count=%s",
                entry_id,
                location_id,
                elapsed_ms,
                device_count,
            )
        except UpdateFailed:
            raise
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _mark_api_unavailable(f"Polling exception: {err}")
            raise UpdateFailed(f"Exception while fetching data from API: {err}")
        
        # Log what changed in alarm state
        old_alarm = _get_alarm_state(runtime_data.last_data)
        new_alarm = _get_alarm_state(updated)
        
        # If API returns None for alarm state but we have a cached value (from WebSocket), keep the cached value
        # This handles ARM_PENDING and other states where API might not include the alarm state
        if new_alarm is None and old_alarm is not None:
            _LOGGER.debug("API alarm missing; keeping cached alarm entry_id=%s location_id=%s", entry_id, location_id)
            _set_alarm_state(updated, old_alarm)
            new_alarm = old_alarm
        elif new_alarm is not None:
            # Normalize alarm state structure so entities see consistent data.
            _set_alarm_state(updated, new_alarm)
        
        runtime_data.last_data = updated
        _handle_device_topology_change(updated)

        # Keep status sensor synchronized even if no websocket callback fired.
        ws = runtime_data.websocket
        if ws is None:
            runtime_data.ws_status = "Not initialized"
            runtime_data.ws_status_reason = None
        else:
            runtime_data.ws_status = ws.status
            runtime_data.ws_status_reason = ws.status_reason
        
        if old_alarm != new_alarm:
            _LOGGER.debug(
                "Alarm state changed entry_id=%s location_id=%s: %s -> %s",
                entry_id,
                location_id,
                old_alarm,
                new_alarm,
            )

        return updated

    # Get scan interval from options or use default
    scan_interval = int(entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    ))
    enable_websocket = entry.options.get(
        CONF_ENABLE_WEBSOCKET,
        entry.data.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET)
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
    entry.runtime_data = runtime_data
    
    # Initialize WebSocket for real-time updates (non-blocking) if enabled
    if enable_websocket:
        hass.async_create_task(init_websocket())
        _LOGGER.debug("WebSocket initialization scheduled entry_id=%s location_id=%s", entry_id, location_id)
        # Listen for Home Assistant "internet_available" event and trigger reconnect
        def _internet_available(event):
            try:
                if runtime_data is None:
                    return
                ws = runtime_data.websocket
                if ws and not ws.is_connected():
                    _LOGGER.debug(
                        "Internet available event; requesting websocket reconnect entry_id=%s location_id=%s",
                        entry_id,
                        location_id,
                    )
                    try:
                        ws.request_reconnect(reason="internet_available event")
                    except Exception as err:
                        _LOGGER.debug(
                            "Error requesting websocket reconnect entry_id=%s location_id=%s: %s",
                            entry_id,
                            location_id,
                            err,
                        )
            except Exception as err:
                _LOGGER.debug(
                    "Error handling internet_available event entry_id=%s location_id=%s: %s",
                    entry_id,
                    location_id,
                    err,
                )

        try:
            internet_unsub = hass.bus.async_listen("internet_available", _internet_available)
            entry.async_on_unload(internet_unsub)
        except Exception:
            _LOGGER.debug("Could not register internet_available listener entry_id=%s location_id=%s", entry_id, location_id)
    else:
        _LOGGER.info("WebSocket disabled in options entry_id=%s location_id=%s; using polling only", entry_id, location_id)
    
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Reload the entry when options are updated.
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    _LOGGER.info("Homely Alarm integration setup completed entry_id=%s location_id=%s", entry_id, location_id)
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
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

    _LOGGER.info(
        "Allowing manual removal of stale Homely device entry_id=%s ha_device_id=%s",
        entry.entry_id,
        device_entry.id,
    )
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    _LOGGER.debug("Options changed; reloading entry_id=%s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_data = getattr(entry, "runtime_data", None)
    location_id = entry_data.location_id if entry_data is not None else None
    _LOGGER.debug("Unloading Homely Alarm entry entry_id=%s location_id=%s", entry.entry_id, location_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Disconnect WebSocket
        ws = entry_data.websocket if entry_data is not None else None
        if ws:
            try:
                await ws.disconnect()
                _LOGGER.debug("WebSocket disconnected entry_id=%s location_id=%s", entry.entry_id, location_id)
            except Exception as err:
                _LOGGER.error(
                    "Error disconnecting websocket entry_id=%s location_id=%s: %s",
                    entry.entry_id,
                    location_id,
                    err,
                )

        entry.runtime_data = None
        _LOGGER.info("Homely Alarm integration unloaded entry_id=%s location_id=%s", entry.entry_id, location_id)
    return unload_ok
