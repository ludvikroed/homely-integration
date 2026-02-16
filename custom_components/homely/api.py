"""API client for Homely."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://sdk.iotiliti.cloud/homely/"


async def fetch_token(hass: HomeAssistant, username: str, password: str) -> dict[str, Any] | None:
    """Fetch access token from API."""
    session = async_get_clientsession(hass)
    url = f"{BASE_URL}oauth/token"
    payload = {
        "username": username,
        "password": password,
    }
    
    try:
        async with session.post(url, json=payload) as response:
            if response.status in (200, 201):
                _LOGGER.debug("Token fetch successful")
                return await response.json()
            _LOGGER.error("Token fetch failed with status %s", response.status)
            return None
    except aiohttp.ClientError as err:
        _LOGGER.error("Network error during token fetch: %s", err)
        return None


async def fetch_refresh_token(hass: HomeAssistant, refresh_token: str) -> dict[str, Any] | None:
    """Refresh access token using refresh token."""
    session = async_get_clientsession(hass)
    url = f"{BASE_URL}oauth/refresh-token"
    payload = {
        "refresh_token": refresh_token,
    }
    
    try:
        async with session.post(url, json=payload) as response:
            if response.status in (200, 201):
                _LOGGER.debug("Token refresh successful")
                return await response.json()
            _LOGGER.error("Token refresh failed with status %s", response.status)
            return None
    except aiohttp.ClientError as err:
        _LOGGER.error("Network error during token refresh: %s", err)
        return None


async def get_location_id(hass: HomeAssistant, token: str) -> dict[str, Any] | None:
    """Get location ID from API."""
    session = async_get_clientsession(hass)
    url = f"{BASE_URL}locations"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                _LOGGER.debug("Locations fetch successful")
                return await response.json()
            _LOGGER.error("Locations fetch failed with status %s", response.status)
            return None
    except aiohttp.ClientError as err:
        _LOGGER.error("Network error fetching locations: %s", err)
        return None


async def get_data(hass: HomeAssistant, token: str, location_id: int) -> dict[str, Any] | None:
    """Get location data from API."""
    session = async_get_clientsession(hass)
    url = f"{BASE_URL}home/{location_id}"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                _LOGGER.debug("Location data fetch successful")
                return await response.json()
            _LOGGER.error("Location data fetch failed with status %s", response.status)
            return None
    except aiohttp.ClientError as err:
        _LOGGER.error("Network error fetching location data: %s", err)
        return None
