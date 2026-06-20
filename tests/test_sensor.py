"""Tests for the Deye Cloud sensor platform - energy accumulation sensors."""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

# Conftest patches sys.modules before our imports
from custom_components.deye_cloud.models import DeviceData, MPPTChannelData, PhaseData
from custom_components.deye_cloud.helpers import generate_unique_id
from custom_components.deye_cloud.sensor import (
    DeyeEnergySensor,
    DeyeSensorEntityDescription,
    ENERGY_ACCUMULATION_SENSORS,
)


class MockCoordinator:
    """Mock coordinator for sensor testing."""

    def __init__(self, device_sn: str, data: DeviceData | None = None):
        self.device_sn = device_sn
        self.data = data
        self.last_update_success = True


def _make_device_data(**overrides) -> DeviceData:
    """Create a DeviceData instance with sensible defaults, applying overrides."""
    defaults = {
        "pv_power_total_w": 3500.0,
        "pv_daily_yield_kwh": 12.5,
        "pv_total_yield_kwh": 5432.1,
        "grid_total_import_kwh": 1234.5,
        "grid_total_export_kwh": 2345.6,
        "load_total_consumption_kwh": 3456.7,
        "battery_total_charge_kwh": 456.7,
        "battery_total_discharge_kwh": 321.0,
    }
    defaults.update(overrides)
    return DeviceData(**defaults)


def _make_sensor(
    device_sn: str = "INV123456",
    data: DeviceData | None = None,
    description: DeyeSensorEntityDescription | None = None,
) -> DeyeEnergySensor:
    """Create a DeyeEnergySensor for testing."""
    if data is None:
        data = _make_device_data()
    if description is None:
        description = ENERGY_ACCUMULATION_SENSORS[0]

    coordinator = MockCoordinator(device_sn=device_sn, data=data)

    sensor = DeyeEnergySensor.__new__(DeyeEnergySensor)
    sensor.coordinator = coordinator
    sensor.entity_description = description
    sensor._device_sn = device_sn
    sensor._attr_unique_id = generate_unique_id(device_sn, description.key)
    sensor._attr_device_info = {"identifiers": {("deye_cloud", device_sn)}}
    return sensor


class TestEnergyAccumulationSensorDescriptions:
    """Tests for energy accumulation sensor entity descriptions."""

    def test_all_six_energy_sensors_defined(self):
        """Verify all 6 required energy accumulation sensors are defined."""
        assert len(ENERGY_ACCUMULATION_SENSORS) == 6

    def test_sensor_keys(self):
        """Verify sensor keys match expected naming pattern."""
        expected_keys = {
            "total_solar_production",
            "total_grid_import",
            "total_grid_export",
            "total_battery_charge",
            "total_battery_discharge",
            "total_load_consumption",
        }
        actual_keys = {desc.key for desc in ENERGY_ACCUMULATION_SENSORS}
        assert actual_keys == expected_keys

    def test_all_sensors_have_energy_device_class(self):
        """All energy accumulation sensors must have device_class=energy."""
        for desc in ENERGY_ACCUMULATION_SENSORS:
            assert desc.device_class == "energy", (
                f"Sensor {desc.key} has wrong device_class: {desc.device_class}"
            )

    def test_all_sensors_have_total_increasing_state_class(self):
        """All energy accumulation sensors must have state_class=total_increasing."""
        for desc in ENERGY_ACCUMULATION_SENSORS:
            assert desc.state_class == "total_increasing", (
                f"Sensor {desc.key} has wrong state_class: {desc.state_class}"
            )

    def test_all_sensors_have_kwh_unit(self):
        """All energy accumulation sensors must have unit kWh."""
        for desc in ENERGY_ACCUMULATION_SENSORS:
            assert desc.native_unit_of_measurement == "kWh", (
                f"Sensor {desc.key} has wrong unit: {desc.native_unit_of_measurement}"
            )

    def test_value_fn_attributes_exist_on_device_data(self):
        """All value_fn attributes must exist on DeviceData."""
        data = _make_device_data()
        for desc in ENERGY_ACCUMULATION_SENSORS:
            assert hasattr(data, desc.value_fn), (
                f"DeviceData has no attribute '{desc.value_fn}' for sensor {desc.key}"
            )


