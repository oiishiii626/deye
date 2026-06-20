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
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import DeyeDeviceCoordinator
from .helpers import generate_unique_id
from .models import Device, DeviceData

_LOGGER = logging.getLogger(__name__)


class DeyeSensorEntityDescription(SensorEntityDescription):
    """Describes a Deye sensor entity with a value extraction function."""

    def __init__(self, *, value_fn: str, **kwargs: Any) -> None:
        """Initialize the description.

        Args:
            value_fn: Attribute name on DeviceData to read the value from.
            **kwargs: Passed through to SensorEntityDescription.
        """
        super().__init__(**kwargs)
        self.value_fn = value_fn


# Energy accumulation sensors for Energy Dashboard compatibility.
# These use state_class=total_increasing, device_class=energy, unit=kWh,
# and do NOT set last_reset. Counter resets are handled by HA automatically.
ENERGY_ACCUMULATION_SENSORS: tuple[DeyeSensorEntityDescription, ...] = (
    DeyeSensorEntityDescription(
        key="total_solar_production",
        translation_key="total_solar_production",
        name="Total Solar Production",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn="pv_total_yield_kwh",
    ),
    DeyeSensorEntityDescription(
        key="total_grid_import",
        translation_key="total_grid_import",
        name="Total Grid Import",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn="grid_total_import_kwh",
    ),
    DeyeSensorEntityDescription(
        key="total_grid_export",
        translation_key="total_grid_export",
        name="Total Grid Export",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn="grid_total_export_kwh",
    ),
    DeyeSensorEntityDescription(
        key="total_battery_charge",
        translation_key="total_battery_charge",
        name="Total Battery Charge",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn="battery_total_charge_kwh",
    ),
    DeyeSensorEntityDescription(
        key="total_battery_discharge",
        translation_key="total_battery_discharge",
        name="Total Battery Discharge",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn="battery_total_discharge_kwh",
    ),
    DeyeSensorEntityDescription(
        key="total_load_consumption",
        translation_key="total_load_consumption",
        name="Total Load Consumption",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn="load_total_consumption_kwh",
    ),
)

# PV aggregate sensors (single-instance, not per-channel).
PV_SENSORS: tuple[DeyeSensorEntityDescription, ...] = (
    DeyeSensorEntityDescription(
        key="pv_power_total",
        translation_key="pv_power_total",
        name="PV Power Total",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn="pv_power_total_w",
    ),
    DeyeSensorEntityDescription(
        key="pv_daily_yield",
        translation_key="pv_daily_yield",
        name="PV Daily Yield",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn="pv_daily_yield_kwh",
    ),
    DeyeSensorEntityDescription(
        key="pv_total_yield",
        translation_key="pv_total_yield",
        name="PV Total Yield",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn="pv_total_yield_kwh",
    ),
)

# Battery sensors.
BATTERY_SENSORS: tuple[DeyeSensorEntityDescription, ...] = (
    DeyeSensorEntityDescription(
        key="battery_soc",
        translation_key="battery_soc",
        name="Battery SOC",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn="battery_soc_pct",
    ),
    DeyeSensorEntityDescription(
        key="battery_power",
        translation_key="battery_power",
        name="Battery Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn="battery_power_w",
    ),
    DeyeSensorEntityDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        name="Battery Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        value_fn="battery_voltage_v",
    ),
    DeyeSensorEntityDescription(
        key="battery_current",
        translation_key="battery_current",
        name="Battery Current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        value_fn="battery_current_a",
    ),
    DeyeSensorEntityDescription(
        key="battery_temperature",
        translation_key="battery_temperature",
        name="Battery Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn="battery_temperature_c",
    ),
)

