"""Entity ID helpers."""
from __future__ import annotations


def battery_problem_unique_id(location_id: str | int) -> str:
    """Build a unique ID for the aggregate battery problem entity."""
    return f"location_{location_id}_any_battery_problem"
