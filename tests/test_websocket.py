"""Tests for websocket client behavior."""

from __future__ import annotations

import asyncio
import builtins
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from custom_components.homely.websocket import HomelyWebSocket


class _FakeAsyncClient:
    """Minimal socket.io client stub."""

    def __init__(self, *args, **kwargs) -> None:
        self.connected = False
        self._events = {}
        self._catch_all = None

    def event(self, func):
        self._events[func.__name__] = func
        return func

    def on(self, name, handler=None):
        def _register(func):
            if name == "*":
                self._catch_all = func
            else:
                self._events[name] = func
            return func

        if handler is not None:
            return _register(handler)
        return _register

    async def connect(self, *args, **kwargs):
        self.connected = True
        if "connect" in self._events:
            await self._events["connect"]()

    async def disconnect(self):
        self.connected = False
        if "disconnect" in self._events:
            await self._events["disconnect"]("manual")


class _BrokenString:
    """Object whose __str__ raises to exercise repr fallback."""

    def __str__(self) -> str:
        raise RuntimeError("boom")


class _ExplodingConnected:
    """Socket-like object with failing connected access."""

    @property
    def connected(self):
        raise RuntimeError("boom")


def test_websocket_token_helpers_and_status_callback():
    """Token normalization and status callbacks should work predictably."""
    callback_calls = []
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
        status_update_callback=lambda status, reason: callback_calls.append(
            (status, reason)
        ),
    )

    assert ws._bearer_value(" abc ") == "Bearer abc"
    assert ws._bearer_value("Bearer abc") == "Bearer abc"

    ws._set_status("Connected", "ok")
    assert ws.status == "Connected"
    assert ws.status_reason == "ok"
    assert callback_calls[-1] == ("Connected", "ok")


async def test_websocket_connect_and_disconnect_lifecycle():
    """Successful connect/disconnect should update connection state."""
    fake_socketio = SimpleNamespace(AsyncClient=_FakeAsyncClient)
    events = []
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: events.append(data),
    )

    with patch.dict(sys.modules, {"socketio": fake_socketio}):
        assert await ws.connect() is True
        assert ws.is_connected() is True
        assert ws.status == "Connected"

        ws._on_event({"type": "device_state_changed", "data": {"deviceId": "dev-1"}})
        assert events[-1]["type"] == "device_state_changed"

        await ws.disconnect()
        assert ws.is_connected() is False
        assert ws.status == "Disconnected"


def test_websocket_reason_and_disconnect_warning_helpers():
    """Disconnect helpers should classify reasons consistently."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )

    assert ws._build_reason(None) is None
    assert ws._build_reason({"error": "boom"}) == "{'error': 'boom'}"
    assert ws._build_reason(_BrokenString()) is not None
    assert ws._should_warn_disconnect(None) is True
    assert ws._should_warn_disconnect("manual disconnect") is False
    assert ws._should_warn_disconnect("connect timeout") is False
    assert ws._should_warn_disconnect("server closed") is True


async def test_websocket_connect_handles_missing_socketio():
    """Missing socketio dependency should disable websocket cleanly."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )

    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "socketio":
            raise ImportError
        return original_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=_fake_import),
        patch.object(ws, "_start_reconnect_loop"),
    ):
        assert await ws.connect() is False
        assert ws.status == "Disconnected"
        assert ws.status_reason == "socketio missing"


def test_websocket_reconnect_request_and_token_update():
    """Manual reconnects and token updates should reuse the reconnect loop."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="old-token",
        on_data_update=lambda data: None,
    )

    with patch.object(ws, "_start_reconnect_loop") as start_reconnect:
        ws.update_token("new-token", reconnect_if_disconnected=True)
        assert ws.token == "new-token"
        start_reconnect.assert_called_once()

    with patch.object(ws, "_start_reconnect_loop") as start_reconnect:
        ws.request_reconnect("manual")
        start_reconnect.assert_called_once_with("manual")


def test_websocket_update_token_ignores_empty_values():
    """Empty token updates should be ignored."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="old-token",
        on_data_update=lambda data: None,
    )

    with patch.object(ws, "_start_reconnect_loop") as start_reconnect:
        ws.update_token("", reconnect_if_disconnected=True)

    assert ws.token == "old-token"
    start_reconnect.assert_not_called()


