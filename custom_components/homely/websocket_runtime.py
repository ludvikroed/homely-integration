"""Websocket lifecycle helpers for Homely config entries."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any, Protocol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .models import HomelyConfigEntry, HomelyRuntimeData
from .runtime_state import (
    device_id_snapshot,
    record_websocket_event,
    update_runtime_websocket_state,
    websocket_is_connected,
)

type RuntimeDataGetter = Callable[[], HomelyRuntimeData | None]
type IdentifierFormatter = Callable[[Any], str | None]
type JsonDebugFormatter = Callable[[Any], str]
type RedactionHelper = Callable[[Any], Any]
type WebSocketApplyCallable = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

WEBSOCKET_CONNECTED_FALLBACK_POLL_INTERVAL = timedelta(hours=6)


class ContextBuilder(Protocol):
    """Typed callable protocol for structured log context helpers."""

    def __call__(
        self,
        entry_id: str,
        location_id: str | int | None = None,
        device_id: str | int | None = None,
    ) -> str: ...


def update_websocket_token(websocket: Any, token: str) -> str:
    """Update websocket token without nudging healthy connections."""
    try:
        is_connected = bool(websocket.is_connected())
    except Exception:
        is_connected = False

    reconnect_if_disconnected = not is_connected

    try:
        websocket.update_token(
            token,
            reconnect_if_disconnected=reconnect_if_disconnected,
        )
    except TypeError as err:
        if "reconnect_if_disconnected" not in str(err):
            raise
        websocket.update_token(token)
        return (
            "legacy_no_reconnect"
            if not reconnect_if_disconnected
            else "legacy_reconnect"
        )

    return "no_reconnect" if not reconnect_if_disconnected else "reconnect_if_disconnected"


def build_device_topology_change_handler(
    *,
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    location_id: str | int,
    logger: logging.Logger,
    runtime_data_getter: RuntimeDataGetter,
    ctx: ContextBuilder,
    log_identifier: IdentifierFormatter,
) -> Callable[[dict[str, Any]], None]:
    """Build a handler that reloads the entry when device topology changes."""

    async def _reload_for_device_topology_change(
        pending_runtime: HomelyRuntimeData,
    ) -> None:
        """Reload the entry once when the device list changes."""
        current_runtime = runtime_data_getter()
        if current_runtime is not pending_runtime:
            return

        try:
            logger.info(
                "Reloading Homely entry after device topology change %s",
                ctx(entry.entry_id, location_id),
            )
            await hass.config_entries.async_reload(entry.entry_id)
        finally:
            current_runtime = runtime_data_getter()
            if current_runtime is pending_runtime:
                current_runtime.topology_reload_pending = False

    def _handle_device_topology_change(updated_data: dict[str, Any]) -> None:
        """Detect added or removed devices and schedule a reload when needed."""
        runtime_data = runtime_data_getter()
        if runtime_data is None:
            return

        updated_ids = device_id_snapshot(updated_data)
        previous_ids = runtime_data.tracked_device_ids
        if not previous_ids:
            runtime_data.tracked_device_ids = updated_ids
            return

        if updated_ids == previous_ids:
            return

        added = sorted(updated_ids - previous_ids)
        removed = sorted(previous_ids - updated_ids)
        runtime_data.tracked_device_ids = updated_ids

        if runtime_data.topology_reload_pending:
            logger.debug(
                "Device topology changed again while reload is pending %s added_count=%s removed_count=%s",
                ctx(entry.entry_id, location_id),
                len(added),
                len(removed),
            )
            return

        runtime_data.topology_reload_pending = True
        logger.info(
            "Homely device topology changed %s added_count=%s removed_count=%s",
            ctx(entry.entry_id, location_id),
            len(added),
            len(removed),
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Device topology identifiers %s added=%s removed=%s",
                ctx(entry.entry_id, location_id),
                [log_identifier(device_id) for device_id in added],
                [log_identifier(device_id) for device_id in removed],
            )
        hass.async_create_task(_reload_for_device_topology_change(runtime_data))

    return _handle_device_topology_change


def build_websocket_data_handler(
    *,
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    location_id: str | int,
    logger: logging.Logger,
    runtime_data_getter: RuntimeDataGetter,
    websocket_getter: Callable[[], Any | None],
    coordinator: DataUpdateCoordinator[dict[str, Any]],
    apply_websocket_event: WebSocketApplyCallable,
    ctx: ContextBuilder,
    json_debug: JsonDebugFormatter,
    redact_for_debug_logging: RedactionHelper,
) -> Callable[[dict[str, Any]], None]:
    """Build the websocket data callback for a config entry runtime."""

    def _requires_followup_refresh(applied_changes: list[dict[str, Any]]) -> bool:
        """Return whether applied websocket changes should trigger a full API refresh."""
        for change in applied_changes:
            feature = change.get("feature")
            state_name = change.get("state_name")
            if feature == "lock" and state_name in {
                "soundvolume",
                "language",
            }:
                return True
        return False

    def on_websocket_data(event_data: dict[str, Any]) -> None:
        """Handle websocket data updates and update local cache directly."""
        try:
            runtime_data = runtime_data_getter()
            current_ws = websocket_getter()
            if runtime_data is None:
                logger.debug(
                    "Ignoring websocket callback for unloaded entry %s",
                    ctx(entry.entry_id, location_id),
                )
                return
            if current_ws is None or runtime_data.websocket is not current_ws:
                logger.debug(
                    "Ignoring websocket callback for stale websocket %s",
                    ctx(entry.entry_id, location_id),
                )
                return

            ws_device_id = None
            payload = event_data.get("data") if isinstance(event_data, dict) else None
            if not isinstance(payload, dict):
                payload = (
                    event_data.get("payload") if isinstance(event_data, dict) else None
                )
            if isinstance(payload, dict):
                ws_device_id = payload.get("deviceId")
            logger.debug(
                "WebSocket event payload %s payload=%s",
                ctx(
                    entry.entry_id,
                    location_id,
                    str(ws_device_id) if ws_device_id is not None else None,
                ),
                json_debug(redact_for_debug_logging(event_data)),
            )
            result = apply_websocket_event(runtime_data.last_data, event_data)
            event_type = result.get("event_type")
            device_id = result.get("device_id")

            if isinstance(event_type, str):
                record_websocket_event(runtime_data, event_type)

            if event_type in ("connect", "disconnect"):
                return

            if event_type == "alarm-state-changed":
                logger.debug(
                    "Applied websocket alarm update %s alarm_state=%s",
                    ctx(entry.entry_id, location_id),
                    result.get("alarm_state"),
                )
                if result.get("updated"):
                    record_websocket_event(
                        runtime_data,
                        event_type,
                        update_data_activity=True,
                    )
                    coordinator.async_update_listeners()
                else:
                    coordinator.async_update_listeners()
                return

            if event_type == "device-state-changed":
                applied_changes = result.get("changes", [])
                if applied_changes:
                    record_websocket_event(
                        runtime_data,
                        event_type,
                        update_data_activity=True,
                    )
                    for change in applied_changes:
                        logger.debug(
                            "Applied websocket device update %s feature=%s state=%s "
                            "value=%s old_value=%s",
                            ctx(
                                entry.entry_id,
                                location_id,
                                str(change.get("device_id"))
                                if change.get("device_id") is not None
                                else None,
                            ),
                            change.get("feature"),
                            change.get("state_name"),
                            change.get("value"),
                            change.get("old_value"),
                        )
                    if _requires_followup_refresh(applied_changes):
                        runtime_data.force_api_refresh_once = True
                        hass.async_create_task(coordinator.async_request_refresh())
                        logger.debug(
                            "Requested immediate API refresh after partial lock websocket update %s",
                            ctx(entry.entry_id, location_id),
                        )
                    coordinator.async_update_listeners()
                else:
                    logger.debug(
                        "Device websocket event could not be applied directly; %s",
                        ctx(
                            entry.entry_id,
                            location_id,
                            str(device_id) if device_id is not None else None,
                        ),
                    )
                    coordinator.async_update_listeners()
                return

            logger.debug(
                "Ignoring unsupported websocket event %s event_type=%s",
                ctx(entry.entry_id, location_id),
                event_type,
            )
            if isinstance(event_type, str):
                coordinator.async_update_listeners()

        except Exception as err:
            logger.error(
                "Unhandled exception in websocket callback %s: %s",
                ctx(entry.entry_id, location_id),
                err,
                exc_info=True,
            )

    return on_websocket_data


async def async_init_websocket(
    *,
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    location_id: str | int,
    logger: logging.Logger,
    runtime_data_getter: RuntimeDataGetter,
    coordinator: DataUpdateCoordinator[dict[str, Any]],
    enable_websocket: bool,
    poll_when_websocket: bool,
    websocket_factory: Any,
    apply_websocket_event: WebSocketApplyCallable,
    ctx: ContextBuilder,
    json_debug: JsonDebugFormatter,
    redact_for_debug_logging: RedactionHelper,
) -> None:
    """Initialize the websocket connection for a Homely entry."""
    try:
        runtime_data = runtime_data_getter()
        if runtime_data is None:
            logger.debug(
                "Skipping websocket init; entry data missing entry_id=%s",
                entry.entry_id,
            )
            return

        websocket_holder: dict[str, Any] = {}

        def _current_websocket() -> Any | None:
            return websocket_holder.get("websocket")

        on_websocket_data = build_websocket_data_handler(
            hass=hass,
            entry=entry,
            location_id=location_id,
            logger=logger,
            runtime_data_getter=runtime_data_getter,
            websocket_getter=_current_websocket,
            coordinator=coordinator,
            apply_websocket_event=apply_websocket_event,
            ctx=ctx,
            json_debug=json_debug,
            redact_for_debug_logging=redact_for_debug_logging,
        )

        def _status_callback(status: str, reason: str | None) -> None:
            """Propagate websocket status changes back to runtime listeners."""

            def _dispatch_status_update() -> None:
                runtime = runtime_data_getter()
                current_ws = _current_websocket()
                if runtime is None or current_ws is None or runtime.websocket is not current_ws:
                    return

                previous_status = runtime.ws_status
                runtime.ws_status = status
                runtime.ws_status_reason = reason
                if (
                    status == "Disconnected"
                    and reason
                    and reason != "manual disconnect"
                ):
                    runtime.last_disconnect_reason = reason

                for listener in list(runtime.ws_status_listeners):
                    try:
                        listener()
                    except Exception as err:
                        logger.debug(
                            "ws_status listener callback failed %s: %s",
                            ctx(entry.entry_id, location_id),
                            err,
                        )

                try:
                    coordinator.async_update_listeners()
                except Exception as err:
                    logger.debug(
                        "coordinator listener update failed %s: %s",
                        ctx(entry.entry_id, location_id),
                        err,
                    )

                if (
                    status == "Disconnected"
                    and previous_status != "Disconnected"
                    and reason != "manual disconnect"
                ):
                    try:
                        current_ws.request_reconnect("status callback observed disconnect")
                    except Exception as err:
                        logger.debug(
                            "Failed to request websocket reconnect after disconnect status %s: %s",
                            ctx(entry.entry_id, location_id),
                            err,
                        )

                if (
                    status == "Disconnected"
                    and previous_status != "Disconnected"
                    and enable_websocket
                    and not poll_when_websocket
                    and reason != "manual disconnect"
                ):
                    try:
                        last_refresh = runtime.ws_disconnect_refresh_monotonic
                        now_monotonic = time.monotonic()
                        if now_monotonic - last_refresh < 30:
                            logger.debug(
                                "Skipping immediate refresh due to disconnect debounce %s",
                                ctx(entry.entry_id, location_id),
                            )
                            return
                        runtime.ws_disconnect_refresh_monotonic = now_monotonic
                        hass.async_create_task(coordinator.async_request_refresh())
                        logger.debug(
                            "Requested immediate polling refresh after websocket disconnect "
                            "%s",
                            ctx(entry.entry_id, location_id),
                        )
                    except Exception as err:
                        logger.debug(
                            "Failed to request refresh after websocket disconnect %s: %s",
                            ctx(entry.entry_id, location_id),
                            err,
                        )

            try:
                hass.loop.call_soon_threadsafe(_dispatch_status_update)
            except Exception as err:
                logger.debug(
                    "WebSocket status callback failed %s status=%s reason=%s: %s",
                    ctx(entry.entry_id, location_id),
                    status,
                    reason,
                    err,
                )

        ws = websocket_factory(
            entry_id=entry.entry_id,
            location_id=runtime_data.location_id,
            token=runtime_data.access_token,
            on_data_update=on_websocket_data,
            status_update_callback=_status_callback,
        )
        websocket_holder["websocket"] = ws

        current_runtime = runtime_data_getter()
        if current_runtime is not runtime_data:
            logger.debug(
                "Skipping websocket connect because entry runtime changed %s",
                ctx(entry.entry_id, location_id),
            )
            return

        current_runtime.websocket = ws
        update_runtime_websocket_state(current_runtime)
        success = await ws.connect()
        if success:
            logger.debug(
                "WebSocket initial connect succeeded entry_id=%s location_id=%s",
                entry.entry_id,
                location_id,
            )
        else:
            logger.info(
                "WebSocket connection failed entry_id=%s location_id=%s. "
                "Polling continues and reconnect loop retries",
                entry.entry_id,
                location_id,
            )
    except KeyError:
        logger.debug(
            "Skipping websocket init; entry data missing entry_id=%s", entry.entry_id
        )
    except Exception as err:
        logger.warning(
            "WebSocket initialization failed %s; polling continues: %s",
            ctx(entry.entry_id, location_id),
            err,
            exc_info=logger.isEnabledFor(logging.DEBUG),
        )


def register_internet_available_listener(
    *,
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    location_id: str | int,
    logger: logging.Logger,
    runtime_data_getter: RuntimeDataGetter,
) -> Any | None:
    """Register an internet recovery hook that nudges websocket reconnects."""

    def _internet_available(event: Any) -> None:
        try:
            runtime_data = runtime_data_getter()
            if runtime_data is None:
                return

            ws = runtime_data.websocket
            if ws is not None:
                logger.debug(
                    "Internet available event; requesting websocket reconnect entry_id=%s location_id=%s",
                    entry.entry_id,
                    location_id,
                )
                try:
                    ws.request_reconnect(reason="internet_available event")
                except Exception as err:
                    logger.debug(
                        "Error requesting websocket reconnect entry_id=%s location_id=%s: %s",
                        entry.entry_id,
                        location_id,
                        err,
                    )
        except Exception as err:
            logger.debug(
                "Error handling internet_available event entry_id=%s location_id=%s: %s",
                entry.entry_id,
                location_id,
                err,
            )

    try:
        return hass.bus.async_listen("internet_available", _internet_available)
    except Exception:
        logger.debug(
            "Could not register internet_available listener entry_id=%s location_id=%s",
            entry.entry_id,
            location_id,
        )
        return None


def register_websocket_connected_poll_fallback(
    *,
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    location_id: str | int,
    logger: logging.Logger,
    runtime_data_getter: RuntimeDataGetter,
    coordinator: DataUpdateCoordinator[dict[str, Any]],
    ctx: ContextBuilder,
) -> Any | None:
    """Force an occasional API poll while websocket suppresses normal polling."""

    async def _async_request_refresh(
        expected_runtime: HomelyRuntimeData,
    ) -> None:
        """Request a one-off refresh if this runtime is still current."""
        if runtime_data_getter() is not expected_runtime:
            return

        try:
            await coordinator.async_request_refresh()
        except Exception as err:
            logger.debug(
                "Failed to request periodic websocket-backed API refresh %s: %s",
                ctx(entry.entry_id, location_id),
                err,
            )

    def _periodic_refresh(_: Any) -> None:
        """Request a forced refresh when websocket-backed polling is suppressed."""
        runtime_data = runtime_data_getter()
        if runtime_data is None:
            return

        if not websocket_is_connected(runtime_data):
            logger.debug(
                "Skipping periodic websocket-backed API refresh because websocket is not connected %s",
                ctx(entry.entry_id, location_id),
            )
            return

        runtime_data.force_api_refresh_once = True
        logger.debug(
            "Requesting periodic websocket-backed API refresh %s interval_s=%s",
            ctx(entry.entry_id, location_id),
            int(WEBSOCKET_CONNECTED_FALLBACK_POLL_INTERVAL.total_seconds()),
        )
        hass.async_create_task(_async_request_refresh(runtime_data))

    try:
        return async_track_time_interval(
            hass,
            _periodic_refresh,
            WEBSOCKET_CONNECTED_FALLBACK_POLL_INTERVAL,
        )
    except Exception:
        logger.debug(
            "Could not register periodic websocket-backed API refresh entry_id=%s location_id=%s",
            entry.entry_id,
            location_id,
        )
        return None
