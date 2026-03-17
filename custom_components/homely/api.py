"""Compatibility wrappers around the reusable Homely SDK client."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homely import BASE_URL, REQUEST_TIMEOUT, HomelyClient, auth_header_value


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


async def fetch_token(hass: HomeAssistant, username: str, password: str) -> dict[str, Any] | None:
    """Fetch access token from API."""
    response, _reason = await fetch_token_with_reason(hass, username, password)
    return response


async def fetch_refresh_token(hass: HomeAssistant, refresh_token: str) -> dict[str, Any] | None:
    """Refresh access token using refresh token."""
    return await _client(hass).fetch_refresh_token(refresh_token)


async def get_location_id(hass: HomeAssistant, token: str) -> list[dict[str, Any]] | None:
    """Get available locations from API."""
    return await _client(hass).get_locations(token)


async def get_data(hass: HomeAssistant, token: str, location_id: str | int) -> dict[str, Any] | None:
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
