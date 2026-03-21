from __future__ import annotations

from typing import Any

import aiohttp

BASE_URL: str
REQUEST_TIMEOUT: aiohttp.ClientTimeout


def auth_header_value(token: str | None) -> str: ...


class HomelyClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        base_url: str = ...,
        timeout: aiohttp.ClientTimeout = ...,
    ) -> None: ...
    @property
    def base_url(self) -> str: ...
    @property
    def timeout(self) -> aiohttp.ClientTimeout: ...
    async def fetch_token_with_reason(
        self,
        username: str,
        password: str,
    ) -> tuple[dict[str, Any] | None, str | None]: ...
    async def fetch_refresh_token(self, refresh_token: str) -> dict[str, Any] | None: ...
    async def get_locations(self, token: str) -> list[dict[str, Any]] | None: ...
    async def get_home_data(
        self,
        token: str,
        location_id: str | int,
    ) -> dict[str, Any] | None: ...
    async def get_home_data_with_status(
        self,
        token: str,
        location_id: str | int,
    ) -> tuple[dict[str, Any] | None, int | None]: ...