# Grid sensors (single-instance, not per-phase).
GRID_SENSORS: tuple[DeyeSensorEntityDescription, ...] = (
    DeyeSensorEntityDescription(
        key="grid_import_power",
        translation_key="grid_import_power",
        name="Grid Import Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn="grid_import_power_w",
    ),
    DeyeSensorEntityDescription(
        key="grid_export_power",
        translation_key="grid_export_power",
        name="Grid Export Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn="grid_export_power_w",
    ),
    DeyeSensorEntityDescription(
        key="grid_daily_import",
        translation_key="grid_daily_import",
        name="Grid Daily Import",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn="grid_daily_import_kwh",
    ),
    DeyeSensorEntityDescription(
        key="grid_daily_export",
        translation_key="grid_daily_export",
        name="Grid Daily Export",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn="grid_daily_export_kwh",
    ),
    DeyeSensorEntityDescription(
        key="grid_frequency",
        translation_key="grid_frequency",
        name="Grid Frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        value_fn="grid_frequency_hz",
    ),
)

# Load sensors.
LOAD_SENSORS: tuple[DeyeSensorEntityDescription, ...] = (
    DeyeSensorEntityDescription(
        key="load_power",
        translation_key="load_power",
        name="Load Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn="load_power_w",
    ),
    DeyeSensorEntityDescription(
        key="load_daily_consumption",
        translation_key="load_daily_consumption",
        name="Load Daily Consumption",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn="load_daily_consumption_kwh",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Deye Cloud sensor entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    device_coordinators: dict[str, DeyeDeviceCoordinator] = data["device_coordinators"]
    devices_metadata: dict[str, Device] = data.get("devices_metadata", {})
    stations_metadata: dict[str, dict[str, Any]] = data.get("stations_metadata", {})
    station_devices_map: dict[str, list[str]] = data.get("station_devices_map", {})

    entities: list[SensorEntity] = []

    for device_sn, coordinator in device_coordinators.items():
        device: Device | None = devices_metadata.get(device_sn)

        # Add energy accumulation sensors for Energy Dashboard
        for description in ENERGY_ACCUMULATION_SENSORS:
            entities.append(
                DeyeEnergySensor(
                    coordinator=coordinator,
                    description=description,
                    device_sn=device_sn,
                )
            )

        # Add PV aggregate sensors
        for description in PV_SENSORS:
            entities.append(
                DeyeEnergySensor(
                    coordinator=coordinator,
                    description=description,
                    device_sn=device_sn,
                )
            )

        # Add battery sensors
        for description in BATTERY_SENSORS:
            entities.append(
                DeyeEnergySensor(
                    coordinator=coordinator,
                    description=description,
                    device_sn=device_sn,
                )
            )

        # Add grid sensors (single-instance)
        for description in GRID_SENSORS:
            entities.append(
                DeyeEnergySensor(
                    coordinator=coordinator,
                    description=description,
                    device_sn=device_sn,
                )
            )

        # Add load sensors
        for description in LOAD_SENSORS:
            entities.append(
                DeyeEnergySensor(
                    coordinator=coordinator,
                    description=description,
                    device_sn=device_sn,
                )
            )

        # Determine MPPT count and phase count from device metadata
        mppt_count = getattr(device, "mppt_count", 0) if device else 0
        phase_count = getattr(device, "phase_count", 1) if device else 1

        # Dynamic MPPT channel sensors (per-channel power, voltage, current)
        for channel in range(1, mppt_count + 1):
            entities.append(
                DeyeMPPTChannelSensor(
                    coordinator=coordinator,
                    device_sn=device_sn,
                    channel=channel,
                    sensor_type="power",
                    name=f"PV Power MPPT {channel}",
                    device_class=SensorDeviceClass.POWER,
                    state_class=SensorStateClass.MEASUREMENT,
                    unit=UnitOfPower.WATT,
                    value_attr="power_w",
                )
            )
            entities.append(
                DeyeMPPTChannelSensor(
                    coordinator=coordinator,
                    device_sn=device_sn,
                    channel=channel,
                    sensor_type="voltage",
                    name=f"PV Voltage MPPT {channel}",
                    device_class=SensorDeviceClass.VOLTAGE,
                    state_class=SensorStateClass.MEASUREMENT,
                    unit=UnitOfElectricPotential.VOLT,
                    value_attr="voltage_v",
                )
            )
            entities.append(
                DeyeMPPTChannelSensor(
                    coordinator=coordinator,
                    device_sn=device_sn,
                    channel=channel,
                    sensor_type="current",
                    name=f"PV Current MPPT {channel}",
                    device_class=SensorDeviceClass.CURRENT,
                    state_class=SensorStateClass.MEASUREMENT,
                    unit=UnitOfElectricCurrent.AMPERE,
                    value_attr="current_a",
                )
            )

        # Dynamic phase sensors (per-phase voltage, current, power, frequency)
        for phase in range(1, phase_count + 1):
            entities.append(
                DeyePhaseSensor(
                    coordinator=coordinator,
                    device_sn=device_sn,
                    phase=phase,
                    sensor_type="voltage",
                    name=f"Grid Voltage Phase {phase}",
                    device_class=SensorDeviceClass.VOLTAGE,
                    state_class=SensorStateClass.MEASUREMENT,
                    unit=UnitOfElectricPotential.VOLT,
                    value_attr="voltage_v",
                )
            )
            entities.append(
                DeyePhaseSensor(
                    coordinator=coordinator,
                    device_sn=device_sn,
                    phase=phase,
                    sensor_type="current",
                    name=f"Grid Current Phase {phase}",
                    device_class=SensorDeviceClass.CURRENT,
                    state_class=SensorStateClass.MEASUREMENT,
                    unit=UnitOfElectricCurrent.AMPERE,
                    value_attr="current_a",
                )
            )
            entities.append(
                DeyePhaseSensor(
                    coordinator=coordinator,
                    device_sn=device_sn,
                    phase=phase,
                    sensor_type="power",
                    name=f"Grid Power Phase {phase}",
                    device_class=SensorDeviceClass.POWER,
                    state_class=SensorStateClass.MEASUREMENT,
                    unit=UnitOfPower.WATT,
                    value_attr="power_w",
                )
            )
            entities.append(
                DeyePhaseSensor(
                    coordinator=coordinator,
                    device_sn=device_sn,
                    phase=phase,
                    sensor_type="frequency",
                    name=f"Grid Frequency Phase {phase}",
                    device_class=SensorDeviceClass.FREQUENCY,
                    state_class=SensorStateClass.MEASUREMENT,
                    unit=UnitOfFrequency.HERTZ,
                    value_attr="frequency_hz",
                )
            )

        # Add last-update timestamp sensor (Requirement 5.5)
        entities.append(
            DeyeLastUpdateSensor(
                coordinator=coordinator,
                device_sn=device_sn,
                device=device,
            )
        )

    # Create station aggregate sensors
    for station_id, metadata in stations_metadata.items():
        device_sns = station_devices_map.get(station_id, [])
        child_coordinators = [
            device_coordinators[sn]
            for sn in device_sns
            if sn in device_coordinators
        ]
        if not child_coordinators:
            continue

        station_name = metadata.get("name", f"Station {station_id}")

        entities.append(
            DeyeStationTotalPowerSensor(
                station_id=station_id,
                station_name=station_name,
                metadata=metadata,
                child_coordinators=child_coordinators,
            )
        )
        entities.append(
            DeyeStationDailyProductionSensor(
                station_id=station_id,
                station_name=station_name,
                metadata=metadata,
                child_coordinators=child_coordinators,
            )
        )
        entities.append(
            DeyeStationDailyConsumptionSensor(
                station_id=station_id,
                station_name=station_name,
                metadata=metadata,
                child_coordinators=child_coordinators,
            )
        )

    async_add_entities(entities)


class DeyeEnergySensor(CoordinatorEntity, SensorEntity):
    """Representation of a Deye sensor entity using a description.

    Used for energy accumulation sensors, PV aggregate sensors, battery
    sensors, grid sensors, and load sensors. Reads values from DeviceData
    using the value_fn attribute name from the entity description.

    Null handling: If the value_fn attribute returns None (e.g., battery
    sensors on non-battery inverters), the sensor state is set to "unknown"
    while retaining device_class and state_class attributes.
    """

    entity_description: DeyeSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        description: DeyeSensorEntityDescription,
        device_sn: str,
    ) -> None:
        """Initialize the sensor.

        Args:
            coordinator: The device data coordinator.
            description: The sensor entity description.
            device_sn: The inverter serial number.
        """
        super().__init__(coordinator)
        self.entity_description = description
        self._device_sn = device_sn
        self._attr_unique_id = generate_unique_id(device_sn, description.key)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
        )

    @property
    def native_value(self) -> float | None:
        """Return the current sensor value from coordinator data.

        Returns the raw API value without adjustment. If the value is None
        (e.g., battery sensors on a non-battery inverter), returns None
        which HA displays as "unknown".
        """
        if self.coordinator.data is None:
            return None
        data: DeviceData = self.coordinator.data
        value = getattr(data, self.entity_description.value_fn, None)
        return value

    @property
    def last_reset(self) -> None:
        """Return None - total_increasing sensors must not have last_reset.

        Home Assistant uses state_class=total_increasing to detect counter
        resets automatically without needing the last_reset attribute.
        """
        return None


