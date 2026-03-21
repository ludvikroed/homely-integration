"""Compatibility wrappers around the reusable Homely SDK client."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homely.client import (
    HomelyClient,
    auth_header_value,
)

_LAST_REFRESH_TOKEN_RESULT: ContextVar["RefreshTokenResult | None"] = ContextVar(
    "homely_last_refresh_token_result",
    default=None,
)


@dataclass(frozen=True)
class RefreshTokenResult:
    """Structured refresh-token result used for diagnostics and logging."""

    response: dict[str, Any] | None
    reason: str | None = None
    status: int | None = None
    detail: str | None = None
    body_preview: str | None = None


def clear_last_refresh_token_result() -> None:
    """Clear the task-local refresh-token diagnostics snapshot."""
    _LAST_REFRESH_TOKEN_RESULT.set(None)


def get_last_refresh_token_result() -> RefreshTokenResult | None:
    """Return the task-local refresh-token diagnostics snapshot."""
    return _LAST_REFRESH_TOKEN_RESULT.get()


def _set_last_refresh_token_result(result: RefreshTokenResult) -> RefreshTokenResult:
    """Store and return the latest refresh result for the current task."""
    _LAST_REFRESH_TOKEN_RESULT.set(result)
    return result


def _body_preview(body: str) -> str | None:
    """Return a compact preview of an HTTP response body for logs."""
    preview = body.replace("\n", " ").strip()
    return preview[:200] or None


def _payload_preview(payload: Any) -> str | None:
    """Return a compact preview of a parsed payload for diagnostics."""
    preview = repr(payload).strip()
    return preview[:200] or None


def _refresh_token_failure_reason(status: int) -> str:
    """Map refresh-token HTTP status to a stable failure reason."""
    if status in (400, 401, 403):
        return "invalid_refresh_token"
    return "http_error"


def describe_refresh_token_failure(result: RefreshTokenResult | None) -> str:
    """Return a compact string that explains a refresh-token failure."""
    if result is None:
        return "reason=unknown"
    if result.response is not None:
        return "reason=success"

    parts = [f"reason={result.reason or 'unknown'}"]
    if result.status is not None:
        parts.append(f"status={result.status}")
    if result.detail:
        parts.append(f"detail={result.detail}")
    if result.body_preview:
        parts.append(f"body_preview={result.body_preview!r}")
    return " ".join(parts)


def _client(hass: HomeAssistant) -> HomelyClient:
    """Build a reusable client bound to Home Assistant's shared session."""
    return HomelyClient(async_get_clientsession(hass))


def _auth_header_value(token: str | None) -> str:
    """Return normalized Authorization header value.

    Kept as a compatibility alias while the integration migrates to the SDK.
    """
    return auth_header_value(token)


