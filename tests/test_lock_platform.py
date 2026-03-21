"""Tests for lock helpers and entity behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.homely.lock import (
    HomelyLock,
    _coerce_bool,
    _is_lock_device,
    async_setup_entry,
)
from tests.common import build_config_entry


def test_lock_bool_coercion_and_detection(location_data):
    """Lock helpers should detect lock devices and normalize lock values."""
    assert _coerce_bool(1) is True
    assert _coerce_bool("lock") is True
    assert _coerce_bool("unlock") is False
    assert _coerce_bool("other") is None

    assert _is_lock_device(location_data["devices"][2]) is True
    assert _is_lock_device(location_data["devices"][0]) is False


async def test_lock_setup_entry_handles_sparse_device_payloads(hass, location_data):
    """Lock setup should ignore invalid device collections and payloads."""
    entry = build_config_entry()
    coordinator = SimpleNamespace(data={"devices": "not-a-list"})
    entry.runtime_data = SimpleNamespace(coordinator=coordinator, last_data={})
    added_entities: list[HomelyLock] = []

    await async_setup_entry(hass, entry, added_entities.extend)

    assert added_entities == []

    coordinator.data = {"devices": ["bad-payload", location_data["devices"][2], 3]}

    await async_setup_entry(hass, entry, added_entities.extend)

    assert len(added_entities) == 1
    assert isinstance(added_entities[0], HomelyLock)


async def test_lock_entity_unsupported_commands_raise(location_data):
    """Homely locks are read-only and should reject service calls."""
    coordinator = MagicMock()
    coordinator.data = location_data
    entity = HomelyLock(coordinator, location_data["devices"][2])

    with pytest.raises(HomeAssistantError):
        await entity.async_lock()
    with pytest.raises(HomeAssistantError):
        await entity.async_unlock()
