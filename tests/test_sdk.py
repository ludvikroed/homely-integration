"""Tests for the reusable Homely SDK package."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiohttp

from homely import (
    HomelyAuthError,
    HomelyClient,
    HomelyConnectionError,
    HomelyResponseError,
    HomelyWebSocket,
    HomelyWebSocketError,
    TokenResponse,
    __version__,
    auth_header_value,
)
from custom_components.homely.websocket import HomelyWebSocket as CompatibilityWebSocket


class _FakeResponse:
    """Simple async HTTP response stub."""

    def __init__(self, *, status: int, json_data=None, text_data: str = "") -> None:
        self.status = status
        self._json_data = json_data
        self._text_data = text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data


class _FakeSession:
    """Simple aiohttp client stub."""

    def __init__(
        self, *, post_response=None, get_response=None, post_exc=None, get_exc=None
    ) -> None:
        self._post_response = post_response
        self._get_response = get_response
        self._post_exc = post_exc
        self._get_exc = get_exc

    def post(self, *args, **kwargs):
        if self._post_exc is not None:
            raise self._post_exc
        return self._post_response

    def get(self, *args, **kwargs):
        if self._get_exc is not None:
            raise self._get_exc
        return self._get_response


async def test_sdk_exports_public_client_and_websocket_symbols():
    """The reusable package should expose the core client surface."""
    assert auth_header_value("token") == "Bearer token"
    assert CompatibilityWebSocket is HomelyWebSocket
    assert __version__ == "0.1.3"


async def test_manifest_runtime_dependency_matches_tested_sdk_version():
    """The integration should pin the same SDK version that CI verifies."""
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "homely"
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert f"python-homely=={__version__}" in manifest["requirements"]


async def test_homely_client_fetch_token_with_reason_success():
    """The reusable client should fetch tokens without Home Assistant wrappers."""
    session = _FakeSession(
        post_response=_FakeResponse(status=200, json_data={"access_token": "token"})
    )
    client = HomelyClient(session)

    response, reason = await client.fetch_token_with_reason("user", "pass")

    assert response == {"access_token": "token"}
    assert reason is None


async def test_homely_client_get_home_data_with_status_handles_network_error():
    """The reusable client should normalize transport failures."""
    client = HomelyClient(_FakeSession(get_exc=aiohttp.ClientError("boom")))

    data, status = await client.get_home_data_with_status("token", "loc-1")

    assert data is None
    assert status is None


async def test_homely_client_fetch_refresh_token_handles_timeout():
    """Refresh requests should return None on timeout in the reusable client."""
    client = HomelyClient(_FakeSession(post_exc=asyncio.TimeoutError()))

    assert await client.fetch_refresh_token("refresh-token") is None


async def test_homely_client_public_authenticate_returns_typed_token():
    """The publishable client API should expose typed authentication responses."""
    client = HomelyClient(
        _FakeSession(
            post_response=_FakeResponse(
                status=200,
                json_data={
                    "access_token": "token",
                    "refresh_token": "refresh",
                    "expires_in": "120",
                },
            )
        )
    )

    response = await client.authenticate("user", "pass")

    assert response == TokenResponse(
        access_token="token",
        refresh_token="refresh",
        expires_in=120,
        raw={
            "access_token": "token",
            "refresh_token": "refresh",
            "expires_in": "120",
        },
    )


async def test_homely_client_public_methods_raise_typed_exceptions():
    """Publishable SDK methods should raise predictable typed exceptions."""
    auth_client = HomelyClient(_FakeSession(post_response=_FakeResponse(status=401)))
    locations_client = HomelyClient(_FakeSession(get_exc=aiohttp.ClientError("boom")))
    data_client = HomelyClient(_FakeSession(get_response=_FakeResponse(status=403)))

    try:
        await auth_client.authenticate("user", "pass")
    except HomelyAuthError:
        pass
    else:
        raise AssertionError("Expected HomelyAuthError")

    try:
        await locations_client.get_locations_or_raise("token")
    except HomelyConnectionError:
        pass
    else:
        raise AssertionError("Expected HomelyConnectionError")

    try:
        await data_client.get_home_data_or_raise("token", "loc-1")
    except HomelyAuthError:
        pass
    else:
        raise AssertionError("Expected HomelyAuthError")


async def test_homely_client_get_home_data_or_raise_includes_response_status():
    """Unexpected data fetch failures should raise a response error with status."""
    client = HomelyClient(
        _FakeSession(get_response=_FakeResponse(status=500, text_data="server error"))
    )

    try:
        await client.get_home_data_or_raise("token", "loc-1")
    except HomelyResponseError as err:
        assert err.status == 500
    else:
        raise AssertionError("Expected HomelyResponseError")


async def test_homely_websocket_public_aliases_cover_publishable_api():
    """The websocket client should expose package-friendly aliases."""
    ws = HomelyWebSocket(
        location_id="loc-1",
        token="token",
        on_data_update=lambda _data: None,
        context_id="ctx-1",
    )

    assert ws.context_id == "ctx-1"
    assert ws.entry_id == "ctx-1"

    ws.set_token("new-token")
    assert ws.token == "new-token"


async def test_homely_websocket_connect_or_raise_uses_typed_exception():
    """The websocket client should expose a raise-on-failure connect helper."""
    ws = HomelyWebSocket(
        location_id="loc-1",
        token="token",
        on_data_update=lambda _data: None,
    )
    ws.connect = _FakeAsyncCallable(False)
    ws._status_reason = "connect timeout"

    try:
        await ws.connect_or_raise()
    except HomelyWebSocketError:
        pass
    else:
        raise AssertionError("Expected HomelyWebSocketError")


class _FakeAsyncCallable:
    """Simple async callable test helper."""

    def __init__(self, result):
        self._result = result

    async def __call__(self, *args, **kwargs):
        return self._result
