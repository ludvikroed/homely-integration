"""Repair issue helpers for Homely."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .models import HomelyConfigEntry
from .runtime_state import device_id_snapshot

_MISSING_DEVICES_ISSUE_PREFIX = "missing_devices_"
_MAX_REPAIR_DEVICE_NAMES = 20


def _escape_markdown(value: str) -> str:
    """Keep device names from changing the repair issue's Markdown layout."""
    escaped = " ".join(value.split())
    for character in ("\\", "`", "*", "_", "[", "]"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def missing_devices_issue_id(entry_id: str) -> str:
    """Return the stable repair issue id for an entry."""
    return f"{_MISSING_DEVICES_ISSUE_PREFIX}{entry_id}"


@callback
def async_sync_missing_devices_issue(
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    location_data: dict[str, Any],
) -> None:
    """Create or clear the repair issue for confirmed missing devices."""
    active_ids = device_id_snapshot(location_data)
    registry = dr.async_get(hass)
    missing_names: list[str] = []

    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        homely_ids = {
            str(identifier)
            for identifier_domain, identifier in device.identifiers
            if identifier_domain == DOMAIN
            and not str(identifier).startswith("location_")
        }
        if not homely_ids or homely_ids & active_ids:
            continue
        missing_names.append(
            _escape_markdown(
                str(device.name_by_user or device.name or sorted(homely_ids)[0])
            )
        )

    issue_id = missing_devices_issue_id(entry.entry_id)
    if not missing_names:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    missing_names.sort(key=str.casefold)
    displayed_names = missing_names[:_MAX_REPAIR_DEVICE_NAMES]
    devices = "\n".join(f"- {name}" for name in displayed_names)

    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        data={"config_entry_id": entry.entry_id, "device_count": len(missing_names)},
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="missing_devices",
        translation_placeholders={
            "count": str(len(missing_names)),
            "devices": devices,
            "home": entry.title,
        },
    )


@callback
def async_delete_missing_devices_issue(
    hass: HomeAssistant, entry: HomelyConfigEntry
) -> None:
    """Delete the missing-device repair issue for an entry."""
    ir.async_delete_issue(hass, DOMAIN, missing_devices_issue_id(entry.entry_id))
