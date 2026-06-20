"""Tests for the Deye Cloud number platform (battery configuration)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.deye_cloud.models import Device, DeviceData, WorkMode, EnergyPattern
from custom_components.deye_cloud.number import (
    BATTERY_NUMBER_DESCRIPTIONS,
    DeyeBatteryNumberEntity,
    async_setup_entry,
)


def _make_device(
    device_sn: str = "SN123456",
    battery_soc_min: int = 10,
    battery_soc_max: int = 100,
    battery_charge_current_max: float = 50.0,
    battery_discharge_current_max: float = 50.0,
) -> Device:
    """Create a Device fixture with battery config bounds."""
    return Device(
        device_sn=device_sn,
        station_id="station_1",
        model_name="SUN-8K-SG04LP3",
        firmware_version="1.2.3",
        rated_power_w=8000,
        phase_count=3,
        mppt_count=2,
        has_battery=True,
        has_smart_load=False,
        smart_load_channels=0,
        supported_work_modes=[WorkMode.SELF_CONSUMPTION],
        supported_energy_patterns=[EnergyPattern.BATTERY_FIRST],
        battery_soc_min=battery_soc_min,
        battery_soc_max=battery_soc_max,
        battery_charge_current_max=battery_charge_current_max,
        battery_discharge_current_max=battery_discharge_current_max,
    )


def _make_device_data(
    battery_soc_min_setting: int = 20,
    battery_soc_max_setting: int = 95,
    battery_charge_current_setting: float = 30.0,
    battery_discharge_current_setting: float = 25.0,
) -> DeviceData:
    """Create a DeviceData fixture with battery settings."""
    return DeviceData(
        pv_power_total_w=5000.0,
        pv_daily_yield_kwh=15.0,
        pv_total_yield_kwh=1000.0,
        battery_soc_min_setting=battery_soc_min_setting,
        battery_soc_max_setting=battery_soc_max_setting,
        battery_charge_current_setting=battery_charge_current_setting,
        battery_discharge_current_setting=battery_discharge_current_setting,
    )


def _make_coordinator(
    device_sn: str = "SN123456",
    data: DeviceData | None = None,
) -> MagicMock:
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.device_sn = device_sn
    coordinator.data = data if data is not None else _make_device_data()
    coordinator.api = MagicMock()
    coordinator.api.set_device_config = AsyncMock(return_value=True)
    coordinator.rated_power_w = 8000
    coordinator.last_update_success = True
    return coordinator


class TestDeyeBatteryNumberEntity:
    """Tests for DeyeBatteryNumberEntity."""

    def test_entity_creation_with_device_metadata(self):
        """Entities are created with correct bounds from device metadata."""
        device = _make_device(
            battery_soc_min=10,
            battery_soc_max=100,
            battery_charge_current_max=50.0,
            battery_discharge_current_max=40.0,
        )
        coordinator = _make_coordinator()

        desc = BATTERY_NUMBER_DESCRIPTIONS[0]  # battery_soc_min
        entity = DeyeBatteryNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN123456",
            device=device,
        )

        assert entity._attr_unique_id == "SN123456_battery_soc_min"
        assert entity._attr_name == "Battery Min SOC"
        assert entity._attr_native_min_value == 10.0
        assert entity._attr_native_max_value == 100.0
        assert entity._attr_native_step == 1.0
        assert entity._attr_native_unit_of_measurement == "%"
        assert entity.available is True

    def test_entity_creation_soc_max(self):
        """SOC max entity has correct attributes."""
        device = _make_device(battery_soc_min=10, battery_soc_max=100)
        coordinator = _make_coordinator()

        desc = BATTERY_NUMBER_DESCRIPTIONS[1]  # battery_soc_max
        entity = DeyeBatteryNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN123456",
            device=device,
        )

        assert entity._attr_unique_id == "SN123456_battery_soc_max"
        assert entity._attr_name == "Battery Max SOC"
        assert entity._attr_native_min_value == 10.0
        assert entity._attr_native_max_value == 100.0
        assert entity._attr_native_step == 1.0

    def test_entity_creation_charge_current(self):
        """Charge current entity has correct attributes and step size."""
        device = _make_device(battery_charge_current_max=50.0)
        coordinator = _make_coordinator()

        desc = BATTERY_NUMBER_DESCRIPTIONS[2]  # battery_charge_current_max
        entity = DeyeBatteryNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN123456",
            device=device,
        )

        assert entity._attr_unique_id == "SN123456_battery_charge_current_max"
        assert entity._attr_name == "Battery Max Charge Current"
        assert entity._attr_native_min_value == 0.0
        assert entity._attr_native_max_value == 50.0
        assert entity._attr_native_step == 0.1
        assert entity._attr_native_unit_of_measurement == "A"

    def test_entity_creation_discharge_current(self):
        """Discharge current entity has correct attributes and step size."""
        device = _make_device(battery_discharge_current_max=40.0)
        coordinator = _make_coordinator()

        desc = BATTERY_NUMBER_DESCRIPTIONS[3]  # battery_discharge_current_max
        entity = DeyeBatteryNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN123456",
            device=device,
        )

        assert entity._attr_unique_id == "SN123456_battery_discharge_current_max"
        assert entity._attr_name == "Battery Max Discharge Current"
        assert entity._attr_native_min_value == 0.0
        assert entity._attr_native_max_value == 40.0
        assert entity._attr_native_step == 0.1

    def test_unavailable_when_no_device_metadata(self):
        """Entity is unavailable if device metadata (range) is not available."""
        coordinator = _make_coordinator()

        desc = BATTERY_NUMBER_DESCRIPTIONS[0]
        entity = DeyeBatteryNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN123456",
            device=None,
        )

        assert entity.available is False

    def test_unavailable_when_coordinator_has_no_data(self):
        """Entity is unavailable if coordinator has no data."""
        device = _make_device()
        coordinator = _make_coordinator()
        coordinator.data = None

        desc = BATTERY_NUMBER_DESCRIPTIONS[0]
        entity = DeyeBatteryNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN123456",
            device=device,
        )

        assert entity.available is False

    def test_native_value_from_coordinator_data(self):
        """Entity value is read from coordinator data."""
        device = _make_device()
        data = _make_device_data(battery_soc_min_setting=25)
        coordinator = _make_coordinator(data=data)

        desc = BATTERY_NUMBER_DESCRIPTIONS[0]  # battery_soc_min
        entity = DeyeBatteryNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN123456",
            device=device,
        )

        assert entity.native_value == 25.0

    def test_native_value_returns_none_when_no_data(self):
        """Entity returns None when coordinator has no data."""
        device = _make_device()
        coordinator = _make_coordinator()
        coordinator.data = None

        desc = BATTERY_NUMBER_DESCRIPTIONS[0]
        entity = DeyeBatteryNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN123456",
            device=device,
        )

        assert entity.native_value is None

    @pytest.mark.asyncio
    async def test_set_value_optimistic_update(self):
        """Setting a value applies optimistic update and calls API."""
        device = _make_device()
        coordinator = _make_coordinator()
        hass = MagicMock()
        hass.components = MagicMock()
        hass.components.persistent_notification = MagicMock()

        desc = BATTERY_NUMBER_DESCRIPTIONS[0]  # battery_soc_min
        entity = DeyeBatteryNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN123456",
            device=device,
        )
        entity.hass = hass

        await entity.async_set_native_value(30.0)

        # After success, optimistic value should be cleared
        assert entity._optimistic_value is None
        # API should have been called
        coordinator.api.set_device_config.assert_called_once_with(
            "SN123456", {"batterySocMin": 30.0}
        )

    @pytest.mark.asyncio
    async def test_set_value_out_of_range_rejected(self):
        """Setting a value outside bounds is rejected without API call."""
        device = _make_device(battery_soc_min=10, battery_soc_max=100)
        coordinator = _make_coordinator()
        hass = MagicMock()
        hass.components = MagicMock()
        hass.components.persistent_notification = MagicMock()
        hass.components.persistent_notification.async_create = MagicMock()

        desc = BATTERY_NUMBER_DESCRIPTIONS[0]  # battery_soc_min (min=10, max=100)
        entity = DeyeBatteryNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN123456",
            device=device,
        )
        entity.hass = hass

        await entity.async_set_native_value(5.0)  # Below min of 10

        # API should NOT be called
        coordinator.api.set_device_config.assert_not_called()
        # Notification should be raised
        hass.components.persistent_notification.async_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_value_api_rejection_reverts(self):
        """API rejection reverts entity value and raises notification."""
        device = _make_device()
        coordinator = _make_coordinator()
        coordinator.api.set_device_config = AsyncMock(
            side_effect=Exception("API error: invalid parameter")
        )
        hass = MagicMock()
        hass.components = MagicMock()
        hass.components.persistent_notification = MagicMock()
        hass.components.persistent_notification.async_create = MagicMock()

        desc = BATTERY_NUMBER_DESCRIPTIONS[0]
        entity = DeyeBatteryNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN123456",
            device=device,
        )
        entity.hass = hass

        await entity.async_set_native_value(50.0)

        # Optimistic value should be cleared (reverted)
        assert entity._optimistic_value is None
        # Notification should be raised
        hass.components.persistent_notification.async_create.assert_called_once()
        call_args = hass.components.persistent_notification.async_create.call_args
        assert "reverted" in call_args[0][0].lower()

    def test_handle_coordinator_update_clears_optimistic(self):
        """Coordinator update clears any stale optimistic value."""
        device = _make_device()
        coordinator = _make_coordinator()

        desc = BATTERY_NUMBER_DESCRIPTIONS[0]
        entity = DeyeBatteryNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN123456",
            device=device,
        )

        # Simulate an optimistic value
        entity._optimistic_value = 50.0
        assert entity.native_value == 50.0

        # Simulate coordinator update
        entity._handle_coordinator_update()
        assert entity._optimistic_value is None

    def test_unique_id_includes_device_serial(self):
        """Unique ID incorporates device serial number for uniqueness."""
        device = _make_device()
        coordinator = _make_coordinator()

        for desc in BATTERY_NUMBER_DESCRIPTIONS:
            entity = DeyeBatteryNumberEntity(
                coordinator=coordinator,
                description=desc,
                device_sn="SN123456",
                device=device,
            )
            assert "SN123456" in entity._attr_unique_id

    def test_four_entities_created(self):
        """Four battery number entities are defined."""
        assert len(BATTERY_NUMBER_DESCRIPTIONS) == 4
        keys = [d.key for d in BATTERY_NUMBER_DESCRIPTIONS]
        assert "battery_soc_min" in keys
        assert "battery_soc_max" in keys
        assert "battery_charge_current_max" in keys
        assert "battery_discharge_current_max" in keys


class TestAsyncSetupEntry:
    """Tests for the async_setup_entry platform function."""

    @pytest.mark.asyncio
    async def test_entities_created_for_each_device(self):
        """Entities are created for each device coordinator."""
        device = _make_device(device_sn="INV001")
        coordinator = _make_coordinator(device_sn="INV001")

        hass = MagicMock()
        hass.data = {
            "deye_cloud": {
                "test_entry_id": {
                    "device_coordinators": {"INV001": coordinator},
                    "devices_metadata": {"INV001": device},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry_id"

        added_entities: list = []

        def capture_entities(entities):
            added_entities.extend(entities)

        await async_setup_entry(hass, entry, capture_entities)

        # Should create 4 battery + 2 grid = 6 entities per device
        assert len(added_entities) == 6
        battery_entities = [e for e in added_entities if isinstance(e, DeyeBatteryNumberEntity)]
        assert len(battery_entities) == 4

    @pytest.mark.asyncio
    async def test_entities_created_without_device_metadata(self):
        """Entities are created but unavailable when no device metadata."""
        coordinator = _make_coordinator(device_sn="INV002")
        coordinator.rated_power_w = None

        hass = MagicMock()
        hass.data = {
            "deye_cloud": {
                "test_entry_id": {
                    "device_coordinators": {"INV002": coordinator},
                    "devices_metadata": {},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry_id"

        added_entities: list = []

        def capture_entities(entities):
            added_entities.extend(entities)

        await async_setup_entry(hass, entry, capture_entities)

        # Should still create 4 battery + 2 grid = 6 entities
        assert len(added_entities) == 6
        # Battery entities unavailable (no device metadata)
        battery_entities = [e for e in added_entities if isinstance(e, DeyeBatteryNumberEntity)]
        for ent in battery_entities:
            assert ent.available is False



# ─── Grid Control Number Entity Tests ─────────────────────────────────────────

from custom_components.deye_cloud.number import (
    GRID_NUMBER_DESCRIPTIONS,
    DeyeGridNumberEntity,
)
from custom_components.deye_cloud.const import DOMAIN


def _make_grid_device_data(
    grid_export_limit_w: int = 3000,
    peak_shaving_threshold_w: int = 4000,
) -> DeviceData:
    """Create a DeviceData fixture with grid settings."""
    return DeviceData(
        pv_power_total_w=1500.0,
        pv_daily_yield_kwh=5.2,
        pv_total_yield_kwh=1200.0,
        grid_export_limit_w=grid_export_limit_w,
        peak_shaving_threshold_w=peak_shaving_threshold_w,
    )


def _make_grid_coordinator(
    device_sn: str = "SN12345",
    rated_power_w: int | None = 5000,
    data: DeviceData | None = None,
) -> MagicMock:
    """Create a mock coordinator for grid entity tests."""
    coordinator = MagicMock()
    coordinator.device_sn = device_sn
    coordinator.rated_power_w = rated_power_w
    coordinator.data = data if data is not None else _make_grid_device_data()
    coordinator.api = MagicMock()
    coordinator.api.set_device_config = AsyncMock(return_value=True)
    coordinator.last_update_success = True
    return coordinator


class TestDeyeGridNumberEntityExportLimit:
    """Tests for DeyeGridNumberEntity - Grid Export Limit."""

    def test_unique_id_format(self):
        """Unique ID follows {device_sn}_grid_export_limit pattern."""
        device = _make_device(device_sn="SN12345")
        coordinator = _make_grid_coordinator()
        desc = GRID_NUMBER_DESCRIPTIONS[0]  # grid_export_limit

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity._attr_unique_id == "SN12345_grid_export_limit"

    def test_unique_id_different_serial(self):
        """Unique ID uses the correct serial number."""
        device = _make_device(device_sn="INV_XYZ_42")
        coordinator = _make_grid_coordinator(device_sn="INV_XYZ_42")
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="INV_XYZ_42",
            device=device,
        )

        assert entity._attr_unique_id == "INV_XYZ_42_grid_export_limit"

    def test_min_value_is_zero(self):
        """Min value is 0 W."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity._attr_native_min_value == 0.0

    def test_max_value_equals_rated_power(self):
        """Max value equals inverter rated power."""
        device = _make_device()  # rated_power_w=8000
        coordinator = _make_grid_coordinator(rated_power_w=8000)
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity.native_max_value == 8000.0

    def test_step_is_one(self):
        """Step size is 1 W."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity._attr_native_step == 1.0

    def test_native_value_from_coordinator(self):
        """native_value reads grid_export_limit_w from coordinator data."""
        device = _make_device()
        data = _make_grid_device_data(grid_export_limit_w=3000)
        coordinator = _make_grid_coordinator(data=data)
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity.native_value == 3000.0

    def test_native_value_none_when_no_data(self):
        """native_value returns None when coordinator has no data."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        coordinator.data = None
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity.native_value is None

    def test_available_when_rated_power_known(self):
        """Entity is available when rated_power_w is known."""
        device = _make_device()  # rated_power_w=8000
        coordinator = _make_grid_coordinator()
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity.available is True

    def test_unavailable_when_rated_power_unknown(self):
        """Entity is unavailable when rated_power_w is unknown."""
        device = _make_device()
        device.rated_power_w = 0
        coordinator = _make_grid_coordinator(rated_power_w=None)
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity.available is False

    def test_unavailable_when_no_device_and_no_coordinator_rated_power(self):
        """Entity is unavailable when both device and coordinator have no rated power."""
        coordinator = _make_grid_coordinator(rated_power_w=None)
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=None,
        )

        assert entity.available is False

    def test_device_info_identifiers(self):
        """device_info links to the correct device."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity._attr_device_info["identifiers"] == {(DOMAIN, "SN12345")}

    @pytest.mark.asyncio
    async def test_set_value_sends_to_api(self):
        """Setting a valid value sends it to the API."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        hass = MagicMock()
        hass.components = MagicMock()
        hass.components.persistent_notification = MagicMock()
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )
        entity.hass = hass

        await entity.async_set_native_value(2500.0)

        coordinator.api.set_device_config.assert_called_once_with(
            "SN12345", {"gridExportLimit": 2500}
        )

    @pytest.mark.asyncio
    async def test_set_value_optimistic_update(self):
        """Setting a value performs optimistic state update."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        hass = MagicMock()
        hass.components = MagicMock()
        hass.components.persistent_notification = MagicMock()
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )
        entity.hass = hass

        await entity.async_set_native_value(4000.0)

        # After success, optimistic value should be cleared
        assert entity._optimistic_value is None

    @pytest.mark.asyncio
    async def test_set_value_reverts_on_api_failure(self):
        """Value reverts on API rejection and notification is raised."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        coordinator.api.set_device_config = AsyncMock(
            side_effect=Exception("API rejected")
        )
        hass = MagicMock()
        hass.components = MagicMock()
        hass.components.persistent_notification = MagicMock()
        hass.components.persistent_notification.async_create = MagicMock()
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )
        entity.hass = hass

        await entity.async_set_native_value(2000.0)

        # Optimistic value should be cleared (reverted)
        assert entity._optimistic_value is None
        # Notification should be raised
        hass.components.persistent_notification.async_create.assert_called_once()
        call_args = hass.components.persistent_notification.async_create.call_args
        assert "reverted" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_set_value_rejects_out_of_range(self):
        """Rejects value outside valid range without calling API."""
        device = _make_device()  # rated_power_w=8000
        coordinator = _make_grid_coordinator(rated_power_w=8000)
        hass = MagicMock()
        hass.components = MagicMock()
        hass.components.persistent_notification = MagicMock()
        hass.components.persistent_notification.async_create = MagicMock()
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )
        entity.hass = hass

        await entity.async_set_native_value(9000.0)  # Above max 8000

        # API should NOT be called
        coordinator.api.set_device_config.assert_not_called()
        # Notification should be raised
        hass.components.persistent_notification.async_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_value_rejects_negative(self):
        """Rejects negative value without calling API."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        hass = MagicMock()
        hass.components = MagicMock()
        hass.components.persistent_notification = MagicMock()
        hass.components.persistent_notification.async_create = MagicMock()
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )
        entity.hass = hass

        await entity.async_set_native_value(-100.0)

        coordinator.api.set_device_config.assert_not_called()
        hass.components.persistent_notification.async_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_boundary_zero(self):
        """Setting value to 0 (min boundary) succeeds."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        hass = MagicMock()
        hass.components = MagicMock()
        hass.components.persistent_notification = MagicMock()
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )
        entity.hass = hass

        await entity.async_set_native_value(0.0)

        coordinator.api.set_device_config.assert_called_with(
            "SN12345", {"gridExportLimit": 0}
        )

    @pytest.mark.asyncio
    async def test_set_boundary_max(self):
        """Setting value to rated_power_w (max boundary) succeeds."""
        device = _make_device()  # rated_power_w=8000
        coordinator = _make_grid_coordinator(rated_power_w=8000)
        hass = MagicMock()
        hass.components = MagicMock()
        hass.components.persistent_notification = MagicMock()
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )
        entity.hass = hass

        await entity.async_set_native_value(8000.0)

        coordinator.api.set_device_config.assert_called_with(
            "SN12345", {"gridExportLimit": 8000}
        )

    def test_coordinator_update_clears_optimistic(self):
        """Coordinator update clears any stale optimistic value."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        desc = GRID_NUMBER_DESCRIPTIONS[0]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        entity._optimistic_value = 1234.0
        assert entity.native_value == 1234.0

        entity._handle_coordinator_update()
        assert entity._optimistic_value is None


class TestDeyeGridNumberEntityPeakShaving:
    """Tests for DeyeGridNumberEntity - Peak Shaving Threshold."""

    def test_unique_id_format(self):
        """Unique ID follows {device_sn}_peak_shaving_threshold pattern."""
        device = _make_device(device_sn="SN12345")
        coordinator = _make_grid_coordinator()
        desc = GRID_NUMBER_DESCRIPTIONS[1]  # peak_shaving_threshold

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity._attr_unique_id == "SN12345_peak_shaving_threshold"

    def test_min_value_is_zero(self):
        """Min value is 0 W."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        desc = GRID_NUMBER_DESCRIPTIONS[1]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity._attr_native_min_value == 0.0

    def test_max_value_equals_rated_power(self):
        """Max value equals inverter rated power."""
        device = _make_device()  # rated_power_w=8000
        coordinator = _make_grid_coordinator(rated_power_w=8000)
        desc = GRID_NUMBER_DESCRIPTIONS[1]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity.native_max_value == 8000.0

    def test_step_is_one(self):
        """Step size is 1 W."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        desc = GRID_NUMBER_DESCRIPTIONS[1]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity._attr_native_step == 1.0

    def test_native_value_from_coordinator(self):
        """native_value reads peak_shaving_threshold_w from coordinator data."""
        device = _make_device()
        data = _make_grid_device_data(peak_shaving_threshold_w=4500)
        coordinator = _make_grid_coordinator(data=data)
        desc = GRID_NUMBER_DESCRIPTIONS[1]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity.native_value == 4500.0

    def test_unavailable_when_rated_power_unknown(self):
        """Entity is unavailable when rated_power_w is unknown."""
        device = _make_device()
        device.rated_power_w = 0
        coordinator = _make_grid_coordinator(rated_power_w=None)
        desc = GRID_NUMBER_DESCRIPTIONS[1]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )

        assert entity.available is False

    @pytest.mark.asyncio
    async def test_set_value_sends_to_api(self):
        """Setting a valid value sends it to the API with correct param key."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        hass = MagicMock()
        hass.components = MagicMock()
        hass.components.persistent_notification = MagicMock()
        desc = GRID_NUMBER_DESCRIPTIONS[1]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )
        entity.hass = hass

        await entity.async_set_native_value(3500.0)

        coordinator.api.set_device_config.assert_called_once_with(
            "SN12345", {"peakShavingThreshold": 3500}
        )

    @pytest.mark.asyncio
    async def test_set_value_reverts_on_api_failure(self):
        """Value reverts on API rejection and notification is raised."""
        device = _make_device()
        coordinator = _make_grid_coordinator()
        coordinator.api.set_device_config = AsyncMock(
            side_effect=Exception("API rejected")
        )
        hass = MagicMock()
        hass.components = MagicMock()
        hass.components.persistent_notification = MagicMock()
        hass.components.persistent_notification.async_create = MagicMock()
        desc = GRID_NUMBER_DESCRIPTIONS[1]

        entity = DeyeGridNumberEntity(
            coordinator=coordinator,
            description=desc,
            device_sn="SN12345",
            device=device,
        )
        entity.hass = hass

        await entity.async_set_native_value(1500.0)

        assert entity._optimistic_value is None
        hass.components.persistent_notification.async_create.assert_called_once()
        call_args = hass.components.persistent_notification.async_create.call_args
        assert "reverted" in call_args[0][0].lower()


