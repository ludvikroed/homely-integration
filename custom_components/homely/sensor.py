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
        HomelyWebSocketStatusSensor(coordinator, hass, entry, location_id)
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


class HomelyWebSocketStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for WebSocket connection status."""
    
    def __init__(self, coordinator, hass, entry, location_id):
        """Initialize the WebSocket status sensor."""
        super().__init__(coordinator)
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
        self._status_listener = None

    async def async_added_to_hass(self) -> None:
        """Register for immediate websocket status callbacks."""
        await super().async_added_to_hass()
        try:
            entry_data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
            if entry_data is None:
                return

            def _listener() -> None:
                # Schedule state write on HA loop when websocket status changes.
                if self.hass is not None and self.entity_id is not None:
                    self.async_schedule_update_ha_state()

            listeners = entry_data.setdefault("ws_status_listeners", [])
            listeners.append(_listener)
            self._status_listener = _listener
            self.async_schedule_update_ha_state()
        except Exception:
            pass

    async def async_will_remove_from_hass(self) -> None:
        """Unregister websocket status callback."""
        try:
            entry_data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
            if entry_data is not None and self._status_listener is not None:
                listeners = entry_data.get("ws_status_listeners", [])
                if self._status_listener in listeners:
                    listeners.remove(self._status_listener)
        except Exception:
            pass
        self._status_listener = None
        await super().async_will_remove_from_hass()
    
    @property
    def native_value(self) -> str:
        """Return the WebSocket connection status."""
        try:
            entry_data = self._hass.data[DOMAIN][self._entry.entry_id]
            status = entry_data.get("ws_status")
            if isinstance(status, str) and status:
                return status

            # Fallback if status has not yet been initialized.
            ws = entry_data.get("websocket")
            if ws is None:
                return "Not initialized"
            return "Connected" if ws.is_connected() else "Disconnected"
        except (KeyError, AttributeError):
            return "Unknown"

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose last websocket status reason for debugging."""
        try:
            entry_data = self._hass.data[DOMAIN][self._entry.entry_id]
            reason = entry_data.get("ws_status_reason")
            if reason:
                return {"reason": reason}
        except (KeyError, AttributeError):
            return None
        return None
