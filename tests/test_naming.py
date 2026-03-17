"""Tests for naming helpers."""
from __future__ import annotations

from custom_components.homely import naming


def test_clean_text_and_location_parts():
    """Text cleaning and location parsing should handle multiple formats."""
    assert naming._clean_text("  Hello ") == "Hello"
    assert naming._clean_text("   ") is None
    assert naming._location_parts("Floor 2 - Living room") == ("Floor 2", "Living room")
    assert naming._location_parts({"floorName": "Floor 1", "roomName": "Entrance"}) == (
        "Floor 1",
        "Entrance",
    )
    assert naming._location_parts(None) == (None, None)


def test_device_area_and_display_name_fallbacks():
    """Area and display names should use room and id fallbacks."""
    device = {"id": "abc", "name": " Door Sensor ", "location": "Floor 1 - Hall"}
    unnamed = {"id": "xyz"}

    assert naming.get_device_area(device) == "Hall"
    assert naming.get_device_display_name(device) == "Door Sensor"
    assert naming.get_device_display_name(unnamed) == "Homely device xyz"


def test_humanize_entity_name_and_object_id():
    """Naming helpers should dedupe labels and create stable object ids."""
    device = {"name": "Front Door", "location": "Floor 1 - Front Door"}

    assert naming.humanize_label("battery_low") == "Battery Low"
    assert naming.humanize_label(None) == "Sensor"
    assert naming.build_entity_name(device, "door") == "Front Door"
    assert naming.build_entity_name(device, "battery_low") == "Front Door Battery Low"
    assert naming.build_suggested_object_id(device, "door") == "floor_1_front_door"


def test_slug_helpers_remove_immediate_duplicates():
    """Slug helpers should avoid repeated adjacent tokens."""
    tokens: list[str] = []
    naming._extend_tokens(tokens, "Living Room")
    naming._extend_tokens(tokens, "Room")
    naming._extend_tokens(tokens, "Sensor")

    assert tokens == ["living", "room", "sensor"]

