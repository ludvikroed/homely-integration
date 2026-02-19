"""WebSocket client for Homely real-time updates."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import aiohttp

_LOGGER = logging.getLogger(__name__)

class HomelyWebSocket:
    """WebSocket client for Homely using SocketIO."""

    def __init__(
        self,
        location_id: str | int,
        token: str,
        on_data_update: Callable[[dict[str, Any]], None],
        status_update_callback: Callable[[], None] | None = None,
    ):
        """Initialize WebSocket client.
        
        Args:
            location_id: Location ID for the device
            token: Access token for authentication
            on_data_update: Callback function when data is updated
        """
        self.location_id = location_id
        self.token = token
        self.on_data_update = on_data_update
        self.socket = None
        self._connect_task: asyncio.Task | None = None
        self._reconnect_delay = 5
        self._max_reconnect_delay = 600
        self._max_reconnect_attempts = 500
        self._is_closing = False
        # Background reconnect task when connection lost (keeps trying)
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_interval = 10
        # Optional callback to notify status sensors immediately
        self._status_update_callback = status_update_callback

    @property
    def websocket_url(self) -> str:
        """WebSocket URL."""
        return "https://sdk.iotiliti.cloud"

    def _on_event(self, data: Any) -> None:
        """Handle event from WebSocket (called from sync/async context)."""
        _LOGGER.debug("WebSocket event received: %r", data)
        if isinstance(data, dict):
            try:
                self.on_data_update(data)
            except Exception as err:
                _LOGGER.error("Error in on_data_update callback: %s", err, exc_info=True)

    def _on_connect(self) -> None:
        """Handle successful connection (called from sync context)."""
        _LOGGER.info("WebSocket connected")
        self._reconnect_delay = 5
        # Stop any background reconnect attempts once connected
        try:
            self._stop_reconnect_loop()
        except Exception:
            pass
        # Notify status sensors via callback if provided
        if self._status_update_callback:
            try:
                self._status_update_callback()
            except Exception as err:
                _LOGGER.debug("Status callback error on connect: %s", err)
        else:
            self._notify_status_sensors()

    def _on_disconnect(self) -> None:
        """Handle disconnection (called from sync context)."""
        _LOGGER.info("WebSocket disconnected")
        # Notify status sensors via callback if provided
        if self._status_update_callback:
            try:
                self._status_update_callback()
            except Exception as err:
                _LOGGER.debug("Status callback error on disconnect: %s", err)
        else:
            self._notify_status_sensors()
        # Start background reconnect attempts
        try:
            self._start_reconnect_loop()
        except Exception:
            pass
        if not self._is_closing:
            _LOGGER.debug("Unexpected disconnection, will attempt automatic reconnection")

    def _start_reconnect_loop(self) -> None:
        """Start a background task that keeps trying to reconnect.

        This is resilient to network outages: it will keep attempting
        to connect until successful or the websocket is closed.
        """
        if self._reconnect_task and not self._reconnect_task.done():
            return

        loop = asyncio.get_event_loop()
        self._reconnect_task = loop.create_task(self._reconnect_loop())

    def _stop_reconnect_loop(self) -> None:
        """Cancel background reconnect task if running."""
        if self._reconnect_task:
            try:
                self._reconnect_task.cancel()
            except Exception:
                pass
            self._reconnect_task = None

    async def _reconnect_loop(self) -> None:
        """Continuously attempt to reconnect with exponential backoff."""
        attempt = 0
        while not self._is_closing and (self.socket is None or not getattr(self.socket, "connected", False)):
            try:
                _LOGGER.debug("Reconnect loop: attempt %s", attempt + 1)
                success = await self.connect()
                if success:
                    _LOGGER.debug("Reconnect loop: connection successful")
                    return
            except Exception as err:
                _LOGGER.debug("Reconnect loop exception: %s", err)

            # exponential backoff up to max_reconnect_delay
            delay = min(self._reconnect_interval * (2 ** attempt), self._max_reconnect_delay)
            await asyncio.sleep(delay)
            attempt += 1

    def _notify_status_sensors(self):
        """Notify HomelyWebSocketStatusSensor entities to update state immediately."""
        try:
            import homeassistant.helpers.entity_platform
            # Find all loaded platforms for this integration
            hass = getattr(self, '_hass', None)
            if not hass:
                return
            for entry in getattr(hass, 'config_entries', []):
                entry_data = hass.data.get('homely', {}).get(entry.entry_id, {})
                for entity in getattr(entry_data, 'entities', []):
                    if entity.__class__.__name__ == 'HomelyWebSocketStatusSensor':
                        entity.async_write_ha_state()
        except Exception as e:
            _LOGGER.debug("Could not notify status sensors: %s", e)

    def _on_error(self, error: Any) -> None:
        """Handle error (called from sync context)."""
        _LOGGER.warning("WebSocket error: %s", error)

    async def connect(self) -> bool:
        """Connect to WebSocket server."""
        try:
            if self._is_closing:
                _LOGGER.debug("Not connecting: WebSocket is closing")
                return False

            try:
                import socketio
            except ImportError:
                _LOGGER.error("python-socketio is not installed. WebSocket support disabled.")
                return False

            if self.socket is not None:
                _LOGGER.warning("WebSocket already connected")
                return True

            try:
                self.socket = socketio.AsyncClient(
                    reconnection=True,
                    reconnection_delay=self._reconnect_delay,
                    reconnection_delay_max=self._max_reconnect_delay,
                    reconnection_attempts=self._max_reconnect_attempts,
                    logger=False,
                    engineio_logger=False,
                )

                # Register event handlers
                @self.socket.event
                async def connect():
                    try:
                        self._on_connect()
                    except Exception as err:
                        _LOGGER.error("Exception in connect handler: %s", err, exc_info=True)

                @self.socket.event
                async def disconnect():
                    try:
                        self._on_disconnect()
                    except Exception as err:
                        _LOGGER.error("Exception in disconnect handler: %s", err, exc_info=True)

                @self.socket.event
                async def message(data):
                    try:
                        self._on_event(data)
                    except Exception as err:
                        _LOGGER.error("Exception in message handler: %s", err, exc_info=True)

                @self.socket.event
                async def event(data):
                    try:
                        self._on_event(data)
                    except Exception as err:
                        _LOGGER.error("Exception in event handler: %s", err, exc_info=True)

                @self.socket.on("*")
                async def catch_all(event, data):
                    try:
                        _LOGGER.debug("WebSocket event: %s", event)
                        if event not in ("connect", "disconnect", "message", "event", "connect_error"):
                            self._on_event({"type": event, "payload": data})
                    except Exception as err:
                        _LOGGER.error("Exception in catch_all handler: %s", err, exc_info=True)

                @self.socket.event
                async def connect_error(data):
                    try:
                        _LOGGER.error("WebSocket CONNECT ERROR: %s", data)
                        self._on_error(f"Connect error: {data}")
                    except Exception as err:
                        _LOGGER.error("Exception in connect_error handler: %s", err, exc_info=True)

                # Build URL - use https:// with Bearer token and space
                url = f"https://sdk.iotiliti.cloud?locationId={self.location_id}&token=Bearer {self.token}"

                _LOGGER.debug("WebSocket connecting to %s", self.websocket_url)
                await self.socket.connect(
                    url,
                    transports=["websocket", "polling"],
                    headers={
                        "Authorization": f"Bearer {self.token}",
                    },
                    wait_timeout=10,
                )
                _LOGGER.info("WebSocket connection established")
                return True

            except asyncio.TimeoutError:
                _LOGGER.error("WebSocket connection timeout")
                self.socket = None
                return False
            except aiohttp.ClientError as err:
                _LOGGER.error("WebSocket network error: %s", err)
                self.socket = None
                return False
            except Exception as err:
                _LOGGER.error("WebSocket connection failed: %s", err, exc_info=True)
                self.socket = None
                return False
        except Exception as err:
            _LOGGER.error("Exception in connect(): %s", err, exc_info=True)
            self.socket = None
            return False

    async def disconnect(self) -> None:
        """Disconnect from WebSocket server."""
        try:
            self._is_closing = True
            if self.socket is not None:
                try:
                    _LOGGER.debug("Disconnecting WebSocket")
                    await asyncio.wait_for(self.socket.disconnect(), timeout=5)
                except asyncio.TimeoutError:
                    _LOGGER.warning("WebSocket disconnect timeout, forcing close")
                except Exception as err:
                    _LOGGER.debug("Error during WebSocket disconnect: %s", err, exc_info=True)
                finally:
                    self.socket = None
        except Exception as err:
            _LOGGER.error("Exception in disconnect(): %s", err, exc_info=True)
        finally:
            # stop reconnect loop and mark closing finished
            try:
                self._stop_reconnect_loop()
            except Exception:
                pass
            self._is_closing = False

    async def reconnect_with_token(self, token: str) -> None:
        """Update token and reconnect."""
        try:
            _LOGGER.debug("Updating WebSocket token and reconnecting")
            self.token = token
            await self.disconnect()
            await asyncio.sleep(1)
            success = await self.connect()
            if not success:
                _LOGGER.error("Failed to reconnect WebSocket with new token")
            else:
                _LOGGER.debug("WebSocket reconnected with new token")
        except Exception as err:
            _LOGGER.error("Exception in reconnect_with_token(): %s", err, exc_info=True)

    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self.socket is not None and self.socket.connected