async def test_websocket_disconnect_callback_starts_reconnect_loop():
    """Unexpected disconnects should start reconnect handling."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="old-token",
        on_data_update=lambda data: None,
    )

    with patch.object(ws, "_start_reconnect_loop") as start_reconnect:
        ws._on_disconnect("network error: boom")

    assert ws.status == "Disconnected"
    assert ws.status_reason == "network error: boom"
    start_reconnect.assert_called_once_with("disconnect event")


def test_websocket_disconnect_while_closing_uses_manual_reason():
    """Manual shutdown disconnects should not start reconnects."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="old-token",
        on_data_update=lambda data: None,
    )
    ws._is_closing = True

    with patch.object(ws, "_start_reconnect_loop") as start_reconnect:
        ws._on_disconnect("server closed")

    assert ws.status_reason == "manual disconnect"
    start_reconnect.assert_not_called()


async def test_websocket_connect_handles_network_error():
    """aiohttp failures should map to disconnected network errors."""
    fake_socketio = SimpleNamespace(AsyncClient=_FakeAsyncClient)
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )

    with (
        patch.dict(sys.modules, {"socketio": fake_socketio}),
        patch.object(ws, "_start_reconnect_loop"),
        patch.object(
            _FakeAsyncClient, "connect", side_effect=aiohttp.ClientError("boom")
        ),
    ):
        assert await ws.connect() is False
        assert ws.status == "Disconnected"
        assert ws.status_reason == "network error: boom"


async def test_websocket_connect_handles_timeout():
    """Connect timeouts should produce a stable disconnected reason."""
    fake_socketio = SimpleNamespace(AsyncClient=_FakeAsyncClient)
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )

    with (
        patch.dict(sys.modules, {"socketio": fake_socketio}),
        patch.object(ws, "_start_reconnect_loop"),
        patch.object(_FakeAsyncClient, "connect", side_effect=asyncio.TimeoutError),
    ):
        assert await ws.connect() is False

    assert ws.status == "Disconnected"
    assert ws.status_reason == "connect timeout"


async def test_websocket_connect_skips_when_closing():
    """Closing websockets should not attempt new connections."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )
    ws._is_closing = True

    assert await ws.connect() is False


async def test_websocket_connect_returns_true_when_already_connected():
    """Already connected sockets should be treated as successful."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )
    ws.socket = SimpleNamespace(connected=True)

    assert await ws.connect() is True
    assert ws.status == "Connected"


async def test_websocket_connect_handles_generic_exception():
    """Unexpected connect exceptions should be surfaced in status."""
    fake_socketio = SimpleNamespace(AsyncClient=_FakeAsyncClient)
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )

    with (
        patch.dict(sys.modules, {"socketio": fake_socketio}),
        patch.object(ws, "_start_reconnect_loop"),
        patch.object(_FakeAsyncClient, "connect", side_effect=RuntimeError("boom")),
    ):
        assert await ws.connect() is False

    assert ws.status == "Disconnected"
    assert ws.status_reason == "connect exception: boom"


async def test_websocket_socketio_events_bridge_to_callbacks():
    """Socket.IO event handlers should feed Homely callback logic."""
    fake_socketio = SimpleNamespace(AsyncClient=_FakeAsyncClient)
    received = []
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: received.append(data),
    )

    with patch.dict(sys.modules, {"socketio": fake_socketio}):
        assert await ws.connect() is True
        await ws.socket._catch_all("custom_event", {"foo": "bar"})
        await ws.socket._events["connect_error"]("bad gateway")

    assert received[-1] == {"type": "custom_event", "payload": {"foo": "bar"}}
    assert ws.status == "Disconnected"
    assert ws.status_reason == "connect_error: bad gateway"


async def test_websocket_message_and_event_handlers_forward_payloads():
    """Registered message and event handlers should forward payloads."""
    fake_socketio = SimpleNamespace(AsyncClient=_FakeAsyncClient)
    received = []
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: received.append(data),
    )

    with patch.dict(sys.modules, {"socketio": fake_socketio}):
        assert await ws.connect() is True
        await ws.socket._events["message"](
            {"type": "message", "data": {"deviceId": "dev-1"}}
        )
        await ws.socket._events["event"](
            {"type": "event", "data": {"deviceId": "dev-2"}}
        )

    assert received[0]["type"] == "message"
    assert received[1]["type"] == "event"


def test_websocket_reconnect_requests_are_guarded():
    """Reconnect should be skipped when already connected or shutting down."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )

    with patch.object(ws, "_start_reconnect_loop") as start_reconnect:
        ws.socket = SimpleNamespace(connected=True)
        ws.request_reconnect("manual")
        start_reconnect.assert_not_called()

    with patch.object(ws, "_start_reconnect_loop") as start_reconnect:
        ws.socket = SimpleNamespace(connected=False)
        ws._is_closing = True
        ws.request_reconnect("manual")
        start_reconnect.assert_not_called()


def test_websocket_is_connected_handles_property_errors():
    """Broken socket objects should be treated as disconnected."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )
    ws.socket = _ExplodingConnected()

    assert ws.is_connected() is False


