"""Aggregated battery health sensor for Homely."""
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .entity_ids import battery_problem_unique_id

AGGREGATE_SENSOR_NAME = "Status of batteries"


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
    def __init__(self, coordinator, location_name, location_id):
        super().__init__(coordinator)
        self._attr_name = AGGREGATE_SENSOR_NAME
        self._attr_unique_id = battery_problem_unique_id(location_id)
        self._attr_icon = "mdi:battery-alert"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_class = "problem"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"location_{location_id}")},
            name=location_name,
            manufacturer="Homely",
            model="Location",
        )

    @property
    def is_on(self):
        """Return True when any device reports battery issue."""
        data = self.coordinator.data or {}
        for device in data.get("devices", []):
            battery = device.get("features", {}).get("battery", {}).get("states", {})
            battery_defect = battery.get("defect", {}).get("value")
            battery_low = battery.get("low", {}).get("value")
            # Some lock devices (e.g. Yale Doorman) report battery state under report.lowbat.
            report_states = device.get("features", {}).get("report", {}).get("states", {})
            report_low_battery = report_states.get("lowbat", {}).get("value")
            if _is_true(battery_defect) or _is_true(battery_low) or _is_true(report_low_battery):
                return True
        return False

    @property
    def extra_state_attributes(self):
        """Expose human-friendly aggregate status."""
        return {"status": "Defective" if self.is_on else "Healthy"}
