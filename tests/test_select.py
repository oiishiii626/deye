"""Tests for the Deye Cloud select platform."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.deye_cloud.models import (
    Device,
    DeviceData,
    EnergyPattern,
    WorkMode,
)
from custom_components.deye_cloud.exceptions import DeyeApiError
from custom_components.deye_cloud.select import (
    DeyeEnergyPatternSelect,
    DeyeWorkModeSelect,
    ENERGY_PATTERN_NAMES,
    WORK_MODE_NAMES,
    async_setup_entry,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_device():
    """Create a mock Device with all work modes and energy patterns."""
    return Device(
        device_sn="TEST123",
        station_id="station_1",
        model_name="SUN-5K-SG03LP1-EU",
        firmware_version="1.0.0",
        rated_power_w=5000,
        phase_count=1,
        mppt_count=2,
        has_battery=True,
        has_smart_load=False,
        smart_load_channels=0,
        supported_work_modes=[
            WorkMode.SELF_CONSUMPTION,
            WorkMode.TIME_OF_USE,
            WorkMode.SELLING_FIRST,
            WorkMode.ZERO_EXPORT,
        ],
        supported_energy_patterns=[
            EnergyPattern.BATTERY_FIRST,
            EnergyPattern.LOAD_FIRST,
        ],
    )


@pytest.fixture
def mock_device_data():
    """Create a DeviceData instance with default values."""
    return DeviceData(
        pv_power_total_w=1500.0,
        pv_daily_yield_kwh=8.5,
        pv_total_yield_kwh=1200.0,
        work_mode=WorkMode.SELF_CONSUMPTION,
        energy_pattern=EnergyPattern.BATTERY_FIRST,
    )


@pytest.fixture
def mock_coordinator(mock_device_data):
    """Create a mock coordinator with device data."""
    coordinator = MagicMock()
    coordinator.data = mock_device_data
    coordinator.device_sn = "TEST123"
    coordinator.device_name = "Deye TEST123"
    return coordinator


@pytest.fixture
def mock_api():
    """Create a mock DeyeCloudAPI."""
    api = MagicMock()
    api.set_work_mode = AsyncMock(return_value=True)
    api.set_energy_pattern = AsyncMock(return_value=True)
    return api


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.components = MagicMock()
    hass.components.persistent_notification = MagicMock()
    hass.components.persistent_notification.async_create = MagicMock()
    return hass


# ─── Work Mode Select Tests ──────────────────────────────────────────────────


class TestDeyeWorkModeSelect:
    """Tests for the DeyeWorkModeSelect entity."""

    def test_options_match_supported_modes(self, mock_coordinator, mock_api):
        """Options should be the human-readable names of supported work modes."""
        supported_modes = [
            WorkMode.SELF_CONSUMPTION,
            WorkMode.TIME_OF_USE,
            WorkMode.SELLING_FIRST,
        ]
        entity = DeyeWorkModeSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_modes=supported_modes,
        )
        expected_options = [
            "Self Consumption",
            "Time of Use",
            "Selling First",
        ]
        assert entity._attr_options == expected_options

    def test_current_option_from_coordinator_data(
        self, mock_coordinator, mock_api
    ):
        """current_option should reflect the work mode from coordinator data."""
        entity = DeyeWorkModeSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_modes=[WorkMode.SELF_CONSUMPTION, WorkMode.TIME_OF_USE],
        )
        assert entity.current_option == "Self Consumption"

    def test_current_option_none_when_no_data(self, mock_api):
        """current_option should return None when coordinator has no data."""
        coordinator = MagicMock()
        coordinator.data = None
        entity = DeyeWorkModeSelect(
            coordinator=coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_modes=[WorkMode.SELF_CONSUMPTION],
        )
        assert entity.current_option is None

    @pytest.mark.asyncio
    async def test_select_option_success(
        self, mock_coordinator, mock_api, mock_hass
    ):
        """Selecting an option should update coordinator data and call the API."""
        entity = DeyeWorkModeSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_modes=[WorkMode.SELF_CONSUMPTION, WorkMode.TIME_OF_USE],
        )
        entity.hass = mock_hass
        entity.async_write_ha_state = MagicMock()

        await entity.async_select_option("Time of Use")

        # Verify optimistic update was applied
        assert mock_coordinator.data.work_mode == WorkMode.TIME_OF_USE
        # Verify API was called with correct mode integer
        mock_api.set_work_mode.assert_called_once_with("TEST123", 1)
        # Verify state was written
        entity.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_select_option_api_rejection_reverts(
        self, mock_coordinator, mock_api, mock_hass
    ):
        """On API rejection, entity should revert to previous value and notify."""
        mock_api.set_work_mode = AsyncMock(
            side_effect=DeyeApiError("Rejected by inverter", error_code="4001")
        )
        entity = DeyeWorkModeSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_modes=[WorkMode.SELF_CONSUMPTION, WorkMode.TIME_OF_USE],
        )
        entity.hass = mock_hass
        entity.async_write_ha_state = MagicMock()

        # Initial state is SELF_CONSUMPTION
        await entity.async_select_option("Time of Use")

        # Should revert to SELF_CONSUMPTION
        assert mock_coordinator.data.work_mode == WorkMode.SELF_CONSUMPTION
        # Should create a persistent notification
        mock_hass.components.persistent_notification.async_create.assert_called_once()
        call_kwargs = (
            mock_hass.components.persistent_notification.async_create.call_args
        )
        assert "Work Mode" in call_kwargs.kwargs.get("title", "") or "Work Mode" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_select_unknown_option_does_nothing(
        self, mock_coordinator, mock_api, mock_hass
    ):
        """Selecting an unknown option should not call the API."""
        entity = DeyeWorkModeSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_modes=[WorkMode.SELF_CONSUMPTION],
        )
        entity.hass = mock_hass
        entity.async_write_ha_state = MagicMock()

        await entity.async_select_option("Nonexistent Mode")

        mock_api.set_work_mode.assert_not_called()

    def test_unique_id_includes_device_sn(self, mock_coordinator, mock_api):
        """Unique ID should incorporate the device serial number."""
        entity = DeyeWorkModeSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_modes=[WorkMode.SELF_CONSUMPTION],
        )
        assert "TEST123" in entity._attr_unique_id
        assert "work_mode" in entity._attr_unique_id


# ─── Energy Pattern Select Tests ──────────────────────────────────────────────


class TestDeyeEnergyPatternSelect:
    """Tests for the DeyeEnergyPatternSelect entity."""

    def test_options_match_supported_patterns(self, mock_coordinator, mock_api):
        """Options should be the human-readable names of supported energy patterns."""
        supported_patterns = [
            EnergyPattern.BATTERY_FIRST,
            EnergyPattern.LOAD_FIRST,
        ]
        entity = DeyeEnergyPatternSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_patterns=supported_patterns,
        )
        expected_options = ["Battery First", "Load First"]
        assert entity._attr_options == expected_options

    def test_current_option_from_coordinator_data(
        self, mock_coordinator, mock_api
    ):
        """current_option should reflect the energy pattern from coordinator data."""
        entity = DeyeEnergyPatternSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_patterns=[EnergyPattern.BATTERY_FIRST, EnergyPattern.LOAD_FIRST],
        )
        assert entity.current_option == "Battery First"

    def test_current_option_none_when_no_data(self, mock_api):
        """current_option should return None when coordinator has no data."""
        coordinator = MagicMock()
        coordinator.data = None
        entity = DeyeEnergyPatternSelect(
            coordinator=coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_patterns=[EnergyPattern.BATTERY_FIRST],
        )
        assert entity.current_option is None

    @pytest.mark.asyncio
    async def test_select_option_success(
        self, mock_coordinator, mock_api, mock_hass
    ):
        """Selecting an option should update coordinator data and call the API."""
        entity = DeyeEnergyPatternSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_patterns=[EnergyPattern.BATTERY_FIRST, EnergyPattern.LOAD_FIRST],
        )
        entity.hass = mock_hass
        entity.async_write_ha_state = MagicMock()

        await entity.async_select_option("Load First")

        # Verify optimistic update was applied
        assert mock_coordinator.data.energy_pattern == EnergyPattern.LOAD_FIRST
        # Verify API was called with correct pattern integer
        mock_api.set_energy_pattern.assert_called_once_with("TEST123", 1)
        # Verify state was written
        entity.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_select_option_api_rejection_reverts(
        self, mock_coordinator, mock_api, mock_hass
    ):
        """On API rejection, entity should revert to previous value and notify."""
        mock_api.set_energy_pattern = AsyncMock(
            side_effect=DeyeApiError("Rejected by inverter", error_code="4001")
        )
        entity = DeyeEnergyPatternSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_patterns=[EnergyPattern.BATTERY_FIRST, EnergyPattern.LOAD_FIRST],
        )
        entity.hass = mock_hass
        entity.async_write_ha_state = MagicMock()

        # Initial state is BATTERY_FIRST
        await entity.async_select_option("Load First")

        # Should revert to BATTERY_FIRST
        assert mock_coordinator.data.energy_pattern == EnergyPattern.BATTERY_FIRST
        # Should create a persistent notification
        mock_hass.components.persistent_notification.async_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_unknown_option_does_nothing(
        self, mock_coordinator, mock_api, mock_hass
    ):
        """Selecting an unknown option should not call the API."""
        entity = DeyeEnergyPatternSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_patterns=[EnergyPattern.BATTERY_FIRST],
        )
        entity.hass = mock_hass
        entity.async_write_ha_state = MagicMock()

        await entity.async_select_option("Nonexistent Pattern")

        mock_api.set_energy_pattern.assert_not_called()

    def test_unique_id_includes_device_sn(self, mock_coordinator, mock_api):
        """Unique ID should incorporate the device serial number."""
        entity = DeyeEnergyPatternSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_patterns=[EnergyPattern.BATTERY_FIRST],
        )
        assert "TEST123" in entity._attr_unique_id
        assert "energy_pattern" in entity._attr_unique_id


# ─── Platform Setup Tests ─────────────────────────────────────────────────────


class TestAsyncSetupEntry:
    """Tests for the select platform async_setup_entry."""

    @pytest.mark.asyncio
    async def test_creates_entities_for_supported_modes(self, mock_device):
        """Should create work mode and energy pattern entities when device supports them."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = DeviceData(
            pv_power_total_w=0, pv_daily_yield_kwh=0, pv_total_yield_kwh=0
        )
        mock_coordinator.device_sn = "TEST123"

        mock_api = MagicMock()
        hass = MagicMock()
        hass.data = {
            "deye_cloud": {
                "entry_1": {
                    "device_coordinators": {"TEST123": mock_coordinator},
                    "devices_metadata": {"TEST123": mock_device},
                    "api": mock_api,
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "entry_1"

        entities_added = []

        def capture_entities(entities):
            entities_added.extend(entities)

        await async_setup_entry(hass, entry, capture_entities)

        # Should have 2 entities: work mode + energy pattern
        assert len(entities_added) == 2
        # Verify types
        work_mode_entities = [
            e for e in entities_added if isinstance(e, DeyeWorkModeSelect)
        ]
        energy_pattern_entities = [
            e for e in entities_added if isinstance(e, DeyeEnergyPatternSelect)
        ]
        assert len(work_mode_entities) == 1
        assert len(energy_pattern_entities) == 1

    @pytest.mark.asyncio
    async def test_no_entities_when_no_supported_modes(self):
        """Should not create entities when device reports no supported modes/patterns."""
        mock_device = Device(
            device_sn="TEST456",
            station_id="station_1",
            model_name="SUN-5K",
            firmware_version="1.0.0",
            rated_power_w=5000,
            phase_count=1,
            mppt_count=2,
            has_battery=True,
            has_smart_load=False,
            smart_load_channels=0,
            supported_work_modes=[],
            supported_energy_patterns=[],
        )

        mock_coordinator = MagicMock()
        mock_coordinator.data = DeviceData(
            pv_power_total_w=0, pv_daily_yield_kwh=0, pv_total_yield_kwh=0
        )
        mock_coordinator.device_sn = "TEST456"

        mock_api = MagicMock()
        hass = MagicMock()
        hass.data = {
            "deye_cloud": {
                "entry_1": {
                    "device_coordinators": {"TEST456": mock_coordinator},
                    "devices_metadata": {"TEST456": mock_device},
                    "api": mock_api,
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "entry_1"

        entities_added = []

        def capture_entities(entities):
            entities_added.extend(entities)

        await async_setup_entry(hass, entry, capture_entities)

        # Should have 0 entities
        assert len(entities_added) == 0

    @pytest.mark.asyncio
    async def test_no_entities_when_no_device_metadata(self):
        """Should not create entities when device metadata is not available."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = DeviceData(
            pv_power_total_w=0, pv_daily_yield_kwh=0, pv_total_yield_kwh=0
        )
        mock_coordinator.device_sn = "TEST789"

        mock_api = MagicMock()
        hass = MagicMock()
        hass.data = {
            "deye_cloud": {
                "entry_1": {
                    "device_coordinators": {"TEST789": mock_coordinator},
                    "devices_metadata": {},
                    "api": mock_api,
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "entry_1"

        entities_added = []

        def capture_entities(entities):
            entities_added.extend(entities)

        await async_setup_entry(hass, entry, capture_entities)

        # No metadata -> no supported modes known -> no entities
        assert len(entities_added) == 0


# ─── State Sync Tests ─────────────────────────────────────────────────────────


class TestStateSync:
    """Tests verifying state synchronization from coordinator poll."""

    def test_work_mode_syncs_from_poll(self, mock_coordinator, mock_api):
        """Work mode entity should reflect updated coordinator data."""
        entity = DeyeWorkModeSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_modes=[WorkMode.SELF_CONSUMPTION, WorkMode.TIME_OF_USE],
        )

        # Initial state
        assert entity.current_option == "Self Consumption"

        # Simulate coordinator poll updating the data
        mock_coordinator.data.work_mode = WorkMode.TIME_OF_USE
        assert entity.current_option == "Time of Use"

    def test_energy_pattern_syncs_from_poll(self, mock_coordinator, mock_api):
        """Energy pattern entity should reflect updated coordinator data."""
        entity = DeyeEnergyPatternSelect(
            coordinator=mock_coordinator,
            api=mock_api,
            device_sn="TEST123",
            supported_patterns=[EnergyPattern.BATTERY_FIRST, EnergyPattern.LOAD_FIRST],
        )

        # Initial state
        assert entity.current_option == "Battery First"

        # Simulate coordinator poll updating the data
        mock_coordinator.data.energy_pattern = EnergyPattern.LOAD_FIRST
        assert entity.current_option == "Load First"
