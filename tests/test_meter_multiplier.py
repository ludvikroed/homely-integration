"""Tests for the HAN meter multiplier (current transformer ratio) setting."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import homeassistant.helpers.entity as entity_helper
from homeassistant.components.number import NumberMode

from custom_components.homely import async_reload_entry
from custom_components.homely.const import CONF_METER_MULTIPLIERS
from custom_components.homely.meter_multiplier import (
    get_meter_multiplier,
    options_without_meter_multipliers,
)
from custom_components.homely.number import (
    HomelyMeterMultiplierNumber,
    async_setup_entry,
)
from custom_components.homely.sensor import HomelySensor
from custom_components.homely.sensors.discover import discover_device_sensors
from tests.common import LOCATION_ID, build_config_entry

HAN_DEVICE_INDEX = 4
MOTION_DEVICE_INDEX = 0


def _coordinator(location_data):
    coordinator = MagicMock()
    coordinator.data = location_data
    coordinator.last_update_success = True
    return coordinator


def _sensor(location_data, device_index, suffix, multiplier=None):
    device = location_data["devices"][device_index]
    config = next(
        sensor
        for sensor in discover_device_sensors(device)
        if sensor["device_suffix"] == suffix
    )
    getter = None if multiplier is None else (lambda _device_id: multiplier)
    return HomelySensor(
        _coordinator(location_data),
        device,
        config,
        meter_multiplier_getter=getter,
    )


def test_get_meter_multiplier_defaults_to_one():
    """Devices without a stored multiplier report unscaled values."""
    assert get_meter_multiplier({}, "device-1") == 1.0
    assert get_meter_multiplier({CONF_METER_MULTIPLIERS: {}}, "device-1") == 1.0


def test_get_meter_multiplier_reads_stored_value():
    """A stored per-device multiplier is returned as a float."""
    options = {CONF_METER_MULTIPLIERS: {"device-1": 100}}

    assert get_meter_multiplier(options, "device-1") == 100.0
    assert get_meter_multiplier(options, "device-2") == 1.0


def test_get_meter_multiplier_ignores_invalid_values():
    """Corrupt or non-positive stored values fall back to 1."""
    assert get_meter_multiplier({CONF_METER_MULTIPLIERS: "bad"}, "d") == 1.0
    assert get_meter_multiplier({CONF_METER_MULTIPLIERS: {"d": "x"}}, "d") == 1.0
    assert get_meter_multiplier({CONF_METER_MULTIPLIERS: {"d": 0}}, "d") == 1.0
    assert get_meter_multiplier({CONF_METER_MULTIPLIERS: {"d": -5}}, "d") == 1.0


def test_options_without_meter_multipliers_strips_only_that_key():
    """Reload comparison should ignore the multiplier key and keep the rest."""
    options = {"scan_interval": 60, CONF_METER_MULTIPLIERS: {"d": 100}}

    assert options_without_meter_multipliers(options) == {"scan_interval": 60}


def test_consumption_is_scaled_by_meter_multiplier(location_data):
    """Energy totals are multiplied after the Wh to kWh conversion."""
    entity = _sensor(location_data, HAN_DEVICE_INDEX, "consumption", 100.0)

    assert entity.native_value == 76967.0


def test_production_is_scaled_by_meter_multiplier(location_data):
    """Production totals are scaled the same way as consumption."""
    location_data["devices"][HAN_DEVICE_INDEX]["features"]["metering"]["states"][
        "summationreceived"
    ]["value"] = 1234
    entity = _sensor(location_data, HAN_DEVICE_INDEX, "production", 100.0)

    assert entity.native_value == 123.4


def test_demand_is_scaled_by_meter_multiplier(location_data):
    """Instantaneous power is scaled too."""
    entity = _sensor(location_data, HAN_DEVICE_INDEX, "demand", 100.0)

    assert entity.native_value == 10500.0


def test_scaled_values_are_rounded_to_three_decimals(location_data):
    """Fractional multipliers should not leak floating point noise."""
    entity = _sensor(location_data, HAN_DEVICE_INDEX, "consumption", 0.1)

    assert entity.native_value == 76.967


def test_meter_multiplier_does_not_touch_other_sensors(location_data):
    """Non-metering sensors ignore the multiplier."""
    unscaled = _sensor(location_data, MOTION_DEVICE_INDEX, "temperature")
    scaled = _sensor(location_data, MOTION_DEVICE_INDEX, "temperature", 100.0)

    assert scaled.native_value == unscaled.native_value


def test_missing_meter_value_stays_none_when_scaled(location_data):
    """A missing reading must not turn into a number."""
    location_data["devices"][HAN_DEVICE_INDEX]["features"]["metering"]["states"][
        "demand"
    ]["value"] = None
    entity = _sensor(location_data, HAN_DEVICE_INDEX, "demand", 100.0)

    assert entity.native_value is None


async def test_number_setup_adds_entity_only_for_metering_devices(
    hass, location_data
):
    """Only HAN meters get a multiplier setting."""
    entry = build_config_entry()
    entry.runtime_data = SimpleNamespace(
        coordinator=_coordinator(location_data),
        last_data=location_data,
        location_id=LOCATION_ID,
    )
    added: list[HomelyMeterMultiplierNumber] = []

    await async_setup_entry(hass, entry, added.extend)

    assert len(added) == 1
    han_id = str(location_data["devices"][HAN_DEVICE_INDEX]["id"])
    assert added[0].unique_id == f"{han_id}_meter_multiplier"


def test_number_entity_is_a_config_box_defaulting_to_one(location_data):
    """The setting is a configuration entity typed in a box."""
    entry = build_config_entry()
    device = location_data["devices"][HAN_DEVICE_INDEX]
    entity = HomelyMeterMultiplierNumber(_coordinator(location_data), entry, device)

    assert entity.entity_category == entity_helper.EntityCategory.CONFIG
    assert entity.mode == NumberMode.BOX
    assert entity.translation_key == "meter_multiplier"
    assert entity.native_value == 1.0
    assert entity.native_min_value > 0


async def test_setting_multiplier_stores_option_and_refreshes_sensors(
    hass, location_data
):
    """Changing the value persists it per device and re-renders entities."""
    entry = build_config_entry(options={"scan_interval": 60})
    entry.add_to_hass(hass)
    coordinator = _coordinator(location_data)
    device = location_data["devices"][HAN_DEVICE_INDEX]
    entity = HomelyMeterMultiplierNumber(coordinator, entry, device)
    entity.hass = hass

    await entity.async_set_native_value(100.0)

    device_id = str(device["id"])
    assert entry.options[CONF_METER_MULTIPLIERS] == {device_id: 100.0}
    assert entry.options["scan_interval"] == 60
    assert entity.native_value == 100.0
    coordinator.async_update_listeners.assert_called_once()


async def test_setting_multiplier_back_to_one_removes_stored_value(
    hass, location_data
):
    """The default is not stored, keeping options clean."""
    device = location_data["devices"][HAN_DEVICE_INDEX]
    device_id = str(device["id"])
    entry = build_config_entry(options={CONF_METER_MULTIPLIERS: {device_id: 100.0}})
    entry.add_to_hass(hass)
    entity = HomelyMeterMultiplierNumber(_coordinator(location_data), entry, device)
    entity.hass = hass

    await entity.async_set_native_value(1.0)

    assert CONF_METER_MULTIPLIERS not in entry.options


async def test_reload_skipped_when_only_meter_multipliers_change(hass):
    """A multiplier change must not reconnect the websocket or re-poll."""
    entry = build_config_entry(
        options={"scan_interval": 60, CONF_METER_MULTIPLIERS: {"d": 100.0}}
    )
    entry.runtime_data = SimpleNamespace(reload_options={"scan_interval": 60})

    with patch.object(
        hass.config_entries, "async_reload", AsyncMock(return_value=True)
    ) as async_reload:
        await async_reload_entry(hass, entry)

    async_reload.assert_not_awaited()


async def test_reload_still_happens_when_other_options_change(hass):
    """Other option changes keep the existing reload behavior."""
    entry = build_config_entry(options={"scan_interval": 120})
    entry.runtime_data = SimpleNamespace(reload_options={"scan_interval": 60})

    with patch.object(
        hass.config_entries, "async_reload", AsyncMock(return_value=True)
    ) as async_reload:
        await async_reload_entry(hass, entry)

    async_reload.assert_awaited_once_with(entry.entry_id)
