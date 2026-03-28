"""Aggregated battery health sensor for Homely."""

from __future__ import annotations

from typing import Any

import homeassistant.helpers.entity as entity_helper
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .entity_ids import battery_problem_unique_id

AGGREGATE_SENSOR_NAME = "Status of batteries"
DIAGNOSTIC_ENTITY_CATEGORY = getattr(entity_helper, "EntityCategory").DIAGNOSTIC


def _is_true(value: Any) -> bool:
    """Return True for common true-like API values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return False


class HomelyAllBatteriesHealthySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor that is on when any battery reports low/defective."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        location_name: str,
        location_id: str | int,
    ) -> None:
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_name = AGGREGATE_SENSOR_NAME
        self._attr_unique_id = battery_problem_unique_id(location_id)
        self._attr_icon = "mdi:battery-alert"
        self._attr_entity_category = DIAGNOSTIC_ENTITY_CATEGORY
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"location_{location_id}")},
            name=location_name,
            manufacturer="Homely",
            model="Location",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        """Return True when any device reports battery issue."""
        data = self.coordinator.data or {}
        devices = data.get("devices", [])
        if not isinstance(devices, list):
            return False

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

            battery_defect = battery.get("defect", {}).get("value")
            battery_low = battery.get("low", {}).get("value")
            # Some lock devices (e.g. Yale Doorman) report battery state under report.lowbat.
            report_feature = features.get("report", {})
            if isinstance(report_feature, dict):
                report_states = report_feature.get("states", {})
            else:
                report_states = {}
            if not isinstance(report_states, dict):
                report_states = {}
            report_low_battery = report_states.get("lowbat", {}).get("value")
            if (
                _is_true(battery_defect)
                or _is_true(battery_low)
                or _is_true(report_low_battery)
            ):
                return True
        return False

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Expose human-friendly aggregate status."""
        return {"status": "Defective" if self.is_on else "Healthy"}
