"""Tests for config entry setup and cleanup."""

from __future__ import annotations

import logging
import time
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.homely import api
from custom_components.homely import (
    _cached_data_grace_seconds,
    _device_id_snapshot,
    _log_startup_device_payloads,
    _pending_import_locations,
    _redact_for_debug_logging,
    _schedule_pending_location_imports,
    async_reload_entry,
    async_migrate_entry,
    async_remove_config_entry_device,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.homely.const import (
    CONF_ENABLE_WEBSOCKET,
    CONF_HOME_ID,
    CONF_LOCATION_ID,
    CONF_PASSWORD,
    CONF_PENDING_IMPORT_LOCATIONS,
    CONF_POLL_WHEN_WEBSOCKET,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)
from custom_components.homely.models import HomelyRuntimeData
from tests.common import LOCATION_ID, SECOND_LOCATION_ID, build_config_entry


class _FakeHomelyWebSocket:
    """Minimal websocket stub for integration setup tests."""

    instances: list["_FakeHomelyWebSocket"] = []
    connect_result = True
    connect_error: Exception | None = None
    initial_status = "Not initialized"
    initial_reason = None

    def __init__(
        self,
        location_id,
        token,
        on_data_update,
        status_update_callback=None,
        entry_id=None,
    ) -> None:
        self.entry_id = entry_id
        self.location_id = location_id
        self.token = token
        self.on_data_update = on_data_update
        self.status_update_callback = status_update_callback
        self.status = self.initial_status
        self.status_reason = self.initial_reason
        self.connected = False
        self.update_token_calls: list[str] = []
        self.sync_token_calls: list[str] = []
        self.request_reconnect_calls: list[str] = []
        self.disconnect = AsyncMock()
        type(self).instances.append(self)

    @classmethod
    def reset(cls) -> None:
        """Reset class state between tests."""
        cls.instances = []
        cls.connect_result = True
        cls.connect_error = None
        cls.initial_status = "Not initialized"
        cls.initial_reason = None

    async def connect(self) -> bool:
        """Return configured connection result."""
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = self.connect_result
        if self.connected:
            self.status = "Connected"
            self.status_reason = None
        return self.connect_result

    def is_connected(self) -> bool:
        """Return connection state."""
        return self.connected

    def update_token(self, token: str) -> None:
        """Track token refreshes."""
        self.update_token_calls.append(token)
        self.token = token

    def sync_token(self, token: str) -> str:
        """Track token sync calls and mirror SDK reconnect semantics."""
        self.sync_token_calls.append(token)
        self.token = token
        return "no_reconnect" if self.connected else "reconnect_if_disconnected"

    def request_reconnect(self, reason: str = "manual request") -> None:
        """Track reconnect requests."""
        self.request_reconnect_calls.append(reason)


def test_debug_redaction_and_device_snapshot_cover_defensive_branches():
    """Small helper functions should handle sparse payloads predictably."""
    assert _redact_for_debug_logging([{"name": "Living room"}]) == [
        {"name": "**REDACTED**"}
    ]
    assert _redact_for_debug_logging(
        [
            {
                "gatewayId": "gw-1",
                "rootLocationId": "loc-1",
                "modelId": "model-1",
                "userId": "user-1",
            }
        ]
    ) == [
        {
            "gatewayId": "**REDACTED**",
            "rootLocationId": "**REDACTED**",
            "modelId": "**REDACTED**",
            "userId": "**REDACTED**",
        }
    ]
    assert _device_id_snapshot(None) == set()
    assert _device_id_snapshot({"devices": {}}) == set()


def test_cached_data_grace_seconds_stays_short_when_websocket_is_down():
    """Cached polling data should expire quickly without websocket connectivity."""
    assert _cached_data_grace_seconds(30) == 60
    assert _cached_data_grace_seconds(120) == 120
    assert _cached_data_grace_seconds(600) == 300


async def _setup_loaded_entry(
    hass,
    config_entry,
    token_response,
    location_response,
    location_data,
    updated_location_data,
    extra_patches=(),
):
    """Helper to load a Homely config entry with mocked API responses."""
    config_entry.add_to_hass(hass)
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "custom_components.homely.fetch_token_with_reason",
                AsyncMock(return_value=(token_response, None)),
            )
        )
        stack.enter_context(
            patch(
                "custom_components.homely.get_location_id",
                AsyncMock(return_value=location_response),
            )
        )
        stack.enter_context(
            patch(
                "custom_components.homely.get_data",
                AsyncMock(return_value=location_data),
            )
        )
        stack.enter_context(
            patch(
                "custom_components.homely.get_data_with_status",
                AsyncMock(return_value=(updated_location_data, 200)),
            )
        )
        stack.enter_context(
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                AsyncMock(return_value=None),
            )
        )
        for extra_patch in extra_patches:
            stack.enter_context(extra_patch)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()


async def test_async_setup_entry_loads_runtime_data(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Config entry setup should populate runtime_data and normalize location id."""
    config_entry = build_config_entry(
        data_overrides={CONF_LOCATION_ID: None},
        unique_id=None,
    )
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.unique_id == LOCATION_ID
    assert config_entry.data[CONF_LOCATION_ID] == LOCATION_ID

    runtime_data = config_entry.runtime_data
    assert runtime_data.location_id == LOCATION_ID
    assert runtime_data.last_data["name"] == "JF23"
    assert runtime_data.coordinator.data["alarmState"] == "ARMED_AWAY"
    assert runtime_data.last_successful_poll_at is not None


async def test_async_setup_entry_reenables_legacy_integration_disabled_error_code_sensor(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Legacy integration-disabled Yale error code sensors should be restored."""
    config_entry = build_config_entry()
    config_entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    entity_entry = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "6c120e85-e8d5-49ac-abc0-baa29f9243b7_error_code",
        suggested_object_id="yale_doorman_feilkode",
        config_entry=config_entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "custom_components.homely.fetch_token_with_reason",
                AsyncMock(return_value=(token_response, None)),
            )
        )
        stack.enter_context(
            patch(
                "custom_components.homely.get_location_id",
                AsyncMock(return_value=location_response),
            )
        )
        stack.enter_context(
            patch(
                "custom_components.homely.get_data",
                AsyncMock(return_value=location_data),
            )
        )
        stack.enter_context(
            patch(
                "custom_components.homely.get_data_with_status",
                AsyncMock(return_value=(updated_location_data, 200)),
            )
        )
        stack.enter_context(
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                AsyncMock(return_value=None),
            )
        )
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    refreshed = entity_registry.async_get(entity_entry.entity_id)
    assert refreshed is not None
    assert refreshed.disabled_by is None


async def test_async_setup_entry_keeps_user_disabled_error_code_sensor_disabled(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """User-disabled Yale error code sensors should stay disabled."""
    config_entry = build_config_entry()
    config_entry.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    entity_entry = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "6c120e85-e8d5-49ac-abc0-baa29f9243b7_error_code",
        suggested_object_id="yale_doorman_feilkode",
        config_entry=config_entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "custom_components.homely.fetch_token_with_reason",
                AsyncMock(return_value=(token_response, None)),
            )
        )
        stack.enter_context(
            patch(
                "custom_components.homely.get_location_id",
                AsyncMock(return_value=location_response),
            )
        )
        stack.enter_context(
            patch(
                "custom_components.homely.get_data",
                AsyncMock(return_value=location_data),
            )
        )
        stack.enter_context(
            patch(
                "custom_components.homely.get_data_with_status",
                AsyncMock(return_value=(updated_location_data, 200)),
            )
        )
        stack.enter_context(
            patch.object(
                hass.config_entries,
                "async_forward_entry_setups",
                AsyncMock(return_value=None),
            )
        )
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    refreshed = entity_registry.async_get(entity_entry.entity_id)
    assert refreshed is not None
    assert refreshed.disabled_by is er.RegistryEntryDisabler.USER