class DeyeMPPTChannelSensor(CoordinatorEntity, SensorEntity):
    """Sensor for a single MPPT channel measurement.

    Dynamically created based on device.mppt_count, providing per-channel
    power (W), voltage (V), and current (A) sensors.

    Entity naming: sensor.{device_name}_pv_{sensor_type}_{channel}
    Unique ID: {device_sn}_pv_{sensor_type}_{channel}

    Null handling: Returns None (state "unknown") if channel data is
    not present in the coordinator data.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        device_sn: str,
        channel: int,
        sensor_type: str,
        name: str,
        device_class: str,
        state_class: str,
        unit: str,
        value_attr: str,
    ) -> None:
        """Initialize the MPPT channel sensor.

        Args:
            coordinator: The device data coordinator.
            device_sn: The inverter serial number.
            channel: The MPPT channel number (1-indexed).
            sensor_type: Sensor type key (power, voltage, current).
            name: Human-readable sensor name.
            device_class: HA device class.
            state_class: HA state class.
            unit: Unit of measurement.
            value_attr: Attribute name on MPPTChannelData to read.
        """
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._channel = channel
        self._value_attr = value_attr
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit
        self._attr_unique_id = generate_unique_id(
            device_sn, f"pv_{sensor_type}", channel
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
        )

    @property
    def native_value(self) -> float | None:
        """Return the channel measurement value.

        Searches pv_channels for the matching channel number and returns
        the requested attribute. Returns None (state "unknown") if the
        channel data is not present or the coordinator has no data.
        """
        if self.coordinator.data is None:
            return None
        data: DeviceData = self.coordinator.data
        for ch_data in data.pv_channels:
            if ch_data.channel == self._channel:
                value = getattr(ch_data, self._value_attr, None)
                return value
        return None


class DeyePhaseSensor(CoordinatorEntity, SensorEntity):
    """Sensor for a single AC phase measurement.

    Dynamically created based on device.phase_count, providing per-phase
    voltage (V), current (A), power (W), and frequency (Hz) sensors.

    Entity naming: sensor.{device_name}_grid_{sensor_type}_{phase}
    Unique ID: {device_sn}_grid_{sensor_type}_{phase}

    Null handling: Returns None (state "unknown") if phase data is
    not present in the coordinator data.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        device_sn: str,
        phase: int,
        sensor_type: str,
        name: str,
        device_class: str,
        state_class: str,
        unit: str,
        value_attr: str,
    ) -> None:
        """Initialize the phase sensor.

        Args:
            coordinator: The device data coordinator.
            device_sn: The inverter serial number.
            phase: The phase number (1, 2, or 3).
            sensor_type: Sensor type key (voltage, current, power, frequency).
            name: Human-readable sensor name.
            device_class: HA device class.
            state_class: HA state class.
            unit: Unit of measurement.
            value_attr: Attribute name on PhaseData to read.
        """
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._phase = phase
        self._value_attr = value_attr
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit
        self._attr_unique_id = generate_unique_id(
            device_sn, f"grid_{sensor_type}", phase
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
        )

    @property
    def native_value(self) -> float | None:
        """Return the phase measurement value.

        Searches grid_phases for the matching phase number and returns
        the requested attribute. Returns None (state "unknown") if the
        phase data is not present or the coordinator has no data.
        """
        if self.coordinator.data is None:
            return None
        data: DeviceData = self.coordinator.data
        for phase_data in data.grid_phases:
            if phase_data.phase == self._phase:
                value = getattr(phase_data, self._value_attr, None)
                return value
        return None


class DeyeLastUpdateSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing the last successful data collection time.

    Reports the last_update_time from DeviceData as a timestamp sensor,
    allowing users to see when data was last collected from the inverter.
    Inverter metadata (model, serial, firmware, rated power) is exposed
    as extra state attributes on this entity.

    Requirement 5.2: Expose inverter metadata as device attributes.
    Requirement 5.5: Timestamp sensor for last data collection time.
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_name = "Last Update"
    _attr_translation_key = "last_update"

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        device_sn: str,
        device: Device | None = None,
    ) -> None:
        """Initialize the last-update timestamp sensor.

        Args:
            coordinator: The device data coordinator.
            device_sn: The inverter serial number.
            device: Optional Device model with metadata (model, firmware, etc.).
        """
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._device = device
        self._attr_unique_id = generate_unique_id(device_sn, "last_update")

        # Build DeviceInfo with inverter metadata as device attributes
        # (Requirement 5.2)
        device_info_kwargs: dict[str, Any] = {
            "identifiers": {(DOMAIN, device_sn)},
        }
        if device is not None:
            device_info_kwargs["name"] = device.model_name
            device_info_kwargs["model"] = device.model_name
            device_info_kwargs["sw_version"] = device.firmware_version
            device_info_kwargs["serial_number"] = device.device_sn
            device_info_kwargs["manufacturer"] = "Deye"

        self._attr_device_info = DeviceInfo(**device_info_kwargs)

    @property
    def native_value(self) -> datetime | None:
        """Return the last successful data collection timestamp.

        Returns the last_update_time from DeviceData, or None if
        coordinator data is unavailable.
        """
        if self.coordinator.data is None:
            return None
        data: DeviceData = self.coordinator.data
        return data.last_update_time

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return inverter metadata as extra state attributes.

        Exposes model name, serial number, firmware version, and rated
        power as attributes on this sensor entity (Requirement 5.2).
        """
        attrs: dict[str, Any] = {
            "serial_number": self._device_sn,
        }
        if self._device is not None:
            attrs["model_name"] = self._device.model_name
            attrs["firmware_version"] = self._device.firmware_version
            attrs["rated_power_w"] = self._device.rated_power_w
        elif self.coordinator.model_name is not None:
            # Fall back to coordinator-stored metadata
            attrs["model_name"] = self.coordinator.model_name
            if self.coordinator.firmware_version is not None:
                attrs["firmware_version"] = self.coordinator.firmware_version
            if self.coordinator.rated_power_w is not None:
                attrs["rated_power_w"] = self.coordinator.rated_power_w
        return attrs



class _DeyeStationSensorBase(SensorEntity):
    """Base class for station aggregate sensors.

    Station sensors aggregate data from multiple child inverter coordinators.
    They are marked unavailable when all child inverters are offline or
    have no data available.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        station_id: str,
        station_name: str,
        metadata: dict[str, Any],
        child_coordinators: list[Any],
    ) -> None:
        """Initialize the station sensor base.

        Args:
            station_id: The station identifier from the Deye Cloud API.
            station_name: Human-readable station name.
            metadata: Station metadata dict (name, latitude, longitude, rated_capacity_kwp).
            child_coordinators: List of DeyeDeviceCoordinator instances for inverters in this station.
        """
        self._station_id = station_id
        self._station_name = station_name
        self._metadata = metadata
        self._child_coordinators = child_coordinators

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info for the station device entry."""
        return {
            "identifiers": {(DOMAIN, f"station_{self._station_id}")},
            "name": self._station_name,
            "manufacturer": "Deye",
            "model": "Solar Station",
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return station metadata as extra state attributes."""
        return {
            "station_name": self._station_name,
            "latitude": self._metadata.get("latitude"),
            "longitude": self._metadata.get("longitude"),
            "rated_capacity_kwp": self._metadata.get("rated_capacity_kwp"),
        }

    @property
    def available(self) -> bool:
        """Return True if at least one child inverter is online with data."""
        for coord in self._child_coordinators:
            if coord.data is not None and getattr(coord.data, "is_online", False):
                return True
        return False

    def _get_online_coordinators(self) -> list[Any]:
        """Return coordinators whose inverters are online and have data."""
        return [
            coord
            for coord in self._child_coordinators
            if coord.data is not None and getattr(coord.data, "is_online", False)
        ]


