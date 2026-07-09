"""Alarm control panel for Homely."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.alarm_control_panel import AlarmControlPanelEntity
from homeassistant.components.alarm_control_panel.const import (
    AlarmControlPanelState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .models import HomelyConfigEntry, HomelyRuntimeData, get_entry_runtime_data
from .runtime_state import LAST_DISARMED_CACHE_KEY

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0

STATE_MAP: dict[str, AlarmControlPanelState] = {
    # Main states
    "DISARMED": AlarmControlPanelState.DISARMED,
    "ARMED_AWAY": AlarmControlPanelState.ARMED_AWAY,
    "ARMED_NIGHT": AlarmControlPanelState.ARMED_NIGHT,
    "ARMED_STAY": AlarmControlPanelState.ARMED_HOME,
    "ARMED_PARTLY": AlarmControlPanelState.ARMED_HOME,
    # Pending/transitional states
    "ARM_PENDING": AlarmControlPanelState.ARMING,
    "ARM_STAY_PENDING": AlarmControlPanelState.ARMING,
    "ARM_NIGHT_PENDING": AlarmControlPanelState.ARMING,
    "ALARM_PENDING": AlarmControlPanelState.ARMING,
    "ALARM_STAY_PENDING": AlarmControlPanelState.ARMING,
    "ARMED_NIGHT_PENDING": AlarmControlPanelState.ARMING,
    "ARMED_AWAY_PENDING": AlarmControlPanelState.ARMING,
    "TRIGGERED": AlarmControlPanelState.TRIGGERED,
    "BREACHED": AlarmControlPanelState.TRIGGERED,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomelyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Homely alarm panel entity."""
    runtime_data = get_entry_runtime_data(entry)
    coordinator = runtime_data.coordinator
    location_id = runtime_data.location_id

    def _fallback_data_getter() -> dict[str, Any] | None:
        return runtime_data.last_data

    async_add_entities(
        [
            HomelyAlarmPanel(
                coordinator,
                location_id,
                runtime_data=runtime_data,
                fallback_data_getter=_fallback_data_getter,
            )
        ]
    )


class HomelyAlarmPanel(CoordinatorEntity, AlarmControlPanelEntity):
    """Read-only alarm state for a Homely location."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        location_id: str,
        runtime_data: HomelyRuntimeData | None = None,
        fallback_data_getter: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._runtime_data = runtime_data
        self._fallback_data_getter = fallback_data_getter
        self._attr_has_entity_name = True
        self._location_id = location_id
        self._last_unknown_state: str | None = None
        location_name = str(
            (coordinator.data or {}).get("name") or f"Homely location {location_id}"
        )
        self._attr_name = None
        self._attr_unique_id = f"location_{location_id}_alarm_panel"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"location_{location_id}")},
            name=location_name,
            manufacturer="Homely",
            model="Homely",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Return the mapped alarm state."""
        data = self._location_data()

        # Top-level alarmState is present in polling responses and updated by websocket helpers.
        api_state = data.get("alarmState")

        # Fallback to nested features path for older payload variants.
        if api_state is None:
            api_state = (
                data.get("features", {})
                .get("alarm", {})
                .get("states", {})
                .get("alarm", {})
                .get("value")
            )

        if api_state is not None:
            mapped_state = STATE_MAP.get(str(api_state))
            if mapped_state:
                self._last_unknown_state = None
                return mapped_state
            api_state_str = str(api_state)
            if api_state_str != self._last_unknown_state:
                self._last_unknown_state = api_state_str
                location_hint = (
                    self._location_id
                    if len(self._location_id) <= 8
                    else f"{self._location_id[:8]}..."
                )
                _LOGGER.warning(
                    "Unknown alarm state from API location=%s state=%s. Please open a GitHub issue if this keeps happening.",
                    location_hint,
                    api_state_str,
                )
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return metadata for the last known disarm event."""
        attrs = self._last_disarmed_attrs()
        return attrs or None

    def _location_data(self) -> dict[str, Any]:
        """Return current location data, with cached data as fallback."""
        data: Any = self.coordinator.data
        if not data and self._fallback_data_getter is not None:
            data = self._fallback_data_getter()
        return data if isinstance(data, dict) else {}

    def _last_disarmed_attrs(self) -> dict[str, Any]:
        """Return alarm-panel attributes for the last DISARMED event."""
        runtime_data = self._runtime_data
        if runtime_data is not None:
            attrs: dict[str, Any] = {}
            if runtime_data.last_disarmed_by:
                attrs["last_disarmed_by"] = runtime_data.last_disarmed_by
            if runtime_data.last_disarmed_user_id:
                attrs["last_disarmed_user_id"] = runtime_data.last_disarmed_user_id
            if runtime_data.last_disarmed_at:
                attrs["last_disarmed_at"] = runtime_data.last_disarmed_at
            if runtime_data.last_disarmed_event_id is not None:
                attrs["last_disarmed_event_id"] = runtime_data.last_disarmed_event_id
            if runtime_data.last_disarmed_device_id:
                attrs["last_disarmed_device_id"] = runtime_data.last_disarmed_device_id
            return attrs

        last_disarmed = self._location_data().get(LAST_DISARMED_CACHE_KEY)
        if not isinstance(last_disarmed, dict):
            return {}

        attrs = {}
        user_name = last_disarmed.get("user_name") or last_disarmed.get("userName")
        user_id = last_disarmed.get("user_id") or last_disarmed.get("userId")
        disarmed_at = last_disarmed.get("timestamp") or last_disarmed.get("time")
        event_id = last_disarmed.get("event_id") or last_disarmed.get("eventId")
        device_id = last_disarmed.get("device_id") or last_disarmed.get("deviceId")
        if user_name:
            attrs["last_disarmed_by"] = user_name
        if user_id:
            attrs["last_disarmed_user_id"] = user_id
        if disarmed_at:
            attrs["last_disarmed_at"] = disarmed_at
        if event_id is not None:
            attrs["last_disarmed_event_id"] = event_id
        if device_id:
            attrs["last_disarmed_device_id"] = device_id
        return attrs
