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

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.ALARM_CONTROL_PANEL]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Homely Alarm from a config entry."""
    _LOGGER.debug("Setting up Homely Alarm entry")
    
    # Initial login to get tokens
    response = await fetch_token(hass, entry.data["username"], entry.data["password"])

    if not response:
        _LOGGER.error("Failed to fetch token - check username/password")
        return False

    access_token_str = response.get("access_token")
    refresh_token_str = response.get("refresh_token")
    expires_in = response.get("expires_in")
    if not access_token_str or not refresh_token_str:
        _LOGGER.error("Token response missing required fields")
        return False
    if not expires_in:
        _LOGGER.error("Token response missing expires_in")
        return False

    # Resolve location id for the selected home
    location_response = await get_location_id(hass, access_token_str)
    if not location_response:
        _LOGGER.error("Failed to fetch locations from API")
        return False

    # Map user-provided home_id to the API location_id
    # Check options first, then data, then use default
    home_id = int(entry.options.get(
        CONF_HOME_ID,
        entry.data.get(CONF_HOME_ID, DEFAULT_HOME_ID)
    ))
    _LOGGER.debug("Using home_id: %s", home_id)
    try:
        location_item = location_response[home_id]
        location_id = location_item["locationId"]
    except (KeyError, IndexError, TypeError) as err:
        _LOGGER.error("Failed to find location_id for home_id %s: %s", home_id, err)
        return False
    
    _LOGGER.debug("Resolved home_id %s to location_id %s", home_id, location_id)
    
    # Initial data fetch
    data = await get_data(hass, access_token_str, location_id)
    if not data:
        _LOGGER.error("Failed to fetch location data")
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

    def _ensure_alarm_root(data_dict: dict) -> dict:
        """Ensure alarm root structure exists and return alarm state dict."""
        features = data_dict.setdefault("features", {})
        alarm_feature = features.setdefault("alarm", {})
        states = alarm_feature.setdefault("states", {})
        return states.setdefault("alarm", {})

    def _apply_device_state_changes(data_dict: dict, event_payload: dict) -> bool:
        """Apply device-state-changed payload directly to local cached data."""
        device_id = event_payload.get("deviceId")
        if not device_id:
            return False

        devices = data_dict.get("devices", [])
        device = next((d for d in devices if d.get("id") == device_id), None)
        if not isinstance(device, dict):
            _LOGGER.debug("WebSocket change for unknown device_id=%s", device_id)
            return False

        changes = event_payload.get("changes")
        if not isinstance(changes, list) or not changes:
            single_change = event_payload.get("change")
            changes = [single_change] if isinstance(single_change, dict) else []

        applied = False
        for change in changes:
            if not isinstance(change, dict):
                continue

            feature = change.get("feature")
            state_name = change.get("stateName")
            if not feature or not state_name:
                continue

            value = change.get("value")
            last_updated = change.get("lastUpdated")

            features = device.setdefault("features", {})
            feature_dict = features.setdefault(feature, {})
            states = feature_dict.setdefault("states", {})
            state = states.setdefault(state_name, {})

            old_value = state.get("value")
            state["value"] = value
            if last_updated is not None:
                state["lastUpdated"] = last_updated

            _LOGGER.debug(
                "Applied WS change device=%s feature=%s state=%s value=%s (old=%s)",
                device_id,
                feature,
                state_name,
                value,
                old_value,
            )
            applied = True

        return applied

    # WebSocket callback to update data when events are received
    def on_websocket_data(event_data: dict) -> None:
        """Handle WebSocket data updates and update local cache directly."""
        event_type = event_data.get("type")
        event_payload = event_data.get("data")
        if not isinstance(event_payload, dict):
            event_payload = event_data.get("payload")
        if not isinstance(event_payload, dict):
            event_payload = {}
        
        # Get current entry_data from hass.data (not from closure)
        try:
            current_entry_data = hass.data[DOMAIN][entry.entry_id]
            
            # Handle location alarm state changes.
            if event_type == "alarm-state-changed":
                alarm_state = event_payload.get("state")
                _LOGGER.info("Alarm state changed via WebSocket: %s", alarm_state)

                alarm_state_dict = _ensure_alarm_root(current_entry_data["data"])
                alarm_state_dict["value"] = alarm_state
                current_entry_data["data"]["alarmState"] = alarm_state

                if coordinator:
                    coordinator.async_set_updated_data(current_entry_data["data"])
                return

            # Handle device state changes directly from websocket payload.
            elif event_type == "device-state-changed":
                device_id = event_payload.get("deviceId")
                change = event_payload.get("change", {})
                feature = change.get("feature", "unknown")
                value = change.get("value")
                _LOGGER.debug("Device state changed: %s, feature=%s, value=%s", device_id, feature, value)

                applied = _apply_device_state_changes(current_entry_data["data"], event_payload)
                if applied and coordinator:
                    coordinator.async_set_updated_data(current_entry_data["data"])
                elif not applied:
                    _LOGGER.debug(
                        "WS device-state-changed could not be applied directly (device/state missing). "
                        "No immediate API refresh; periodic polling will reconcile state."
                    )
                return

            # Ignore pure connection lifecycle events in data handler.
            elif event_type in ("connect", "disconnect"):
                return

            # Other websocket events are logged only; periodic polling remains backup sync.
            _LOGGER.debug(
                "WebSocket event %s received; no API refresh triggered by websocket handler",
                event_type,
            )
            
        except KeyError as e:
            _LOGGER.error("Entry data not found during WebSocket callback: %s", e)
        except Exception as e:
            _LOGGER.error("Error in WebSocket callback: %s", e, exc_info=True)

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
                            except Exception:
                                pass
                        if coordinator:
                            try:
                                coordinator.async_update_listeners()
                            except Exception:
                                pass

                    hass.loop.call_soon_threadsafe(_dispatch_status_update)
                except Exception:
                    pass

            ws = HomelyWebSocket(
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
                _LOGGER.info("WebSocket connection established")
            else:
                _LOGGER.warning(
                    "WebSocket connection failed. Polling continues, and reconnect loop will keep retrying"
                )
        except KeyError:
            _LOGGER.error("Entry data not found for WebSocket initialization")
        except Exception as err:
            _LOGGER.error("Error initializing WebSocket: %s", err, exc_info=True)

    async def async_update_data() -> dict:
        """Periodic refresh of location data."""
        entry_data = hass.data[DOMAIN][entry.entry_id]
        access_token = entry_data["access_token"]
        refresh_token = entry_data["refresh_token"]
        expires_at = entry_data["expires_at"]

        _LOGGER.debug("Polling: Fetching data from Homely API...")
        
        # Refresh token a bit before it expires
        if time.time() >= expires_at:
            _LOGGER.debug("Token expires soon, refreshing")
            refresh_response = await fetch_refresh_token(hass, refresh_token)
            if not refresh_response:
                _LOGGER.error("Token refresh failed! Trying full login with username/password.")
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
                _LOGGER.info("Token refreshed via full login.")
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
                _LOGGER.debug("Token refreshed")
            # Update WebSocket token in-place (do not disconnect/reconnect)
            ws = entry_data.get("websocket")
            if ws is not None:
                try:
                    ws.update_token(new_access_token)
                    _LOGGER.debug("Updated WebSocket token")
                except Exception as err:
                    _LOGGER.debug("Failed to update WebSocket token: %s", err)

        location_id_value = entry_data["location_id"]
        # Fetch latest data
        try:
            updated = await get_data(hass, access_token, location_id_value)
            if not updated:
                _LOGGER.error("Polling: Failed to fetch data from API")
                raise UpdateFailed("Failed to fetch data from API")
            _LOGGER.debug("Polling: Successfully fetched data from Homely API")
        except Exception as err:
            _LOGGER.error(f"Polling: Exception while fetching data from API: {err}")
            raise UpdateFailed(f"Exception while fetching data from API: {err}")
        
        # Log what changed in alarm state
        old_alarm = entry_data["data"].get("features", {}).get("alarm", {}).get("states", {}).get("alarm", {}).get("value")
        new_alarm = updated.get("features", {}).get("alarm", {}).get("states", {}).get("alarm", {}).get("value")
        
        # If API returns None for alarm state but we have a cached value (from WebSocket), keep the cached value
        # This handles ARM_PENDING and other states where API might not include the alarm state
        if new_alarm is None and old_alarm is not None:
            _LOGGER.debug("API returned None for alarm state, keeping cached value")
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
            _LOGGER.info("Alarm state changed: %s -> %s", old_alarm, new_alarm)
        
        _LOGGER.debug("Data refresh completed")
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
    
    _LOGGER.debug("Using scan_interval=%d seconds, enable_websocket=%s", scan_interval, enable_websocket)
    
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
        _LOGGER.debug("WebSocket initialization scheduled")
        # Listen for Home Assistant "internet_available" event and trigger reconnect
        def _internet_available(event):
            try:
                entry_data = hass.data[DOMAIN].get(entry.entry_id)
                if not entry_data:
                    return
                ws = entry_data.get("websocket")
                if ws and not ws.is_connected():
                    _LOGGER.debug("Internet available event received, attempting websocket reconnect")
                    try:
                        ws.request_reconnect(reason="internet_available event")
                    except Exception as err:
                        _LOGGER.debug("Error scheduling websocket reconnect: %s", err)
            except Exception as err:
                _LOGGER.debug("Error handling internet_available event: %s", err)

        try:
            internet_unsub = hass.bus.async_listen("internet_available", _internet_available)
            hass.data[DOMAIN][entry.entry_id]["internet_unsub"] = internet_unsub
        except Exception:
            _LOGGER.debug("Could not register internet_available listener")
    else:
        _LOGGER.info("WebSocket disabled in options, using polling only")
    
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Add options update listener
    entry.add_update_listener(async_reload_entry)
    
    _LOGGER.info("Homely Alarm integration setup completed")
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    _LOGGER.debug("Options changed, reloading entry")
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Homely Alarm entry")
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
                _LOGGER.debug("WebSocket disconnected")
            except Exception as err:
                _LOGGER.error("Error disconnecting WebSocket: %s", err)
        
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.info("Homely Alarm integration unloaded")
    return unload_ok
