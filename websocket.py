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
        use_test_server: bool = False,
    ):
        """Initialize WebSocket client.
        
        Args:
            location_id: Location ID for the device
            token: Access token for authentication
            on_data_update: Callback function when data is updated
            use_test_server: Use test server (test-sdk.iotiliti.cloud) instead of production
        """
        self.location_id = location_id
        self.token = token
        self.on_data_update = on_data_update
        self.use_test_server = use_test_server
        self.socket = None
        self._connect_task: asyncio.Task | None = None
        self._reconnect_delay = 5
        self._max_reconnect_delay = 60
        self._is_closing = False

    @property
    def websocket_url(self) -> str:
        """Get WebSocket URL."""
        if self.use_test_server:
            return "https://test-sdk.iotiliti.cloud"
        return "https://sdk.iotiliti.cloud"

    def _on_event(self, data: Any) -> None:
        """Handle event from WebSocket (called from sync/async context)."""
        _LOGGER.debug("WebSocket event received")
        
        if isinstance(data, dict):
            try:
                self.on_data_update(data)
            except Exception as err:
                _LOGGER.error("Error in on_data_update callback: %s", err, exc_info=True)

    def _on_connect(self) -> None:
        """Handle successful connection (called from sync context)."""
        _LOGGER.info("WebSocket connected")
        self._reconnect_delay = 5

    def _on_disconnect(self) -> None:
        """Handle disconnection (called from sync context)."""
        _LOGGER.info("WebSocket disconnected")
        if not self._is_closing:
            _LOGGER.debug("Unexpected disconnection, will attempt automatic reconnection")

    def _on_error(self, error: Any) -> None:
        """Handle error (called from sync context)."""
        _LOGGER.warning("WebSocket error: %s", error)

    async def connect(self) -> bool:
        """Connect to WebSocket server."""
        if self._is_closing:
            _LOGGER.debug("Not connecting: WebSocket is closing")
            return False

        try:
            # Import here to avoid issues if python-socketio is not installed
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
                reconnection_attempts=10,
                logger=False,
                engineio_logger=False,
            )

            # Register event handlers
            @self.socket.event
            async def connect():
                """Handle connect event."""
                self._on_connect()

            @self.socket.event
            async def disconnect():
                """Handle disconnect event."""
                self._on_disconnect()

            @self.socket.event
            async def message(data):
                """Handle message event."""
                self._on_event(data)

            @self.socket.event
            async def event(data):
                """Handle event event."""
                self._on_event(data)

            @self.socket.on("*")
            async def catch_all(event, data):
                """Catch all events."""
                _LOGGER.debug("WebSocket event: %s", event)
                if event not in ("connect", "disconnect", "message", "event", "connect_error"):
                    self._on_event({"type": event, "payload": data})

            @self.socket.event
            async def connect_error(data):
                """Handle connect error."""
                _LOGGER.error("WebSocket CONNECT ERROR: %s", data)
                self._on_error(f"Connect error: {data}")

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
            _LOGGER.error("WebSocket connection failed: %s", err)
            self.socket = None
            return False

    async def disconnect(self) -> None:
        """Disconnect from WebSocket server."""
        self._is_closing = True
        if self.socket is not None:
            try:
                _LOGGER.debug("Disconnecting WebSocket")
                await asyncio.wait_for(self.socket.disconnect(), timeout=5)
            except asyncio.TimeoutError:
                _LOGGER.warning("WebSocket disconnect timeout, forcing close")
            except Exception as err:
                _LOGGER.debug("Error during WebSocket disconnect: %s", err)
            finally:
                self.socket = None
        self._is_closing = False

    async def reconnect_with_token(self, token: str) -> None:
        """Update token and reconnect."""
        _LOGGER.debug("Updating WebSocket token and reconnecting")
        self.token = token
        await self.disconnect()
        await asyncio.sleep(1)
        success = await self.connect()
        if not success:
            _LOGGER.error("Failed to reconnect WebSocket with new token")
        else:
            _LOGGER.debug("WebSocket reconnected with new token")

    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self.socket is not None and self.socket.connected

