"""Aggregated battery health sensor for Homely."""
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

AGGREGATE_SENSOR_NAME = "Status of batteries"
AGGREGATE_SENSOR_UNIQUE_ID = "any_battery_problem"

class HomelyAllBatteriesHealthySensor(CoordinatorEntity, BinarySensorEntity):
    """Sensor that reports 'problem' if any battery is defective, otherwise 'good'."""
    def __init__(self, coordinator, location_name, location_id):
        super().__init__(coordinator)
        self._attr_name = AGGREGATE_SENSOR_NAME
        self._attr_unique_id = AGGREGATE_SENSOR_UNIQUE_ID
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
        # Deprecated for compatibility, always False (use state property)
        return None

    @property
    def state(self):
        data = self.coordinator.data or {}
        for device in data.get("devices", []):
            battery = device.get("features", {}).get("battery", {}).get("states", {})
            battery_defect = battery.get("defect", {}).get("value")
            battery_low = battery.get("low", {}).get("value")
            if battery_defect or battery_low:
                return "Defective"
        return "Healthy"