class TestDeyeEnergySensor:
    """Tests for the DeyeEnergySensor entity class."""

    def test_unique_id_based_on_serial_and_key(self):
        """Unique ID must be based on inverter serial + sensor type."""
        sensor = _make_sensor(device_sn="SN987654")
        assert sensor._attr_unique_id == "SN987654_total_solar_production"

    def test_unique_id_different_for_different_sensors(self):
        """Each sensor type produces a different unique_id."""
        device_sn = "INV111"

        unique_ids = set()
        for desc in ENERGY_ACCUMULATION_SENSORS:
            uid = generate_unique_id(device_sn, desc.key)
            unique_ids.add(uid)

        # All 6 sensors should produce different unique IDs
        assert len(unique_ids) == 6

    def test_native_value_returns_api_data(self):
        """native_value returns the raw API value from DeviceData."""
        data = _make_device_data(pv_total_yield_kwh=9999.9)
        sensor = _make_sensor(data=data)
        assert sensor.native_value == 9999.9

    def test_native_value_returns_none_when_coordinator_data_is_none(self):
        """native_value returns None when coordinator has no data."""
        sensor = _make_sensor()
        sensor.coordinator.data = None
        assert sensor.native_value is None

    def test_native_value_returns_none_for_optional_fields(self):
        """Battery total sensors return None when battery data is unavailable."""
        # battery_total_charge_kwh is Optional[float] and defaults to None
        data = _make_device_data(battery_total_charge_kwh=None)

        # Find the battery charge sensor description
        battery_charge_desc = next(
            d for d in ENERGY_ACCUMULATION_SENSORS if d.key == "total_battery_charge"
        )
        sensor = _make_sensor(data=data, description=battery_charge_desc)
        assert sensor.native_value is None

    def test_last_reset_is_always_none(self):
        """last_reset must always be None for total_increasing sensors."""
        sensor = _make_sensor()
        assert sensor.last_reset is None

    def test_counter_reset_reports_lower_value_without_adjustment(self):
        """When API returns a lower value (counter reset), report it as-is.

        HA handles counter reset detection for total_increasing sensors.
        The sensor just reports whatever the API gives.
        """
        # First value is high
        data_high = _make_device_data(pv_total_yield_kwh=5000.0)
        sensor = _make_sensor(data=data_high)
        assert sensor.native_value == 5000.0

        # Simulate counter reset: API returns lower value
        data_low = _make_device_data(pv_total_yield_kwh=100.0)
        sensor.coordinator.data = data_low
        # Sensor reports the new lower value without any adjustment
        assert sensor.native_value == 100.0

    def test_all_energy_sensors_map_to_correct_fields(self):
        """Verify each sensor maps to the correct DeviceData field."""
        expected_mappings = {
            "total_solar_production": "pv_total_yield_kwh",
            "total_grid_import": "grid_total_import_kwh",
            "total_grid_export": "grid_total_export_kwh",
            "total_battery_charge": "battery_total_charge_kwh",
            "total_battery_discharge": "battery_total_discharge_kwh",
            "total_load_consumption": "load_total_consumption_kwh",
        }

        for desc in ENERGY_ACCUMULATION_SENSORS:
            assert desc.value_fn == expected_mappings[desc.key], (
                f"Sensor {desc.key} maps to {desc.value_fn} "
                f"but expected {expected_mappings[desc.key]}"
            )

    def test_sensor_values_for_all_types(self):
        """Verify all 6 energy sensors return correct values from DeviceData."""
        data = _make_device_data(
            pv_total_yield_kwh=1111.1,
            grid_total_import_kwh=2222.2,
            grid_total_export_kwh=3333.3,
            battery_total_charge_kwh=4444.4,
            battery_total_discharge_kwh=5555.5,
            load_total_consumption_kwh=6666.6,
        )

        expected_values = {
            "total_solar_production": 1111.1,
            "total_grid_import": 2222.2,
            "total_grid_export": 3333.3,
            "total_battery_charge": 4444.4,
            "total_battery_discharge": 5555.5,
            "total_load_consumption": 6666.6,
        }

        for desc in ENERGY_ACCUMULATION_SENSORS:
            sensor = _make_sensor(data=data, description=desc)
            assert sensor.native_value == expected_values[desc.key], (
                f"Sensor {desc.key} returned {sensor.native_value} "
                f"but expected {expected_values[desc.key]}"
            )

    def test_unique_ids_stable_across_different_inverters(self):
        """Unique IDs incorporate serial number to prevent collisions."""
        desc = ENERGY_ACCUMULATION_SENSORS[0]
        uid1 = generate_unique_id("INVERTER_A", desc.key)
        uid2 = generate_unique_id("INVERTER_B", desc.key)

        assert uid1 != uid2
        assert "INVERTER_A" in uid1
        assert "INVERTER_B" in uid2


