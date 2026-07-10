"""Aggregated battery health sensor for Homely."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .entity_ids import battery_problem_unique_id

DIAGNOSTIC_ENTITY_CATEGORY = EntityCategory.DIAGNOSTIC


def _as_bool(value: Any) -> bool | None:
    """Return a parsed API boolean, or None when the value is unknown."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


def _is_true(value: Any) -> bool:
    """Return True for common true-like API values."""
    return _as_bool(value) is True


def _state_value(states: dict[str, Any], state_name: str) -> Any:
    """Return a nested state value without trusting payload shape."""
    state = states.get(state_name)
    return state.get("value") if isinstance(state, dict) else None


class HomelyAllBatteriesHealthySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor that is on when any battery reports low/defective."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        location_name: str,
        location_id: str | int,
        fallback_data_getter: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._fallback_data_getter = fallback_data_getter
        self._attr_has_entity_name = True
        self._attr_translation_key = "any_battery_problem"
        self._attr_unique_id = battery_problem_unique_id(location_id)
        self._attr_icon = "mdi:battery-alert"
        self._attr_entity_category = DIAGNOSTIC_ENTITY_CATEGORY
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"location_{location_id}")},
            name=location_name,
            manufacturer="Homely",
            model="Homely",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        """Return whether there is a location snapshot to aggregate."""
        data = self._location_data()
        return (
            super().available
            and isinstance(data, dict)
            and isinstance(data.get("devices"), list)
        )

    @property
    def is_on(self) -> bool | None:
        """Return True when any device reports battery issue."""
        data = self._location_data() or {}
        devices = data.get("devices", [])
        if not isinstance(devices, list):
            return None

        has_known_battery_state = False
        for device in devices:
            if not isinstance(device, dict):
                continue

            features = device.get("features", {})
            if not isinstance(features, dict):
                continue

            battery_feature = features.get("battery", {})
            if isinstance(battery_feature, dict):
                battery = battery_feature.get("states", {})
            else:
                battery = {}
            if not isinstance(battery, dict):
                battery = {}

            battery_defect = _state_value(battery, "defect")
            battery_low = _state_value(battery, "low")
            # Some lock devices (e.g. Yale Doorman) report battery state under report.lowbat.
            report_feature = features.get("report", {})
            if isinstance(report_feature, dict):
                report_states = report_feature.get("states", {})
            else:
                report_states = {}
            if not isinstance(report_states, dict):
                report_states = {}
            report_low_battery = _state_value(report_states, "lowbat")
            parsed_values = (
                _as_bool(battery_defect),
                _as_bool(battery_low),
                _as_bool(report_low_battery),
            )
            if any(value is True for value in parsed_values):
                return True
            if any(value is not None for value in parsed_values):
                has_known_battery_state = True
        return False if has_known_battery_state else None

    def _location_data(self) -> dict[str, Any] | None:
        """Return current data, falling back to the last stored snapshot."""
        data: Any = self.coordinator.data
        if isinstance(data, dict):
            return data
        if self._fallback_data_getter is None:
            return None
        fallback_data = self._fallback_data_getter()
        return fallback_data if isinstance(fallback_data, dict) else None
