"""Tests for station aggregate sensor entities."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from custom_components.deye_cloud.models import DeviceData
from custom_components.deye_cloud.sensor import (
    DeyeStationDailyConsumptionSensor,
    DeyeStationDailyProductionSensor,
    DeyeStationTotalPowerSensor,
    async_setup_entry,
)
from custom_components.deye_cloud.const import DOMAIN


def _make_coordinator(
    device_sn: str = "INV001",
    is_online: bool = True,
    pv_power_total_w: float = 1000.0,
    pv_daily_yield_kwh: float = 5.0,
    load_daily_consumption_kwh: float = 3.0,
):
    """Create a mock coordinator with device data."""
    coordinator = MagicMock()
    coordinator.device_sn = device_sn
    coordinator.data = DeviceData(
        pv_power_total_w=pv_power_total_w,
        pv_daily_yield_kwh=pv_daily_yield_kwh,
        pv_total_yield_kwh=100.0,
        load_power_w=500.0,
        load_daily_consumption_kwh=load_daily_consumption_kwh,
        is_online=is_online,
        last_update_time=datetime(2024, 1, 15, 12, 0, 0),
    )
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    return coordinator


def _make_station_metadata():
    """Return a sample station metadata dict."""
    return {
        "name": "Home Station",
        "latitude": 51.5074,
        "longitude": -0.1278,
        "rated_capacity_kwp": 10.0,
    }


class TestDeyeStationTotalPowerSensor:
    """Tests for DeyeStationTotalPowerSensor."""

    def test_aggregates_power_from_multiple_inverters(self):
        """Station total power sums all child inverters' PV power."""
        coord1 = _make_coordinator("INV001", pv_power_total_w=1500.0)
        coord2 = _make_coordinator("INV002", pv_power_total_w=2000.0)

        sensor = DeyeStationTotalPowerSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord1, coord2],
        )

        assert sensor.native_value == 3500.0

    def test_single_inverter_power(self):
        """Station total power with a single inverter."""
        coord = _make_coordinator("INV001", pv_power_total_w=3200.0)

        sensor = DeyeStationTotalPowerSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord],
        )

        assert sensor.native_value == 3200.0

    def test_unavailable_when_all_offline(self):
        """Station sensor unavailable when all inverters are offline."""
        coord1 = _make_coordinator("INV001", is_online=False)
        coord2 = _make_coordinator("INV002", is_online=False)

        sensor = DeyeStationTotalPowerSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord1, coord2],
        )

        assert sensor.available is False
        assert sensor.native_value is None

    def test_available_when_one_online(self):
        """Station sensor available if at least one inverter is online."""
        coord1 = _make_coordinator("INV001", is_online=True, pv_power_total_w=1000.0)
        coord2 = _make_coordinator("INV002", is_online=False)

        sensor = DeyeStationTotalPowerSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord1, coord2],
        )

        assert sensor.available is True
        # Only sums online inverters
        assert sensor.native_value == 1000.0

    def test_device_class_and_state_class(self):
        """Station total power has correct device_class and state_class."""
        coord = _make_coordinator("INV001")

        sensor = DeyeStationTotalPowerSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord],
        )

        assert sensor._attr_device_class == "power"
        assert sensor._attr_state_class == "measurement"
        assert sensor._attr_native_unit_of_measurement == "W"

    def test_unique_id(self):
        """Station total power sensor has correct unique_id."""
        coord = _make_coordinator("INV001")

        sensor = DeyeStationTotalPowerSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord],
        )

        assert sensor._attr_unique_id == "station_ST001_total_power"

    def test_device_info(self):
        """Station sensor has correct device_info for station device entry."""
        coord = _make_coordinator("INV001")

        sensor = DeyeStationTotalPowerSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord],
        )

        device_info = sensor.device_info
        assert device_info.get("identifiers") == {(DOMAIN, "station_ST001")}
        assert device_info.get("name") == "Home Station"
        assert device_info.get("manufacturer") == "Deye"
        assert device_info.get("model") == "Solar Station"

    def test_extra_state_attributes(self):
        """Station sensor exposes station metadata as attributes."""
        coord = _make_coordinator("INV001")
        metadata = _make_station_metadata()

        sensor = DeyeStationTotalPowerSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=metadata,
            child_coordinators=[coord],
        )

        attrs = sensor.extra_state_attributes
        assert attrs["station_name"] == "Home Station"
        assert attrs["latitude"] == 51.5074
        assert attrs["longitude"] == -0.1278
        assert attrs["rated_capacity_kwp"] == 10.0

    def test_unavailable_when_coordinator_data_none(self):
        """Station sensor unavailable when coordinator.data is None."""
        coord = MagicMock()
        coord.data = None
        coord.async_add_listener = MagicMock(return_value=lambda: None)

        sensor = DeyeStationTotalPowerSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord],
        )

        assert sensor.available is False


