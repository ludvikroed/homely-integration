"""HAN meter multiplier helpers.

Meters behind current transformers report values divided by the transformer
ratio when the grid company leaves the ratio unset on the meter. The multiplier
is stored per device in the config entry options and applied to the metering
sensors.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any, TypeGuard

from .const import CONF_METER_MULTIPLIERS

DEFAULT_METER_MULTIPLIER = 1.0
METER_MULTIPLIER_MIN = 0.001
METER_MULTIPLIER_MAX = 100000.0
METER_MULTIPLIER_STEP = 0.001


def _valid_meter_multiplier(value: Any) -> TypeGuard[int | float]:
    """Return whether a value can safely be used as a meter multiplier."""
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and METER_MULTIPLIER_MIN <= value <= METER_MULTIPLIER_MAX
        and isfinite(value)
    )


def get_meter_multiplier(options: Mapping[str, Any], device_id: str) -> float:
    """Return the stored multiplier for a device, or 1 when unset or invalid."""
    multipliers = options.get(CONF_METER_MULTIPLIERS)
    if not isinstance(multipliers, Mapping):
        return DEFAULT_METER_MULTIPLIER
    value = multipliers.get(device_id)
    if not _valid_meter_multiplier(value):
        return DEFAULT_METER_MULTIPLIER
    return float(value)


def options_with_meter_multiplier(
    options: Mapping[str, Any], device_id: str, value: float
) -> dict[str, Any]:
    """Return a copy of options with the device's multiplier set.

    The default is not stored, so options stay empty for unaffected homes.
    """
    if not _valid_meter_multiplier(value):
        raise ValueError("Meter multiplier must be finite and within the allowed range")
    new_options = dict(options)
    stored = new_options.get(CONF_METER_MULTIPLIERS)
    multipliers = dict(stored) if isinstance(stored, Mapping) else {}
    if value == DEFAULT_METER_MULTIPLIER:
        multipliers.pop(device_id, None)
    else:
        multipliers[device_id] = float(value)
    if multipliers:
        new_options[CONF_METER_MULTIPLIERS] = multipliers
    else:
        new_options.pop(CONF_METER_MULTIPLIERS, None)
    return new_options


def options_without_meter_multipliers(options: Mapping[str, Any]) -> dict[str, Any]:
    """Return options minus the multiplier key, for reload comparisons."""
    return {
        key: value for key, value in options.items() if key != CONF_METER_MULTIPLIERS
    }


def apply_meter_multiplier(value: Any, multiplier: float) -> Any:
    """Scale a numeric meter value; leave missing or non-numeric values alone."""
    if multiplier == DEFAULT_METER_MULTIPLIER:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return round(value * multiplier, 3)
