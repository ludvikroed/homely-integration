"""The Homely Alarm integration."""
from __future__ import annotations

import asyncio
import logging
import time

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.const import Platform
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from datetime import timedelta
from .api import fetch_refresh_token, fetch_token, get_data, get_location_id
from .const import (
    CONF_HOME_ID,
    CONF_SCAN_INTERVAL,
    CONF_ENABLE_WEBSOCKET,
    DEFAULT_HOME_ID,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_ENABLE_WEBSOCKET,
    DOMAIN,
)
from .websocket import HomelyWebSocket
from .ws_updates import apply_websocket_event_to_data

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.ALARM_CONTROL_PANEL]
_LOGGER = logging.getLogger(__name__)


def _ctx(entry_id: str, location_id: str | None = None, device_id: str | None = None) -> str:
    """Build consistent structured logging context."""
    context = f"entry_id={entry_id}"
    if location_id is not None:
        context += f" location_id={location_id}"
    if device_id is not None:
        context += f" device_id={device_id}"
    return context


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Homely Alarm from a config entry."""
    entry_id = entry.entry_id
    _LOGGER.debug("Setting up Homely Alarm entry entry_id=%s", entry_id)
    
    # Initial login to get tokens
    response = await fetch_token(hass, entry.data["username"], entry.data["password"])

    if not response:
        _LOGGER.error("Failed to fetch token - check username/password entry_id=%s", entry_id)
        return False

    access_token_str = response.get("access_token")
    refresh_token_str = response.get("refresh_token")
    expires_in = response.get("expires_in")
    if not access_token_str or not refresh_token_str:
        _LOGGER.error("Token response missing required fields entry_id=%s", entry_id)
        return False
    if not expires_in:
        _LOGGER.error("Token response missing expires_in entry_id=%s", entry_id)
        return False

    # Resolve location id for the selected home
    location_response = await get_location_id(hass, access_token_str)
    if not location_response:
        _LOGGER.error("Failed to fetch locations from API entry_id=%s", entry_id)
        return False

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
        return False
    
    _LOGGER.debug(
        "Resolved home_id=%s to location_id=%s entry_id=%s",
        home_id,
        location_id,
        entry_id,
    )
    
    # Initial data fetch
    data = await get_data(hass, access_token_str, location_id)
    if not data:
        _LOGGER.error("Failed to fetch location data entry_id=%s location_id=%s", entry_id, location_id)
        return False
    
    # Store state for coordinator and entities
    hass.data.setdefault(DOMAIN, {})
    
    hass.data[DOMAIN][entry.entry_id] = {
        "access_token": access_token_str,
        "refresh_token": refresh_token_str,
        "expires_at": time.time() + int(expires_in) - 60,
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
            current_entry_data = hass.data[DOMAIN][entry.entry_id]
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
                    coordinator.async_set_updated_data(current_entry_data["data"])
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
                        coordinator.async_set_updated_data(current_entry_data["data"])
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
            
        except KeyError as err:
            _LOGGER.error(
                "Entry data missing during websocket callback %s: %s",
                _ctx(entry_id, location_id),
                err,
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
            entry_data = hass.data[DOMAIN][entry.entry_id]
            # Define a status callback that updates registered entities immediately
            def _status_callback(status: str, reason: str | None):
                try:
                    ed = hass.data[DOMAIN].get(entry.entry_id)
                    if not ed:
                        return
                    ed["ws_status"] = status
                    ed["ws_status_reason"] = reason

                    def _dispatch_status_update() -> None:
                        current = hass.data[DOMAIN].get(entry.entry_id)
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
            _LOGGER.error("Entry data missing for websocket init entry_id=%s", entry_id)
        except Exception as err:
            _LOGGER.error("Error initializing websocket entry_id=%s: %s", entry_id, err, exc_info=True)

    async def async_update_data() -> dict:
        """Periodic refresh of location data."""
        entry_data = hass.data[DOMAIN][entry.entry_id]
        access_token = entry_data["access_token"]
        refresh_token = entry_data["refresh_token"]
        expires_at = entry_data["expires_at"]

        _LOGGER.debug("Polling fetch start entry_id=%s location_id=%s", entry_id, location_id)
        
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
                try:
                    login_response = await fetch_token(hass, entry_data["username"], entry_data["password"])
                except Exception as err:
                    raise UpdateFailed(f"Full login after refresh failed: {err}")
                if not login_response:
                    raise UpdateFailed("Failed to refresh token and full login also failed.")
                new_access_token = login_response.get("access_token")
                new_refresh_token = login_response.get("refresh_token") or refresh_token
                new_expires_in = login_response.get("expires_in")
                if not new_access_token or not new_expires_in:
                    raise UpdateFailed("Full login response missing required fields")
                entry_data["access_token"] = new_access_token
                entry_data["refresh_token"] = new_refresh_token
                entry_data["expires_at"] = time.time() + int(new_expires_in) - 60
                access_token = new_access_token
                _LOGGER.info("Token refreshed via full login entry_id=%s location_id=%s", entry_id, location_id)
            else:
                new_access_token = refresh_response.get("access_token")
                new_refresh_token = refresh_response.get("refresh_token") or refresh_token
                new_expires_in = refresh_response.get("expires_in")
                if not new_access_token or not new_expires_in:
                    raise UpdateFailed("Refresh response missing required fields")
                entry_data["access_token"] = new_access_token
                entry_data["refresh_token"] = new_refresh_token
                entry_data["expires_at"] = time.time() + int(new_expires_in) - 60
                access_token = new_access_token
                _LOGGER.debug("Token refreshed entry_id=%s location_id=%s", entry_id, location_id)
            # Update WebSocket token in-place (do not disconnect/reconnect)
            ws = entry_data.get("websocket")
            if ws is not None:
                try:
                    ws.update_token(new_access_token)
                    _LOGGER.debug("Updated websocket token entry_id=%s location_id=%s", entry_id, location_id)
                except Exception as err:
                    _LOGGER.debug(
                        "Failed to update websocket token entry_id=%s location_id=%s: %s",
                        entry_id,
                        location_id,
                        err,
                    )

        location_id_value = entry_data["location_id"]
        # Fetch latest data
        try:
            updated = await get_data(hass, access_token, location_id_value)
            if not updated:
                raise UpdateFailed("Failed to fetch data from API")
            _LOGGER.debug("Polling fetch success entry_id=%s location_id=%s", entry_id, location_id)
        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.warning(
                "Polling exception %s: %s",
                _ctx(entry_id, location_id),
                err,
            )
            raise UpdateFailed(f"Exception while fetching data from API: {err}")
        
        # Log what changed in alarm state
        old_alarm = entry_data["data"].get("features", {}).get("alarm", {}).get("states", {}).get("alarm", {}).get("value")
        new_alarm = updated.get("features", {}).get("alarm", {}).get("states", {}).get("alarm", {}).get("value")
        
        # If API returns None for alarm state but we have a cached value (from WebSocket), keep the cached value
        # This handles ARM_PENDING and other states where API might not include the alarm state
        if new_alarm is None and old_alarm is not None:
            _LOGGER.debug("API alarm missing; keeping cached alarm entry_id=%s location_id=%s", entry_id, location_id)
            # Copy the alarm state from old data to new data
            if "features" not in updated:
                updated["features"] = {}
            if "alarm" not in updated["features"]:
                updated["features"]["alarm"] = {"states": {}}
            if "states" not in updated["features"]["alarm"]:
                updated["features"]["alarm"]["states"] = {}
            if "alarm" not in updated["features"]["alarm"]["states"]:
                updated["features"]["alarm"]["states"]["alarm"] = {}
            updated["features"]["alarm"]["states"]["alarm"]["value"] = old_alarm
            new_alarm = old_alarm
        
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
        
        _LOGGER.debug("Data refresh completed entry_id=%s location_id=%s", entry_id, location_id)
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
    
    _LOGGER.debug(
        "Configured polling entry_id=%s location_id=%s scan_interval=%ss websocket=%s",
        entry_id,
        location_id,
        scan_interval,
        enable_websocket,
    )
    
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="homely",
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )
    remove_listener = coordinator.async_add_listener(lambda: None)

    hass.data[DOMAIN][entry.entry_id]["coordinator"] = coordinator
    hass.data[DOMAIN][entry.entry_id]["coordinator_listener"] = remove_listener
    
    # Initialize WebSocket for real-time updates (non-blocking) if enabled
    if enable_websocket:
        asyncio.create_task(init_websocket())
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
            hass.data[DOMAIN][entry.entry_id]["internet_unsub"] = internet_unsub
        except Exception:
            _LOGGER.debug("Could not register internet_available listener entry_id=%s location_id=%s", entry_id, location_id)
    else:
        _LOGGER.info("WebSocket disabled in options entry_id=%s location_id=%s; using polling only", entry_id, location_id)
    
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Add options update listener
    entry.add_update_listener(async_reload_entry)
    
    _LOGGER.info("Homely Alarm integration setup completed entry_id=%s location_id=%s", entry_id, location_id)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    _LOGGER.debug("Options changed; reloading entry_id=%s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    location_id = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("location_id")
    _LOGGER.debug("Unloading Homely Alarm entry entry_id=%s location_id=%s", entry.entry_id, location_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        remove_listener = hass.data[DOMAIN][entry.entry_id].get("coordinator_listener")
        if remove_listener:
            remove_listener()
        # Remove internet event listener if registered
        internet_unsub = hass.data[DOMAIN][entry.entry_id].get("internet_unsub")
        if internet_unsub:
            try:
                internet_unsub()
            except Exception:
                pass
        
        # Disconnect WebSocket
        ws = hass.data[DOMAIN][entry.entry_id].get("websocket")
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
        
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.info("Homely Alarm integration unloaded entry_id=%s location_id=%s", entry.entry_id, location_id)
    return unload_ok
