"""Compatibility re-export for the reusable Homely SDK websocket client."""

from homely.websocket import (
    WEBSOCKET_STATUS_OPTIONS,
    HomelyWebSocket,
    WebSocketConnectionState,
    normalize_websocket_status,
)

__all__ = [
    "WEBSOCKET_STATUS_OPTIONS",
    "HomelyWebSocket",
    "WebSocketConnectionState",
    "normalize_websocket_status",
]