class DeyeStationTotalPowerSensor(_DeyeStationSensorBase):
    """Station-level total PV power sensor (W) aggregating all child inverters.

    Uses state_class=measurement since power is an instantaneous value.
    """

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(
        self,
        station_id: str,
        station_name: str,
        metadata: dict[str, Any],
        child_coordinators: list[Any],
    ) -> None:
        """Initialize the station total power sensor."""
        super().__init__(station_id, station_name, metadata, child_coordinators)
        self._attr_unique_id = f"station_{station_id}_total_power"
        self._attr_name = f"{station_name} Total Power"

    @property
    def native_value(self) -> float | None:
        """Return the sum of PV power from all online child inverters."""
        if not self.available:
            return None
        online = self._get_online_coordinators()
        return sum(coord.data.pv_power_total_w for coord in online)


class DeyeStationDailyProductionSensor(_DeyeStationSensorBase):
    """Station-level daily production sensor (kWh) aggregating all child inverters.

    Uses state_class=total_increasing for energy accumulation values.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        station_id: str,
        station_name: str,
        metadata: dict[str, Any],
        child_coordinators: list[Any],
    ) -> None:
        """Initialize the station daily production sensor."""
        super().__init__(station_id, station_name, metadata, child_coordinators)
        self._attr_unique_id = f"station_{station_id}_daily_production"
        self._attr_name = f"{station_name} Daily Production"

    @property
    def native_value(self) -> float | None:
        """Return the sum of daily PV yield from all online child inverters."""
        if not self.available:
            return None
        online = self._get_online_coordinators()
        return sum(coord.data.pv_daily_yield_kwh for coord in online)


class DeyeStationDailyConsumptionSensor(_DeyeStationSensorBase):
    """Station-level daily consumption sensor (kWh) aggregating all child inverters.

    Uses state_class=total_increasing for energy accumulation values.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        station_id: str,
        station_name: str,
        metadata: dict[str, Any],
        child_coordinators: list[Any],
    ) -> None:
        """Initialize the station daily consumption sensor."""
        super().__init__(station_id, station_name, metadata, child_coordinators)
        self._attr_unique_id = f"station_{station_id}_daily_consumption"
        self._attr_name = f"{station_name} Daily Consumption"

    @property
    def native_value(self) -> float | None:
        """Return the sum of daily consumption from all online child inverters."""
        if not self.available:
            return None
        online = self._get_online_coordinators()
        return sum(coord.data.load_daily_consumption_kwh for coord in online)