def test_pending_import_locations_ignores_invalid_items():
    """Pending import metadata should be sanitized before use."""
    entry = build_config_entry(
        data_overrides={
            CONF_PENDING_IMPORT_LOCATIONS: [
                {
                    CONF_LOCATION_ID: SECOND_LOCATION_ID,
                    "title": "Cabin",
                },
                {"title": "Missing id"},
                "bad-item",
            ]
        }
    )

    assert _pending_import_locations(entry) == [
        {
            CONF_LOCATION_ID: SECOND_LOCATION_ID,
            "title": "Cabin",
        }
    ]


async def test_schedule_pending_location_imports_starts_import_flows_and_clears_data(
    hass,
):
    """Setup helper should queue missing locations and remove internal metadata."""
    entry = build_config_entry(
        data_overrides={
            CONF_PENDING_IMPORT_LOCATIONS: [
                {
                    CONF_LOCATION_ID: SECOND_LOCATION_ID,
                    "title": "Cabin",
                }
            ]
        }
    )
    entry.add_to_hass(hass)

    async_init = AsyncMock(return_value={"type": "create_entry"})
    create_task = MagicMock(side_effect=lambda coro: coro.close())

    with (
        patch.object(hass.config_entries.flow, "async_init", async_init),
        patch.object(hass, "async_create_task", create_task),
    ):
        _schedule_pending_location_imports(hass, entry)

    async_init.assert_called_once_with(
        DOMAIN,
        context={"source": "import"},
        data={
            CONF_USERNAME: entry.data[CONF_USERNAME],
            CONF_PASSWORD: entry.data[CONF_PASSWORD],
            CONF_LOCATION_ID: SECOND_LOCATION_ID,
            "title": "Cabin",
        },
    )
    create_task.assert_called_once()
    assert CONF_PENDING_IMPORT_LOCATIONS not in entry.data


async def test_schedule_pending_location_imports_skips_locations_already_added(
    hass,
):
    """Setup helper should not queue duplicates when another entry exists."""
    entry = build_config_entry(
        data_overrides={
            CONF_PENDING_IMPORT_LOCATIONS: [
                {
                    CONF_LOCATION_ID: SECOND_LOCATION_ID,
                    "title": "Cabin",
                }
            ]
        }
    )
    entry.add_to_hass(hass)
    build_config_entry(
        data_overrides={CONF_LOCATION_ID: SECOND_LOCATION_ID},
        unique_id=SECOND_LOCATION_ID,
    ).add_to_hass(hass)

    async_init = AsyncMock()
    create_task = MagicMock(side_effect=lambda coro: coro.close())

    with (
        patch.object(hass.config_entries.flow, "async_init", async_init),
        patch.object(hass, "async_create_task", create_task),
    ):
        _schedule_pending_location_imports(hass, entry)

    async_init.assert_not_called()
    create_task.assert_not_called()
    assert CONF_PENDING_IMPORT_LOCATIONS not in entry.data


async def test_async_setup_entry_invalid_auth_raises(hass):
    """Invalid credentials during setup should trigger reauthentication."""
    config_entry = build_config_entry()
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.homely.fetch_token_with_reason",
        AsyncMock(return_value=(None, "invalid_auth")),
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is False

    assert config_entry.state is not ConfigEntryState.LOADED


async def test_async_setup_entry_missing_credentials_raises_auth_failed(hass):
    """Missing stored credentials should fail immediately."""
    config_entry = build_config_entry(
        data_overrides={"username": None, "password": None},
    )

    try:
        await async_setup_entry(hass, config_entry)
    except ConfigEntryAuthFailed:
        pass
    else:
        raise AssertionError("Expected ConfigEntryAuthFailed")


async def test_async_setup_entry_missing_locations_raises_not_ready(
    hass, token_response
):
    """Missing location data should mark the entry as not ready."""
    config_entry = build_config_entry()
    config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.get_location_id",
            AsyncMock(return_value=None),
        ),
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is False

    assert config_entry.state is not ConfigEntryState.LOADED


async def test_async_setup_entry_missing_token_fields_raise_not_ready(hass):
    """Incomplete token payloads should fail setup cleanly."""
    config_entry = build_config_entry()

    with patch(
        "custom_components.homely.fetch_token_with_reason",
        AsyncMock(return_value=({"access_token": "access-only"}, None)),
    ):
        try:
            await async_setup_entry(hass, config_entry)
        except ConfigEntryNotReady:
            pass
        else:
            raise AssertionError("Expected ConfigEntryNotReady")


async def test_async_setup_entry_invalid_expires_in_raises_not_ready(hass):
    """Non-numeric expires_in should be rejected."""
    config_entry = build_config_entry()

    with patch(
        "custom_components.homely.fetch_token_with_reason",
        AsyncMock(
            return_value=(
                {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": "bad",
                },
                None,
            )
        ),
    ):
        try:
            await async_setup_entry(hass, config_entry)
        except ConfigEntryNotReady:
            pass
        else:
            raise AssertionError("Expected ConfigEntryNotReady")


async def test_async_setup_entry_login_connection_failure_raises_not_ready(hass):
    """Non-auth login failures should surface as not-ready."""
    config_entry = build_config_entry()

    with patch(
        "custom_components.homely.fetch_token_with_reason",
        AsyncMock(return_value=(None, "cannot_connect")),
    ):
        try:
            await async_setup_entry(hass, config_entry)
        except ConfigEntryNotReady:
            pass
        else:
            raise AssertionError("Expected ConfigEntryNotReady")


async def test_async_setup_entry_missing_expires_in_raises_not_ready(hass):
    """Token payloads without expires_in should fail setup."""
    config_entry = build_config_entry()

    with patch(
        "custom_components.homely.fetch_token_with_reason",
        AsyncMock(
            return_value=(
                {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                },
                None,
            )
        ),
    ):
        try:
            await async_setup_entry(hass, config_entry)
        except ConfigEntryNotReady:
            pass
        else:
            raise AssertionError("Expected ConfigEntryNotReady")


async def test_async_setup_entry_invalid_home_mapping_raises_not_ready(
    hass,
    token_response,
    location_response,
):
    """Legacy entries with invalid home ids should fail setup."""
    config_entry = build_config_entry(
        data_overrides={CONF_LOCATION_ID: None},
        options={CONF_HOME_ID: 99},
        unique_id=None,
    )

    with (
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.get_location_id",
            AsyncMock(return_value=location_response),
        ),
    ):
        try:
            await async_setup_entry(hass, config_entry)
        except ConfigEntryNotReady:
            pass
        else:
            raise AssertionError("Expected ConfigEntryNotReady")


async def test_async_setup_entry_missing_configured_location_raises_not_ready(
    hass,
    token_response,
):
    """Missing configured locations should raise not-ready."""
    config_entry = build_config_entry()

    with (
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.get_location_id",
            AsyncMock(return_value=[{"locationId": "other-location", "name": "Other"}]),
        )
    ):
        try:
            await async_setup_entry(hass, config_entry)
        except ConfigEntryNotReady:
            pass
        else:
            raise AssertionError("Expected ConfigEntryNotReady")


async def test_async_setup_entry_missing_location_payload_raises_not_ready(
    hass,
    token_response,
    location_response,
):
    """Setup should fail if the first location fetch returns no data."""
    config_entry = build_config_entry()

    with (
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.get_location_id",
            AsyncMock(return_value=location_response),
        ),
        patch(
            "custom_components.homely.get_data",
            AsyncMock(return_value=None),
        ),
    ):
        try:
            await async_setup_entry(hass, config_entry)
        except ConfigEntryNotReady:
            pass
        else:
            raise AssertionError("Expected ConfigEntryNotReady")


