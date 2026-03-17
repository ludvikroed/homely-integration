"""Tests for lock helpers and entity behavior."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.homely.lock import HomelyLock, _coerce_bool, _is_lock_device


def test_lock_bool_coercion_and_detection(location_data):
    """Lock helpers should detect lock devices and normalize lock values."""
    assert _coerce_bool("lock") is True
    assert _coerce_bool("unlock") is False
    assert _coerce_bool("other") is None

    assert _is_lock_device(location_data["devices"][2]) is True
    assert _is_lock_device(location_data["devices"][0]) is False


async def test_lock_entity_unsupported_commands_raise(location_data):
    """Homely locks are read-only and should reject service calls."""
    coordinator = MagicMock()
    coordinator.data = location_data
    entity = HomelyLock(coordinator, location_data["devices"][2])

    with pytest.raises(HomeAssistantError):
        await entity.async_lock()
    with pytest.raises(HomeAssistantError):
        await entity.async_unlock()

