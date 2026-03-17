"""Lock platform for Homely."""
from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .models import get_entry_runtime_data
from .naming import (
    build_suggested_object_id,
    get_device_area,
    get_device_display_name,
)
from .sensors.discover import _get_value_by_path

PARALLEL_UPDATES = 0


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
        if normalized in {"true", "1", "yes", "on", "locked", "lock"}:
            return True
        if normalized in {"false", "0", "no", "off", "unlocked", "unlock"}:
            return False
    return None


def _is_lock_device(device: dict[str, Any]) -> bool:
    """Return True when device payload includes a lock feature."""
    lock_state = _get_value_by_path(device, "features.lock.states.state.value") is not None
    if lock_state:
        return True

    report_locked = _get_value_by_path(device, "features.report.states.locked.value")
    if report_locked is None:
        return False

    report_lock_model = _get_value_by_path(device, "features.report.states.lockmodel.value")
    model_name = str(device.get("modelName", "")).lower()
    looks_like_lock = any(part in model_name for part in ("lock", "doorman", "yale"))
    return report_lock_model is not None or looks_like_lock


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up lock entities for Homely devices."""
    runtime_data = get_entry_runtime_data(entry)
    coordinator = runtime_data.coordinator
    data = coordinator.data or runtime_data.last_data or {}

    entities = []
    for device in data.get("devices", []):
        if _is_lock_device(device):
            entities.append(HomelyLock(coordinator, device))

    async_add_entities(entities)


class HomelyLock(CoordinatorEntity, LockEntity):
    """Read-only lock entity backed by Homely device state."""

    def __init__(self, coordinator, device):
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._device_id = device.get("id")
        self._device_name = get_device_display_name(device)

        self._attr_name = None
        self._attr_unique_id = f"{self._device_id}_lock"
        suggested_object_id = build_suggested_object_id(device, "lock")
        if suggested_object_id:
            self._attr_suggested_object_id = suggested_object_id
        self._attr_icon = "mdi:lock"
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
        data = self.coordinator.data or {}
        for device in data.get("devices", []):
            if device.get("id") == self._device_id:
                return device
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        device = self._get_current_device()
        if not device:
            return False
        online = device.get("online")
        return True if online is None else bool(online)

    @property
    def is_locked(self) -> bool | None:
        """Return True if lock is locked."""
        device = self._get_current_device()
        if not device:
            return None

        state = _get_value_by_path(device, "features.lock.states.state.value")
        if state is None:
            state = _get_value_by_path(device, "features.report.states.locked.value")
        return _coerce_bool(state)

    @property
    def is_jammed(self) -> bool | None:
        """Return whether lock reports jammed/broken state."""
        device = self._get_current_device()
        if not device:
            return None

        jammed = _get_value_by_path(device, "features.report.states.Broken.value")
        if jammed is None:
            jammed = _get_value_by_path(device, "features.report.states.broken.value")
        return _coerce_bool(jammed)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose lock metadata from report states when available."""
        device = self._get_current_device()
        if not device:
            return {}

        attrs: dict[str, Any] = {}
        event = _get_value_by_path(device, "features.report.states.event.value")
        door_closed = _coerce_bool(_get_value_by_path(device, "features.report.states.doorclosed.value"))
        low_battery = _coerce_bool(_get_value_by_path(device, "features.report.states.lowbat.value"))
        part_of_alarm = _coerce_bool(_get_value_by_path(device, "features.report.states.partofalarm.value"))
        lock_model = _get_value_by_path(device, "features.report.states.lockmodel.value")
        error_code = _get_value_by_path(device, "features.report.states.errorcode.value")

        if event is not None:
            attrs["event"] = event
        if door_closed is not None:
            attrs["door_closed"] = door_closed
        if low_battery is not None:
            attrs["low_battery"] = low_battery
        if part_of_alarm is not None:
            attrs["part_of_alarm"] = part_of_alarm
        if lock_model is not None:
            attrs["lock_model"] = lock_model
        if error_code is not None:
            attrs["error_code"] = error_code
        return attrs

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock command is not supported by this integration."""
        raise HomeAssistantError("Lock control is not supported by Homely API")

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock command is not supported by this integration."""
        raise HomeAssistantError("Unlock control is not supported by Homely API")