# Import the new sensor class for testing
from custom_components.deye_cloud.sensor import DeyeLastUpdateSensor
from custom_components.deye_cloud.models import Device, WorkMode, EnergyPattern


class MockCoordinatorWithMetadata:
    """Mock coordinator with optional device metadata attributes."""

    def __init__(
        self,
        device_sn: str,
        data: DeviceData | None = None,
        model_name: str | None = None,
        firmware_version: str | None = None,
        rated_power_w: int | None = None,
    ):
        self.device_sn = device_sn
        self.data = data
        self.last_update_success = True
        self.model_name = model_name
        self.firmware_version = firmware_version
        self.rated_power_w = rated_power_w


def _make_device() -> Device:
    """Create a Device instance with typical metadata."""
    return Device(
        device_sn="INV123456",
        station_id="STATION01",
        model_name="SUN-8K-SG04LP3",
        firmware_version="1.53.0",
        rated_power_w=8000,
        phase_count=3,
        mppt_count=2,
        has_battery=True,
        has_smart_load=True,
        smart_load_channels=2,
        supported_work_modes=[WorkMode.SELF_CONSUMPTION, WorkMode.TIME_OF_USE],
        supported_energy_patterns=[EnergyPattern.BATTERY_FIRST, EnergyPattern.LOAD_FIRST],
    )


def _make_last_update_sensor(
    device_sn: str = "INV123456",
    data: DeviceData | None = None,
    device: Device | None = None,
    model_name: str | None = None,
    firmware_version: str | None = None,
    rated_power_w: int | None = None,
) -> DeyeLastUpdateSensor:
    """Create a DeyeLastUpdateSensor for testing."""
    if data is None:
        data = _make_device_data()

    coordinator = MockCoordinatorWithMetadata(
        device_sn=device_sn,
        data=data,
        model_name=model_name,
        firmware_version=firmware_version,
        rated_power_w=rated_power_w,
    )

    sensor = DeyeLastUpdateSensor.__new__(DeyeLastUpdateSensor)
    sensor.coordinator = coordinator
    sensor._device_sn = device_sn
    sensor._device = device
    sensor._attr_unique_id = generate_unique_id(device_sn, "last_update")
    sensor._attr_device_info = {"identifiers": {("deye_cloud", device_sn)}}
    return sensor


