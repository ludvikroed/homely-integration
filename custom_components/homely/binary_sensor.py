"""Binary sensor platform for Homely."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
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
DIAGNOSTIC_ENTITY_CATEGORY = EntityCategory.DIAGNOSTIC
CONFIG_ENTITY_CATEGORY = EntityCategory.CONFIG


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

    def _last_data() -> dict[str, Any] | None:
        return runtime_data.last_data

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
                entities.append(HomelyBinarySensor(coordinator, device, sensor_config, _last_data))
        entities.append(HomelyDeviceOnlineSensor(coordinator, device, _last_data))
    location_id = runtime_data.location_id
    location_name = (data or {}).get("name", "Location")
    entities.append(
        HomelyAllBatteriesHealthySensor(
            coordinator,
            str(location_name),
            location_id,
            fallback_data_getter=_last_data,
        )
    )

    async_add_entities(entities)


class HomelyDeviceOnlineSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for device online status."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        device: dict[str, Any],
        fallback_data_getter: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._fallback_data_getter = fallback_data_getter
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
        self._attr_entity_registry_enabled_default = True
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
        """Return latest device payload from coordinator or last-known cache."""
        data: dict[str, Any] | None = self.coordinator.data
        if data is None and self._fallback_data_getter is not None:
            data = self._fallback_data_getter()
        return get_current_device(data, self._device_id)

    @property
    def available(self) -> bool:
        """Return whether the entity still has a backing device."""
        return super().available and self._get_current_device() is not None

    @property
    def is_on(self) -> bool | None:
        """Return True if device is online."""
        device = self._get_current_device()
        if not device:
            return None

        return _coerce_bool(device.get("online"))


class HomelyBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Homely binary sensor entity."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        device: dict[str, Any],
        sensor_config: SensorConfig,
        fallback_data_getter: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._fallback_data_getter = fallback_data_getter
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
        """Return latest device payload from coordinator or last-known cache."""
        data: dict[str, Any] | None = self.coordinator.data
        if data is None and self._fallback_data_getter is not None:
            data = self._fallback_data_getter()
        return get_current_device(data, self._device_id)

    @property
    def available(self) -> bool:
        """Return whether the backing Homely device is available."""
        return super().available and is_device_available(self._get_current_device())

    @property
    def is_on(self) -> bool | None:
        """Return True if sensor is on."""
        device = self._get_current_device()
        if not device:
            return None

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
            return None
        return not parsed if self._invert else parsed
