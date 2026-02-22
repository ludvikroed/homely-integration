"""Aggregated battery health sensor for Homely."""
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .entity_ids import battery_problem_unique_id

AGGREGATE_SENSOR_NAME = "Status of batteries"

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
            if battery_defect or battery_low:
                return True
        return False

    @property
    def extra_state_attributes(self):
        """Expose human-friendly aggregate status."""
        return {"status": "Defective" if self.is_on else "Healthy"}