async def test_websocket_reconnect_with_token_delegates_to_update_token():
    """Explicit reconnect-with-token should request reconnect through update_token."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )

    with patch.object(ws, "update_token") as update_token:
        await ws.reconnect_with_token("new-token")

    update_token.assert_called_once_with("new-token", reconnect_if_disconnected=True)


def test_websocket_status_callback_failures_are_swallowed():
    """Broken status callbacks should not crash websocket status changes."""
    callback = MagicMock(side_effect=RuntimeError("boom"))
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
        status_update_callback=callback,
    )

    ws._set_status("Connected", "ok")

    assert ws.status == "Connected"
    assert ws.status_reason == "ok"


def test_websocket_set_status_covers_additional_logging_branches():
    """Status updates without reasons and reason-only changes should be safe."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )

    ws._set_status("Disconnected")
    ws._set_status("Connecting")
    ws._set_status("Connecting", "waiting")

    assert ws.status == "Connecting"
    assert ws.status_reason == "waiting"


def test_websocket_on_event_handles_non_dict_and_status_recovery():
    """Non-dict websocket events should still recover connected status."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )
    ws.socket = SimpleNamespace(connected=True)
    ws._status = "Connecting"

    ws._on_event("raw-payload")

    assert ws.status == "Connected"


def test_websocket_on_event_swallows_callback_exceptions():
    """Callback failures should not bubble out of _on_event."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    ws._on_event({"type": "device-state-changed", "data": {"deviceId": "dev-1"}})


async def test_websocket_reconnect_loop_success_and_failure_paths():
    """Reconnect loop should stop on success and sleep between failures."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )

    ws.connect = AsyncMock(side_effect=[False, True])

    async def _fake_sleep(_seconds):
        return None

    with patch("homely.websocket.asyncio.sleep", side_effect=_fake_sleep):
        await ws._reconnect_loop()

    assert ws.connect.await_count == 2


def test_websocket_start_and_stop_reconnect_loop_branches():
    """Reconnect loop helpers should handle guards and cancellations."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )

    class _FakeTask:
        def __init__(self, done=False) -> None:
            self._done = done
            self.cancelled = False

        def done(self):
            return self._done

        def cancel(self):
            self.cancelled = True

    class _FakeLoop:
        def __init__(self) -> None:
            self.created = None

        def create_task(self, coro):
            self.created = coro
            coro.close()
            return _FakeTask()

    loop = _FakeLoop()
    with patch("homely.websocket.asyncio.get_running_loop", return_value=loop):
        ws._start_reconnect_loop()
    assert ws._reconnect_task is not None

    existing = _FakeTask(done=False)
    ws._reconnect_task = existing
    ws._start_reconnect_loop("again")
    assert ws._reconnect_task is existing

    ws._stop_reconnect_loop()
    assert existing.cancelled is True
    assert ws._reconnect_task is None


def test_websocket_start_reconnect_loop_fallback_event_loop_and_closing_guard():
    """Reconnect startup should fall back to event loop and skip while closing."""
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )

    class _FakeTask:
        def done(self):
            return True

    class _FakeLoop:
        def create_task(self, coro):
            coro.close()
            return _FakeTask()

    with (
        patch("homely.websocket.asyncio.get_running_loop", side_effect=RuntimeError),
        patch("homely.websocket.asyncio.get_event_loop", return_value=_FakeLoop()),
    ):
        ws._start_reconnect_loop("fallback")

    ws._is_closing = True
    current_task = ws._reconnect_task
    ws._start_reconnect_loop("closing")
    assert ws._reconnect_task is current_task


async def test_websocket_connect_cleans_up_stale_socket_and_disconnect_swallows_errors():
    """Stale sockets should be disconnected before reconnecting, and disconnect should be robust."""
    fake_socketio = SimpleNamespace(AsyncClient=_FakeAsyncClient)
    stale_socket = SimpleNamespace(
        disconnect=AsyncMock(side_effect=RuntimeError("boom")), connected=False
    )
    ws = HomelyWebSocket(
        entry_id="entry-1",
        location_id="loc-1",
        token="token",
        on_data_update=lambda data: None,
    )
    ws.socket = stale_socket

    with patch.dict(sys.modules, {"socketio": fake_socketio}):
        assert await ws.connect() is True

    ws.socket = SimpleNamespace(
        disconnect=AsyncMock(side_effect=RuntimeError("boom")), connected=False
    )
    await ws.disconnect()
    assert ws.status == "Disconnected"
