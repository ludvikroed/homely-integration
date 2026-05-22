from __future__ import annotations

from typing import Any, Literal

import aiohttp

BASE_URL: str
REQUEST_TIMEOUT: aiohttp.ClientTimeout

TokenFailureReason = Literal[
    "invalid_auth",
    "invalid_refresh_token",
    "http_error",
    "network_error",
    "timeout",
    "invalid_json",
    "invalid_payload",
    "empty_response",
]

class TokenResponse:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    raw: dict[str, Any] | None
    def __init__(
        self,
        access_token: str,
        refresh_token: str | None = ...,
        expires_in: int | None = ...,
        raw: dict[str, Any] | None = ...,
    ) -> None: ...
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenResponse: ...

class TokenEndpointResult:
    token: TokenResponse | None
    reason: TokenFailureReason | None
    status: int | None
    detail: str | None
    body_preview: str | None
    def __init__(
        self,
        token: TokenResponse | None = ...,
        reason: TokenFailureReason | None = ...,
        status: int | None = ...,
        detail: str | None = ...,
        body_preview: str | None = ...,
    ) -> None: ...
    @property
    def ok(self) -> bool: ...
    @property
    def raw(self) -> dict[str, Any] | None: ...


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
    async def fetch_refresh_token_details(self, refresh_token: str) -> TokenEndpointResult: ...
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
