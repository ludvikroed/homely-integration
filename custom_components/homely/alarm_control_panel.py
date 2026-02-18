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

_LOGGER = logging.getLogger(__name__)

STATE_MAP = {
    # Main states
    "DISARMED": AlarmControlPanelState.DISARMED,
    "ARMED_AWAY": AlarmControlPanelState.ARMED_AWAY,
    "ARMED_NIGHT": AlarmControlPanelState.ARMED_NIGHT,
    "ARMED_STAY": AlarmControlPanelState.ARMED_HOME,
    # Pending/transitional states
    "ARM_PENDING": AlarmControlPanelState.ARMING,
    "ARM_STAY_PENDING": AlarmControlPanelState.ARMING,
    "ARM_NIGHT_PENDING": AlarmControlPanelState.ARMING,

    "TRIGGERED": AlarmControlPanelState.TRIGGERED,
    "BREACHED": AlarmControlPanelState.TRIGGERED,
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    location_id = hass.data[DOMAIN][entry.entry_id].get("location_id")
    async_add_entities([HomelyAlarmPanel(coordinator, location_id)])


class HomelyAlarmPanel(CoordinatorEntity, AlarmControlPanelEntity):
    def __init__(self, coordinator, location_id):
        super().__init__(coordinator)
        location_name = (coordinator.data or {}).get("name", "Location")
        self._attr_name = f"{location_name} Alarm"
        self._attr_unique_id = f"location_{location_id}_alarm_panel"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"location_{location_id}")},
            name=location_name,
            manufacturer="Homely",
            model="Location",
        )

    @property
    def state(self):
        data = self.coordinator.data or {}
        
        # Try to get alarm state from features (WebSocket source)
        api_state = data.get("features", {}).get("alarm", {}).get("states", {}).get("alarm", {}).get("value")
        
        # Fallback to alarmState field
        if not api_state:
            api_state = data.get("alarmState")
        
        if api_state:
            mapped_state = STATE_MAP.get(api_state)
            if mapped_state:
                return mapped_state
            else:
                _LOGGER.warning("Unknown alarm state from API: %s", api_state)
                return None
        
        _LOGGER.debug("No alarm state found in coordinator data")
        return None