class TestDeyeLastUpdateSensor:
    """Tests for the DeyeLastUpdateSensor entity class."""

    def test_device_class_is_timestamp(self):
        """The last-update sensor must have device_class=timestamp."""
        from homeassistant.components.sensor import SensorDeviceClass

        assert DeyeLastUpdateSensor._attr_device_class == SensorDeviceClass.TIMESTAMP

    def test_unique_id_based_on_serial(self):
        """Unique ID must be based on inverter serial + 'last_update'."""
        sensor = _make_last_update_sensor(device_sn="SN999")
        assert sensor._attr_unique_id == "SN999_last_update"

    def test_native_value_returns_last_update_time(self):
        """native_value returns the last_update_time from DeviceData."""
        test_time = datetime(2024, 6, 15, 14, 30, 0)
        data = _make_device_data(last_update_time=test_time)
        sensor = _make_last_update_sensor(data=data)
        assert sensor.native_value == test_time

    def test_native_value_returns_none_when_coordinator_data_is_none(self):
        """native_value returns None when coordinator has no data."""
        sensor = _make_last_update_sensor()
        sensor.coordinator.data = None
        assert sensor.native_value is None

    def test_extra_state_attributes_with_device_metadata(self):
        """Extra attributes expose inverter metadata from Device model."""
        device = _make_device()
        sensor = _make_last_update_sensor(device=device)

        attrs = sensor.extra_state_attributes
        assert attrs is not None
        assert attrs["serial_number"] == "INV123456"
        assert attrs["model_name"] == "SUN-8K-SG04LP3"
        assert attrs["firmware_version"] == "1.53.0"
        assert attrs["rated_power_w"] == 8000

    def test_extra_state_attributes_without_device_uses_coordinator(self):
        """When no Device metadata, fall back to coordinator attributes."""
        sensor = _make_last_update_sensor(
            device=None,
            model_name="SUN-5K-SG03LP1",
            firmware_version="2.0.1",
            rated_power_w=5000,
        )

        attrs = sensor.extra_state_attributes
        assert attrs is not None
        assert attrs["serial_number"] == "INV123456"
        assert attrs["model_name"] == "SUN-5K-SG03LP1"
        assert attrs["firmware_version"] == "2.0.1"
        assert attrs["rated_power_w"] == 5000

    def test_extra_state_attributes_minimal_without_metadata(self):
        """When no metadata is available, only serial_number is returned."""
        sensor = _make_last_update_sensor(device=None)

        attrs = sensor.extra_state_attributes
        assert attrs is not None
        assert attrs["serial_number"] == "INV123456"
        assert "model_name" not in attrs
        assert "firmware_version" not in attrs
        assert "rated_power_w" not in attrs

    def test_extra_state_attributes_coordinator_partial_metadata(self):
        """Coordinator with only model_name exposes what's available."""
        sensor = _make_last_update_sensor(
            device=None,
            model_name="SUN-3K",
            firmware_version=None,
            rated_power_w=None,
        )

        attrs = sensor.extra_state_attributes
        assert attrs["model_name"] == "SUN-3K"
        assert "firmware_version" not in attrs
        assert "rated_power_w" not in attrs

    def test_timestamp_updates_with_coordinator_data(self):
        """Sensor value updates when coordinator data changes."""
        time1 = datetime(2024, 1, 1, 10, 0, 0)
        time2 = datetime(2024, 1, 1, 10, 1, 0)

        data1 = _make_device_data(last_update_time=time1)
        sensor = _make_last_update_sensor(data=data1)
        assert sensor.native_value == time1

        # Simulate new data arriving
        data2 = _make_device_data(last_update_time=time2)
        sensor.coordinator.data = data2
        assert sensor.native_value == time2



from custom_components.deye_cloud.sensor import (
    PV_SENSORS,
    BATTERY_SENSORS,
    GRID_SENSORS,
    LOAD_SENSORS,
    DeyeMPPTChannelSensor,
    DeyePhaseSensor,
)


class TestPVSensorDescriptions:
    """Tests for PV aggregate sensor entity descriptions."""

    def test_pv_sensors_count(self):
        """Verify 3 PV aggregate sensors are defined."""
        assert len(PV_SENSORS) == 3

    def test_pv_sensor_keys(self):
        """Verify PV sensor keys."""
        expected_keys = {"pv_power_total", "pv_daily_yield", "pv_total_yield"}
        actual_keys = {desc.key for desc in PV_SENSORS}
        assert actual_keys == expected_keys

    def test_pv_power_total_is_measurement(self):
        """PV power total must be device_class=power, state_class=measurement."""
        desc = next(d for d in PV_SENSORS if d.key == "pv_power_total")
        assert desc.device_class == "power"
        assert desc.state_class == "measurement"
        assert desc.native_unit_of_measurement == "W"

    def test_pv_yield_sensors_are_energy(self):
        """PV yield sensors must be energy/total_increasing/kWh."""
        for key in ("pv_daily_yield", "pv_total_yield"):
            desc = next(d for d in PV_SENSORS if d.key == key)
            assert desc.device_class == "energy"
            assert desc.state_class == "total_increasing"
            assert desc.native_unit_of_measurement == "kWh"

    def test_value_fn_attributes_exist_on_device_data(self):
        """All value_fn attributes must exist on DeviceData."""
        data = _make_device_data()
        for desc in PV_SENSORS:
            assert hasattr(data, desc.value_fn), (
                f"DeviceData has no attribute '{desc.value_fn}' for sensor {desc.key}"
            )


