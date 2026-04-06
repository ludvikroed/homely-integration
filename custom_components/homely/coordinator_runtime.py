"""Coordinator update helpers for Homely config entries."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from homeassistant.core import HomeAssistant
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
        force_api_refresh_once = runtime_data.force_api_refresh_once
        runtime_data.force_api_refresh_once = False

        def _classify_refresh_failure(
            result: RefreshTokenResult | None,
        ) -> str:
            """Group refresh failures into practical logging categories."""
            if result is None or result.response is not None:
                return "unknown_refresh_failure"

            if result.reason == "invalid_refresh_token":
                return "refresh_token_rejected"
            if result.reason in {"cannot_connect", "http_error"}:
                return "homely_unavailable"
            if result.reason in {"invalid_json", "invalid_payload", "empty_response"}:
                return "malformed_auth_response"
            return result.reason or "unknown_refresh_failure"

        def _classify_login_reason(login_reason: str | None) -> str:
            """Group full-login failures into practical logging categories."""
            if login_reason == "invalid_auth":
                return "reported_invalid_auth"
            if login_reason == "cannot_connect":
                return "homely_unavailable"
            return login_reason or "full_login_failed"

        def _auth_issue_log_level(kind: str, *, used_cache: bool) -> int:
            """Return log level for background auth issues."""
            if not used_cache:
                return logging.WARNING
            if kind in {"malformed_auth_response", "full_login_failed"}:
                return logging.WARNING
            return logging.DEBUG

        def _log_auth_issue(
            message: str,
            *,
            kind: str,
            used_cache: bool,
            refresh_failure: str | None = None,
            login_reason: str | None = None,
            status_code: int | None = None,
            detail: str | None = None,
            exc_info: bool = False,
        ) -> None:
            """Log a normalized background auth issue with consistent context."""
            parts = [message, f"kind={kind}", ctx(entry_id, location_id)]
            if status_code is not None:
                parts.append(f"status={status_code}")
            if login_reason:
                parts.append(f"login_reason={login_reason}")
            if refresh_failure:
                parts.append(f"refresh={refresh_failure}")
            if detail:
                parts.append(f"detail={detail}")
            parts.append(websocket_state_context(runtime_data))
            if kind == "malformed_auth_response":
                parts.append("Please open a GitHub issue if this keeps happening.")
            logger.log(
                _auth_issue_log_level(kind, used_cache=used_cache),
                " ".join(parts),
                exc_info=exc_info,
            )

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

        def _sync_websocket_token(token: str) -> None:
            """Update the websocket token without nudging healthy sessions."""
            ws = runtime_data.websocket
            if ws is None:
                return

            try:
                sync_token = getattr(ws, "sync_token", None)
                if callable(sync_token):
                    update_mode = str(sync_token(token))
                else:
                    ws.update_token(token)
                    update_mode = "legacy_no_reconnect"

                if update_mode == "reconnect_if_disconnected":
                    logger.debug(
                        "Updated websocket token and allowed reconnect because websocket was disconnected entry_id=%s location_id=%s",
                        entry_id,
                        location_id,
                    )
                else:
                    logger.debug(
                        "Updated websocket token in-place without reconnect entry_id=%s location_id=%s",
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
                cached_data = _use_cached_data(
                    "Homely auth endpoint failed during fallback login; using cached data"
                )
                _log_auth_issue(
                    "Fallback full login raised during background authentication",
                    kind="homely_unavailable",
                    used_cache=cached_data is not None,
                    refresh_failure=refresh_failure,
                    detail=str(err),
                    exc_info=logger.isEnabledFor(logging.DEBUG)
                    and cached_data is None,
                )
                if cached_data is not None:
                    return None, cached_data
                raise UpdateFailed(
                    f"Exception while performing fallback login: {err}"
                ) from err

            if not login_response:
                failure_kind = _classify_login_reason(login_reason)
                if login_reason == "invalid_auth":
                    cached_data = _use_cached_data(
                        "Homely login endpoint reported invalid_auth during background refresh; using cached data and retrying later"
                    )
                    _log_auth_issue(
                        "Fallback full login reported invalid_auth during background refresh",
                        kind=failure_kind,
                        used_cache=cached_data is not None,
                        refresh_failure=refresh_failure,
                        login_reason=login_reason,
                    )
                    if cached_data is not None:
                        return None, cached_data
                    raise UpdateFailed(
                        "Homely login endpoint reported invalid_auth, but automatic reauthentication is disabled; will retry later"
                    )
                cached_data = _use_cached_data(
                    "Homely auth endpoint did not return a usable token during fallback login; using cached data"
                )
                _log_auth_issue(
                    "Fallback full login returned no usable token",
                    kind=failure_kind,
                    used_cache=cached_data is not None,
                    refresh_failure=refresh_failure,
                    login_reason=login_reason,
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

        async def _retry_poll_with_stored_credentials(
            auth_status_code: int,
        ) -> tuple[dict[str, Any] | None, int | None, dict[str, Any] | None]:
            """Retry a rejected API poll with a fresh full login before reauth."""
            logger.debug(
                "Polling API rejected current access token; retrying with stored credentials "
                "kind=access_token_rejected status=%s %s %s",
                auth_status_code,
                ctx(entry_id, location_id),
                websocket_state_context(runtime_data),
            )
            recovered_token, cached_data = await _perform_full_login(
                f"reason=api_auth_status status={auth_status_code}"
            )
            if cached_data is not None:
                return None, None, cached_data
            if recovered_token is None:
                raise UpdateFailed("Fallback full login returned no usable token")

            _sync_websocket_token(recovered_token)
            updated, retry_status_code = await get_data_with_status(
                hass,
                recovered_token,
                runtime_data.location_id,
            )
            return updated, retry_status_code, None

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
                cached_data = _use_cached_data(
                    "Homely auth endpoint failed during token refresh; using cached data"
                )
                _log_auth_issue(
                    "Token refresh request raised during background refresh",
                    kind="homely_unavailable",
                    used_cache=cached_data is not None,
                    detail=str(err),
                    exc_info=logger.isEnabledFor(logging.DEBUG)
                    and cached_data is None,
                )
                if cached_data is not None:
                    return cached_data
                raise UpdateFailed(f"Exception while refreshing token: {err}") from err

            refresh_result = get_last_refresh_token_result()
            refresh_failure = describe_refresh_token_failure(refresh_result)
            if not refresh_response:
                refresh_failure_kind = _classify_refresh_failure(refresh_result)
                _log_auth_issue(
                    "Token refresh returned no usable token; trying full login",
                    kind=refresh_failure_kind,
                    used_cache=True,
                    refresh_failure=refresh_failure,
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
                    _log_auth_issue(
                        "Token refresh returned incomplete payload; trying full login",
                        kind="malformed_auth_response",
                        used_cache=True,
                        refresh_failure=refresh_failure,
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
                        _log_auth_issue(
                            "Token refresh returned invalid expires_in; trying full login",
                            kind="malformed_auth_response",
                            used_cache=True,
                            refresh_failure=refresh_failure,
                            detail=repr(new_expires_in),
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

            _sync_websocket_token(access_token)

        ws = runtime_data.websocket
        ws_connected = websocket_is_connected(runtime_data)
        if (
            enable_websocket
            and ws is not None
            and not ws_connected
        ):
            try:
                ws.request_reconnect("poll detected disconnected websocket")
                logger.debug(
                    "Requested websocket reconnect because polling observed a disconnected websocket "
                    "entry_id=%s location_id=%s",
                    entry_id,
                    location_id,
                )
            except Exception as err:
                logger.debug(
                    "Failed to request websocket reconnect entry_id=%s location_id=%s: %s",
                    entry_id,
                    location_id,
                    err,
                )

        if (
            enable_websocket
            and ws_connected
            and not poll_when_websocket
            and not force_api_refresh_once
        ):
            update_runtime_websocket_state(runtime_data)
            logger.debug(
                "Polling skipped API request because websocket is connected "
                "entry_id=%s location_id=%s",
                entry_id,
                location_id,
            )
            return runtime_data.last_data
        if force_api_refresh_once:
            logger.debug(
                "Bypassing websocket polling skip due to forced API refresh "
                "entry_id=%s location_id=%s",
                entry_id,
                location_id,
            )

        try:
            updated, status_code = await get_data_with_status(
                hass,
                access_token,
                runtime_data.location_id,
            )
            if not updated and status_code in (401, 403):
                updated, status_code, cached_data = await _retry_poll_with_stored_credentials(
                    status_code
                )
                if cached_data is not None:
                    return cached_data

            if not updated:
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
                if status_code in (401, 403):
                    cached_data = _use_cached_data(
                        "Homely API still rejected credentials after retrying stored credentials; using cached data"
                    )
                    _log_auth_issue(
                        "Polling API still rejected credentials after retrying stored credentials",
                        kind="access_token_rejected",
                        used_cache=cached_data is not None,
                        status_code=status_code,
                    )
                    if cached_data is not None:
                        return cached_data
                    raise UpdateFailed(
                        "Failed to fetch data from API after retrying stored credentials"
                    )
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
