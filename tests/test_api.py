"""Tests for the Homely API client."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp

from custom_components.homely import api


class _FakeResponse:
    """Simple async HTTP response stub."""

    def __init__(
        self,
        *,
        status: int,
        json_data=None,
        text_data: str = "",
        json_exc: Exception | None = None,
    ) -> None:
        self.status = status
        self._json_data = json_data
        self._text_data = text_data
        self._json_exc = json_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        if self._json_exc is not None:
            raise self._json_exc
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


async def test_auth_header_value_normalizes_bearer_prefix():
    """Tokens should always be returned as bearer values."""
    assert api._auth_header_value("abc") == "Bearer abc"
    assert api._auth_header_value(" Bearer abc ") == "Bearer abc"


async def test_fetch_token_with_reason_success(hass):
    """Token fetch should return payload on success."""
    session = _FakeSession(
        post_response=_FakeResponse(
            status=200,
            json_data={"access_token": "token"},
        )
    )

    with patch(
        "custom_components.homely.api.async_get_clientsession", return_value=session
    ):
        response, reason = await api.fetch_token_with_reason(hass, "user", "pass")

    assert response == {"access_token": "token"}
    assert reason is None


async def test_fetch_token_with_reason_invalid_auth(hass):
    """Auth rejections should map to invalid_auth."""
    session = _FakeSession(post_response=_FakeResponse(status=401))

    with patch(
        "custom_components.homely.api.async_get_clientsession", return_value=session
    ):
        response, reason = await api.fetch_token_with_reason(hass, "user", "pass")

    assert response is None
    assert reason == "invalid_auth"


async def test_fetch_token_with_reason_server_error(hass):
    """Unexpected HTTP statuses should map to cannot_connect."""
    session = _FakeSession(post_response=_FakeResponse(status=500))

    with patch(
        "custom_components.homely.api.async_get_clientsession", return_value=session
    ):
        response, reason = await api.fetch_token_with_reason(hass, "user", "pass")

    assert response is None
    assert reason == "cannot_connect"


async def test_fetch_token_with_reason_network_error(hass):
    """Network failures should map to cannot_connect."""
    session = _FakeSession(post_exc=aiohttp.ClientError("boom"))

    with patch(
        "custom_components.homely.api.async_get_clientsession", return_value=session
    ):
        response, reason = await api.fetch_token_with_reason(hass, "user", "pass")

    assert response is None
    assert reason == "cannot_connect"


async def test_fetch_token_wrapper_returns_payload_only(hass):
    """fetch_token should unwrap the reason tuple."""
    with patch(
        "custom_components.homely.api.fetch_token_with_reason",
        AsyncMock(return_value=({"access_token": "token"}, None)),
    ):
        response = await api.fetch_token(hass, "user", "pass")

    assert response == {"access_token": "token"}


async def test_fetch_refresh_token_and_locations(hass):
    """Refresh and locations helpers should return parsed JSON."""
    refresh_session = _FakeSession(
        post_response=_FakeResponse(
            status=200,
            json_data={
                "access_token": "new-token",
                "refresh_token": "new-refresh-token",
                "expires_in": 1800,
            },
        )
    )
    locations_session = _FakeSession(
        get_response=_FakeResponse(status=200, json_data=[{"locationId": "abc"}])
    )

    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=refresh_session,
    ):
        refresh_data = await api.fetch_refresh_token(hass, "refresh")
    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=locations_session,
    ):
        locations = await api.get_location_id(hass, "token")

    assert refresh_data == {
        "access_token": "new-token",
        "refresh_token": "new-refresh-token",
        "expires_in": 1800,
    }
    assert locations == [{"locationId": "abc"}]


async def test_fetch_refresh_token_handles_failure_status_and_network_error(hass):
    """Refresh helper should return None on HTTP and network failures."""
    status_session = _FakeSession(post_response=_FakeResponse(status=500))
    network_session = _FakeSession(post_exc=asyncio.TimeoutError())

    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=status_session,
    ):
        assert await api.fetch_refresh_token(hass, "refresh") is None

    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=network_session,
    ):
        assert await api.fetch_refresh_token(hass, "refresh") is None


async def test_fetch_refresh_token_details_expose_structured_http_failure(hass):
    """Refresh diagnostics should keep HTTP failure context for logs."""
    session = _FakeSession(
        post_response=_FakeResponse(status=503, text_data="temporarily unavailable")
    )

    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=session,
    ):
        result = await api.fetch_refresh_token_details(hass, "refresh")

    assert result.response is None
    assert result.reason == "http_error"
    assert result.status == 503
    assert result.body_preview == "temporarily unavailable"
    assert "status=503" in api.describe_refresh_token_failure(result)


async def test_fetch_refresh_token_details_handle_empty_and_invalid_json(hass):
    """Refresh diagnostics should distinguish empty and malformed success bodies."""
    empty_session = _FakeSession(
        post_response=_FakeResponse(status=200, json_data={})
    )
    invalid_json_session = _FakeSession(
        post_response=_FakeResponse(
            status=200,
            json_exc=ValueError("bad json"),
            text_data="not json",
        )
    )

    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=empty_session,
    ):
        empty_result = await api.fetch_refresh_token_details(hass, "refresh")

    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=invalid_json_session,
    ):
        invalid_result = await api.fetch_refresh_token_details(hass, "refresh")

    assert empty_result.reason == "empty_response"
    assert empty_result.status == 200
    assert invalid_result.reason == "invalid_json"
    assert invalid_result.body_preview == "not json"


async def test_fetch_refresh_token_details_validate_required_fields_and_expires(hass):
    """Refresh diagnostics should reject unusable token payloads."""
    missing_fields_session = _FakeSession(
        post_response=_FakeResponse(status=200, json_data={"access_token": "token"})
    )
    invalid_expires_session = _FakeSession(
        post_response=_FakeResponse(
            status=200,
            json_data={
                "access_token": "token",
                "refresh_token": "refresh",
                "expires_in": "bad",
            },
        )
    )

    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=missing_fields_session,
    ):
        missing_result = await api.fetch_refresh_token_details(hass, "refresh")

    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=invalid_expires_session,
    ):
        invalid_expires_result = await api.fetch_refresh_token_details(hass, "refresh")

    assert missing_result.response is None
    assert missing_result.reason == "invalid_payload"
    assert missing_result.detail == "missing access_token or expires_in"

    assert invalid_expires_result.response is None
    assert invalid_expires_result.reason == "invalid_payload"
    assert "invalid_expires_in" in (invalid_expires_result.detail or "")


async def test_fetch_refresh_token_tracks_last_result_for_current_task(hass):
    """The compatibility wrapper should retain structured refresh diagnostics."""
    session = _FakeSession(post_response=_FakeResponse(status=401, text_data="denied"))

    api.clear_last_refresh_token_result()
    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=session,
    ):
        assert await api.fetch_refresh_token(hass, "refresh") is None

    result = api.get_last_refresh_token_result()
    assert result is not None
    assert result.reason == "invalid_refresh_token"
    assert result.status == 401


def test_refresh_helper_formatting_and_reason_mapping():
    """Helper utilities should normalize previews and failure descriptions."""
    assert api._body_preview("\n hello\nworld \n") == "hello world"
    assert api._body_preview("   ") is None
    assert api._payload_preview({"a": 1}).startswith("{'a': 1}")
    assert api._refresh_token_failure_reason(401) == "invalid_refresh_token"
    assert api._refresh_token_failure_reason(500) == "http_error"
    assert api.describe_refresh_token_failure(None) == "reason=unknown"
    assert api.describe_refresh_token_failure(
        api.RefreshTokenResult(response={"access_token": "token"}, status=200)
    ) == "reason=success"


async def test_fetch_refresh_token_details_supports_sdk_payload_validation(hass):
    """SDK-native refresh helpers should still validate payload structure."""
    client = SimpleNamespace(
        fetch_refresh_token_details=AsyncMock(
            side_effect=[
                SimpleNamespace(raw=["bad"], status=200),
                SimpleNamespace(raw={"access_token": "token"}, status=200),
                SimpleNamespace(
                    raw={"access_token": "token", "expires_in": "bad"},
                    status=200,
                ),
                SimpleNamespace(
                    raw={
                        "access_token": "token",
                        "refresh_token": "refresh",
                        "expires_in": 1800,
                    },
                    status=200,
                ),
            ]
        )
    )

    with patch("custom_components.homely.api._client", return_value=client):
        invalid_type = await api.fetch_refresh_token_details(hass, "refresh")
        missing_fields = await api.fetch_refresh_token_details(hass, "refresh")
        invalid_expires = await api.fetch_refresh_token_details(hass, "refresh")
        success = await api.fetch_refresh_token_details(hass, "refresh")

    assert invalid_type.reason == "invalid_payload"
    assert invalid_type.detail == "unexpected payload type=list"
    assert invalid_type.body_preview == "['bad']"

    assert missing_fields.reason == "invalid_payload"
    assert missing_fields.detail == "missing access_token or expires_in"

    assert invalid_expires.reason == "invalid_payload"
    assert "invalid_expires_in" in (invalid_expires.detail or "")

    assert success.response == {
        "access_token": "token",
        "refresh_token": "refresh",
        "expires_in": 1800,
    }
    assert success.status == 200


async def test_get_location_id_handles_failure_status_and_network_error(hass):
    """Location helper should return None on HTTP and network failures."""
    status_session = _FakeSession(get_response=_FakeResponse(status=500))
    network_session = _FakeSession(get_exc=aiohttp.ClientError("boom"))

    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=status_session,
    ):
        assert await api.get_location_id(hass, "token") is None

    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=network_session,
    ):
        assert await api.get_location_id(hass, "token") is None


async def test_get_data_with_status_handles_http_error_and_network_error(hass):
    """Location fetch should expose status codes and network errors."""
    error_session = _FakeSession(
        get_response=_FakeResponse(status=500, text_data="server error")
    )
    timeout_session = _FakeSession(get_exc=asyncio.TimeoutError())

    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=error_session,
    ):
        data, status = await api.get_data_with_status(hass, "token", "loc-1")
    assert data is None
    assert status == 500

    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=timeout_session,
    ):
        data, status = await api.get_data_with_status(hass, "token", "loc-1")
    assert data is None
    assert status is None


async def test_get_data_with_status_success(hass):
    """Successful location fetches should return payload and status."""
    success_session = _FakeSession(
        get_response=_FakeResponse(status=200, json_data={"name": "JF23"})
    )

    with patch(
        "custom_components.homely.api.async_get_clientsession",
        return_value=success_session,
    ):
        data, status = await api.get_data_with_status(hass, "token", "loc-1")

    assert data == {"name": "JF23"}
    assert status == 200


async def test_get_data_wrapper_returns_only_payload(hass):
    """get_data should unwrap the helper status tuple."""
    with patch(
        "custom_components.homely.api.get_data_with_status",
        return_value=({"name": "JF23"}, 200),
    ):
        data = await api.get_data(hass, "token", "loc-1")

    assert data == {"name": "JF23"}