async def test_async_remove_config_entry_device_only_allows_stale_devices(
    hass, location_data
):
    """Only stale Homely devices should be removable from the device registry."""
    config_entry = build_config_entry()
    config_entry.runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data),
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )

    location_device = SimpleNamespace(
        identifiers={(DOMAIN, f"location_{LOCATION_ID}")},
        id="location-device",
    )
    active_device = SimpleNamespace(
        identifiers={(DOMAIN, location_data["devices"][0]["id"])},
        id="active-device",
    )
    stale_device = SimpleNamespace(
        identifiers={(DOMAIN, "stale-device-id")},
        id="stale-device",
    )
    foreign_device = SimpleNamespace(
        identifiers={("other", "device")},
        id="foreign-device",
    )

    assert (
        await async_remove_config_entry_device(hass, config_entry, location_device)
        is False
    )
    assert (
        await async_remove_config_entry_device(hass, config_entry, active_device)
        is False
    )
    assert (
        await async_remove_config_entry_device(hass, config_entry, stale_device) is True
    )
    assert (
        await async_remove_config_entry_device(hass, config_entry, foreign_device)
        is False
    )


async def test_async_unload_entry_disconnects_websocket_and_cleans_up(
    hass, location_data
):
    """Unload should disconnect websocket clients and remove runtime state."""
    config_entry = build_config_entry()
    fake_websocket = AsyncMock()
    config_entry.runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data),
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
        websocket=fake_websocket,
    )

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        AsyncMock(return_value=True),
    ):
        assert await async_unload_entry(hass, config_entry) is True

    fake_websocket.disconnect.assert_awaited_once()
    assert config_entry.runtime_data is None


async def test_async_unload_entry_returns_false_without_cleanup(hass, location_data):
    """Failed platform unload should keep runtime data intact."""
    config_entry = build_config_entry()
    fake_websocket = AsyncMock()
    config_entry.runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data),
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
        websocket=fake_websocket,
    )

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        AsyncMock(return_value=False),
    ):
        assert await async_unload_entry(hass, config_entry) is False

    fake_websocket.disconnect.assert_not_awaited()
    assert config_entry.runtime_data is not None


async def test_async_migrate_entry_moves_options_out_of_data(hass):
    """Legacy entries should migrate option-like values into entry.options."""
    config_entry = build_config_entry(
        data_overrides={
            CONF_HOME_ID: 1,
            CONF_SCAN_INTERVAL: 30,
            CONF_ENABLE_WEBSOCKET: True,
        },
        options={},
        version=1,
        include_default_options=False,
    )
    config_entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, config_entry) is True
    assert config_entry.version == 2
    assert config_entry.data[CONF_LOCATION_ID] == LOCATION_ID
    assert CONF_HOME_ID not in config_entry.data
    assert config_entry.options[CONF_HOME_ID] == 1
    assert config_entry.options[CONF_SCAN_INTERVAL] == 30
    assert config_entry.options[CONF_ENABLE_WEBSOCKET] is True


async def test_async_migrate_entry_sets_unique_id_from_location_when_missing(hass):
    """Migration should promote the location id to unique_id when needed."""
    config_entry = build_config_entry(
        unique_id=None,
        version=1,
        include_default_options=False,
    )
    config_entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, config_entry) is True
    assert config_entry.unique_id == LOCATION_ID


def test_startup_debug_logging_redacts_private_device_fields(location_data, caplog):
    """Startup payload logging should redact identifiers and human labels."""
    with caplog.at_level(logging.DEBUG):
        _log_startup_device_payloads(location_data, "entry-1", LOCATION_ID)

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "Bevegelse stue" not in joined
    assert "Floor 2 - Living room" not in joined
    assert "0015BC001A10CD0A" not in joined
    assert "**REDACTED**" in joined