class TestAsyncSetupEntryGridEntities:
    """Tests for async_setup_entry creating grid number entities."""

    @pytest.mark.asyncio
    async def test_grid_entities_created_per_inverter(self):
        """Grid entities are created for each inverter."""
        device = _make_device(device_sn="INV001")
        coordinator = _make_grid_coordinator(device_sn="INV001")

        hass = MagicMock()
        hass.data = {
            "deye_cloud": {
                "test_entry_id": {
                    "device_coordinators": {"INV001": coordinator},
                    "devices_metadata": {"INV001": device},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry_id"

        added_entities: list = []

        def capture_entities(entities):
            added_entities.extend(entities)

        await async_setup_entry(hass, entry, capture_entities)

        # Should have battery (4) + grid (2) = 6 entities
        grid_entities = [e for e in added_entities if isinstance(e, DeyeGridNumberEntity)]
        assert len(grid_entities) == 2

        grid_unique_ids = {e._attr_unique_id for e in grid_entities}
        assert "INV001_grid_export_limit" in grid_unique_ids
        assert "INV001_peak_shaving_threshold" in grid_unique_ids

    @pytest.mark.asyncio
    async def test_grid_entities_created_without_device_meta(self):
        """Grid entities are created but unavailable without device metadata."""
        coordinator = _make_grid_coordinator(device_sn="INV002", rated_power_w=None)

        hass = MagicMock()
        hass.data = {
            "deye_cloud": {
                "test_entry_id": {
                    "device_coordinators": {"INV002": coordinator},
                    "devices_metadata": {},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry_id"

        added_entities: list = []

        def capture_entities(entities):
            added_entities.extend(entities)

        await async_setup_entry(hass, entry, capture_entities)

        grid_entities = [e for e in added_entities if isinstance(e, DeyeGridNumberEntity)]
        assert len(grid_entities) == 2
        # All should be unavailable since no rated power
        for ent in grid_entities:
            assert ent.available is False

    @pytest.mark.asyncio
    async def test_multiple_inverters_get_separate_grid_entities(self):
        """Multiple inverters get separate grid entities with unique IDs."""
        device1 = _make_device(device_sn="INV001")
        device2 = _make_device(device_sn="INV002")
        coord1 = _make_grid_coordinator(device_sn="INV001")
        coord2 = _make_grid_coordinator(device_sn="INV002", rated_power_w=10000)

        hass = MagicMock()
        hass.data = {
            "deye_cloud": {
                "test_entry_id": {
                    "device_coordinators": {
                        "INV001": coord1,
                        "INV002": coord2,
                    },
                    "devices_metadata": {
                        "INV001": device1,
                        "INV002": device2,
                    },
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry_id"

        added_entities: list = []

        def capture_entities(entities):
            added_entities.extend(entities)

        await async_setup_entry(hass, entry, capture_entities)

        grid_entities = [e for e in added_entities if isinstance(e, DeyeGridNumberEntity)]
        # 2 grid entities per inverter × 2 inverters = 4
        assert len(grid_entities) == 4

        grid_unique_ids = {e._attr_unique_id for e in grid_entities}
        assert "INV001_grid_export_limit" in grid_unique_ids
        assert "INV001_peak_shaving_threshold" in grid_unique_ids
        assert "INV002_grid_export_limit" in grid_unique_ids
        assert "INV002_peak_shaving_threshold" in grid_unique_ids
