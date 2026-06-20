"""Sensor platform for the Deye Cloud integration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import DeyeDeviceCoordinator
from .helpers import generate_unique_id
from .models import Device, DeviceData

_LOGGER = logging.getLogger(__name__)


# Simple sensor definition: (key, name, device_class, state_class, unit, value_fn)
SENSOR_DEFINITIONS: list[tuple[str, str, SensorDeviceClass | None, SensorStateClass | None, str | None, str]] = [
    # Energy accumulation sensors
    ("total_solar_production", "Total Solar Production", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR, "pv_total_yield_kwh"),
    ("total_grid_import", "Total Grid Import", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR, "grid_total_import_kwh"),
    ("total_grid_export", "Total Grid Export", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR, "grid_total_export_kwh"),
    ("total_battery_charge", "Total Battery Charge", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR, "battery_total_charge_kwh"),
    ("total_battery_discharge", "Total Battery Discharge", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR, "battery_total_discharge_kwh"),
    ("total_load_consumption", "Total Load Consumption", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR, "load_total_consumption_kwh"),
    # PV sensors
    ("pv_power_total", "PV Power Total", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, UnitOfPower.WATT, "pv_power_total_w"),
    ("pv_daily_yield", "PV Daily Yield", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR, "pv_daily_yield_kwh"),
    # Battery sensors
    ("battery_soc", "Battery SOC", SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT, PERCENTAGE, "battery_soc_pct"),
    ("battery_power", "Battery Power", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, UnitOfPower.WATT, "battery_power_w"),
    ("battery_voltage", "Battery Voltage", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, UnitOfElectricPotential.VOLT, "battery_voltage_v"),
    ("battery_current", "Battery Current", SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT, UnitOfElectricCurrent.AMPERE, "battery_current_a"),
    ("battery_temperature", "Battery Temperature", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, UnitOfTemperature.CELSIUS, "battery_temperature_c"),
    # Grid sensors
    ("grid_import_power", "Grid Import Power", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, UnitOfPower.WATT, "grid_import_power_w"),
    ("grid_export_power", "Grid Export Power", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, UnitOfPower.WATT, "grid_export_power_w"),
    ("grid_frequency", "Grid Frequency", SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT, UnitOfFrequency.HERTZ, "grid_frequency_hz"),
    # Load sensors
    ("load_power", "Load Power", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, UnitOfPower.WATT, "load_power_w"),
    ("load_daily_consumption", "Load Daily Consumption", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, UnitOfEnergy.KILO_WATT_HOUR, "load_daily_consumption_kwh"),
    # Status
    ("last_update", "Last Update", SensorDeviceClass.TIMESTAMP, None, None, "last_update_time"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Deye Cloud sensor entities from a config entry."""
    _LOGGER.info("Setting up Deye Cloud sensor platform")
    data = hass.data[DOMAIN][entry.entry_id]
    device_coordinators: dict[str, DeyeDeviceCoordinator] = data["device_coordinators"]

    entities: list[SensorEntity] = []

    for device_sn, coordinator in device_coordinators.items():
        for key, name, device_class, state_class, unit, value_fn in SENSOR_DEFINITIONS:
            entities.append(
                DeyeSensor(
                    coordinator=coordinator,
                    device_sn=device_sn,
                    sensor_key=key,
                    sensor_name=name,
                    sensor_device_class=device_class,
                    sensor_state_class=state_class,
                    sensor_unit=unit,
                    value_attr=value_fn,
                )
            )

    _LOGGER.info("Adding %d Deye Cloud sensor entities", len(entities))
    async_add_entities(entities)


class DeyeSensor(CoordinatorEntity[DeyeDeviceCoordinator], SensorEntity):
    """A Deye Cloud sensor entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        device_sn: str,
        sensor_key: str,
        sensor_name: str,
        sensor_device_class: SensorDeviceClass | None,
        sensor_state_class: SensorStateClass | None,
        sensor_unit: str | None,
        value_attr: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._value_attr = value_attr
        self._attr_unique_id = f"{device_sn}_{sensor_key}"
        self._attr_name = sensor_name
        self._attr_device_class = sensor_device_class
        self._attr_state_class = sensor_state_class
        self._attr_native_unit_of_measurement = sensor_unit
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
            name=f"Deye Inverter {device_sn}",
            manufacturer="Deye",
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        if self.coordinator.data is None:
            return None
        return getattr(self.coordinator.data, self._value_attr, None)
