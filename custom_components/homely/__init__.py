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
    CONF_SCAN_INTERVAL,
    CONF_ENABLE_WEBSOCKET,
    CONF_POLL_WHEN_WEBSOCKET,
    DEFAULT_HOME_ID,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_ENABLE_WEBSOCKET,
    DEFAULT_POLL_WHEN_WEBSOCKET,
    DOMAIN,
)
from .websocket import HomelyWebSocket
from .ws_updates import apply_websocket_event_to_data

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.ALARM_CONTROL_PANEL, Platform.LOCK]
_LOGGER = logging.getLogger(__name__)
_TRANSIENT_HTTP_STATUS = {429, 500, 502, 503, 504}


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

        device_id = device.get("id")
        device_name = device.get("name") or f"Enhet {index}"
        device_dump = json.dumps(device, indent=2, ensure_ascii=True, sort_keys=True)

        _LOGGER.debug(
            "Startup API payload for '%s' %s\n%s",
            device_name,
            _ctx(entry_id, location_id_str, str(device_id) if device_id is not None else None),
            device_dump,
        )

    _LOGGER.debug("Startup API device dump complete %s", _ctx(entry_id, location_id_str))


def _tracked_api_device_ids(entry_data: dict[str, Any] | None) -> tuple[bool, set[str]]:
    """Return current Homely device ids from coordinator/cache with availability flag."""
    if not isinstance(entry_data, dict):
        return False, set()

    data: Any = None
    coordinator = entry_data.get("coordinator")
    if coordinator is not None:
        data = getattr(coordinator, "data", None)

    if not isinstance(data, dict):
        data = entry_data.get("data")

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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Homely Alarm from a config entry."""
    entry_id = entry.entry_id
    _LOGGER.debug("Setting up Homely Alarm entry entry_id=%s", entry_id)
    
    # Initial login to get tokens
    response, reason = await fetch_token_with_reason(
        hass,
        entry.data["username"],
        entry.data["password"],
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

    # Resolve location id for the selected home
    location_response = await get_location_id(hass, access_token_str)
    if not location_response:
        raise ConfigEntryNotReady("Failed to fetch Homely locations")

    # Map user-provided home_id to the API location_id
    # Check options first, then data, then use default
    home_id = int(entry.options.get(
        CONF_HOME_ID,
        entry.data.get(CONF_HOME_ID, DEFAULT_HOME_ID)
    ))
    _LOGGER.debug("Using home_id=%s entry_id=%s", home_id, entry_id)
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
        raise ConfigEntryNotReady(f"Configured home_id={home_id} is not available") from err
    
    _LOGGER.debug(
        "Resolved home_id=%s to location_id=%s entry_id=%s",
        home_id,
        location_id,
        entry_id,
    )
    
    # Initial data fetch
    data = await get_data(hass, access_token_str, location_id)
    if not data:
        raise ConfigEntryNotReady("Failed to fetch Homely location data")
    initial_alarm_state = _get_alarm_state(data)
    if initial_alarm_state is not None:
        _set_alarm_state(data, initial_alarm_state)
    _log_startup_device_payloads(data, entry_id, location_id)
    
    # Store state for coordinator and entities
    hass.data.setdefault(DOMAIN, {})
    
    hass.data[DOMAIN][entry.entry_id] = {
        "access_token": access_token_str,
        "refresh_token": refresh_token_str,
        "expires_at": time.time() + expires_in_seconds - 60,
        "username": entry.data["username"],
        "password": entry.data["password"],
        "location_id": location_id,
        "data": data,
        "websocket": None,
        "ws_status": "Not initialized",
        "ws_status_reason": None,
        "ws_status_listeners": [],
    }

    # WebSocket callback to update data when events are received
    def on_websocket_data(event_data: dict) -> None:
        """Handle WebSocket data updates and update local cache directly."""
        # Get current entry_data from hass.data (not from closure)
        try:
            current_entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if current_entry_data is None:
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
            result = apply_websocket_event_to_data(current_entry_data["data"], event_data)
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
            entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if entry_data is None:
                _LOGGER.debug("Skipping websocket init; entry data missing entry_id=%s", entry_id)
                return
            # Define a status callback that updates registered entities immediately
            def _status_callback(status: str, reason: str | None):
                try:
                    ed = hass.data.get(DOMAIN, {}).get(entry.entry_id)
                    if not ed:
                        return
                    previous_status = ed.get("ws_status")
                    ed["ws_status"] = status
                    ed["ws_status_reason"] = reason

                    def _dispatch_status_update() -> None:
                        current = hass.data.get(DOMAIN, {}).get(entry.entry_id)
                        if not current:
                            return
                        for listener in list(current.get("ws_status_listeners", [])):
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
                                    last_refresh = current.get("_ws_disconnect_refresh_monotonic", 0.0)
                                    now_monotonic = time.monotonic()
                                    if now_monotonic - last_refresh < 30:
                                        _LOGGER.debug(
                                            "Skipping immediate refresh due to disconnect debounce %s",
                                            _ctx(entry_id, location_id),
                                        )
                                        return
                                    current["_ws_disconnect_refresh_monotonic"] = now_monotonic
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
                location_id=entry_data["location_id"],
                token=entry_data["access_token"],
                on_data_update=on_websocket_data,
                status_update_callback=_status_callback,
            )
            entry_data["websocket"] = ws
            entry_data["ws_status"] = ws.status
            entry_data["ws_status_reason"] = ws.status_reason
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
        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if entry_data is None:
            raise UpdateFailed("Entry data is unavailable during coordinator update")
        access_token = entry_data["access_token"]
        refresh_token = entry_data["refresh_token"]
        expires_at = entry_data["expires_at"]
        poll_started_at = time.monotonic()
        ws = entry_data.get("websocket")
        ws_connected = bool(ws and ws.is_connected())
        
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
                    entry_data["username"],
                    entry_data["password"],
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
                entry_data["access_token"] = new_access_token
                entry_data["refresh_token"] = new_refresh_token
                entry_data["expires_at"] = time.time() + new_expires_in_seconds - 60
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
                entry_data["access_token"] = new_access_token
                entry_data["refresh_token"] = new_refresh_token
                entry_data["expires_at"] = time.time() + new_expires_in_seconds - 60
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
            ws = entry_data.get("websocket")
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
        ws = entry_data.get("websocket")
        ws_connected = bool(ws and ws.is_connected())
        if enable_websocket and ws_connected and not poll_when_websocket:
            if ws is not None:
                entry_data["ws_status"] = ws.status
                entry_data["ws_status_reason"] = ws.status_reason
            _LOGGER.debug(
                "Polling skipped API request because websocket is connected "
                "entry_id=%s location_id=%s",
                entry_id,
                location_id,
            )
            return entry_data.get("data", {})

        location_id_value = entry_data["location_id"]
        # Fetch latest data
        try:
            updated, status_code = await get_data_with_status(hass, access_token, location_id_value)
            if not updated:
                if status_code in (401, 403):
                    raise ConfigEntryAuthFailed("Homely token is no longer accepted by API")
                if (
                    status_code in _TRANSIENT_HTTP_STATUS
                    and isinstance(entry_data.get("data"), dict)
                    and entry_data["data"]
                ):
                    _LOGGER.warning(
                        "Polling API request failed with transient status=%s; "
                        "continuing with cached data entry_id=%s location_id=%s",
                        status_code,
                        entry_id,
                        location_id,
                    )
                    return entry_data["data"]
                raise UpdateFailed("Failed to fetch data from API")
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
            _LOGGER.warning(
                "Polling exception %s: %s",
                _ctx(entry_id, location_id),
                err,
            )
            raise UpdateFailed(f"Exception while fetching data from API: {err}")
        
        # Log what changed in alarm state
        old_alarm = _get_alarm_state(entry_data["data"])
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
        
        entry_data["data"] = updated

        # Keep status sensor synchronized even if no websocket callback fired.
        ws = entry_data.get("websocket")
        if ws is None:
            entry_data["ws_status"] = "Not initialized"
            entry_data["ws_status_reason"] = None
        else:
            entry_data["ws_status"] = ws.status
            entry_data["ws_status_reason"] = ws.status_reason
        
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

    hass.data[DOMAIN][entry.entry_id]["coordinator"] = coordinator
    
    # Initialize WebSocket for real-time updates (non-blocking) if enabled
    if enable_websocket:
        hass.async_create_task(init_websocket())
        _LOGGER.debug("WebSocket initialization scheduled entry_id=%s location_id=%s", entry_id, location_id)
        # Listen for Home Assistant "internet_available" event and trigger reconnect
        def _internet_available(event):
            try:
                entry_data = hass.data[DOMAIN].get(entry.entry_id)
                if not entry_data:
                    return
                ws = entry_data.get("websocket")
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
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
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
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    location_id = (entry_data or {}).get("location_id")
    _LOGGER.debug("Unloading Homely Alarm entry entry_id=%s location_id=%s", entry.entry_id, location_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Disconnect WebSocket
        ws = (entry_data or {}).get("websocket")
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
        
        domain_data = hass.data.get(DOMAIN)
        if isinstance(domain_data, dict):
            domain_data.pop(entry.entry_id, None)
            if not domain_data:
                hass.data.pop(DOMAIN, None)
        _LOGGER.info("Homely Alarm integration unloaded entry_id=%s location_id=%s", entry.entry_id, location_id)
    return unload_ok