class TestDeyeStationDailyProductionSensor:
    """Tests for DeyeStationDailyProductionSensor."""

    def test_aggregates_daily_yield(self):
        """Station daily production sums all child inverters' daily yield."""
        coord1 = _make_coordinator("INV001", pv_daily_yield_kwh=8.5)
        coord2 = _make_coordinator("INV002", pv_daily_yield_kwh=7.3)

        sensor = DeyeStationDailyProductionSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord1, coord2],
        )

        assert sensor.native_value == pytest.approx(15.8)

    def test_device_class_and_state_class(self):
        """Station daily production has energy device_class and total_increasing state."""
        coord = _make_coordinator("INV001")

        sensor = DeyeStationDailyProductionSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord],
        )

        assert sensor._attr_device_class == "energy"
        assert sensor._attr_state_class == "total_increasing"
        assert sensor._attr_native_unit_of_measurement == "kWh"

    def test_unique_id(self):
        """Station daily production has correct unique_id."""
        coord = _make_coordinator("INV001")

        sensor = DeyeStationDailyProductionSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord],
        )

        assert sensor._attr_unique_id == "station_ST001_daily_production"

    def test_unavailable_when_all_offline(self):
        """Station daily production unavailable when all inverters offline."""
        coord1 = _make_coordinator("INV001", is_online=False)
        coord2 = _make_coordinator("INV002", is_online=False)

        sensor = DeyeStationDailyProductionSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord1, coord2],
        )

        assert sensor.available is False
        assert sensor.native_value is None

    def test_only_sums_online_inverters(self):
        """Only online inverters contribute to aggregate daily production."""
        coord1 = _make_coordinator("INV001", is_online=True, pv_daily_yield_kwh=6.0)
        coord2 = _make_coordinator("INV002", is_online=False, pv_daily_yield_kwh=4.0)

        sensor = DeyeStationDailyProductionSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord1, coord2],
        )

        assert sensor.native_value == 6.0


class TestDeyeStationDailyConsumptionSensor:
    """Tests for DeyeStationDailyConsumptionSensor."""

    def test_aggregates_daily_consumption(self):
        """Station daily consumption sums all child inverters' consumption."""
        coord1 = _make_coordinator("INV001", load_daily_consumption_kwh=4.2)
        coord2 = _make_coordinator("INV002", load_daily_consumption_kwh=3.8)

        sensor = DeyeStationDailyConsumptionSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord1, coord2],
        )

        assert sensor.native_value == pytest.approx(8.0)

    def test_device_class_and_state_class(self):
        """Station daily consumption has energy device_class and total_increasing state."""
        coord = _make_coordinator("INV001")

        sensor = DeyeStationDailyConsumptionSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord],
        )

        assert sensor._attr_device_class == "energy"
        assert sensor._attr_state_class == "total_increasing"
        assert sensor._attr_native_unit_of_measurement == "kWh"

    def test_unique_id(self):
        """Station daily consumption has correct unique_id."""
        coord = _make_coordinator("INV001")

        sensor = DeyeStationDailyConsumptionSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord],
        )

        assert sensor._attr_unique_id == "station_ST001_daily_consumption"

    def test_unavailable_when_all_offline(self):
        """Station daily consumption unavailable when all inverters offline."""
        coord = _make_coordinator("INV001", is_online=False)

        sensor = DeyeStationDailyConsumptionSensor(
            station_id="ST001",
            station_name="Home Station",
            metadata=_make_station_metadata(),
            child_coordinators=[coord],
        )

        assert sensor.available is False
        assert sensor.native_value is None


