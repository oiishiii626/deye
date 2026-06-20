"""Tests for the Deye Cloud binary sensor platform."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta

from custom_components.deye_cloud.binary_sensor import (
    async_setup_entry,
    DeyeOnlineBinarySensor,
)
from custom_components.deye_cloud.const import DOMAIN
from custom_components.deye_cloud.models import DeviceData


@pytest.fixture
def mock_device_data_online():
    """Create a DeviceData instance that is online."""
    return DeviceData(
        pv_power_total_w=1500.0,
        pv_daily_yield_kwh=5.2,
        pv_total_yield_kwh=1200.0,
        is_online=True,
    )


@pytest.fixture
def mock_device_data_offline():
    """Create a DeviceData instance that is offline."""
    return DeviceData(
        pv_power_total_w=0.0,
        pv_daily_yield_kwh=0.0,
        pv_total_yield_kwh=1200.0,
        is_online=False,
    )


@pytest.fixture
def mock_coordinator(mock_device_data_online):
    """Create a mock DeyeDeviceCoordinator with online data."""
    coordinator = MagicMock()
    coordinator.data = mock_device_data_online
    coordinator.device_sn = "SN12345"
    return coordinator


@pytest.fixture
def mock_hass():
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.data = {}
    return hass


@pytest.fixture
def mock_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    return entry


class TestDeyeOnlineBinarySensor:
    """Tests for DeyeOnlineBinarySensor entity."""

    def test_is_on_returns_true_when_online(self, mock_coordinator, mock_device_data_online):
        """Test is_on returns True when inverter is online."""
        mock_coordinator.data = mock_device_data_online
        sensor = DeyeOnlineBinarySensor(mock_coordinator, "SN12345")

        assert sensor.is_on is True

    def test_is_on_returns_false_when_offline(self, mock_coordinator, mock_device_data_offline):
        """Test is_on returns False when inverter is offline."""
        mock_coordinator.data = mock_device_data_offline
        sensor = DeyeOnlineBinarySensor(mock_coordinator, "SN12345")

        assert sensor.is_on is False

    def test_is_on_returns_none_when_no_data(self, mock_coordinator):
        """Test is_on returns None when coordinator has no data yet."""
        mock_coordinator.data = None
        sensor = DeyeOnlineBinarySensor(mock_coordinator, "SN12345")

        assert sensor.is_on is None

    def test_unique_id_format(self, mock_coordinator):
        """Test unique_id follows {device_sn}_online_status pattern."""
        sensor = DeyeOnlineBinarySensor(mock_coordinator, "SN12345")

        assert sensor.unique_id == "SN12345_online_status"

    def test_unique_id_different_serial(self, mock_coordinator):
        """Test unique_id uses the correct serial number."""
        sensor = DeyeOnlineBinarySensor(mock_coordinator, "INV_ABC_99")

        assert sensor.unique_id == "INV_ABC_99_online_status"

    def test_device_class_is_connectivity(self, mock_coordinator):
        """Test device_class is set to CONNECTIVITY."""
        from homeassistant.components.binary_sensor import BinarySensorDeviceClass

        sensor = DeyeOnlineBinarySensor(mock_coordinator, "SN12345")

        assert sensor.device_class == BinarySensorDeviceClass.CONNECTIVITY

    def test_device_info_identifiers(self, mock_coordinator):
        """Test device_info links to the correct device."""
        sensor = DeyeOnlineBinarySensor(mock_coordinator, "SN12345")
        device_info = sensor.device_info

        assert device_info["identifiers"] == {(DOMAIN, "SN12345")}

    def test_has_entity_name(self, mock_coordinator):
        """Test entity uses has_entity_name pattern."""
        sensor = DeyeOnlineBinarySensor(mock_coordinator, "SN12345")

        assert sensor._attr_has_entity_name is True
        assert sensor._attr_name == "Online Status"


class TestAsyncSetupEntry:
    """Tests for async_setup_entry platform function."""

    @pytest.mark.asyncio
    async def test_creates_one_sensor_per_inverter(self, mock_hass, mock_entry):
        """Test that one binary sensor is created per configured inverter."""
        coord1 = MagicMock()
        coord1.data = DeviceData(
            pv_power_total_w=0.0, pv_daily_yield_kwh=0.0, pv_total_yield_kwh=0.0, is_online=True
        )
        coord1.device_sn = "SN001"

        coord2 = MagicMock()
        coord2.data = DeviceData(
            pv_power_total_w=0.0, pv_daily_yield_kwh=0.0, pv_total_yield_kwh=0.0, is_online=False
        )
        coord2.device_sn = "SN002"

        mock_hass.data[DOMAIN] = {
            mock_entry.entry_id: {
                "device_coordinators": {
                    "SN001": coord1,
                    "SN002": coord2,
                },
            }
        }

        added_entities = []
        async_add_entities = lambda entities: added_entities.extend(entities)

        await async_setup_entry(mock_hass, mock_entry, async_add_entities)

        assert len(added_entities) == 2
        assert all(isinstance(e, DeyeOnlineBinarySensor) for e in added_entities)

        # Verify unique IDs are distinct
        unique_ids = {e.unique_id for e in added_entities}
        assert unique_ids == {"SN001_online_status", "SN002_online_status"}

    @pytest.mark.asyncio
    async def test_creates_no_sensors_when_no_inverters(self, mock_hass, mock_entry):
        """Test that no sensors are created when there are no inverters."""
        mock_hass.data[DOMAIN] = {
            mock_entry.entry_id: {
                "device_coordinators": {},
            }
        }

        added_entities = []
        async_add_entities = lambda entities: added_entities.extend(entities)

        await async_setup_entry(mock_hass, mock_entry, async_add_entities)

        assert len(added_entities) == 0
