"""The Homely Alarm integration."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .api import (
    clear_last_refresh_token_result,
    fetch_refresh_token,
    fetch_token_with_reason,
    get_last_refresh_token_result,
    get_data_with_status,
    get_location_id,
)
from .coordinator_runtime import build_async_update_data, schedule_api_error_retry
from .const import (
    CONF_HOME_ID,
    CONF_LOCATION_ID,
    CONF_PASSWORD,
    CONF_PENDING_IMPORT_LOCATIONS,
    CONF_USERNAME,
    DEFAULT_HOME_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPTION_KEYS,
)
from .logging_helpers import (
    _ctx,
    _json_debug,
    _log_identifier,
    _log_startup_device_payloads as _log_startup_device_payloads_impl,
    _redact_for_debug_logging,
)
from .models import HomelyConfigEntry, HomelyRuntimeData
from .repairs import (
    async_delete_missing_devices_issue,
    async_sync_missing_devices_issue,
)
from .runtime_state import (
    current_runtime_data,
    device_id_snapshot,
    LAST_ARMED_CACHE_KEY,
    LAST_DISARMED_CACHE_KEY,
    location_payload_error,
    record_api_poll_status,
    record_last_armed,
    record_last_disarmed,
    record_successful_poll,
    tracked_api_device_ids,
)
from .websocket import HomelyWebSocket
from .websocket_runtime import (
    async_init_websocket,
    build_device_topology_change_handler,
    register_internet_available_listener,
    register_websocket_health_watchdog,
)
from .ws_updates import apply_websocket_event_to_data

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.ALARM_CONTROL_PANEL,
    Platform.LOCK,
]
_LOGGER = logging.getLogger(__name__)


def _device_id_snapshot(data: dict[str, Any] | None) -> set[str]:
    """Compatibility wrapper for device-id snapshot helper tests."""
    return device_id_snapshot(data)


def _tracked_api_device_ids(
    entry_data: HomelyRuntimeData | None,
) -> tuple[bool, set[str]]:
    """Compatibility wrapper for active-device snapshot helper tests."""
    return tracked_api_device_ids(entry_data)


def _log_startup_device_payloads(
    data: dict[str, Any],
    entry_id: str,
    location_id: str | int,
) -> None:
    """Compatibility wrapper for startup payload logging helper tests."""
    _log_startup_device_payloads_impl(_LOGGER, data, entry_id, location_id)


def _get_alarm_state(data: dict[str, Any] | None) -> Any:
    """Return location alarm state, preferring top-level API field."""
    if not isinstance(data, dict):
        return None

    top_level = data.get("alarmState")
    if top_level is not None:
        return top_level

    return (
        data.get("features", {})
        .get("alarm", {})
        .get("states", {})
        .get("alarm", {})
        .get("value")
    )


def _set_alarm_state(data: dict[str, Any], alarm_state: Any) -> None:
    """Write location alarm state to both top-level and nested feature path."""
    data["alarmState"] = alarm_state
    features = data.setdefault("features", {})
    alarm_feature = features.setdefault("alarm", {})
    states = alarm_feature.setdefault("states", {})
    alarm_state_dict = states.setdefault("alarm", {})
    alarm_state_dict["value"] = alarm_state


def _pending_import_locations(
    entry: ConfigEntry,
) -> list[dict[str, str]]:
    """Return sanitized pending multi-location imports from entry data."""
    pending_imports = entry.data.get(CONF_PENDING_IMPORT_LOCATIONS, [])
    if not isinstance(pending_imports, list):
        return []

    sanitized: list[dict[str, str]] = []
    for item in pending_imports:
        if not isinstance(item, dict):
            continue

        location_id = item.get(CONF_LOCATION_ID)
        if location_id is None:
            continue

        sanitized.append(
            {
                CONF_LOCATION_ID: str(location_id),
                "title": str(item.get("title") or "").strip(),
            }
        )

    return sanitized


def _clear_pending_import_locations(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Remove internal pending-import metadata after scheduling."""
    if CONF_PENDING_IMPORT_LOCATIONS not in entry.data:
        return

    updated_data = dict(entry.data)
    updated_data.pop(CONF_PENDING_IMPORT_LOCATIONS, None)
    hass.config_entries.async_update_entry(entry, data=updated_data)


