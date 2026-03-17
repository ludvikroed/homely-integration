"""Sensor platform for Homely."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET, DOMAIN
from .models import get_entry_runtime_data
from .naming import (
    build_suggested_object_id,
    get_device_area,
    get_device_display_name,
    humanize_label,
)
from .sensors.discover import discover_device_sensors, _get_value_by_path

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensor entities for Homely devices."""
    runtime_data = get_entry_runtime_data(entry)
    coordinator = runtime_data.coordinator
    data = coordinator.data or runtime_data.last_data or {}
    location_id = runtime_data.location_id
    
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
                    HomelySensor(coordinator, device, sensor_config)
                )
    
    async_add_entities(entities)


class HomelySensor(CoordinatorEntity, SensorEntity):
    """Homely sensor entity."""
    
    def __init__(self, coordinator, device, sensor_config):
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._device_id = device.get("id")
        self._path = sensor_config["path"]
        self._transform_value = sensor_config.get("transform_value")
        self._device_name = get_device_display_name(device)
        
        # Build entity name
        sensor_name = sensor_config.get("resolved_name", sensor_config.get("name", "sensor"))
        translation_key = sensor_config.get("resolved_translation_key")
        if translation_key:
            self._attr_translation_key = translation_key
        else:
            self._attr_name = humanize_label(sensor_name)
        
        # Build unique ID from device suffix
        device_suffix = sensor_config.get("device_suffix", sensor_config["name"])
        self._attr_unique_id = f"{self._device_id}_{device_suffix}"
        suggested_object_id = build_suggested_object_id(device, device_suffix)
        if suggested_object_id:
            self._attr_suggested_object_id = suggested_object_id
        self._attr_entity_registry_enabled_default = bool(
            sensor_config.get("enabled_default", True)
        )
        
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
            suggested_area=get_device_area(device),
        )
    
    @property
    def native_value(self):
        """Return the current sensor value."""
        data = self.coordinator.data or {}
        for device in data.get("devices", []):
            if device.get("id") == self._device_id:
                value = _get_value_by_path(device, self._path)
                if callable(self._transform_value):
                    try:
                        return self._transform_value(value)
                    except (TypeError, ValueError):
                        return value
                return value
        return None


class HomelyWebSocketStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for WebSocket connection status."""
    
    def __init__(self, coordinator, hass, entry, location_id):
        """Initialize the WebSocket status sensor."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._runtime_data = get_entry_runtime_data(entry)
        self._websocket_enabled = bool(
            entry.options.get(
                CONF_ENABLE_WEBSOCKET,
                entry.data.get(CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET),
            )
        )
        self._location_id = location_id
        location_name = (self._runtime_data.last_data or {}).get("name", "Location")
        
        self._attr_translation_key = "websocket_status"
        self._attr_unique_id = f"location_{location_id}_websocket_status"
        self._attr_icon = "mdi:web"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_entity_registry_enabled_default = False
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = [
            "Disabled",
            "Not initialized",
            "Connecting",
            "Connected",
            "Disconnected",
            "Unknown",
        ]
        
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
        listeners = getattr(self._runtime_data, "ws_status_listeners", None)
        if not isinstance(listeners, list):
            return

        def _listener() -> None:
            # Schedule state write on HA loop when websocket status changes.
            if self.hass is not None and self.entity_id is not None:
                self.async_schedule_update_ha_state()

        listeners.append(_listener)
        self._status_listener = _listener
        self.async_schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Unregister websocket status callback."""
        listeners = getattr(self._runtime_data, "ws_status_listeners", None)
        if isinstance(listeners, list) and self._status_listener in listeners:
            listeners.remove(self._status_listener)
        self._status_listener = None
        await super().async_will_remove_from_hass()
    
    @property
    def native_value(self) -> str:
        """Return the WebSocket connection status."""
        try:
            if not self._websocket_enabled:
                return "Disabled"

            status = self._runtime_data.ws_status
            if isinstance(status, str) and status:
                return status

            # Fallback if status has not yet been initialized.
            ws = self._runtime_data.websocket
            if ws is None:
                return "Not initialized"
            return "Connected" if ws.is_connected() else "Disconnected"
        except (AttributeError, ValueError):
            return "Unknown"

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose last websocket status reason for debugging."""
        try:
            reason = self._runtime_data.ws_status_reason
            if reason:
                return {"reason": reason}
        except (AttributeError, ValueError):
            return None
        return None
