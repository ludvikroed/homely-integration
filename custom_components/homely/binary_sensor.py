"""Binary sensor platform for Homely."""

from __future__ import annotations

from typing import Any

import homeassistant.helpers.entity as entity_helper
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .models import HomelyConfigEntry, get_entry_runtime_data
from .naming import (
    build_suggested_object_id,
    get_device_area,
    get_device_display_name,
    humanize_label,
)
from .all_batteries_healthy import HomelyAllBatteriesHealthySensor
from .device_state import get_current_device, is_device_available
from .sensors.discover import discover_device_sensors, _get_value_by_path

PARALLEL_UPDATES = 0
SensorConfig = dict[str, Any]
DIAGNOSTIC_ENTITY_CATEGORY = getattr(entity_helper, "EntityCategory").DIAGNOSTIC
CONFIG_ENTITY_CATEGORY = getattr(entity_helper, "EntityCategory").CONFIG


def _coerce_bool(value: Any) -> bool | None:
    """Convert common API bool-like values to bool."""
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
        if normalized in {"true", "1", "yes", "on", "locked", "open"}:
            return True
        if normalized in {"false", "0", "no", "off", "unlocked", "closed"}:
            return False
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities for Homely devices."""
    runtime_data = get_entry_runtime_data(entry)
    coordinator = runtime_data.coordinator
    data = coordinator.data or runtime_data.last_data or {}

    entities: list[BinarySensorEntity] = []

    devices = data.get("devices", [])
    if not isinstance(devices, list):
        devices = []

    for device in devices:
        if not isinstance(device, dict):
            continue
        discovered = discover_device_sensors(device)
        for sensor_config in discovered:
            if sensor_config["type"] == "binary_sensor":
                entities.append(HomelyBinarySensor(coordinator, device, sensor_config))
        entities.append(HomelyDeviceOnlineSensor(coordinator, device))
    location_id = runtime_data.location_id
    location_name = (data or {}).get("name", "Location")
    entities.append(
        HomelyAllBatteriesHealthySensor(
            coordinator,
            str(location_name),
            location_id,
        )
    )

    async_add_entities(entities)


class HomelyDeviceOnlineSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for device online status."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        device: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._device_id = str(device.get("id"))
        self._device_name = get_device_display_name(device)
        self._attr_translation_key = "online"
        self._attr_unique_id = f"{self._device_id}_online"
        suggested_object_id = build_suggested_object_id(device, "online")
        if suggested_object_id:
            self._attr_suggested_object_id = suggested_object_id
        self._attr_icon = "mdi:lan-connect"
        self._attr_entity_category = DIAGNOSTIC_ENTITY_CATEGORY
        self._attr_entity_registry_enabled_default = False
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
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
        """Return whether the entity still has a backing device."""
        return super().available and self._get_current_device() is not None

    @property
    def is_on(self) -> bool:
        """Return True if device is online."""
        device = self._get_current_device()
        if not device:
            return False

        return bool(device.get("online", False))


class HomelyBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Homely binary sensor entity."""

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
        self._invert = bool(sensor_config.get("invert", False))
        self._transform_value = sensor_config.get("transform_value")
        self._transform_device_value = sensor_config.get("transform_device_value")
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

        device_class = sensor_config.get("resolved_device_class")
        if device_class is None:
            device_class = sensor_config.get("device_class")
        if device_class:
            self._attr_device_class = device_class

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
    def is_on(self) -> bool:
        """Return True if sensor is on."""
        device = self._get_current_device()
        if not device:
            return False

        value = _get_value_by_path(device, self._path)
        if callable(self._transform_device_value):
            try:
                value = self._transform_device_value(device, value)
            except (TypeError, ValueError):
                pass
        elif callable(self._transform_value):
            try:
                value = self._transform_value(value)
            except (TypeError, ValueError):
                pass
        parsed = _coerce_bool(value)
        if parsed is None:
            return False
        return not parsed if self._invert else parsed