def _schedule_pending_location_imports(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Schedule config flows for additional unconfigured locations."""
    pending_imports = _pending_import_locations(entry)
    if not pending_imports:
        return

    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    if not username or not password:
        _clear_pending_import_locations(hass, entry)
        return

    existing_location_ids = {
        str(existing_entry.data.get(CONF_LOCATION_ID))
        for existing_entry in hass.config_entries.async_entries(DOMAIN)
        if existing_entry.entry_id != entry.entry_id
        and existing_entry.data.get(CONF_LOCATION_ID) is not None
    }

    for pending in pending_imports:
        location_id = pending[CONF_LOCATION_ID]
        if location_id in existing_location_ids:
            continue

        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_IMPORT},
                data={
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                    CONF_LOCATION_ID: location_id,
                    "title": pending["title"],
                },
            )
        )
        existing_location_ids.add(location_id)

    _clear_pending_import_locations(hass, entry)


def _reenable_integration_disabled_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Re-enable Homely entities that older versions disabled by default.

    Home Assistant persists integration-disabled registry entries across
    upgrades. Restore those entries now that every Homely entity is enabled by
    default, while preserving explicit user choices.
    """
    entity_registry = er.async_get(hass)
    reenabled = 0

    for registry_entry in er.async_entries_for_config_entry(
        entity_registry,
        entry.entry_id,
    ):
        if registry_entry.platform != DOMAIN:
            continue
        if registry_entry.disabled_by is not er.RegistryEntryDisabler.INTEGRATION:
            continue

        entity_registry.async_update_entity(
            registry_entry.entity_id,
            disabled_by=None,
        )
        reenabled += 1

    if reenabled:
        _LOGGER.info(
            "Re-enabled %s Homely entity registry entries entry_id=%s",
            reenabled,
            entry.entry_id,
        )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to newer structure."""
    if entry.version > 2:
        _LOGGER.error("Unsupported config entry version %s", entry.version)
        return False

    if entry.version == 1:
        new_data = dict(entry.data)
        new_options = dict(entry.options)
        for key in OPTION_KEYS:
            if key in new_data and key not in new_options:
                new_options[key] = new_data.pop(key)

        new_unique_id = entry.unique_id
        location_id = new_data.get(CONF_LOCATION_ID)
        if new_unique_id is None and location_id is not None:
            new_unique_id = str(location_id)

        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            options=new_options,
            unique_id=new_unique_id,
            version=2,
        )
        _LOGGER.info(
            "Migrated Homely config entry to version 2 entry_id=%s", entry.entry_id
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: HomelyConfigEntry) -> bool:
    """Set up Homely Alarm from a config entry."""
    entry_id = entry.entry_id
    _LOGGER.debug("Setting up Homely Alarm entry entry_id=%s", entry_id)
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    if not username or not password:
        raise ConfigEntryAuthFailed("Homely credentials are missing")

    response, reason = await fetch_token_with_reason(
        hass,
        username,
        password,
    )

    if not response:
        if reason == "invalid_auth":
            raise ConfigEntryAuthFailed("Invalid Homely username or password")
        raise ConfigEntryNotReady("Failed to fetch Homely token")

    access_token_str = response.get("access_token")
    refresh_token_str = response.get("refresh_token")
    expires_in = response.get("expires_in")
    if not access_token_str or not refresh_token_str:
        raise ConfigEntryNotReady("Token response missing required fields")
    if not expires_in:
        raise ConfigEntryNotReady("Token response missing expires_in")
    try:
        expires_in_seconds = int(expires_in)
    except (TypeError, ValueError) as err:
        raise ConfigEntryNotReady("Token response has invalid expires_in") from err
    _LOGGER.debug(
        "Initial token acquired entry_id=%s access_expires_in_s=%s refresh_margin_s=60",
        entry_id,
        expires_in_seconds,
    )

    # Config flow and reauth already validate modern entries. Avoid fetching the
    # complete account location list on every restart; legacy home_id entries
    # still need that lookup once so they can be migrated to a stable location_id.
    partner_code: int | str | None = None
    configured_location_id = entry.data.get(CONF_LOCATION_ID)
    if configured_location_id is not None:
        location_id: str | int = str(configured_location_id)
        _LOGGER.debug(
            "Using stored location_id entry_id=%s location_id=%s",
            entry_id,
            location_id,
        )
    else:
        location_response = await get_location_id(hass, access_token_str)
        if not location_response:
            raise ConfigEntryNotReady("Failed to fetch Homely locations")
        home_id = int(
            entry.options.get(
                CONF_HOME_ID,
                entry.data.get(CONF_HOME_ID, DEFAULT_HOME_ID),
            )
        )
        _LOGGER.debug("Using legacy home_id=%s entry_id=%s", home_id, entry_id)
        try:
            location_item = location_response[home_id]
            location_id = location_item["locationId"]
            partner_code = location_item.get("partnerCode")
        except (KeyError, IndexError, TypeError) as err:
            _LOGGER.debug(
                "Failed to find location_id for home_id=%s entry_id=%s: %s",
                home_id,
                entry_id,
                err,
            )
            raise ConfigEntryNotReady(
                f"Configured home_id={home_id} is not available"
            ) from err

        _LOGGER.debug(
            "Resolved legacy home_id=%s to location_id=%s entry_id=%s",
            home_id,
            location_id,
            entry_id,
        )

    normalized_location_id = str(location_id)
    if (
        entry.unique_id != normalized_location_id
        or entry.data.get(CONF_LOCATION_ID) != normalized_location_id
    ):
        updated_data = dict(entry.data)
        updated_data[CONF_LOCATION_ID] = normalized_location_id
        hass.config_entries.async_update_entry(
            entry,
            data=updated_data,
            unique_id=normalized_location_id,
        )
        _LOGGER.debug(
            "Updated config entry with location_id/unique_id entry_id=%s location_id=%s",
            entry_id,
            normalized_location_id,
        )

    scan_interval = DEFAULT_SCAN_INTERVAL
    enable_websocket = True
    poll_when_websocket = True

    store: Store[dict[str, Any]] = Store(hass, 1, f"homely.{normalized_location_id}")
    stored_data: dict[str, Any] | None = await store.async_load()
    if (
        not isinstance(stored_data, dict)
        or location_payload_error(stored_data, normalized_location_id) is not None
    ):
        stored_data = None

    initial_fetch_deferred = stored_data is not None
    initial_fetch_status: int | None = None
    initial_payload_error: str | None = None
    data: dict[str, Any] | None = stored_data
    if initial_fetch_deferred:
        _LOGGER.debug(
            "Loading entry from stored data while startup API synchronization runs in background %s",
            _ctx(entry_id, location_id),
        )
    else:
        data, initial_fetch_status = await get_data_with_status(
            hass, access_token_str, location_id
        )
        initial_payload_error = (
            location_payload_error(data, normalized_location_id) if data else None
        )
        if initial_payload_error is not None:
            _LOGGER.warning(
                "Initial Homely API poll returned an invalid payload; treating it as a failed poll %s error=%s",
                _ctx(entry_id, location_id),
                initial_payload_error,
            )
            data = None
    seed_without_poll = False
    save_initial_data = False
    initial_pending_removed_ids: set[str] = set()
    if initial_fetch_deferred:
        assert data is not None
        seed_without_poll = True
        initial_alarm_state = _get_alarm_state(data)
        if initial_alarm_state is not None:
            _set_alarm_state(data, initial_alarm_state)
        _log_startup_device_payloads(data, entry_id, location_id)
    elif not data:
        # The initial /home poll returned no usable data. This happens when
        # Homely rate limits us, or when the REST API is temporarily broken
        # while the websocket still works. Degrade gracefully instead of
        # refusing to load: prefer a cached snapshot, otherwise still load
        # when the websocket can carry live alarm state.
        if stored_data:
            _LOGGER.warning(
                "Initial Homely API poll failed (status=%s); using stored data "
                "from previous run entry_id=%s location_id=%s",
                initial_fetch_status,
                entry_id,
                location_id,
            )
            data = stored_data
            seed_without_poll = True
        elif enable_websocket:
            _LOGGER.warning(
                "Initial Homely API poll failed (status=%s) and no stored data is "
                "available; loading with websocket-only data and relying on the "
                "websocket for live alarm state. Per-device sensors stay "
                "unavailable until the API recovers entry_id=%s location_id=%s",
                initial_fetch_status,
                entry_id,
                location_id,
            )
            data = {}
            seed_without_poll = True
        else:
            raise ConfigEntryNotReady("Failed to fetch Homely location data")
    else:
        initial_alarm_state = _get_alarm_state(data)
        if initial_alarm_state is not None:
            _set_alarm_state(data, initial_alarm_state)

        if stored_data is not None:
            initial_pending_removed_ids = _device_id_snapshot(
                stored_data
            ) - _device_id_snapshot(data)
            if initial_pending_removed_ids:
                stored_devices = stored_data.get("devices")
                current_devices = data.get("devices")
                if isinstance(stored_devices, list) and isinstance(
                    current_devices, list
                ):
                    current_devices.extend(
                        device
                        for device in stored_devices
                        if isinstance(device, dict)
                        and str(device.get("id")) in initial_pending_removed_ids
                    )
                _LOGGER.warning(
                    "Initial Homely API poll omitted cached devices; waiting for a second snapshot before removal %s removed_count=%s",
                    _ctx(entry_id, location_id),
                    len(initial_pending_removed_ids),
                )
        _log_startup_device_payloads(data, entry_id, location_id)
        save_initial_data = True

    def _runtime_data() -> HomelyRuntimeData | None:
        """Return runtime data only while the entry is still loaded."""
        return current_runtime_data(entry)

    _LOGGER.debug(
        "Configured polling entry_id=%s location_id=%s scan_interval=%ss websocket=%s",
        entry_id,
        location_id,
        scan_interval,
        enable_websocket,
    )
    _LOGGER.debug(
        "Polling while websocket connected is %s entry_id=%s location_id=%s",
        "enabled" if poll_when_websocket else "disabled",
        entry_id,
        location_id,
    )

    handle_device_topology_change = build_device_topology_change_handler(
        hass=hass,
        entry=entry,
        location_id=location_id,
        logger=_LOGGER,
        runtime_data_getter=_runtime_data,
        ctx=_ctx,
        log_identifier=_log_identifier,
        save_snapshot=store.async_save,
    )

    @callback
    def _sync_missing_devices_issue(snapshot: dict[str, Any]) -> None:
        async_sync_missing_devices_issue(hass, entry, snapshot)

    async_update_data = build_async_update_data(
        hass=hass,
        logger=_LOGGER,
        entry_id=entry_id,
        location_id=location_id,
        username=username,
        password=password,
        scan_interval=scan_interval,
        enable_websocket=bool(enable_websocket),
        poll_when_websocket=poll_when_websocket,
        runtime_data_getter=_runtime_data,
        fetch_refresh_token=lambda runtime_hass, refresh: fetch_refresh_token(
            runtime_hass, refresh
        ),
        fetch_token_with_reason=lambda runtime_hass, runtime_username, runtime_password: fetch_token_with_reason(
            runtime_hass,
            runtime_username,
            runtime_password,
        ),
        get_data_with_status=lambda runtime_hass, token, runtime_location_id: get_data_with_status(
            runtime_hass,
            token,
            runtime_location_id,
        ),
        get_last_refresh_token_result=lambda: get_last_refresh_token_result(),
        clear_last_refresh_token_result=lambda: clear_last_refresh_token_result(),
        get_alarm_state=_get_alarm_state,
        set_alarm_state=_set_alarm_state,
        handle_device_topology_change=handle_device_topology_change,
        sync_missing_devices_issue=_sync_missing_devices_issue,
        ctx=_ctx,
    )
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="homely",
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
        config_entry=entry,
    )
    # Only claim the REST API is reachable when this setup actually got fresh
    # data from a live poll. When we fell back to stored/empty data (e.g. the
    # /home endpoint returning HTTP 439), seed False so the "Cloud API
    # connection" sensor reports the outage immediately instead of defaulting
    # to "connected" until the first failing poll runs.
    initial_api_available = bool(data) and not seed_without_poll
    runtime_data = HomelyRuntimeData(
        coordinator=coordinator,
        access_token=access_token_str,
        refresh_token=refresh_token_str,
        expires_at=time.time() + expires_in_seconds - 60,
        location_id=normalized_location_id,
        last_data=data,
        tracked_device_ids=_device_id_snapshot(data),
        pending_removed_device_ids=initial_pending_removed_ids,
        pending_removal_confirmations=(1 if initial_pending_removed_ids else 0),
        partner_code=partner_code,
        api_available=initial_api_available,
    )
    record_last_armed(runtime_data, data.get(LAST_ARMED_CACHE_KEY))
    record_last_disarmed(runtime_data, data.get(LAST_DISARMED_CACHE_KEY))
    if not initial_fetch_deferred:
        if initial_api_available:
            # Only claim a successful poll when one actually happened. When seeding
            # from cache the data-activity baseline (set by the dataclass default)
            # keeps the cache-grace logic working, but the poll timestamps stay
            # unset so diagnostics don't report a poll that never ran.
            record_successful_poll(runtime_data)
        else:
            record_api_poll_status(
                runtime_data,
                "failed",
                status_code=initial_fetch_status,
                detail=(
                    f"Initial API poll returned an invalid payload: {initial_payload_error}"
                    if initial_payload_error is not None
                    else "Initial API poll failed; using cached or websocket-only data"
                ),
            )
            schedule_api_error_retry(
                hass=hass,
                runtime_data=runtime_data,
                runtime_data_getter=_runtime_data,
                logger=_LOGGER,
                entry_id=entry_id,
                location_id=location_id,
                ctx=_ctx,
                status_code=initial_fetch_status,
            )
    entry.runtime_data = runtime_data
    if save_initial_data:
        entry.async_create_background_task(
            hass,
            store.async_save(data),
            "homely initial data cache save",
        )

    def _save_on_successful_update() -> None:
        # Delay the write: this listener fires for every websocket event, and
        # an immediate save per event would hammer .storage (flash wear).
        if coordinator.last_update_success and runtime_data.last_data:
            store.async_delay_save(lambda: runtime_data.last_data, 60)

    hass.async_create_task(
        async_init_websocket(
            hass=hass,
            entry=entry,
            location_id=location_id,
            logger=_LOGGER,
            runtime_data_getter=_runtime_data,
            coordinator=coordinator,
            enable_websocket=bool(enable_websocket),
            poll_when_websocket=poll_when_websocket,
            websocket_factory=HomelyWebSocket,
            apply_websocket_event=lambda cached_data, event_data: apply_websocket_event_to_data(
                cached_data,
                event_data,
            ),
            ctx=_ctx,
            json_debug=_json_debug,
            redact_for_debug_logging=_redact_for_debug_logging,
        )
    )
    _LOGGER.debug(
        "WebSocket initialization scheduled entry_id=%s location_id=%s",
        entry_id,
        location_id,
    )

    try:
        internet_unsub = register_internet_available_listener(
            hass=hass,
            entry=entry,
            location_id=location_id,
            logger=_LOGGER,
            runtime_data_getter=_runtime_data,
        )
        if internet_unsub is None:
            raise RuntimeError("listener registration unavailable")
        entry.async_on_unload(internet_unsub)
    except Exception:
        _LOGGER.debug(
            "Could not register internet_available listener entry_id=%s location_id=%s",
            entry_id,
            location_id,
        )
    try:
        watchdog_unsub = register_websocket_health_watchdog(
            hass=hass,
            entry=entry,
            location_id=location_id,
            logger=_LOGGER,
            runtime_data_getter=_runtime_data,
            coordinator=coordinator,
            ctx=_ctx,
        )
        if watchdog_unsub is None:
            raise RuntimeError("listener registration unavailable")
        entry.async_on_unload(watchdog_unsub)
    except Exception:
        _LOGGER.debug(
            "Could not register websocket watchdog entry_id=%s location_id=%s",
            entry_id,
            location_id,
        )

    # The initial REST response (or cache fallback) is already the first data
    # snapshot. Seed it directly instead of polling /home a second time through
    # async_config_entry_first_refresh().
    coordinator.async_set_updated_data(data)
    entry.async_on_unload(coordinator.async_add_listener(_save_on_successful_update))
    if seed_without_poll:
        device_count = (
            len(data["devices"])
            if isinstance(data, dict) and isinstance(data.get("devices"), list)
            else 0
        )
        _LOGGER.debug(
            "Seeded coordinator without initial poll entry_id=%s location_id=%s "
            "device_count=%s",
            entry_id,
            location_id,
            device_count,
        )
    _reenable_integration_disabled_entities(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _schedule_pending_location_imports(hass, entry)
    @callback
    def _handle_device_registry_updated(
        event: Event[dr.EventDeviceRegistryUpdatedData],
    ) -> None:
        if event.data.get("action") != "remove":
            return
        current_runtime = _runtime_data()
        if current_runtime is not None:
            _sync_missing_devices_issue(current_runtime.last_data)

    try:
        entry.async_on_unload(
            hass.bus.async_listen(
                dr.EVENT_DEVICE_REGISTRY_UPDATED,
                _handle_device_registry_updated,
            )
        )
    except Exception:
        _LOGGER.debug(
            "Could not register device-registry listener entry_id=%s location_id=%s",
            entry_id,
            location_id,
        )

    if initial_fetch_deferred:
        entry.async_create_background_task(
            hass,
            coordinator.async_refresh(),
            "homely startup API synchronization",
        )

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.debug(
        "Homely Alarm integration setup completed entry_id=%s location_id=%s",
        entry_id,
        location_id,
    )
    return True


async def async_remove_entry(
    hass: HomeAssistant, entry: HomelyConfigEntry
) -> None:
    """Clean up repairs when a config entry is removed."""
    async_delete_missing_devices_issue(hass, entry)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Allow manual deletion of stale Homely devices from the device registry."""
    has_homely_identifier = False
    entry_data = getattr(entry, "runtime_data", None)
    has_snapshot, active_device_ids = _tracked_api_device_ids(entry_data)

    for identifier_domain, identifier in device_entry.identifiers:
        if identifier_domain != DOMAIN:
            continue

        has_homely_identifier = True
        identifier_str = str(identifier)

        # Keep location-level virtual device protected.
        if identifier_str.startswith("location_"):
            _LOGGER.debug(
                "Device removal denied for location device entry_id=%s device_id=%s",
                entry.entry_id,
                identifier_str,
            )
            return False

        if has_snapshot and identifier_str in active_device_ids:
            _LOGGER.debug(
                "Device removal denied for active API device entry_id=%s device_id=%s",
                entry.entry_id,
                identifier_str,
            )
            return False

    if not has_homely_identifier:
        return False

    _LOGGER.debug(
        "Allowing manual removal of stale Homely device entry_id=%s ha_device_id=%s",
        entry.entry_id,
        device_entry.id,
    )
    return True


async def async_reload_entry(hass: HomeAssistant, entry: HomelyConfigEntry) -> None:
    """Reload config entry when options change."""
    _LOGGER.debug("Options changed; reloading entry_id=%s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HomelyConfigEntry) -> bool:
    """Unload a config entry."""
    entry_data = getattr(entry, "runtime_data", None)
    location_id = entry_data.location_id if entry_data is not None else None
    _LOGGER.debug(
        "Unloading Homely Alarm entry entry_id=%s location_id=%s",
        entry.entry_id,
        location_id,
    )
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        retry_unsub = (
            entry_data.api_retry_unsub if entry_data is not None else None
        )
        if entry_data is not None and callable(retry_unsub):
            retry_unsub()
            entry_data.api_retry_unsub = None
        ws = entry_data.websocket if entry_data is not None else None
        if ws:
            disconnect = getattr(ws, "disconnect", None)
            if not callable(disconnect):
                _LOGGER.debug(
                    "WebSocket object has no disconnect method entry_id=%s location_id=%s",
                    entry.entry_id,
                    location_id,
                )
                disconnect = None

            if disconnect is not None:
                try:
                    await disconnect()
                    _LOGGER.debug(
                        "WebSocket disconnected entry_id=%s location_id=%s",
                        entry.entry_id,
                        location_id,
                    )
                except Exception as err:
                    _LOGGER.warning(
                        "Error disconnecting websocket entry_id=%s location_id=%s: %s",
                        entry.entry_id,
                        location_id,
                        err,
                    )

        setattr(entry, "runtime_data", None)
        _LOGGER.debug(
            "Homely Alarm integration unloaded entry_id=%s location_id=%s",
            entry.entry_id,
            location_id,
        )
    return unload_ok