class TestAsyncSetupEntry:
    """Tests for the sensor platform async_setup_entry function."""

    @pytest.mark.asyncio
    async def test_creates_station_sensors(self):
        """Setup creates 3 aggregate sensors per station plus per-device sensors."""
        coord = _make_coordinator("INV001")
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry"

        hass.data = {
            DOMAIN: {
                "test_entry": {
                    "device_coordinators": {"INV001": coord},
                    "stations_metadata": {
                        "ST001": _make_station_metadata(),
                    },
                    "station_devices_map": {
                        "ST001": ["INV001"],
                    },
                }
            }
        }

        added_entities = []

        def mock_add_entities(entities):
            added_entities.extend(entities)

        await async_setup_entry(hass, entry, mock_add_entities)

        # Per-device sensors (no device metadata so mppt=0, phase=1):
        # 6 energy + 3 PV + 5 battery + 5 grid + 2 load + 4 phase + 1 last_update = 26
        # Plus 3 station sensors = 29 total
        station_sensors = [
            e for e in added_entities
            if isinstance(e, (DeyeStationTotalPowerSensor, DeyeStationDailyProductionSensor, DeyeStationDailyConsumptionSensor))
        ]
        assert len(station_sensors) == 3
        assert isinstance(station_sensors[0], DeyeStationTotalPowerSensor)
        assert isinstance(station_sensors[1], DeyeStationDailyProductionSensor)
        assert isinstance(station_sensors[2], DeyeStationDailyConsumptionSensor)

    @pytest.mark.asyncio
    async def test_skips_station_without_coordinators(self):
        """Setup skips stations whose inverters are not configured."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry"

        hass.data = {
            DOMAIN: {
                "test_entry": {
                    "device_coordinators": {},
                    "stations_metadata": {
                        "ST001": _make_station_metadata(),
                    },
                    "station_devices_map": {
                        "ST001": ["INV_NOT_CONFIGURED"],
                    },
                }
            }
        }

        added_entities = []
        await async_setup_entry(hass, entry, lambda entities: added_entities.extend(entities))

        assert len(added_entities) == 0

    @pytest.mark.asyncio
    async def test_multiple_stations(self):
        """Setup creates sensors for multiple stations plus per-device sensors."""
        coord1 = _make_coordinator("INV001")
        coord2 = _make_coordinator("INV002")
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry"

        hass.data = {
            DOMAIN: {
                "test_entry": {
                    "device_coordinators": {"INV001": coord1, "INV002": coord2},
                    "stations_metadata": {
                        "ST001": _make_station_metadata(),
                        "ST002": {
                            "name": "Office Station",
                            "latitude": 40.7128,
                            "longitude": -74.0060,
                            "rated_capacity_kwp": 20.0,
                        },
                    },
                    "station_devices_map": {
                        "ST001": ["INV001"],
                        "ST002": ["INV002"],
                    },
                }
            }
        }

        added_entities = []
        await async_setup_entry(hass, entry, lambda entities: added_entities.extend(entities))

        # 3 station sensors per station × 2 stations = 6 station sensors
        station_sensors = [
            e for e in added_entities
            if isinstance(e, (DeyeStationTotalPowerSensor, DeyeStationDailyProductionSensor, DeyeStationDailyConsumptionSensor))
        ]
        assert len(station_sensors) == 6
