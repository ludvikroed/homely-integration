"""Number platform for Homely: HAN meter multiplier setting."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .meter_multiplier import (
    METER_MULTIPLIER_MAX,
    METER_MULTIPLIER_MIN,
    METER_MULTIPLIER_STEP,
    get_meter_multiplier,
    options_with_meter_multiplier,
)
from .models import HomelyConfigEntry, get_entry_runtime_data
from .naming import build_device_info, build_suggested_object_id

PARALLEL_UPDATES = 0
METER_MULTIPLIER_SUFFIX = "meter_multiplier"


def _has_metering(device: dict[str, Any]) -> bool:
    """Return whether a device payload exposes HAN metering data."""
    features = device.get("features")
    return isinstance(features, dict) and isinstance(features.get("metering"), dict)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a meter multiplier setting for each HAN meter."""
    runtime_data = get_entry_runtime_data(entry)
    coordinator = runtime_data.coordinator
    data = coordinator.data or runtime_data.last_data or {}

    devices = data.get("devices", [])
    if not isinstance(devices, list):
        devices = []

    async_add_entities(
        HomelyMeterMultiplierNumber(coordinator, entry, device)
        for device in devices
        if isinstance(device, dict) and _has_metering(device)
    )


class HomelyMeterMultiplierNumber(CoordinatorEntity, NumberEntity):
    """Multiplier applied to a HAN meter's energy and power readings.

    Meters behind current transformers report values divided by the
    transformer ratio when the ratio is not set on the meter itself.
    """

    _attr_has_entity_name = True
    _attr_translation_key = METER_MULTIPLIER_SUFFIX
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = METER_MULTIPLIER_MIN
    _attr_native_max_value = METER_MULTIPLIER_MAX
    _attr_native_step = METER_MULTIPLIER_STEP
    _attr_icon = "mdi:multiplication"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        entry: HomelyConfigEntry,
        device: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = str(device.get("id"))
        self._attr_unique_id = f"{self._device_id}_{METER_MULTIPLIER_SUFFIX}"
        suggested_object_id = build_suggested_object_id(
            device, METER_MULTIPLIER_SUFFIX
        )
        if suggested_object_id:
            self._attr_suggested_object_id = suggested_object_id
        self._attr_device_info = build_device_info(device)

    @property
    def native_value(self) -> float:
        """Return the current multiplier."""
        return get_meter_multiplier(self._entry.options, self._device_id)

    async def async_set_native_value(self, value: float) -> None:
        """Store the new multiplier and re-render the meter sensors."""
        try:
            options = options_with_meter_multiplier(
                self._entry.options, self._device_id, value
            )
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc
        self.hass.config_entries.async_update_entry(
            self._entry,
            options=options,
        )
        self.coordinator.async_update_listeners()
