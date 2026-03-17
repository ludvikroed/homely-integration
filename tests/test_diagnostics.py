"""Tests for diagnostics support."""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.homely.diagnostics import async_get_config_entry_diagnostics
from custom_components.homely.models import HomelyRuntimeData
from tests.common import LOCATION_ID, build_config_entry


async def test_diagnostics_redact_sensitive_data(hass, location_data):
    """Diagnostics should redact credentials, tokens, and device identifiers."""
    config_entry = build_config_entry()
    config_entry.runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data, last_update_success=True),
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diagnostics["entry"]["data"]["username"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["password"] == "**REDACTED**"
    assert diagnostics["runtime"]["location_id"] == "**REDACTED**"
    assert diagnostics["runtime"]["data"]["name"] == "**REDACTED**"
    assert diagnostics["runtime"]["data"]["devices"][0]["id"] == "**REDACTED**"
    assert diagnostics["runtime"]["data"]["devices"][0]["name"] == "**REDACTED**"
    assert diagnostics["runtime"]["data"]["devices"][0]["location"] == "**REDACTED**"
