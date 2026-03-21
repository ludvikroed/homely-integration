"""Sensor platform for Homely."""

from __future__ import annotations

from typing import Any

import homeassistant.helpers.entity as entity_helper
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import CONF_ENABLE_WEBSOCKET, DEFAULT_ENABLE_WEBSOCKET, DOMAIN
from .device_state import get_current_device, is_device_available
from .models import HomelyConfigEntry, get_entry_runtime_data
from .naming import (
    build_suggested_object_id,
    get_device_area,
    get_device_display_name,
    humanize_label,
)
from .sensors.discover import discover_device_sensors, _get_value_by_path

PARALLEL_UPDATES = 0
SensorConfig = dict[str, Any]
DIAGNOSTIC_ENTITY_CATEGORY = getattr(entity_helper, "EntityCategory").DIAGNOSTIC
CONFIG_ENTITY_CATEGORY = getattr(entity_helper, "EntityCategory").CONFIG


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for Homely devices."""
    runtime_data = get_entry_runtime_data(entry)
    coordinator = runtime_data.coordinator
    data = coordinator.data or runtime_data.last_data or {}
    location_id = runtime_data.location_id

    entities: list[SensorEntity] = []
    entities.append(HomelyWebSocketStatusSensor(coordinator, hass, entry, location_id))

    devices = data.get("devices", [])
    if not isinstance(devices, list):
        devices = []

    for device in devices:
        if not isinstance(device, dict):
            continue
        discovered = discover_device_sensors(device)

        for sensor_config in discovered:
            if sensor_config["type"] == "sensor":
                entities.append(HomelySensor(coordinator, device, sensor_config))

    async_add_entities(entities)


class HomelySensor(CoordinatorEntity, SensorEntity):
    """Homely sensor entity."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        device: dict[str, Any],
        sensor_config: SensorConfig,
    ) -> None:
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._device_id = str(device.get("id"))
        self._path = str(sensor_config["path"])
        self._transform_value = sensor_config.get("transform_value")
        self._device_name = get_device_display_name(device)

        sensor_name = sensor_config.get(
            "resolved_name", sensor_config.get("name", "sensor")
        )
        translation_key = sensor_config.get("resolved_translation_key")
        if translation_key:
            self._attr_translation_key = translation_key
        else:
            self._attr_name = humanize_label(sensor_name)

        device_suffix = sensor_config.get("device_suffix", sensor_config["name"])
        self._attr_unique_id = f"{self._device_id}_{device_suffix}"
        suggested_object_id = build_suggested_object_id(device, device_suffix)
        if suggested_object_id:
            self._attr_suggested_object_id = suggested_object_id
        self._attr_entity_registry_enabled_default = bool(
            sensor_config.get("enabled_default", True)
        )

        if sensor_config.get("device_class"):
            self._attr_device_class = sensor_config["device_class"]

        if sensor_config.get("unit"):
            self._attr_native_unit_of_measurement = sensor_config["unit"]

        if sensor_config.get("state_class"):
            self._attr_state_class = sensor_config["state_class"]

        if sensor_config.get("icon"):
            self._attr_icon = sensor_config["icon"]

        if sensor_config.get("entity_category"):
            category = sensor_config["entity_category"]
            if category == "diagnostic":
                self._attr_entity_category = DIAGNOSTIC_ENTITY_CATEGORY
            elif category == "config":
                self._attr_entity_category = CONFIG_ENTITY_CATEGORY

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer="Homely",
            model=device.get("modelName"),
            serial_number=device.get("serialNumber"),
            suggested_area=get_device_area(device),
        )

    def _get_current_device(self) -> dict[str, Any] | None:
        """Return latest device payload from coordinator cache."""
        return get_current_device(self.coordinator.data, self._device_id)

    @property
    def available(self) -> bool:
        """Return whether the backing Homely device is available."""
        return super().available and is_device_available(self._get_current_device())

    @property
    def native_value(self) -> Any:
        """Return the current sensor value."""
        device = self._get_current_device()
        if not device:
            return None

        value = _get_value_by_path(device, self._path)
        if callable(self._transform_value):
            try:
                return self._transform_value(value)
            except (TypeError, ValueError):
                return value
        return value


class HomelyWebSocketStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for WebSocket connection status."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        hass: HomeAssistant,
        entry: HomelyConfigEntry,
        location_id: str,
    ) -> None:
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
        location_name = str(
            (self._runtime_data.last_data or {}).get("name", "Location")
        )

        self._attr_translation_key = "websocket_status"
        self._attr_unique_id = f"location_{location_id}_websocket_status"
        self._attr_icon = "mdi:web"
        self._attr_entity_category = DIAGNOSTIC_ENTITY_CATEGORY
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
        self._status_listener: Any = None

    async def async_added_to_hass(self) -> None:
        """Register for immediate websocket status callbacks."""
        await super().async_added_to_hass()
        listeners = getattr(self._runtime_data, "ws_status_listeners", None)
        if not isinstance(listeners, list):
            return

        def _listener() -> None:
            # Schedule state writes on the Home Assistant event loop.
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