async def test_coordinator_update_method_skips_polling_when_websocket_connected(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Connected websocket should short-circuit polling when polling is disabled."""
    config_entry = build_config_entry(
        options={
            CONF_ENABLE_WEBSOCKET: True,
            CONF_POLL_WHEN_WEBSOCKET: False,
        }
    )
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.websocket = SimpleNamespace(
        is_connected=lambda: True,
        status="Connected",
        status_reason="ready",
        update_token=lambda token: None,
    )

    with patch(
        "custom_components.homely.get_data_with_status", AsyncMock()
    ) as get_data_with_status:
        result = await runtime_data.coordinator.update_method()

    assert result == runtime_data.last_data
    get_data_with_status.assert_not_awaited()


async def test_coordinator_update_method_forced_refresh_bypasses_websocket_skip(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """A forced API refresh should bypass websocket polling suppression once."""
    config_entry = build_config_entry(
        options={
            CONF_ENABLE_WEBSOCKET: True,
            CONF_POLL_WHEN_WEBSOCKET: False,
        }
    )
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.websocket = SimpleNamespace(
        is_connected=lambda: True,
        status="Connected",
        status_reason="ready",
        update_token=lambda token: None,
    )
    runtime_data.force_api_refresh_once = True

    with patch(
        "custom_components.homely.get_data_with_status",
        AsyncMock(return_value=(updated_location_data, 200)),
    ) as get_data_with_status:
        result = await runtime_data.coordinator.update_method()

    assert result["alarmState"] == "ARMED_AWAY"
    assert runtime_data.force_api_refresh_once is False
    get_data_with_status.assert_awaited_once()


async def test_coordinator_update_method_requests_websocket_reconnect_when_disconnected(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Polling should nudge websocket reconnects when the socket looks disconnected."""
    config_entry = build_config_entry(
        options={
            CONF_ENABLE_WEBSOCKET: True,
            CONF_POLL_WHEN_WEBSOCKET: False,
        }
    )
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    websocket = SimpleNamespace(
        is_connected=lambda: False,
        status="Disconnected",
        status_reason="network error: boom",
        request_reconnect=MagicMock(),
        update_token=lambda token: None,
    )
    runtime_data.websocket = websocket

    with patch(
        "custom_components.homely.get_data_with_status",
        AsyncMock(return_value=(updated_location_data, 200)),
    ) as get_data_with_status:
        result = await runtime_data.coordinator.update_method()

    assert result["alarmState"] == "ARMED_AWAY"
    websocket.request_reconnect.assert_called_once_with(
        "poll detected disconnected websocket"
    )
    get_data_with_status.assert_awaited_once()


async def test_coordinator_update_method_requests_reconnect_for_stale_connecting_websocket(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Polling should still nudge reconnects when status is stale Connecting."""
    config_entry = build_config_entry(
        options={
            CONF_ENABLE_WEBSOCKET: True,
            CONF_POLL_WHEN_WEBSOCKET: False,
        }
    )
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    websocket = SimpleNamespace(
        is_connected=lambda: False,
        status="Connecting",
        status_reason="stuck connect",
        request_reconnect=MagicMock(),
        update_token=lambda token: None,
    )
    runtime_data.websocket = websocket

    with patch(
        "custom_components.homely.get_data_with_status",
        AsyncMock(return_value=(updated_location_data, 200)),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result["alarmState"] == "ARMED_AWAY"
    websocket.request_reconnect.assert_called_once_with(
        "poll detected disconnected websocket"
    )


async def test_coordinator_update_method_does_not_reconnect_live_engineio_websocket(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Polling should not reconnect a websocket with a live Engine.IO transport."""
    config_entry = build_config_entry(
        options={
            CONF_ENABLE_WEBSOCKET: True,
            CONF_POLL_WHEN_WEBSOCKET: False,
        }
    )
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    websocket = SimpleNamespace(
        is_connected=lambda: False,
        status="Connected",
        status_reason="event received",
        socket=SimpleNamespace(
            connected=False,
            eio=SimpleNamespace(state="connected"),
        ),
        request_reconnect=MagicMock(),
        update_token=MagicMock(),
    )
    runtime_data.websocket = websocket

    result = await runtime_data.coordinator.update_method()

    assert result == runtime_data.last_data
    websocket.request_reconnect.assert_not_called()


async def test_coordinator_update_method_swallow_websocket_reconnect_request_errors(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Polling should keep working even if websocket reconnect nudges fail."""
    config_entry = build_config_entry(
        options={
            CONF_ENABLE_WEBSOCKET: True,
            CONF_POLL_WHEN_WEBSOCKET: False,
        }
    )
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.websocket = SimpleNamespace(
        is_connected=lambda: False,
        status="Disconnected",
        status_reason="network error: boom",
        request_reconnect=MagicMock(side_effect=RuntimeError("boom")),
        update_token=lambda token: None,
    )

    with patch(
        "custom_components.homely.get_data_with_status",
        AsyncMock(return_value=(updated_location_data, 200)),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result["alarmState"] == "ARMED_AWAY"


async def test_async_setup_entry_registers_periodic_refresh_when_websocket_polling_is_disabled(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """A 6-hour fallback refresh should be registered for websocket-backed entries."""
    tracked_intervals: list[timedelta] = []

    def _capture_interval(_hass, _action, interval):
        tracked_intervals.append(interval)
        return lambda: None

    config_entry = build_config_entry(
        options={
            CONF_ENABLE_WEBSOCKET: True,
            CONF_POLL_WHEN_WEBSOCKET: False,
        }
    )

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch("custom_components.homely.HomelyWebSocket", _FakeHomelyWebSocket),
            patch(
                "custom_components.homely.websocket_runtime.async_track_time_interval",
                side_effect=_capture_interval,
            ),
        ),
    )

    assert tracked_intervals == [timedelta(hours=6)]


async def test_async_setup_entry_periodic_websocket_refresh_forces_api_poll(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Periodic websocket-backed refreshes should force an API poll once."""
    periodic_callbacks = []

    def _capture_interval(_hass, action, _interval):
        periodic_callbacks.append(action)
        return lambda: None

    _FakeHomelyWebSocket.reset()
    config_entry = build_config_entry(
        options={
            CONF_ENABLE_WEBSOCKET: True,
            CONF_POLL_WHEN_WEBSOCKET: False,
        }
    )

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch("custom_components.homely.HomelyWebSocket", _FakeHomelyWebSocket),
            patch(
                "custom_components.homely.websocket_runtime.async_track_time_interval",
                side_effect=_capture_interval,
            ),
        ),
    )

    runtime_data = config_entry.runtime_data
    assert len(periodic_callbacks) == 1
    assert runtime_data.websocket is _FakeHomelyWebSocket.instances[0]

    with patch(
        "custom_components.homely.get_data_with_status",
        AsyncMock(return_value=(updated_location_data, 200)),
    ) as get_data_with_status:
        periodic_callbacks[0](None)
        await hass.async_block_till_done()

    get_data_with_status.assert_awaited_once()
    assert runtime_data.force_api_refresh_once is False


async def test_coordinator_update_method_uses_cached_data_on_transient_error(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Transient HTTP errors should keep cached data instead of failing hard."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data

    with patch(
        "custom_components.homely.get_data_with_status",
        AsyncMock(return_value=(None, 503)),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result == runtime_data.last_data


async def test_coordinator_update_method_logs_unavailable_once_and_back_once(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
    caplog,
):
    """Transient API failures should log once until the API is reachable again."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data

    with caplog.at_level(logging.INFO):
        with patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(return_value=(None, 503)),
        ):
            first = await runtime_data.coordinator.update_method()
            second = await runtime_data.coordinator.update_method()

        with patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(return_value=(updated_location_data, 200)),
        ):
            recovered = await runtime_data.coordinator.update_method()

    assert first == runtime_data.last_data
    assert second == runtime_data.last_data
    assert recovered["alarmState"] == "ARMED_AWAY"
    assert runtime_data.api_available is True

    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO
    ]
    assert (
        sum(
            "Polling API request failed with transient status=503" in message
            for message in info_messages
        )
        == 1
    )
    assert (
        sum("Homely API is reachable again" in message for message in info_messages)
        == 1
    )


async def test_websocket_debug_logging_redacts_event_payloads(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
    caplog,
):
    """Websocket debug logging should not leak raw names or device identifiers."""
    _FakeHomelyWebSocket.reset()
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch("custom_components.homely.HomelyWebSocket", _FakeHomelyWebSocket),
        ),
    )

    ws = _FakeHomelyWebSocket.instances[0]
    event = {
        "type": "device-state-changed",
        "data": {
            "deviceId": location_data["devices"][0]["id"],
            "name": location_data["devices"][0]["name"],
            "gatewayId": "gw-1",
            "rootLocationId": LOCATION_ID,
            "modelId": "model-1",
            "change": {
                "feature": "battery",
                "stateName": "low",
                "value": True,
            },
        },
    }

    with caplog.at_level(logging.DEBUG):
        ws.on_data_update(event)

    websocket_messages = [
        record.getMessage()
        for record in caplog.records
        if "WebSocket event payload" in record.getMessage()
        or "Applied websocket device update" in record.getMessage()
    ]
    joined = "\n".join(websocket_messages)
    assert location_data["devices"][0]["id"] not in joined
    assert location_data["devices"][0]["name"] not in joined
    assert LOCATION_ID not in joined
    assert "gw-1" not in joined
    assert "model-1" not in joined
    assert "**REDACTED**" in joined


def test_debug_redaction_is_case_insensitive():
    """Debug redaction should catch known identifier keys regardless of casing."""
    payload = {
        "GatewayID": "gw-1",
        "RootLocationID": LOCATION_ID,
        "ModelID": "model-1",
        "nested": {"UserID": "user-1"},
    }

    assert _redact_for_debug_logging(payload) == {
        "GatewayID": "**REDACTED**",
        "RootLocationID": "**REDACTED**",
        "ModelID": "**REDACTED**",
        "nested": {"UserID": "**REDACTED**"},
    }


async def test_coordinator_update_method_reload_on_new_device_topology(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Device additions or removals should trigger a controlled entry reload."""
    config_entry = build_config_entry()
    changed_data = deepcopy(updated_location_data)
    changed_data["devices"].append(
        {
            "id": "new-device-id",
            "name": "Ny sensor",
            "modelName": "Alarm Motion Sensor 2",
            "online": True,
            "features": {},
        }
    )
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data

    with patch.object(
        hass.config_entries,
        "async_reload",
        AsyncMock(return_value=True),
    ) as async_reload:
        with patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(return_value=(changed_data, 200)),
        ):
            result = await runtime_data.coordinator.update_method()
            await hass.async_block_till_done()

    assert result["devices"][-1]["id"] == "new-device-id"
    assert "new-device-id" in runtime_data.tracked_device_ids
    async_reload.assert_awaited_once_with(config_entry.entry_id)
    assert runtime_data.topology_reload_pending is False


async def test_coordinator_update_method_does_not_double_schedule_topology_reload(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Repeated topology changes while a reload is pending should not schedule more reloads."""
    config_entry = build_config_entry()
    changed_data = deepcopy(updated_location_data)
    changed_data["devices"].append(
        {
            "id": "new-device-id",
            "name": "Ny sensor",
            "modelName": "Alarm Motion Sensor 2",
            "online": True,
            "features": {},
        }
    )
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.topology_reload_pending = True

    with patch.object(
        hass.config_entries,
        "async_reload",
        AsyncMock(return_value=True),
    ) as async_reload:
        with patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(return_value=(changed_data, 200)),
        ):
            await runtime_data.coordinator.update_method()
            await hass.async_block_till_done()

    assert "new-device-id" in runtime_data.tracked_device_ids
    async_reload.assert_not_awaited()


async def test_coordinator_update_method_refresh_invalid_auth_uses_cache(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Runtime invalid_auth responses should keep cached data instead of reauth."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0

    with (
        patch(
            "custom_components.homely.fetch_refresh_token", AsyncMock(return_value=None)
        ),
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(return_value=(None, "invalid_auth")),
        ),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result == runtime_data.last_data


async def test_coordinator_update_method_refresh_invalid_auth_with_stale_cache_raises_update_failed(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Runtime invalid_auth should not trigger reauth even when cache is stale."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0
    runtime_data.websocket = None
    runtime_data.last_data_activity_monotonic = time.monotonic() - 301

    with (
        patch(
            "custom_components.homely.fetch_refresh_token", AsyncMock(return_value=None)
        ),
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(return_value=(None, "invalid_auth")),
        ),
    ):
        try:
            await runtime_data.coordinator.update_method()
        except UpdateFailed as err:
            assert "automatic reauthentication is disabled" in str(err)
        else:
            raise AssertionError("Expected UpdateFailed")


async def test_coordinator_update_method_refreshes_via_full_login_and_updates_websocket(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Fallback full login should refresh runtime tokens and websocket token."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0
    websocket = SimpleNamespace(
        is_connected=lambda: False,
        status="Disconnected",
        status_reason="stale token",
        sync_token=MagicMock(return_value="reconnect_if_disconnected"),
    )
    runtime_data.websocket = websocket
    new_tokens = {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "expires_in": 3600,
    }

    with (
        patch(
            "custom_components.homely.fetch_refresh_token", AsyncMock(return_value=None)
        ),
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(return_value=(new_tokens, None)),
        ),
        patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(return_value=(updated_location_data, 200)),
        ),
    ):
        previous_poll_at = runtime_data.last_successful_poll_at
        result = await runtime_data.coordinator.update_method()

    assert result["alarmState"] == "ARMED_AWAY"
    assert runtime_data.access_token == "new-access-token"
    assert runtime_data.refresh_token == "new-refresh-token"
    assert runtime_data.last_successful_poll_at is not None
    assert (
        previous_poll_at is None
        or runtime_data.last_successful_poll_at >= previous_poll_at
    )
    websocket.sync_token.assert_called_once_with("new-access-token")


async def test_coordinator_update_method_refresh_fallback_non_auth_failure_uses_cache(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
    caplog,
):
    """Fallback login failures should keep cached data during transient outages."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0
    runtime_data.websocket = SimpleNamespace(
        is_connected=lambda: True,
        status="Connected",
        status_reason="ready",
        update_token=MagicMock(),
        disconnect=AsyncMock(),
    )
    runtime_data.last_data_activity_monotonic = time.monotonic() - 7200

    with caplog.at_level(logging.DEBUG):
        with (
            patch(
                "custom_components.homely.fetch_refresh_token",
                AsyncMock(return_value=None),
            ),
            patch(
                "custom_components.homely.fetch_token_with_reason",
                AsyncMock(return_value=(None, "cannot_connect")),
            ),
        ):
            result = await runtime_data.coordinator.update_method()

    assert result == runtime_data.last_data
    assert runtime_data.api_available is False
    assert runtime_data.ws_status == "Connected"
    assert runtime_data.ws_status_reason == "ready"
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "Fallback full login returned no usable token" in joined
    assert "kind=homely_unavailable" in joined
    assert "login_reason=cannot_connect" in joined
    assert "websocket_connected=True" in joined


async def test_coordinator_update_method_refresh_exception_uses_cache(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
    caplog,
):
    """Refresh request exceptions should keep cached data during network issues."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0

    with caplog.at_level(logging.DEBUG):
        with patch(
            "custom_components.homely.fetch_refresh_token",
            AsyncMock(side_effect=RuntimeError("network down")),
        ):
            result = await runtime_data.coordinator.update_method()

    assert result == runtime_data.last_data
    assert runtime_data.api_available is False
    assert "Token refresh request raised during background refresh" in "\n".join(
        record.getMessage() for record in caplog.records
    )


async def test_coordinator_update_method_marks_stale_cached_data_unavailable(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Stale cached data should stop masking failures when websocket is down."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0
    runtime_data.websocket = None
    runtime_data.last_data_activity_monotonic = time.monotonic() - 301

    with (
        patch(
            "custom_components.homely.fetch_refresh_token", AsyncMock(return_value=None)
        ),
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(return_value=(None, "cannot_connect")),
        ),
    ):
        try:
            await runtime_data.coordinator.update_method()
        except UpdateFailed as err:
            assert "Failed to refresh token and full login also failed" in str(err)
        else:
            raise AssertionError("Expected UpdateFailed")

    assert runtime_data.api_available is False


async def test_coordinator_update_method_invalid_refresh_payload_and_stale_cache_raises(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Invalid refresh payloads should not mask failures once websocket and cache are both dead."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0
    runtime_data.websocket = None
    runtime_data.last_data_activity_monotonic = time.monotonic() - 301

    with (
        patch(
            "custom_components.homely.fetch_refresh_token",
            AsyncMock(return_value={"access_token": "access-only"}),
        ),
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(return_value=(None, "cannot_connect")),
        ),
    ):
        try:
            await runtime_data.coordinator.update_method()
        except UpdateFailed as err:
            assert "Failed to refresh token and full login also failed" in str(err)
        else:
            raise AssertionError("Expected UpdateFailed")

    assert runtime_data.api_available is False


async def test_coordinator_update_method_full_login_missing_fields_raises_update_failed(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Fallback login without required fields should fail."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0

    with (
        patch(
            "custom_components.homely.fetch_refresh_token", AsyncMock(return_value=None)
        ),
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(return_value=({"access_token": "new-access-token"}, None)),
        ),
    ):
        try:
            await runtime_data.coordinator.update_method()
        except UpdateFailed:
            pass
        else:
            raise AssertionError("Expected UpdateFailed")


async def test_coordinator_update_method_refresh_response_missing_fields_falls_back_to_full_login(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Broken refresh responses should retry full login instead of failing hard."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0
    websocket = SimpleNamespace(
        is_connected=lambda: False,
        status="Disconnected",
        status_reason="stale token",
        sync_token=MagicMock(return_value="reconnect_if_disconnected"),
    )
    runtime_data.websocket = websocket
    new_tokens = {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "expires_in": 3600,
    }

    with (
        patch(
            "custom_components.homely.fetch_refresh_token",
            AsyncMock(return_value={"access_token": "access-only"}),
        ),
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(return_value=(new_tokens, None)),
        ),
        patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(return_value=(updated_location_data, 200)),
        ),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result["alarmState"] == "ARMED_AWAY"
    assert runtime_data.access_token == "new-access-token"
    assert runtime_data.refresh_token == "new-refresh-token"
    websocket.sync_token.assert_called_once_with("new-access-token")


async def test_coordinator_update_method_refresh_response_invalid_expires_uses_cache(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
    caplog,
):
    """Invalid refresh expiry should use the same cache fallback as other refresh failures."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0
    runtime_data.websocket = SimpleNamespace(
        is_connected=lambda: True,
        status="Connected",
        status_reason="ready",
        update_token=MagicMock(),
    )

    with caplog.at_level(logging.WARNING):
        with (
            patch(
                "custom_components.homely.fetch_refresh_token",
                AsyncMock(
                    return_value={
                        "access_token": "new-access-token",
                        "refresh_token": "new-refresh-token",
                        "expires_in": "bad",
                    }
                ),
            ),
            patch(
                "custom_components.homely.fetch_token_with_reason",
                AsyncMock(return_value=(None, "cannot_connect")),
            ),
        ):
            result = await runtime_data.coordinator.update_method()

    assert result == runtime_data.last_data
    assert runtime_data.api_available is False
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "Token refresh returned invalid expires_in; trying full login" in joined
    assert "kind=malformed_auth_response" in joined
    assert "invalid_expires_in" in joined
    assert "Please open a GitHub issue if this keeps happening." in joined


async def test_coordinator_update_method_logs_refresh_failure_detail_and_body_preview(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
    caplog,
):
    """Refresh failure logs should keep structured SDK diagnostics visible."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0
    runtime_data.websocket = SimpleNamespace(
        is_connected=lambda: True,
        status="Connected",
        status_reason="ready",
        update_token=MagicMock(),
        disconnect=AsyncMock(),
    )
    refresh_snapshot = api.RefreshTokenResult(
        response=None,
        reason="invalid_payload",
        status=200,
        detail="missing access_token or expires_in",
        body_preview="{'access_token': 'token'}",
    )

    with caplog.at_level(logging.WARNING):
        with (
            patch(
                "custom_components.homely.fetch_refresh_token",
                AsyncMock(return_value=None),
            ),
            patch(
                "custom_components.homely.get_last_refresh_token_result",
                return_value=refresh_snapshot,
            ),
            patch(
                "custom_components.homely.fetch_token_with_reason",
                AsyncMock(return_value=(None, "cannot_connect")),
            ),
        ):
            result = await runtime_data.coordinator.update_method()

    assert result == runtime_data.last_data
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "kind=malformed_auth_response" in joined
    assert "reason=invalid_payload" in joined
    assert "detail=missing access_token or expires_in" in joined
    assert "body_preview=" in joined
    assert "{'access_token': 'token'}" in joined
    assert "Please open a GitHub issue if this keeps happening." in joined


async def test_coordinator_update_method_refreshes_token_in_place(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """A successful refresh response should update runtime tokens directly."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0
    websocket = SimpleNamespace(
        is_connected=lambda: False,
        status="Disconnected",
        status_reason="expired token",
        sync_token=MagicMock(return_value="reconnect_if_disconnected"),
    )
    runtime_data.websocket = websocket

    with (
        patch(
            "custom_components.homely.fetch_refresh_token",
            AsyncMock(
                return_value={
                    "access_token": "refreshed-access-token",
                    "refresh_token": "refreshed-refresh-token",
                    "expires_in": 1800,
                }
            ),
        ),
        patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(return_value=(updated_location_data, 200)),
        ),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result["alarmState"] == "ARMED_AWAY"
    assert runtime_data.access_token == "refreshed-access-token"
    assert runtime_data.refresh_token == "refreshed-refresh-token"
    websocket.sync_token.assert_called_once_with("refreshed-access-token")


async def test_coordinator_update_method_refreshes_connected_websocket_without_reconnect(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Healthy websocket sessions should not be nudged during token refresh."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0
    websocket = SimpleNamespace(
        is_connected=lambda: True,
        status="Connected",
        status_reason="ready",
        sync_token=MagicMock(return_value="no_reconnect"),
    )
    runtime_data.websocket = websocket

    with (
        patch(
            "custom_components.homely.fetch_refresh_token",
            AsyncMock(
                return_value={
                    "access_token": "connected-access-token",
                    "refresh_token": "connected-refresh-token",
                    "expires_in": 1800,
                }
            ),
        ),
        patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(return_value=(updated_location_data, 200)),
        ),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result["alarmState"] == "ARMED_AWAY"
    assert runtime_data.access_token == "connected-access-token"
    assert runtime_data.refresh_token == "connected-refresh-token"
    websocket.sync_token.assert_called_once_with("connected-access-token")


async def test_coordinator_update_method_refreshes_engineio_connected_websocket_without_reconnect(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Token refresh should not nudge reconnect if the Engine.IO transport is alive."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0
    websocket = SimpleNamespace(
        is_connected=lambda: False,
        status="Connected",
        status_reason="event received",
        socket=SimpleNamespace(
            connected=False,
            eio=SimpleNamespace(state="connected"),
        ),
        sync_token=MagicMock(return_value="no_reconnect"),
    )
    runtime_data.websocket = websocket

    with (
        patch(
            "custom_components.homely.fetch_refresh_token",
            AsyncMock(
                return_value={
                    "access_token": "engineio-access-token",
                    "refresh_token": "engineio-refresh-token",
                    "expires_in": 1800,
                }
            ),
        ),
        patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(return_value=(updated_location_data, 200)),
        ),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result["alarmState"] == "ARMED_AWAY"
    assert runtime_data.access_token == "engineio-access-token"
    assert runtime_data.refresh_token == "engineio-refresh-token"
    websocket.sync_token.assert_called_once_with("engineio-access-token")


async def test_coordinator_update_method_refreshes_token_with_legacy_websocket_api(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Legacy websocket clients without reconnect kwargs should still be updated."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0

    class _LegacyWebSocket:
        def __init__(self) -> None:
            self.tokens: list[str] = []
            self.status = "Disconnected"
            self.status_reason = "expired token"

        def is_connected(self) -> bool:
            return False

        def update_token(self, token: str) -> None:
            self.tokens.append(token)

    websocket = _LegacyWebSocket()
    runtime_data.websocket = websocket

    with (
        patch(
            "custom_components.homely.fetch_refresh_token",
            AsyncMock(
                return_value={
                    "access_token": "legacy-access-token",
                    "refresh_token": "legacy-refresh-token",
                    "expires_in": 1800,
                }
            ),
        ),
        patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(return_value=(updated_location_data, 200)),
        ),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result["alarmState"] == "ARMED_AWAY"
    assert websocket.tokens == ["legacy-access-token"]


async def test_coordinator_update_method_full_login_invalid_expires_raises_update_failed(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Fallback login with invalid expiry should fail."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.expires_at = 0

    with (
        patch(
            "custom_components.homely.fetch_refresh_token", AsyncMock(return_value=None)
        ),
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(
                return_value=(
                    {
                        "access_token": "new-access-token",
                        "refresh_token": "new-refresh-token",
                        "expires_in": "bad",
                    },
                    None,
                )
            ),
        ),
    ):
        try:
            await runtime_data.coordinator.update_method()
        except UpdateFailed:
            pass
        else:
            raise AssertionError("Expected UpdateFailed")


async def test_coordinator_update_method_http_401_retries_full_login_before_reauth(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Polling auth rejections should retry stored credentials before reauth."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data

    with (
        patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(
                side_effect=[
                    (None, 401),
                    (updated_location_data, 200),
                ]
            ),
        ) as get_data_with_status,
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(
                return_value=(
                    {
                        "access_token": "fresh-access-token",
                        "refresh_token": "fresh-refresh-token",
                        "expires_in": 1800,
                    },
                    None,
                )
            ),
        ) as fetch_token_with_reason,
    ):
        result = await runtime_data.coordinator.update_method()

    assert result["alarmState"] == "ARMED_AWAY"
    assert runtime_data.access_token == "fresh-access-token"
    assert runtime_data.refresh_token == "fresh-refresh-token"
    fetch_token_with_reason.assert_awaited_once()
    assert get_data_with_status.await_count == 2


async def test_coordinator_update_method_http_401_updates_connected_websocket_token_in_place(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """A 401 retry should update a healthy websocket token without reconnecting it."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    websocket = SimpleNamespace(
        is_connected=lambda: True,
        status="Connected",
        status_reason="ready",
        sync_token=MagicMock(return_value="no_reconnect"),
    )
    runtime_data.websocket = websocket

    with (
        patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(
                side_effect=[
                    (None, 401),
                    (updated_location_data, 200),
                ]
            ),
        ),
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(
                return_value=(
                    {
                        "access_token": "fresh-access-token",
                        "refresh_token": "fresh-refresh-token",
                        "expires_in": 1800,
                    },
                    None,
                )
            ),
        ),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result["alarmState"] == "ARMED_AWAY"
    websocket.sync_token.assert_called_once_with("fresh-access-token")


async def test_coordinator_update_method_http_401_uses_cache_when_full_login_is_invalid(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Polling invalid_auth should keep retrying later instead of triggering reauth."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data

    with (
        patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(return_value=(None, 401)),
        ),
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(return_value=(None, "invalid_auth")),
        ),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result == runtime_data.last_data


async def test_coordinator_update_method_http_401_uses_cache_when_full_login_cannot_connect(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Polling auth rejections should keep cached data on temporary login outages."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data

    with (
        patch(
            "custom_components.homely.get_data_with_status",
            AsyncMock(return_value=(None, 401)),
        ),
        patch(
            "custom_components.homely.fetch_token_with_reason",
            AsyncMock(return_value=(None, "cannot_connect")),
        ),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result == runtime_data.last_data


async def test_coordinator_update_method_uses_cache_on_unexpected_poll_exception(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Unexpected polling exceptions should fall back to cached data when possible."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data

    with patch(
        "custom_components.homely.get_data_with_status",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result == runtime_data.last_data
    assert runtime_data.api_available is False


async def test_coordinator_update_method_wraps_unexpected_poll_exception_without_cache(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Unexpected polling exceptions should still fail if no cache exists."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.last_data = {}

    with patch(
        "custom_components.homely.get_data_with_status",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        try:
            await runtime_data.coordinator.update_method()
        except UpdateFailed as err:
            assert "boom" in str(err)
        else:
            raise AssertionError("Expected UpdateFailed")


async def test_coordinator_update_method_re_raises_update_failed(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Existing UpdateFailed exceptions should pass through unchanged."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data

    with patch(
        "custom_components.homely.get_data_with_status",
        AsyncMock(side_effect=UpdateFailed("already wrapped")),
    ):
        try:
            await runtime_data.coordinator.update_method()
        except UpdateFailed as err:
            assert str(err) == "already wrapped"
        else:
            raise AssertionError("Expected UpdateFailed")


async def test_coordinator_update_method_non_transient_empty_response_raises_update_failed(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Non-transient empty API responses should fail."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data

    with patch(
        "custom_components.homely.get_data_with_status",
        AsyncMock(return_value=(None, 418)),
    ):
        try:
            await runtime_data.coordinator.update_method()
        except UpdateFailed:
            pass
        else:
            raise AssertionError("Expected UpdateFailed")


async def test_coordinator_update_method_keeps_cached_alarm_if_api_omits_it(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Polling should preserve websocket-updated alarm state when API omits it."""
    config_entry = build_config_entry()
    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
    )
    runtime_data = config_entry.runtime_data
    runtime_data.last_data["alarmState"] = "ARM_PENDING"
    payload = deepcopy(updated_location_data)
    payload.pop("alarmState", None)
    payload["features"]["alarm"]["states"]["alarm"].pop("value", None)

    with patch(
        "custom_components.homely.get_data_with_status",
        AsyncMock(return_value=(payload, 200)),
    ):
        result = await runtime_data.coordinator.update_method()

    assert result["alarmState"] == "ARM_PENDING"
    assert result["features"]["alarm"]["states"]["alarm"]["value"] == "ARM_PENDING"


async def test_async_reload_entry_calls_reload(hass):
    """Options reload helper should delegate to Home Assistant."""
    config_entry = build_config_entry()

    with patch.object(
        hass.config_entries,
        "async_reload",
        AsyncMock(return_value=True),
    ) as async_reload:
        await async_reload_entry(hass, config_entry)

    async_reload.assert_awaited_once_with(config_entry.entry_id)


async def test_async_setup_entry_websocket_callbacks_update_runtime_and_listeners(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Websocket init should wire status callbacks, listeners and event updates."""
    _FakeHomelyWebSocket.reset()
    config_entry = build_config_entry(
        options={
            CONF_ENABLE_WEBSOCKET: True,
            CONF_POLL_WHEN_WEBSOCKET: False,
        }
    )

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch(
                "custom_components.homely.HomelyWebSocket",
                _FakeHomelyWebSocket,
            ),
        ),
    )

    runtime_data = config_entry.runtime_data
    ws = _FakeHomelyWebSocket.instances[0]
    runtime_data.coordinator.async_update_listeners = MagicMock()
    runtime_data.coordinator.async_request_refresh = AsyncMock(return_value=None)
    listener = MagicMock()
    runtime_data.ws_status_listeners.append(listener)

    with patch.object(hass.loop, "call_soon_threadsafe", side_effect=lambda cb: cb()):
        ws.status_update_callback("Disconnected", "network error: boom")
    await hass.async_block_till_done()

    assert runtime_data.ws_status == "Disconnected"
    assert runtime_data.ws_status_reason == "network error: boom"
    assert runtime_data.last_disconnect_reason == "network error: boom"
    assert "status callback observed disconnect" in ws.request_reconnect_calls
    listener.assert_called_once()
    runtime_data.coordinator.async_update_listeners.assert_called()
    runtime_data.coordinator.async_request_refresh.assert_awaited_once()

    with patch.object(hass.loop, "call_soon_threadsafe", side_effect=lambda cb: cb()):
        ws.status_update_callback("Connected", "event received")
    await hass.async_block_till_done()

    assert runtime_data.ws_status == "Connected"
    assert runtime_data.ws_status_reason == "event received"
    assert runtime_data.last_disconnect_reason == "network error: boom"

    runtime_data.last_data_activity_monotonic = 0
    runtime_data.last_websocket_event_at = None
    runtime_data.last_websocket_event_type = None

    ws.on_data_update(
        {
            "type": "alarm-state-changed",
            "data": {"alarmState": "ARMED_AWAY"},
        }
    )
    assert runtime_data.last_data["alarmState"] == "ARMED_AWAY"
    assert runtime_data.last_data_activity_monotonic > 0
    assert runtime_data.last_websocket_event_at is not None
    assert runtime_data.last_websocket_event_type == "alarm-state-changed"

    ws.on_data_update(
        {
            "type": "device-state-changed",
            "data": {
                "deviceId": runtime_data.last_data["devices"][0]["id"],
                "change": {
                    "feature": "battery",
                    "stateName": "low",
                    "value": True,
                },
            },
        }
    )
    assert (
        runtime_data.last_data["devices"][0]["features"]["battery"]["states"]["low"][
            "value"
        ]
        is True
    )
    assert runtime_data.last_websocket_event_type == "device-state-changed"

    runtime_data.coordinator.async_request_refresh.reset_mock()
    ws.on_data_update(
        {
            "type": "device-state-changed",
            "data": {
                "deviceId": runtime_data.last_data["devices"][2]["id"],
                "change": {
                    "feature": "lock",
                    "stateName": "soundvolume",
                    "value": 2,
                },
            },
        }
    )
    await hass.async_block_till_done()
    assert runtime_data.force_api_refresh_once is True
    runtime_data.coordinator.async_request_refresh.assert_awaited_once()

    previous_listener_calls = runtime_data.coordinator.async_update_listeners.call_count
    ws.on_data_update({"type": "disconnect"})
    ws.on_data_update({"type": "unsupported-event"})
    assert runtime_data.last_websocket_event_type == "unsupported-event"
    assert (
        runtime_data.coordinator.async_update_listeners.call_count
        == previous_listener_calls + 1
    )


async def test_async_setup_entry_websocket_handles_connect_failure_and_internet_event(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Failed websocket init should still register reconnect handling."""
    _FakeHomelyWebSocket.reset()
    _FakeHomelyWebSocket.connect_result = False
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch("custom_components.homely.HomelyWebSocket", _FakeHomelyWebSocket),
        ),
    )

    ws = _FakeHomelyWebSocket.instances[0]
    assert config_entry.runtime_data.websocket is ws

    hass.bus.async_fire("internet_available")
    await hass.async_block_till_done()

    assert "poll detected disconnected websocket" in ws.request_reconnect_calls
    assert "internet_available event" in ws.request_reconnect_calls


async def test_async_setup_entry_websocket_status_callback_tolerates_listener_failures(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Broken listeners and coordinator callbacks should not break status updates."""
    _FakeHomelyWebSocket.reset()
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch("custom_components.homely.HomelyWebSocket", _FakeHomelyWebSocket),
        ),
    )

    runtime_data = config_entry.runtime_data
    ws = _FakeHomelyWebSocket.instances[0]
    runtime_data.ws_status_listeners.append(
        MagicMock(side_effect=RuntimeError("bad listener"))
    )
    runtime_data.coordinator.async_update_listeners = MagicMock(
        side_effect=RuntimeError("bad coordinator")
    )

    with patch.object(hass.loop, "call_soon_threadsafe", side_effect=lambda cb: cb()):
        ws.status_update_callback("Connected", "event received")
    assert runtime_data.ws_status == "Connected"
    assert runtime_data.ws_status_reason == "event received"


async def test_async_setup_entry_websocket_disconnect_refresh_request_failure_is_swallowed(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Refresh request creation failures after disconnect should not bubble."""
    _FakeHomelyWebSocket.reset()
    config_entry = build_config_entry(
        options={
            CONF_ENABLE_WEBSOCKET: True,
            CONF_POLL_WHEN_WEBSOCKET: False,
        }
    )

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch("custom_components.homely.HomelyWebSocket", _FakeHomelyWebSocket),
        ),
    )

    runtime_data = config_entry.runtime_data
    ws = _FakeHomelyWebSocket.instances[0]
    runtime_data.coordinator.async_update_listeners = MagicMock()
    runtime_data.coordinator.async_request_refresh = MagicMock(
        side_effect=RuntimeError("refresh boom")
    )
    with patch.object(hass.loop, "call_soon_threadsafe", side_effect=lambda cb: cb()):
        ws.status_update_callback("Disconnected", "network error: boom")


async def test_async_setup_entry_websocket_status_callback_tolerates_dispatch_failure(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Failures scheduling status updates should be swallowed."""
    _FakeHomelyWebSocket.reset()
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch("custom_components.homely.HomelyWebSocket", _FakeHomelyWebSocket),
        ),
    )

    ws = _FakeHomelyWebSocket.instances[0]
    with patch.object(
        hass.loop, "call_soon_threadsafe", side_effect=RuntimeError("schedule failed")
    ):
        ws.status_update_callback("Connected", "event received")


async def test_async_setup_entry_websocket_callback_handles_apply_failures(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Unexpected websocket event processing errors should be swallowed."""
    _FakeHomelyWebSocket.reset()
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch("custom_components.homely.HomelyWebSocket", _FakeHomelyWebSocket),
        ),
    )

    ws = _FakeHomelyWebSocket.instances[0]
    with patch(
        "custom_components.homely.apply_websocket_event_to_data",
        side_effect=RuntimeError("boom"),
    ):
        ws.on_data_update(
            {"type": "device-state-changed", "data": {"deviceId": "dev-1"}}
        )


async def test_async_setup_entry_websocket_callback_handles_no_direct_device_changes(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Device websocket events without concrete changes should still be safe."""
    _FakeHomelyWebSocket.reset()
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch("custom_components.homely.HomelyWebSocket", _FakeHomelyWebSocket),
        ),
    )

    runtime_data = config_entry.runtime_data
    runtime_data.coordinator.async_update_listeners = MagicMock()
    ws = _FakeHomelyWebSocket.instances[0]
    with patch(
        "custom_components.homely.apply_websocket_event_to_data",
        return_value={
            "event_type": "device-state-changed",
            "changes": [],
            "device_id": "missing-device",
        },
    ):
        ws.on_data_update({"type": "device-state-changed"})

    runtime_data.coordinator.async_update_listeners.assert_called_once()
    assert runtime_data.last_websocket_event_type == "device-state-changed"
    assert runtime_data.last_websocket_event_at is not None


async def test_async_setup_entry_ignores_stale_websocket_callbacks_after_runtime_replacement(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Old websocket callbacks should not mutate a replacement runtime object."""
    _FakeHomelyWebSocket.reset()
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch("custom_components.homely.HomelyWebSocket", _FakeHomelyWebSocket),
        ),
    )

    original_runtime = config_entry.runtime_data
    replacement_runtime = HomelyRuntimeData(
        coordinator=original_runtime.coordinator,
        access_token=original_runtime.access_token,
        refresh_token=original_runtime.refresh_token,
        expires_at=original_runtime.expires_at,
        location_id=original_runtime.location_id,
        last_data=deepcopy(original_runtime.last_data),
        tracked_device_ids=set(original_runtime.tracked_device_ids),
    )
    config_entry.runtime_data = replacement_runtime

    ws = _FakeHomelyWebSocket.instances[0]
    with patch(
        "custom_components.homely.apply_websocket_event_to_data",
        return_value={
            "event_type": "alarm-state-changed",
            "updated": True,
            "alarm_state": "TRIGGERED",
        },
    ) as apply_event:
        ws.on_data_update({"type": "alarm-state-changed"})
        await hass.async_block_till_done()

    ws.status_update_callback("Disconnected", "stale callback")
    await hass.async_block_till_done()

    apply_event.assert_not_called()
    assert replacement_runtime.last_data == original_runtime.last_data
    assert replacement_runtime.ws_status == "Not initialized"


async def test_async_setup_entry_websocket_constructor_errors_are_swallowed(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Websocket init should survive constructor-level failures."""
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch(
                "custom_components.homely.HomelyWebSocket",
                side_effect=RuntimeError("boom"),
            ),
        ),
    )

    assert config_entry.runtime_data.websocket is None


async def test_async_setup_entry_websocket_key_error_is_swallowed(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """KeyError during websocket init should be swallowed."""
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch(
                "custom_components.homely.HomelyWebSocket",
                side_effect=KeyError("missing"),
            ),
        ),
    )

    assert config_entry.runtime_data.websocket is None


async def test_async_setup_entry_tolerates_internet_listener_registration_error(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Setup should still succeed if the internet event listener cannot be registered."""
    _FakeHomelyWebSocket.reset()
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch("custom_components.homely.HomelyWebSocket", _FakeHomelyWebSocket),
            patch.object(
                type(hass.bus), "async_listen", side_effect=RuntimeError("no bus")
            ),
        ),
    )

    assert config_entry.state is ConfigEntryState.LOADED