class TestBatterySensorDescriptions:
    """Tests for battery sensor entity descriptions."""

    def test_battery_sensors_count(self):
        """Verify 5 battery sensors are defined."""
        assert len(BATTERY_SENSORS) == 5

    def test_battery_sensor_keys(self):
        """Verify battery sensor keys."""
        expected_keys = {
            "battery_soc",
            "battery_power",
            "battery_voltage",
            "battery_current",
            "battery_temperature",
        }
        actual_keys = {desc.key for desc in BATTERY_SENSORS}
        assert actual_keys == expected_keys

    def test_battery_soc_device_class(self):
        """Battery SOC must have device_class=battery."""
        desc = next(d for d in BATTERY_SENSORS if d.key == "battery_soc")
        assert desc.device_class == "battery"
        assert desc.state_class == "measurement"
        assert desc.native_unit_of_measurement == "%"

    def test_battery_power_device_class(self):
        """Battery power must have device_class=power."""
        desc = next(d for d in BATTERY_SENSORS if d.key == "battery_power")
        assert desc.device_class == "power"
        assert desc.state_class == "measurement"
        assert desc.native_unit_of_measurement == "W"

    def test_battery_voltage_device_class(self):
        """Battery voltage must have device_class=voltage."""
        desc = next(d for d in BATTERY_SENSORS if d.key == "battery_voltage")
        assert desc.device_class == "voltage"
        assert desc.native_unit_of_measurement == "V"

    def test_battery_current_device_class(self):
        """Battery current must have device_class=current."""
        desc = next(d for d in BATTERY_SENSORS if d.key == "battery_current")
        assert desc.device_class == "current"
        assert desc.native_unit_of_measurement == "A"

    def test_battery_temperature_device_class(self):
        """Battery temperature must have device_class=temperature."""
        desc = next(d for d in BATTERY_SENSORS if d.key == "battery_temperature")
        assert desc.device_class == "temperature"
        assert desc.native_unit_of_measurement == "°C"

    def test_all_battery_sensors_are_measurement(self):
        """All battery sensors must have state_class=measurement."""
        for desc in BATTERY_SENSORS:
            assert desc.state_class == "measurement", (
                f"Sensor {desc.key} has wrong state_class: {desc.state_class}"
            )

    def test_battery_sensor_null_handling(self):
        """Battery sensors return None for null values (state 'unknown')."""
        data = _make_device_data(battery_soc_pct=None, battery_power_w=None)
        for desc in BATTERY_SENSORS:
            sensor = _make_sensor(data=data, description=desc)
            assert sensor.native_value is None


class TestGridSensorDescriptions:
    """Tests for grid sensor entity descriptions."""

    def test_grid_sensors_count(self):
        """Verify 5 grid sensors are defined."""
        assert len(GRID_SENSORS) == 5

    def test_grid_sensor_keys(self):
        """Verify grid sensor keys."""
        expected_keys = {
            "grid_import_power",
            "grid_export_power",
            "grid_daily_import",
            "grid_daily_export",
            "grid_frequency",
        }
        actual_keys = {desc.key for desc in GRID_SENSORS}
        assert actual_keys == expected_keys

    def test_grid_power_sensors(self):
        """Grid power sensors must have device_class=power, state_class=measurement."""
        for key in ("grid_import_power", "grid_export_power"):
            desc = next(d for d in GRID_SENSORS if d.key == key)
            assert desc.device_class == "power"
            assert desc.state_class == "measurement"
            assert desc.native_unit_of_measurement == "W"

    def test_grid_energy_sensors(self):
        """Grid energy sensors must have device_class=energy, state_class=total_increasing."""
        for key in ("grid_daily_import", "grid_daily_export"):
            desc = next(d for d in GRID_SENSORS if d.key == key)
            assert desc.device_class == "energy"
            assert desc.state_class == "total_increasing"
            assert desc.native_unit_of_measurement == "kWh"

    def test_grid_frequency_sensor(self):
        """Grid frequency sensor must have device_class=frequency."""
        desc = next(d for d in GRID_SENSORS if d.key == "grid_frequency")
        assert desc.device_class == "frequency"
        assert desc.state_class == "measurement"
        assert desc.native_unit_of_measurement == "Hz"

    def test_value_fn_attributes_exist_on_device_data(self):
        """All value_fn attributes must exist on DeviceData."""
        data = _make_device_data()
        for desc in GRID_SENSORS:
            assert hasattr(data, desc.value_fn)