async def fetch_token_with_reason(
    hass: HomeAssistant,
    username: str,
    password: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch access token and return optional reason key on failure."""
    return await _client(hass).fetch_token_with_reason(username, password)


async def fetch_token(
    hass: HomeAssistant, username: str, password: str
) -> dict[str, Any] | None:
    """Fetch access token from API."""
    response, _reason = await fetch_token_with_reason(hass, username, password)
    return response


async def fetch_refresh_token(
    hass: HomeAssistant, refresh_token: str
) -> dict[str, Any] | None:
    """Refresh access token using refresh token."""
    result = await fetch_refresh_token_details(hass, refresh_token)
    return result.response


async def fetch_refresh_token_details(
    hass: HomeAssistant,
    refresh_token: str,
) -> RefreshTokenResult:
    """Refresh access token and retain structured failure details for logs."""
    client = _client(hass)
    sdk_fetch_refresh_token_details = getattr(client, "fetch_refresh_token_details", None)
    if callable(sdk_fetch_refresh_token_details):
        sdk_result = await sdk_fetch_refresh_token_details(refresh_token)
        response_data = getattr(sdk_result, "raw", None)

        if response_data is None:
            return _set_last_refresh_token_result(
                RefreshTokenResult(
                    response=None,
                    reason=getattr(sdk_result, "reason", None),
                    status=getattr(sdk_result, "status", None),
                    detail=getattr(sdk_result, "detail", None),
                    body_preview=getattr(sdk_result, "body_preview", None),
                )
            )

        if not isinstance(response_data, dict):
            return _set_last_refresh_token_result(
                RefreshTokenResult(
                    response=None,
                    reason="invalid_payload",
                    status=getattr(sdk_result, "status", None),
                    detail=f"unexpected payload type={type(response_data).__name__}",
                    body_preview=_payload_preview(response_data),
                )
            )

        access_token = response_data.get("access_token")
        expires_in = response_data.get("expires_in")
        if not access_token or expires_in is None:
            return _set_last_refresh_token_result(
                RefreshTokenResult(
                    response=None,
                    reason="invalid_payload",
                    status=getattr(sdk_result, "status", None),
                    detail="missing access_token or expires_in",
                    body_preview=_payload_preview(response_data),
                )
            )

        try:
            int(expires_in)
        except (TypeError, ValueError):
            return _set_last_refresh_token_result(
                RefreshTokenResult(
                    response=None,
                    reason="invalid_payload",
                    status=getattr(sdk_result, "status", None),
                    detail=f"invalid_expires_in value={expires_in!r}",
                    body_preview=_payload_preview(response_data),
                )
            )

        return _set_last_refresh_token_result(
            RefreshTokenResult(
                response=response_data,
                status=getattr(sdk_result, "status", None),
            )
        )

    session = async_get_clientsession(hass)
    url = f"{client.base_url}oauth/refresh-token"
    payload = {"refresh_token": refresh_token}

    try:
        async with session.post(url, json=payload, timeout=client.timeout) as response:
            if response.status not in (200, 201):
                return _set_last_refresh_token_result(
                    RefreshTokenResult(
                        response=None,
                        reason=_refresh_token_failure_reason(response.status),
                        status=response.status,
                        body_preview=_body_preview(await response.text()),
                    )
                )

            try:
                parsed = await response.json()
            except (aiohttp.ContentTypeError, TypeError, ValueError) as err:
                return _set_last_refresh_token_result(
                    RefreshTokenResult(
                        response=None,
                        reason="invalid_json",
                        status=response.status,
                        detail=str(err),
                        body_preview=_body_preview(await response.text()),
                    )
                )
    except (aiohttp.ClientError, TimeoutError) as err:
        return _set_last_refresh_token_result(
            RefreshTokenResult(
                response=None,
                reason="cannot_connect",
                detail=str(err),
            )
        )

    if not parsed:
        return _set_last_refresh_token_result(
            RefreshTokenResult(
                response=None,
                reason="empty_response",
                status=response.status,
            )
        )

    if not isinstance(parsed, dict):
        return _set_last_refresh_token_result(
            RefreshTokenResult(
                response=None,
                reason="invalid_payload",
                status=response.status,
                detail=f"unexpected payload type={type(parsed).__name__}",
                body_preview=_payload_preview(parsed),
            )
        )

    access_token = parsed.get("access_token")
    expires_in = parsed.get("expires_in")
    if not access_token or expires_in is None:
        return _set_last_refresh_token_result(
            RefreshTokenResult(
                response=None,
                reason="invalid_payload",
                status=response.status,
                detail="missing access_token or expires_in",
                body_preview=_payload_preview(parsed),
            )
        )

    try:
        int(expires_in)
    except (TypeError, ValueError):
        return _set_last_refresh_token_result(
            RefreshTokenResult(
                response=None,
                reason="invalid_payload",
                status=response.status,
                detail=f"invalid_expires_in value={expires_in!r}",
                body_preview=_payload_preview(parsed),
            )
        )

    return _set_last_refresh_token_result(
        RefreshTokenResult(
            response=parsed,
            status=response.status,
        )
    )


async def get_location_id(
    hass: HomeAssistant, token: str
) -> list[dict[str, Any]] | None:
    """Get available locations from API."""
    return await _client(hass).get_locations(token)


async def get_data(
    hass: HomeAssistant, token: str, location_id: str | int
) -> dict[str, Any] | None:
    """Get location data from API."""
    data, _status = await get_data_with_status(hass, token, location_id)
    return data


async def get_data_with_status(
    hass: HomeAssistant,
    token: str,
    location_id: str | int,
) -> tuple[dict[str, Any] | None, int | None]:
    """Get location data from API and include HTTP status when available."""
    return await _client(hass).get_home_data_with_status(token, location_id)
