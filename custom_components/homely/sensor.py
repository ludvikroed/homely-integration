"""Sensor platform for Homely."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .sensors.discover import discover_device_sensors, _get_value_by_path


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensor entities for Homely devices."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    data = coordinator.data or hass.data[DOMAIN][entry.entry_id].get("data") or {}
    location_id = hass.data[DOMAIN][entry.entry_id].get("location_id")
    
    entities = []
    
    # Add WebSocket status sensor (location-level)
    entities.append(
        HomelyWebSocketStatusSensor(hass, entry, location_id)
    )
    
    for device in data.get("devices", []):
        # Discover all sensors for this device
        discovered = discover_device_sensors(device)
        
        for sensor_config in discovered:
            # Only add number/string sensors (not binary sensors)
            if sensor_config["type"] == "sensor":
                entities.append(
                    HomelyySensor(coordinator, device, sensor_config)
                )
    
    async_add_entities(entities)


class HomelyySensor(CoordinatorEntity, SensorEntity):
    """Homely sensor entity."""
    
    def __init__(self, coordinator, device, sensor_config):
        super().__init__(coordinator)
        self._device_id = device.get("id")
        self._path = sensor_config["path"]
        self._device_name = device.get("name")
        
        # Build entity name
        sensor_name = sensor_config.get("name", "sensor")
        self._attr_name = f"{self._device_name} {sensor_name.replace('_', ' ').title()}"
        
        # Build unique ID from device suffix
        device_suffix = sensor_config.get("device_suffix", sensor_config["name"])
        self._attr_unique_id = f"{self._device_id}_{device_suffix}"
        
        # Set device class
        if sensor_config.get("device_class"):
            self._attr_device_class = sensor_config["device_class"]
        
        # Set unit
        if sensor_config.get("unit"):
            self._attr_native_unit_of_measurement = sensor_config["unit"]
        
        # Set state class if provided (measurement, total, etc)
        if sensor_config.get("state_class"):
            self._attr_state_class = sensor_config["state_class"]
        
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
    def native_value(self):
        """Return the current sensor value."""
        data = self.coordinator.data or {}
        for device in data.get("devices", []):
            if device.get("id") == self._device_id:
                return _get_value_by_path(device, self._path)
        return None


class HomelyWebSocketStatusSensor(SensorEntity):
    """Sensor for WebSocket connection status."""
    
    def __init__(self, hass, entry, location_id):
        """Initialize the WebSocket status sensor."""
        self._hass = hass
        self._entry = entry
        self._location_id = location_id
        location_name = (hass.data[DOMAIN][entry.entry_id].get("data") or {}).get("name", "Location")
        
        self._attr_name = f"{location_name} WebSocket Status"
        self._attr_unique_id = f"location_{location_id}_websocket_status"
        self._attr_icon = "mdi:web"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"location_{location_id}")},
            name=location_name,
            manufacturer="Homely",
            model="Location",
        )
    
    @property
    def native_value(self) -> str:
        """Return the WebSocket connection status."""
        try:
            entry_data = self._hass.data[DOMAIN][self._entry.entry_id]
            ws = entry_data.get("websocket")
            
            if ws is None:
                return "Not initialized"
            elif ws.is_connected():
                return "Connected"
            else:
                return "Disconnected"
        except (KeyError, AttributeError):
            return "Unknown"
