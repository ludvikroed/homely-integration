"""Helpers for stable, user-friendly Homely entity naming."""

from __future__ import annotations

from typing import Any, Mapping

from homeassistant.util import slugify


def _clean_text(value: Any) -> str | None:
    """Return trimmed text value or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _location_parts(location: Any) -> tuple[str | None, str | None]:
    """Extract floor and room from Homely location payload."""
    if isinstance(location, dict):
        floor = _clean_text(
            location.get("floor") or location.get("floorName") or location.get("level")
        )
        room = _clean_text(
            location.get("room") or location.get("roomName") or location.get("name")
        )
        return floor, room

    location_text = _clean_text(location)
    if not location_text:
        return None, None

    if " - " in location_text:
        floor, room = location_text.split(" - ", 1)
        return _clean_text(floor), _clean_text(room)

    return None, location_text


def get_device_area(device: Mapping[str, Any]) -> str | None:
    """Return suggested area name for Home Assistant (prefer room)."""
    floor, room = _location_parts(device.get("location"))
    return room or floor


def get_device_display_name(device: Mapping[str, Any]) -> str:
    """Return user-facing device name without room/floor prefix."""
    return _clean_text(device.get("name")) or f"Homely device {device.get('id')}"


def humanize_label(label: str | None) -> str:
    """Return a title-cased label from API keys."""
    if not label:
        return "Sensor"
    return str(label).replace("_", " ").strip().title()


def _slug_tokens(value: str | None) -> list[str]:
    """Return slugified underscore tokens."""
    if not value:
        return []
    slug = slugify(value)
    if not slug:
        return []
    return [token for token in slug.split("_") if token]


def _extend_tokens(target: list[str], value: str | None) -> None:
    """Append tokens to target while removing immediate duplicates."""
    for token in _slug_tokens(value):
        if not target or target[-1] != token:
            target.append(token)


def build_suggested_object_id(
    device: Mapping[str, Any], suffix: str | None
) -> str | None:
    """Build deterministic floor/room/device_type suggested object id."""
    floor, room = _location_parts(device.get("location"))

    tokens: list[str] = []
    _extend_tokens(tokens, floor)
    _extend_tokens(tokens, room)
    _extend_tokens(tokens, suffix)

    if not tokens:
        return None
    return "_".join(tokens)
