"""Coordinator update helpers for Homely config entries."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import RefreshTokenResult, describe_refresh_token_failure
from .models import HomelyRuntimeData
from .runtime_state import (
    cached_data_grace_seconds,
    cached_location_data,
    record_successful_poll,
    update_runtime_websocket_state,
    websocket_is_connected,
    websocket_state_context,
)
from .websocket_runtime import update_websocket_token

_TRANSIENT_HTTP_STATUS = {429, 500, 502, 503, 504}

type RuntimeDataGetter = Callable[[], HomelyRuntimeData | None]
type RefreshTokenCallable = Callable[[HomeAssistant, str], Awaitable[dict[str, Any] | None]]
type TokenWithReasonCallable = Callable[
    [HomeAssistant, str, str],
    Awaitable[tuple[dict[str, Any] | None, str | None]],
]
type DataWithStatusCallable = Callable[
    [HomeAssistant, str, str | int],
    Awaitable[tuple[dict[str, Any] | None, int | None]],
]
type RefreshResultGetter = Callable[[], RefreshTokenResult | None]
type RefreshResultClearer = Callable[[], None]
type AlarmGetter = Callable[[dict[str, Any] | None], Any]
type AlarmSetter = Callable[[dict[str, Any], Any], None]


class ContextBuilder(Protocol):
    """Typed callable protocol for structured log context helpers."""

    def __call__(
        self,
        entry_id: str,
        location_id: str | int | None = None,
        device_id: str | int | None = None,
    ) -> str: ...


def build_async_update_data(
    *,
    hass: HomeAssistant,
    logger: logging.Logger,
    entry_id: str,
    location_id: str | int,
    username: str,
    password: str,
    scan_interval: int,
    enable_websocket: bool,
    poll_when_websocket: bool,
    runtime_data_getter: RuntimeDataGetter,
    fetch_refresh_token: RefreshTokenCallable,
    fetch_token_with_reason: TokenWithReasonCallable,
    get_data_with_status: DataWithStatusCallable,
    get_last_refresh_token_result: RefreshResultGetter,
    clear_last_refresh_token_result: RefreshResultClearer,
    get_alarm_state: AlarmGetter,
    set_alarm_state: AlarmSetter,
    handle_device_topology_change: Callable[[dict[str, Any]], None],
    ctx: ContextBuilder,
) -> Callable[[], Awaitable[dict[str, Any]]]:
    """Build the periodic coordinator update method for a Homely entry."""

    async def async_update_data() -> dict[str, Any]:
        """Periodic refresh of location data."""
        runtime_data = runtime_data_getter()
        if runtime_data is None:
            raise UpdateFailed("Entry data is unavailable during coordinator update")

        access_token = runtime_data.access_token
        refresh_token = runtime_data.refresh_token
        expires_at = runtime_data.expires_at
        poll_started_at = time.monotonic()

        def _mark_api_unavailable(message: str) -> None:
            if runtime_data.api_available:
                runtime_data.api_available = False
                logger.info("%s %s", message, ctx(entry_id, location_id))

        def _mark_api_available() -> None:
            if not runtime_data.api_available:
                runtime_data.api_available = True
                logger.info(
                    "Homely API is reachable again %s",
                    ctx(entry_id, location_id),
                )

        def _use_cached_data(message: str) -> dict[str, Any] | None:
            cached_data = cached_location_data(runtime_data)
            if cached_data is None:
                return None

            cache_age_seconds = max(
                0.0,
                time.monotonic() - runtime_data.last_data_activity_monotonic,
            )
            websocket_connected = websocket_is_connected(runtime_data)
            stale_grace_seconds = cached_data_grace_seconds(scan_interval)
            if not websocket_connected and cache_age_seconds >= stale_grace_seconds:
                _mark_api_unavailable(
                    f"{message}; cached data age={int(cache_age_seconds)}s exceeded "
                    f"grace={stale_grace_seconds}s"
                )
                logger.warning(
                    "Marking Homely entities unavailable because cached data is stale "
                    "%s age_s=%s grace_s=%s %s",
                    ctx(entry_id, location_id),
                    int(cache_age_seconds),
                    stale_grace_seconds,
                    websocket_state_context(runtime_data),
                )
                return None

            _mark_api_unavailable(message)
            update_runtime_websocket_state(runtime_data)
            logger.debug(
                "Using cached Homely data %s age_s=%s grace_s=%s %s",
                ctx(entry_id, location_id),
                int(cache_age_seconds),
                stale_grace_seconds,
                websocket_state_context(runtime_data),
            )
            return cached_data

        async def _perform_full_login(
            refresh_failure: str | None,
        ) -> tuple[str | None, dict[str, Any] | None]:
            """Retry authentication with full login and update runtime tokens."""
            try:
                login_response, login_reason = await fetch_token_with_reason(
                    hass,
                    username,
                    password,
                )
            except Exception as err:
                logger.warning(
                    "Fallback full login raised %s refresh=%s %s: %s",
                    ctx(entry_id, location_id),
                    refresh_failure or "reason=unknown",
                    websocket_state_context(runtime_data),
                    err,
                    exc_info=logger.isEnabledFor(logging.DEBUG),
                )
                cached_data = _use_cached_data(
                    "Token refresh failed and full login raised "
                    f"({err}); continuing with cached data"
                )
                if cached_data is not None:
                    return None, cached_data
                raise UpdateFailed(
                    f"Exception while performing fallback login: {err}"
                ) from err

            if not login_response:
                if login_reason == "invalid_auth":
                    raise ConfigEntryAuthFailed(
                        "Stored Homely credentials are no longer valid"
                    )
                logger.warning(
                    "Fallback full login returned no token %s login_reason=%s refresh=%s %s",
                    ctx(entry_id, location_id),
                    login_reason or "unknown",
                    refresh_failure or "reason=unknown",
                    websocket_state_context(runtime_data),
                )
                cached_data = _use_cached_data(
                    "Token refresh failed and full login returned no token"
                    + (
                        f" (refresh={refresh_failure}); continuing with cached data"
                        if refresh_failure
                        else "; continuing with cached data"
                    )
                )
                if cached_data is not None:
                    return None, cached_data
                raise UpdateFailed(
                    "Failed to refresh token and full login also failed."
                )

            new_access_token = login_response.get("access_token")
            new_refresh_token = login_response.get("refresh_token") or refresh_token
            new_expires_in = login_response.get("expires_in")
            if not new_access_token or not new_expires_in:
                raise UpdateFailed("Full login response missing required fields")
            try:
                new_expires_in_seconds = int(new_expires_in)
            except (TypeError, ValueError):
                raise UpdateFailed("Full login response has invalid expires_in")

            runtime_data.access_token = new_access_token
            runtime_data.refresh_token = new_refresh_token
            runtime_data.expires_at = time.time() + new_expires_in_seconds - 60
            logger.debug(
                "Token refreshed via full login entry_id=%s location_id=%s "
                "access_expires_in_s=%s next_refresh_in_s=%s",
                entry_id,
                location_id,
                new_expires_in_seconds,
                max(new_expires_in_seconds - 60, 0),
            )
            return new_access_token, None

        if time.time() >= expires_at:
            logger.debug(
                "Token expires soon; refreshing entry_id=%s location_id=%s",
                entry_id,
                location_id,
            )
            clear_last_refresh_token_result()
            try:
                refresh_response = await fetch_refresh_token(hass, refresh_token)
            except Exception as err:
                logger.warning(
                    "Token refresh request failed %s %s: %s",
                    ctx(entry_id, location_id),
                    websocket_state_context(runtime_data),
                    err,
                    exc_info=logger.isEnabledFor(logging.DEBUG),
                )
                cached_data = _use_cached_data(
                    f"Token refresh request failed ({err}); continuing with cached data"
                )
                if cached_data is not None:
                    return cached_data
                raise UpdateFailed(f"Exception while refreshing token: {err}") from err

            refresh_result = get_last_refresh_token_result()
            refresh_failure = describe_refresh_token_failure(refresh_result)
            if not refresh_response:
                logger.debug(
                    "Token refresh returned no token; trying full login %s refresh=%s %s",
                    ctx(entry_id, location_id),
                    refresh_failure,
                    websocket_state_context(runtime_data),
                )
                recovered_token, cached_data = await _perform_full_login(
                    refresh_failure
                )
                if cached_data is not None:
                    return cached_data
                if recovered_token is None:
                    raise UpdateFailed("Fallback full login returned no usable token")
                access_token = recovered_token
            else:
                new_access_token = refresh_response.get("access_token")
                new_refresh_token = (
                    refresh_response.get("refresh_token") or refresh_token
                )
                new_expires_in = refresh_response.get("expires_in")
                if not new_access_token or not new_expires_in:
                    refresh_failure = "reason=invalid_payload"
                    logger.warning(
                        "Token refresh returned incomplete payload %s refresh=%s %s",
                        ctx(entry_id, location_id),
                        refresh_failure,
                        websocket_state_context(runtime_data),
                    )
                    recovered_token, cached_data = await _perform_full_login(
                        refresh_failure
                    )
                    if cached_data is not None:
                        return cached_data
                    if recovered_token is None:
                        raise UpdateFailed(
                            "Fallback full login returned no usable token"
                        )
                    access_token = recovered_token
                else:
                    try:
                        new_expires_in_seconds = int(new_expires_in)
                    except (TypeError, ValueError):
                        refresh_failure = (
                            f"reason=invalid_expires_in value={new_expires_in!r}"
                        )
                        logger.warning(
                            "Token refresh returned invalid expires_in %s refresh=%s expires_in=%r %s",
                            ctx(entry_id, location_id),
                            refresh_failure,
                            new_expires_in,
                            websocket_state_context(runtime_data),
                        )
                        recovered_token, cached_data = await _perform_full_login(
                            refresh_failure
                        )
                        if cached_data is not None:
                            return cached_data
                        if recovered_token is None:
                            raise UpdateFailed(
                                "Fallback full login returned no usable token"
                            )
                        access_token = recovered_token
                    else:
                        runtime_data.access_token = new_access_token
                        runtime_data.refresh_token = new_refresh_token
                        runtime_data.expires_at = (
                            time.time() + new_expires_in_seconds - 60
                        )
                        access_token = new_access_token
                        logger.debug(
                            "Token refreshed entry_id=%s location_id=%s "
                            "access_expires_in_s=%s next_refresh_in_s=%s",
                            entry_id,
                            location_id,
                            new_expires_in_seconds,
                            max(new_expires_in_seconds - 60, 0),
                        )

            ws = runtime_data.websocket
            if ws is not None:
                try:
                    update_mode = update_websocket_token(ws, access_token)
                    if update_mode == "reconnect_if_disconnected":
                        logger.debug(
                            "Updated websocket token and requested reconnect if needed entry_id=%s location_id=%s",
                            entry_id,
                            location_id,
                        )
                    else:
                        logger.debug(
                            "Updated websocket token in-place using legacy websocket API entry_id=%s location_id=%s",
                            entry_id,
                            location_id,
                        )
                except Exception as err:
                    logger.debug(
                        "Failed to update websocket token entry_id=%s location_id=%s: %s",
                        entry_id,
                        location_id,
                        err,
                    )

        ws_connected = websocket_is_connected(runtime_data)
        if enable_websocket and ws_connected and not poll_when_websocket:
            update_runtime_websocket_state(runtime_data)
            logger.debug(
                "Polling skipped API request because websocket is connected "
                "entry_id=%s location_id=%s",
                entry_id,
                location_id,
            )
            return runtime_data.last_data

        try:
            updated, status_code = await get_data_with_status(
                hass,
                access_token,
                runtime_data.location_id,
            )
            if not updated:
                if status_code in (401, 403):
                    raise ConfigEntryAuthFailed(
                        "Homely token is no longer accepted by API"
                    )
                if (
                    status_code in _TRANSIENT_HTTP_STATUS
                    and isinstance(runtime_data.last_data, dict)
                    and runtime_data.last_data
                ):
                    _mark_api_unavailable(
                        "Polling API request failed with transient status="
                        f"{status_code}; continuing with cached data"
                    )
                    return runtime_data.last_data
                raise UpdateFailed("Failed to fetch data from API")

            _mark_api_available()
            record_successful_poll(runtime_data)
            elapsed_ms = int((time.monotonic() - poll_started_at) * 1000)
            devices = updated.get("devices")
            device_count = len(devices) if isinstance(devices, list) else "unknown"
            logger.debug(
                "Polling API fetch success entry_id=%s location_id=%s "
                "duration_ms=%s device_count=%s",
                entry_id,
                location_id,
                elapsed_ms,
                device_count,
            )
        except UpdateFailed:
            raise
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            cached_data = _use_cached_data(
                f"Polling exception: {err}; continuing with cached data"
            )
            if cached_data is not None:
                return cached_data
            _mark_api_unavailable(f"Polling exception: {err}")
            raise UpdateFailed(f"Exception while fetching data from API: {err}") from err

        old_alarm = get_alarm_state(runtime_data.last_data)
        new_alarm = get_alarm_state(updated)

        if new_alarm is None and old_alarm is not None:
            logger.debug(
                "API alarm missing; keeping cached alarm entry_id=%s location_id=%s",
                entry_id,
                location_id,
            )
            set_alarm_state(updated, old_alarm)
            new_alarm = old_alarm
        elif new_alarm is not None:
            set_alarm_state(updated, new_alarm)

        runtime_data.last_data = updated
        handle_device_topology_change(updated)
        update_runtime_websocket_state(runtime_data)

        if old_alarm != new_alarm:
            logger.debug(
                "Alarm state changed entry_id=%s location_id=%s: %s -> %s",
                entry_id,
                location_id,
                old_alarm,
                new_alarm,
            )

        return updated

    return async_update_data
