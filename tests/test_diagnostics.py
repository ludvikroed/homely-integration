"""Tests for diagnostics support."""

from __future__ import annotations

import time
from types import SimpleNamespace

from custom_components.homely.diagnostics import async_get_config_entry_diagnostics
from custom_components.homely.models import HomelyRuntimeData
from tests.common import LOCATION_ID, build_config_entry


async def test_diagnostics_redact_sensitive_data(hass, location_data):
    """Diagnostics should redact credentials and selected private identifiers."""
    location_data["devices"][0]["gatewayId"] = "gw-1"
    location_data["devices"][0]["rootLocationId"] = LOCATION_ID
    location_data["devices"][0]["modelId"] = "model-1"
    location_data["devices"][0]["userId"] = "user-1"
    config_entry = build_config_entry()
    config_entry.runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=location_data, last_update_success=True),
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )
    config_entry.runtime_data.last_successful_poll_monotonic = time.monotonic() - 20
    config_entry.runtime_data.last_websocket_event_monotonic = time.monotonic() - 3
    config_entry.runtime_data.last_websocket_event_type = "alarm-state-changed"
    config_entry.runtime_data.last_disconnect_reason = "network error: boom"

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diagnostics["entry"]["data"]["username"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["password"] == "**REDACTED**"
    assert diagnostics["runtime"]["location_id"] == "**REDACTED**"
    assert diagnostics["runtime"]["api_dump"]["locationId"] == "**REDACTED**"
    assert diagnostics["runtime"]["api_dump"]["name"] == "JF23"
    assert (
        diagnostics["runtime"]["api_dump"]["devices"][0]["id"]
        == "70b9db72-5c00-4316-9ffa-ac7bf60fcb47"
    )
    assert diagnostics["runtime"]["api_dump"]["devices"][0]["name"] == "Bevegelse stue"
    assert (
        diagnostics["runtime"]["api_dump"]["devices"][0]["location"]
        == "Floor 2 - Living room"
    )
    assert diagnostics["runtime"]["api_dump"]["devices"][0]["gatewayId"] == "gw-1"
    assert (
        diagnostics["runtime"]["api_dump"]["devices"][0]["rootLocationId"]
        == "**REDACTED**"
    )
    assert (
        diagnostics["runtime"]["api_dump"]["devices"][0]["serialNumber"]
        == "**REDACTED**"
    )
    assert diagnostics["runtime"]["api_dump"]["devices"][0]["modelId"] == "model-1"
    assert diagnostics["runtime"]["api_dump"]["devices"][0]["userId"] == "user-1"
    assert diagnostics["runtime"]["observability"]["last_websocket_event_type"] == (
        "alarm-state-changed"
    )
    assert (
        diagnostics["runtime"]["observability"]["last_disconnect_reason"]
        == "network error: boom"
    )
    assert diagnostics["runtime"]["observability"]["cache_age_seconds"] is not None


async def test_diagnostics_falls_back_to_last_successful_api_dump(hass, location_data):
    """Diagnostics should still include the latest API dump when coordinator data is empty."""
    config_entry = build_config_entry()
    config_entry.runtime_data = HomelyRuntimeData(
        coordinator=SimpleNamespace(data=None, last_update_success=False),
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=0,
        location_id=LOCATION_ID,
        last_data=location_data,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diagnostics["runtime"]["api_dump"]["name"] == "JF23"
    assert diagnostics["runtime"]["api_dump"]["devices"][0]["name"] == "Bevegelse stue"
