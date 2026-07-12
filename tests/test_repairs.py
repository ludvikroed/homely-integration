"""Tests for Homely repair issues."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir

from custom_components.homely.const import DOMAIN
from custom_components.homely.repairs import (
    async_sync_missing_devices_issue,
    missing_devices_issue_id,
)
from tests.common import build_config_entry


def test_missing_device_issue_clears_when_device_returns(hass):
    """A device reported by Homely again should clear the repair issue."""
    entry = build_config_entry()
    entry.add_to_hass(hass)
    device_id = "returned-device-id"
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_id)},
        name="Returned *sensor*\nupstairs",
    )
    issue_registry = ir.async_get(hass)
    issue_id = missing_devices_issue_id(entry.entry_id)

    async_sync_missing_devices_issue(hass, entry, {"devices": []})
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders["devices"] == (
        "- Returned \\*sensor\\* upstairs"
    )

    async_sync_missing_devices_issue(
        hass,
        entry,
        {"devices": [{"id": device_id}]},
    )
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
