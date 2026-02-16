"""Binary sensor platform for Homely."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .sensors.discover import discover_device_sensors, _get_value_by_path


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up binary sensor entities for Homely devices."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    data = coordinator.data or hass.data[DOMAIN][entry.entry_id].get("data") or {}
    
    entities = []
    
    for device in data.get("devices", []):
        # Discover all sensors for this device
        discovered = discover_device_sensors(device)
        
        for sensor_config in discovered:
            # Only add binary sensors
            if sensor_config["type"] == "binary_sensor":
                entities.append(
                    HomelyBinarySensor(coordinator, device, sensor_config)
                )
    
    async_add_entities(entities)


class HomelyBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Homely binary sensor entity."""
    
    def __init__(self, coordinator, device, sensor_config):
        super().__init__(coordinator)
        self._device_id = device.get("id")
        self._path = sensor_config["path"]
        self._device_name = device.get("name")
        
        # Build entity name using resolved name
        sensor_name = sensor_config.get("resolved_name", sensor_config.get("name", "sensor"))
        self._attr_name = f"{self._device_name} {sensor_name.replace('_', ' ').title()}"
        
        # Build unique ID from device suffix
        device_suffix = sensor_config.get("device_suffix", sensor_config["name"])
        self._attr_unique_id = f"{self._device_id}_{device_suffix}"
        
        # Set device class using resolved device class
        device_class = sensor_config.get("resolved_device_class")
        if device_class is None:
            device_class = sensor_config.get("device_class")
        if device_class:
            self._attr_device_class = device_class
        
        # Set icon if provided
        if sensor_config.get("icon"):
            self._attr_icon = sensor_config["icon"]
        
        # Set entity category if provided (diagnostic, config, etc)
        if sensor_config.get("entity_category"):
            category = sensor_config["entity_category"]
            if category == "diagnostic":
                self._attr_entity_category = EntityCategory.DIAGNOSTIC
            elif category == "config":
                self._attr_entity_category = EntityCategory.CONFIG
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer="Homely",
            model=device.get("modelName"),
            serial_number=device.get("serialNumber"),
        )
    
    @property
    def is_on(self):
        """Return True if sensor is on."""
        data = self.coordinator.data or {}
        for device in data.get("devices", []):
            if device.get("id") == self._device_id:
                value = _get_value_by_path(device, self._path)
                return bool(value) if value is not None else False
        return False