async def test_async_setup_entry_internet_available_callback_swallows_reconnect_errors(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Reconnect callback failures from the internet event should be swallowed."""
    _FakeHomelyWebSocket.reset()
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch("custom_components.homely.HomelyWebSocket", _FakeHomelyWebSocket),
        ),
    )

    ws = _FakeHomelyWebSocket.instances[0]
    ws.request_reconnect = MagicMock(side_effect=RuntimeError("boom"))
    hass.bus.async_fire("internet_available")
    await hass.async_block_till_done()


async def test_async_setup_entry_internet_available_callback_does_not_depend_on_is_connected(
    hass,
    token_response,
    location_response,
    location_data,
    updated_location_data,
):
    """Internet recovery should still request reconnects if connection probes are broken."""
    _FakeHomelyWebSocket.reset()
    config_entry = build_config_entry(options={CONF_ENABLE_WEBSOCKET: True})

    await _setup_loaded_entry(
        hass,
        config_entry,
        token_response,
        location_response,
        location_data,
        updated_location_data,
        extra_patches=(
            patch("custom_components.homely.HomelyWebSocket", _FakeHomelyWebSocket),
        ),
    )

    ws = _FakeHomelyWebSocket.instances[0]

    def _broken_is_connected() -> bool:
        raise RuntimeError("boom")

    ws.is_connected = _broken_is_connected
    hass.bus.async_fire("internet_available")
    await hass.async_block_till_done()

    assert "internet_available event" in ws.request_reconnect_calls