class TestLoadSensorDescriptions:
    """Tests for load sensor entity descriptions."""

    def test_load_sensors_count(self):
        """Verify 2 load sensors are defined."""
        assert len(LOAD_SENSORS) == 2

    def test_load_sensor_keys(self):
        """Verify load sensor keys."""
        expected_keys = {"load_power", "load_daily_consumption"}
        actual_keys = {desc.key for desc in LOAD_SENSORS}
        assert actual_keys == expected_keys

    def test_load_power_sensor(self):
        """Load power sensor must have device_class=power, state_class=measurement."""
        desc = next(d for d in LOAD_SENSORS if d.key == "load_power")
        assert desc.device_class == "power"
        assert desc.state_class == "measurement"
        assert desc.native_unit_of_measurement == "W"

    def test_load_daily_consumption_sensor(self):
        """Load daily consumption must have device_class=energy, state_class=total_increasing."""
        desc = next(d for d in LOAD_SENSORS if d.key == "load_daily_consumption")
        assert desc.device_class == "energy"
        assert desc.state_class == "total_increasing"
        assert desc.native_unit_of_measurement == "kWh"

    def test_value_fn_attributes_exist_on_device_data(self):
        """All value_fn attributes must exist on DeviceData."""
        data = _make_device_data()
        for desc in LOAD_SENSORS:
            assert hasattr(data, desc.value_fn)


class TestDeyeMPPTChannelSensor:
    """Tests for the DeyeMPPTChannelSensor entity class."""

    def _make_mppt_sensor(
        self,
        device_sn: str = "INV123456",
        channel: int = 1,
        sensor_type: str = "power",
        value_attr: str = "power_w",
        data: DeviceData | None = None,
    ) -> DeyeMPPTChannelSensor:
        """Create a DeyeMPPTChannelSensor for testing."""
        if data is None:
            data = _make_device_data(
                pv_channels=[
                    MPPTChannelData(channel=1, power_w=1500.0, voltage_v=380.0, current_a=3.95),
                    MPPTChannelData(channel=2, power_w=1200.0, voltage_v=370.0, current_a=3.24),
                ]
            )
        coordinator = MockCoordinator(device_sn=device_sn, data=data)

        sensor = DeyeMPPTChannelSensor.__new__(DeyeMPPTChannelSensor)
        sensor.coordinator = coordinator
        sensor._device_sn = device_sn
        sensor._channel = channel
        sensor._value_attr = value_attr
        sensor._attr_name = f"PV Power MPPT {channel}"
        sensor._attr_device_class = "power"
        sensor._attr_state_class = "measurement"
        sensor._attr_native_unit_of_measurement = "W"
        sensor._attr_unique_id = generate_unique_id(
            device_sn, f"pv_{sensor_type}", channel
        )
        sensor._attr_device_info = {"identifiers": {("deye_cloud", device_sn)}}
        return sensor

    def test_unique_id_includes_channel(self):
        """Unique ID must include device serial and channel number."""
        sensor = self._make_mppt_sensor(device_sn="SN123", channel=2)
        assert sensor._attr_unique_id == "SN123_pv_power_2"

    def test_native_value_returns_channel_data(self):
        """Returns power from matching MPPT channel."""
        sensor = self._make_mppt_sensor(channel=1, value_attr="power_w")
        assert sensor.native_value == 1500.0

    def test_native_value_second_channel(self):
        """Returns power from second MPPT channel."""
        sensor = self._make_mppt_sensor(channel=2, value_attr="power_w")
        assert sensor.native_value == 1200.0

    def test_native_value_voltage(self):
        """Returns voltage from MPPT channel."""
        sensor = self._make_mppt_sensor(channel=1, sensor_type="voltage", value_attr="voltage_v")
        assert sensor.native_value == 380.0

    def test_native_value_current(self):
        """Returns current from MPPT channel."""
        sensor = self._make_mppt_sensor(channel=1, sensor_type="current", value_attr="current_a")
        assert sensor.native_value == 3.95

    def test_native_value_none_when_no_data(self):
        """Returns None when coordinator has no data."""
        sensor = self._make_mppt_sensor()
        sensor.coordinator.data = None
        assert sensor.native_value is None

    def test_native_value_none_when_channel_not_present(self):
        """Returns None when channel not found in pv_channels."""
        sensor = self._make_mppt_sensor(channel=5)
        assert sensor.native_value is None

    def test_native_value_none_when_empty_channels(self):
        """Returns None when pv_channels is empty."""
        data = _make_device_data(pv_channels=[])
        sensor = self._make_mppt_sensor(data=data)
        assert sensor.native_value is None


