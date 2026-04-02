"""Compatibility export for the reusable Homely SDK websocket client."""

from __future__ import annotations

import asyncio
import logging
from importlib import import_module
from typing import Any, cast

HomelyWebSocket = cast(
    Any,
    getattr(import_module("homely.websocket"), "HomelyWebSocket"),
)

_LOGGER = logging.getLogger(HomelyWebSocket.__module__)


def _socket_transport_is_connected(socket: Any | None) -> bool:
    """Return True when the underlying Socket.IO or Engine.IO transport is alive."""
    if socket is None:
        return False

    try:
        if bool(getattr(socket, "connected")):
            return True
    except Exception:
        pass

    engineio_client = getattr(socket, "eio", None)
    try:
        return str(getattr(engineio_client, "state", "")).lower() == "connected"
    except Exception:
        return False


def _is_connected(self: Any) -> bool:
    """Return True when the websocket transport looks alive."""
    try:
        return _socket_transport_is_connected(getattr(self, "socket", None))
    except Exception:
        return False


def _reconnect_interval_for_attempt(self: Any, attempt: int) -> int:
    """Return reconnect delay for the given attempt number."""
    if attempt <= 3:
        return 10
    if attempt <= 8:
        return 60
    return 300


def _start_reconnect_loop(self: Any, reason: str | None = None) -> None:
    """Start reconnect loop if not already running."""
    if self._is_closing:
        return
    if self._reconnect_task and not self._reconnect_task.done():
        return

    self._reconnect_interval = self._reconnect_interval_for_attempt(1)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()

    self._reconnect_task = loop.create_task(self._reconnect_loop())
    if reason:
        _LOGGER.debug(
            "Started reconnect loop %s (%s). interval=%ss, retries=infinite",
            self._ctx(),
            reason,
            self._reconnect_interval,
        )
    else:
        _LOGGER.debug(
            "Started reconnect loop %s. interval=%ss, retries=infinite",
            self._ctx(),
            self._reconnect_interval,
        )


async def _reconnect_loop(self: Any) -> None:
    """Reconnect with a short burst first, then slower retries."""
    attempt = 0
    while not self._is_closing:
        if self.is_connected():
            return

        attempt += 1
        _LOGGER.debug("WebSocket reconnect attempt %s started %s", attempt, self._ctx())
        success = await self.connect(from_reconnect_loop=True)
        if success:
            _LOGGER.debug(
                "WebSocket reconnect attempt %s succeeded %s",
                attempt,
                self._ctx(),
            )
            return

        self._reconnect_interval = self._reconnect_interval_for_attempt(attempt + 1)
        if attempt % self._reconnect_warn_every == 0:
            _LOGGER.info(
                "WebSocket reconnect attempt %s failed %s. Retrying in %s seconds",
                attempt,
                self._ctx(),
                self._reconnect_interval,
            )
        else:
            _LOGGER.debug(
                "WebSocket reconnect attempt %s failed %s. Retrying in %s seconds",
                attempt,
                self._ctx(),
                self._reconnect_interval,
            )
        await asyncio.sleep(self._reconnect_interval)


setattr(HomelyWebSocket, "_reconnect_interval_for_attempt", _reconnect_interval_for_attempt)
setattr(HomelyWebSocket, "_start_reconnect_loop", _start_reconnect_loop)
setattr(HomelyWebSocket, "_reconnect_loop", _reconnect_loop)
setattr(HomelyWebSocket, "_socket_transport_is_connected", staticmethod(_socket_transport_is_connected))
setattr(HomelyWebSocket, "is_connected", _is_connected)

__all__ = ["HomelyWebSocket"]
