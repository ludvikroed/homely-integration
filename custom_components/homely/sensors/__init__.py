"""Sensor definitions for Homely devices."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass

SOUND_VOLUME_OPTIONS = ["muted", "low", "high"]
LANGUAGE_OPTIONS = ["no", "en", "sv", "da"]


def _as_float(value: Any) -> float | None:
    """Convert numeric API values to float when possible."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _wh_to_kwh(value: Any) -> float | Any:
    """Convert meter totals reported in Wh to kWh."""
    numeric = _as_float(value)
    if numeric is None:
        return value
    return round(numeric / 1000, 3)


def _lock_sound_volume_label(value: Any) -> str | Any:
    """Map known Yale sound volume values to stable enum states."""
    labels = {
        0: "muted",
        1: "low",
        2: "high",
    }
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        if mapped := labels.get(int(value)):
            return mapped
        return str(int(value)) if float(value).is_integer() else str(value)
    if isinstance(value, str):
        return value.strip().lower()
    return value


def _lock_language_label(value: Any) -> str | Any:
    """Normalize Yale language codes to stable enum states."""
    if not isinstance(value, str):
        return value

    normalized = value.strip().lower()
    return normalized


# Sensor definitions grouped by feature type.
SENSORS: list[dict[str, Any]] = [
    # Alarm sensors
    {
        "path": "features.alarm.states.alarm.value",
        "format": "boolean",
        "type": "binary_sensor",
        "name": "alarm",
        "get_translation_key": lambda device: (
            "motion" if "motion" in device.get("modelName", "").lower() else "contact"
        ),
        "device_class": "door",
        "device_suffix": "alarm",
        "get_name": lambda device: (
            "motion" if "motion" in device.get("modelName", "").lower() else "contact"
        ),
        "get_device_class": lambda device: (
            "motion" if "motion" in device.get("modelName", "").lower() else "door"
        ),
    },
    {
        "path": "features.alarm.states.sensitivitylevel.value",
        "format": "number",
        "type": "sensor",
        "name": "motion_sensitivity",
        "translation_key": "motion_sensitivity",
        "device_suffix": "sensitivitylevel",
        "icon": "mdi:tune-vertical",
    },
    {
        "path": "features.alarm.states.fire.value",
        "format": "boolean",
        "type": "binary_sensor",
        "name": "fire",
        "translation_key": "fire",
        "device_class": "smoke",
        "device_suffix": "alarm",
    },
    {
        "path": "features.alarm.states.tamper.value",
        "format": "boolean",
        "type": "binary_sensor",
        "name": "tamper",
        "translation_key": "tamper",
        "device_class": "tamper",
        "device_suffix": "tamper",
    },
    {
        "path": "features.alarm.states.flood.value",
        "format": "boolean",
        "type": "binary_sensor",
        "name": "flood",
        "translation_key": "flood",
        "device_class": "moisture",
        "device_suffix": "flood",
    },
    # Battery sensors
    {
        "path": "features.battery.states.low.value",
        "format": "boolean",
        "type": "binary_sensor",
        "name": "battery_low",
        "translation_key": "battery_low",
        "device_class": "battery",
        "device_suffix": "battery_low",
        "entity_category": "diagnostic",
    },
    {
        "path": "features.battery.states.defect.value",
        "format": "boolean",
        "type": "binary_sensor",
        "name": "battery_defect",
        "translation_key": "battery_defect",
        "device_class": None,
        "device_suffix": "battery_defect",
        "entity_category": "diagnostic",
        "enabled_default": False,
        "icon": "mdi:battery-alert",
    },
    # Practical lock/report sensors (created only when available)
    {
        "path": "features.report.states.doorclosed.value",
        "format": "boolean",
        "type": "binary_sensor",
        "name": "door",
        "translation_key": "door",
        "device_class": "door",
        "device_suffix": "door",
        # Home Assistant door binary_sensor expects "on" = open.
        "invert": True,
    },
    {
        "path": "features.report.states.lowbat.value",
        "format": "boolean",
        "type": "binary_sensor",
        "name": "low_battery",
        "translation_key": "low_battery",
        "device_class": "battery",
        "device_suffix": "report_lowbat",
        "entity_category": "diagnostic",
    },
    {
        "path": "features.report.states.Broken.value",
        "paths": [
            "features.report.states.Broken.value",
            "features.report.states.broken.value",
        ],
        "format": "boolean",
        "type": "binary_sensor",
        "name": "jammed",
        "translation_key": "jammed",
        "device_class": "problem",
        "device_suffix": "jammed",
        "icon": "mdi:lock-alert",
    },
    {
        "path": "features.metering.states.check.value",
        "format": "boolean",
        "type": "binary_sensor",
        "name": "metering_check",
        "translation_key": "metering_check",
        "device_suffix": "metering_check",
        "entity_category": "diagnostic",
        "enabled_default": False,
        "icon": "mdi:counter",
    },
    # Temperature sensors
    {
        "path": "features.temperature.states.temperature.value",
        "format": "number",
        "type": "sensor",
        "name": "temperature",
        "translation_key": "temperature",
        "device_class": "temperature",
        "unit": "°C",
        "device_suffix": "temperature",
        "state_class": "measurement",
    },
    # Lock info sensors
    {
        "path": "features.lock.states.soundvolume.value",
        "format": "string",
        "type": "sensor",
        "name": "sound_volume",
        "translation_key": "sound_volume",
        "device_class": SensorDeviceClass.ENUM,
        "options": SOUND_VOLUME_OPTIONS,
        "device_suffix": "soundvolume",
        "transform_value": _lock_sound_volume_label,
        "icon": "mdi:volume-high",
    },
    {
        "path": "features.lock.states.language.value",
        "format": "string",
        "type": "sensor",
        "name": "language",
        "translation_key": "language",
        "device_class": SensorDeviceClass.ENUM,
        "options": LANGUAGE_OPTIONS,
        "device_suffix": "language",
        "transform_value": _lock_language_label,
        "icon": "mdi:translate",
    },
    # Battery voltage sensors
    {
        "path": "features.battery.states.voltage.value",
        "format": "number",
        "type": "sensor",
        "name": "battery_voltage",
        "translation_key": "battery_voltage",
        "device_class": "voltage",
        "unit": "V",
        "device_suffix": "battery_voltage",
        "entity_category": "diagnostic",
        "enabled_default": False,
    },
    # Diagnostic sensors
    {
        "path": "features.diagnostic.states.networklinkstrength.value",
        "format": "number",
        "type": "sensor",
        "name": "link_quality",
        "translation_key": "link_quality",
        "device_class": None,
        "unit": "%",
        "device_suffix": "networklinkstrength",
        "entity_category": "diagnostic",
        "enabled_default": False,
        "icon": "mdi:wifi",
    },
    {
        "path": "features.diagnostic.states.networklinkaddress.value",
        "format": "string",
        "type": "sensor",
        "name": "network_link_address",
        "translation_key": "network_link_address",
        "device_class": None,
        "device_suffix": "networklinkaddress",
        "entity_category": "diagnostic",
        "enabled_default": False,
        "icon": "mdi:identifier",
    },
    {
        "path": "features.report.states.errorcode.value",
        "format": "string",
        "type": "sensor",
        "name": "error_code",
        "translation_key": "error_code",
        "device_suffix": "error_code",
        "entity_category": "diagnostic",
        "icon": "mdi:alert-circle-outline",
    },
    # Metering sensors (for HAN plugs)
    {
        "path": "features.metering.states.summationdelivered.value",
        "format": "number",
        "type": "sensor",
        "name": "consumption",
        "translation_key": "consumption",
        "device_class": "energy",
        "unit": "kWh",
        "device_suffix": "consumption",
        "state_class": "total_increasing",
        "transform_value": _wh_to_kwh,
    },
    {
        "path": "features.metering.states.summationreceived.value",
        "format": "number",
        "type": "sensor",
        "name": "production",
        "translation_key": "production",
        "device_class": "energy",
        "unit": "kWh",
        "device_suffix": "production",
        "state_class": "total_increasing",
        "transform_value": _wh_to_kwh,
    },
    {
        "path": "features.metering.states.demand.value",
        "format": "number",
        "type": "sensor",
        "name": "demand",
        "translation_key": "demand",
        "device_class": "power",
        "unit": "W",
        "device_suffix": "demand",
        "state_class": "measurement",
    },
]