class TestDeyePhaseSensor:
    """Tests for the DeyePhaseSensor entity class."""

    def _make_phase_sensor(
        self,
        device_sn: str = "INV123456",
        phase: int = 1,
        sensor_type: str = "voltage",
        value_attr: str = "voltage_v",
        data: DeviceData | None = None,
    ) -> DeyePhaseSensor:
        """Create a DeyePhaseSensor for testing."""
        if data is None:
            data = _make_device_data(
                grid_phases=[
                    PhaseData(phase=1, voltage_v=230.1, current_a=5.2, power_w=1196.5, frequency_hz=50.01),
                    PhaseData(phase=2, voltage_v=231.5, current_a=3.8, power_w=879.7, frequency_hz=50.02),
                    PhaseData(phase=3, voltage_v=229.8, current_a=4.1, power_w=942.2, frequency_hz=50.00),
                ]
            )
        coordinator = MockCoordinator(device_sn=device_sn, data=data)

        sensor = DeyePhaseSensor.__new__(DeyePhaseSensor)
        sensor.coordinator = coordinator
        sensor._device_sn = device_sn
        sensor._phase = phase
        sensor._value_attr = value_attr
        sensor._attr_name = f"Grid Voltage Phase {phase}"
        sensor._attr_device_class = "voltage"
        sensor._attr_state_class = "measurement"
        sensor._attr_native_unit_of_measurement = "V"
        sensor._attr_unique_id = generate_unique_id(
            device_sn, f"grid_{sensor_type}", phase
        )
        sensor._attr_device_info = {"identifiers": {("deye_cloud", device_sn)}}
        return sensor

    def test_unique_id_includes_phase(self):
        """Unique ID must include device serial and phase number."""
        sensor = self._make_phase_sensor(device_sn="SN456", phase=2)
        assert sensor._attr_unique_id == "SN456_grid_voltage_2"

    def test_native_value_returns_phase_voltage(self):
        """Returns voltage from matching phase."""
        sensor = self._make_phase_sensor(phase=1, value_attr="voltage_v")
        assert sensor.native_value == 230.1

    def test_native_value_second_phase(self):
        """Returns voltage from second phase."""
        sensor = self._make_phase_sensor(phase=2, value_attr="voltage_v")
        assert sensor.native_value == 231.5

    def test_native_value_third_phase(self):
        """Returns voltage from third phase."""
        sensor = self._make_phase_sensor(phase=3, value_attr="voltage_v")
        assert sensor.native_value == 229.8

    def test_native_value_current(self):
        """Returns current from phase."""
        sensor = self._make_phase_sensor(phase=1, sensor_type="current", value_attr="current_a")
        assert sensor.native_value == 5.2

    def test_native_value_power(self):
        """Returns power from phase."""
        sensor = self._make_phase_sensor(phase=1, sensor_type="power", value_attr="power_w")
        assert sensor.native_value == 1196.5

    def test_native_value_frequency(self):
        """Returns frequency from phase."""
        sensor = self._make_phase_sensor(phase=1, sensor_type="frequency", value_attr="frequency_hz")
        assert sensor.native_value == 50.01

    def test_native_value_none_when_no_data(self):
        """Returns None when coordinator has no data."""
        sensor = self._make_phase_sensor()
        sensor.coordinator.data = None
        assert sensor.native_value is None

    def test_native_value_none_when_phase_not_present(self):
        """Returns None when phase not found in grid_phases."""
        data = _make_device_data(
            grid_phases=[
                PhaseData(phase=1, voltage_v=230.0, current_a=5.0, power_w=1150.0, frequency_hz=50.0),
            ]
        )
        sensor = self._make_phase_sensor(phase=3, data=data)
        assert sensor.native_value is None

    def test_native_value_none_when_empty_phases(self):
        """Returns None when grid_phases is empty."""
        data = _make_device_data(grid_phases=[])
        sensor = self._make_phase_sensor(data=data)
        assert sensor.native_value is None
