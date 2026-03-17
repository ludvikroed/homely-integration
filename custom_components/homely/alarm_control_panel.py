"""Alarm control panel for Homely."""
from __future__ import annotations

import logging
from homeassistant.components.alarm_control_panel import AlarmControlPanelEntity
from homeassistant.components.alarm_control_panel.const import (
    AlarmControlPanelState,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .models import get_entry_runtime_data

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0

STATE_MAP = {
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


async def async_setup_entry(hass, entry, async_add_entities):
    runtime_data = get_entry_runtime_data(entry)
    coordinator = runtime_data.coordinator
    location_id = runtime_data.location_id
    async_add_entities([HomelyAlarmPanel(coordinator, location_id)])


class HomelyAlarmPanel(CoordinatorEntity, AlarmControlPanelEntity):
    def __init__(self, coordinator, location_id):
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._location_id = location_id
        self._last_unknown_state: str | None = None
        location_name = (coordinator.data or {}).get("name") or f"Homely location {location_id}"
        self._attr_name = None
        self._attr_unique_id = f"location_{location_id}_alarm_panel"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"location_{location_id}")},
            name=location_name,
            manufacturer="Homely",
            model="Location",
        )

    @property
    def alarm_state(self):
        data = self.coordinator.data or {}
        
        # Top-level alarmState is present in polling responses and updated by websocket helpers.
        api_state = data.get("alarmState")
        
        # Fallback to nested features path for older payload variants.
        if api_state is None:
            api_state = data.get("features", {}).get("alarm", {}).get("states", {}).get("alarm", {}).get("value")
        
        if api_state is not None:
            mapped_state = STATE_MAP.get(api_state)
            if mapped_state:
                self._last_unknown_state = None
                return mapped_state
            if api_state != self._last_unknown_state:
                self._last_unknown_state = api_state
                _LOGGER.warning(
                    "Unknown alarm state from API location_id=%s state=%s",
                    self._location_id,
                    api_state,
                )
        return None
