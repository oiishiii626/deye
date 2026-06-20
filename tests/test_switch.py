"""Tests for the Deye Cloud switch platform."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from custom_components.deye_cloud.models import Device, DeviceData
from custom_components.deye_cloud.switch import (
    DeyePeakShavingSwitch,
    DeyeSmartLoadSwitch,
    DeyeSolarSellSwitch,
    DeyeTariffAutomationSwitch,
    DeyeTOUEnabledSwitch,
    async_setup_entry,
)
from custom_components.deye_cloud.models import TOUSchedule, TOUSlotData, TOUSlotMode
from custom_components.deye_cloud.helpers import generate_unique_id


def _make_device_data(**overrides) -> DeviceData:
    """Create a DeviceData instance with sensible defaults."""
    defaults = {
        "pv_power_total_w": 3000.0,
        "pv_daily_yield_kwh": 12.5,
        "pv_total_yield_kwh": 5000.0,
        "solar_sell_enabled": False,
        "peak_shaving_enabled": False,
        "tou_enabled": False,
        "tou_slots": [
            TOUSlotData(
                slot_index=0,
                start_time="08:00",
                end_time="12:00",
                mode=TOUSlotMode.CHARGING,
                power_limit_w=3000,
            ),
        ],
    }
    defaults.update(overrides)
    return DeviceData(**defaults)


def _make_coordinator(device_sn: str = "INV001", data: DeviceData | None = None):
    """Create a mock coordinator with the given data."""
    coordinator = MagicMock()
    coordinator.device_sn = device_sn
    coordinator.data = data if data is not None else _make_device_data()
    return coordinator


def _make_api():
    """Create a mock API client."""
    api = MagicMock()
    api.set_device_config = AsyncMock(return_value=True)
    return api


def _make_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.components = MagicMock()
    hass.components.persistent_notification = MagicMock()
    hass.components.persistent_notification.async_create = MagicMock()
    return hass


class TestDeyeSolarSellSwitch:
    """Tests for the DeyeSolarSellSwitch entity."""

    def test_unique_id(self):
        """Test that unique_id uses the device_sn and solar_sell key."""
        coordinator = _make_coordinator("SN12345")
        api = _make_api()
        switch = DeyeSolarSellSwitch(coordinator, api, "SN12345")
        assert switch._attr_unique_id == generate_unique_id("SN12345", "solar_sell")

    def test_name(self):
        """Test that the switch has the correct name."""
        coordinator = _make_coordinator()
        api = _make_api()
        switch = DeyeSolarSellSwitch(coordinator, api, "INV001")
        assert switch._attr_name == "Solar Sell"

    def test_is_on_true(self):
        """Test is_on returns True when solar_sell_enabled is True."""
        data = _make_device_data(solar_sell_enabled=True)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyeSolarSellSwitch(coordinator, api, "INV001")
        assert switch.is_on is True

    def test_is_on_false(self):
        """Test is_on returns False when solar_sell_enabled is False."""
        data = _make_device_data(solar_sell_enabled=False)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyeSolarSellSwitch(coordinator, api, "INV001")
        assert switch.is_on is False

    def test_is_on_none_when_no_data(self):
        """Test is_on returns None when coordinator data is None."""
        coordinator = _make_coordinator()
        coordinator.data = None
        api = _make_api()
        switch = DeyeSolarSellSwitch(coordinator, api, "INV001")
        assert switch.is_on is None

    @pytest.mark.asyncio
    async def test_turn_on_success(self):
        """Test turning on solar sell sends correct API command."""
        data = _make_device_data(solar_sell_enabled=False)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyeSolarSellSwitch(coordinator, api, "INV001")
        switch.hass = _make_hass()
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_on()

        api.set_device_config.assert_awaited_once_with(
            "INV001", {"solarSellEnabled": True}
        )
        # Optimistic update applied
        assert coordinator.data.solar_sell_enabled is True

    @pytest.mark.asyncio
    async def test_turn_off_success(self):
        """Test turning off solar sell sends correct API command."""
        data = _make_device_data(solar_sell_enabled=True)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyeSolarSellSwitch(coordinator, api, "INV001")
        switch.hass = _make_hass()
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_off()

        api.set_device_config.assert_awaited_once_with(
            "INV001", {"solarSellEnabled": False}
        )
        assert coordinator.data.solar_sell_enabled is False

    @pytest.mark.asyncio
    async def test_turn_on_api_rejection_reverts(self):
        """Test that on API rejection, state is reverted and notification is raised."""
        data = _make_device_data(solar_sell_enabled=False)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_device_config = AsyncMock(side_effect=Exception("API rejected"))
        switch = DeyeSolarSellSwitch(coordinator, api, "INV001")
        hass = _make_hass()
        switch.hass = hass
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_on()

        # State should be reverted to False (original)
        assert coordinator.data.solar_sell_enabled is False
        # Persistent notification should be created
        hass.components.persistent_notification.async_create.assert_called_once()
        call_kwargs = hass.components.persistent_notification.async_create.call_args
        assert "Solar Sell" in call_kwargs.kwargs.get("title", call_kwargs[1].get("title", ""))

    @pytest.mark.asyncio
    async def test_turn_off_api_rejection_reverts(self):
        """Test that on API rejection while turning off, state reverts to True."""
        data = _make_device_data(solar_sell_enabled=True)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_device_config = AsyncMock(side_effect=Exception("API rejected"))
        switch = DeyeSolarSellSwitch(coordinator, api, "INV001")
        hass = _make_hass()
        switch.hass = hass
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_off()

        # State should be reverted to True (original)
        assert coordinator.data.solar_sell_enabled is True


class TestDeyePeakShavingSwitch:
    """Tests for the DeyePeakShavingSwitch entity."""

    def test_unique_id(self):
        """Test that unique_id uses the device_sn and peak_shaving key."""
        coordinator = _make_coordinator("SN99999")
        api = _make_api()
        switch = DeyePeakShavingSwitch(coordinator, api, "SN99999")
        assert switch._attr_unique_id == generate_unique_id("SN99999", "peak_shaving")

    def test_name(self):
        """Test that the switch has the correct name."""
        coordinator = _make_coordinator()
        api = _make_api()
        switch = DeyePeakShavingSwitch(coordinator, api, "INV001")
        assert switch._attr_name == "Peak Shaving"

    def test_is_on_true(self):
        """Test is_on returns True when peak_shaving_enabled is True."""
        data = _make_device_data(peak_shaving_enabled=True)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyePeakShavingSwitch(coordinator, api, "INV001")
        assert switch.is_on is True

    def test_is_on_false(self):
        """Test is_on returns False when peak_shaving_enabled is False."""
        data = _make_device_data(peak_shaving_enabled=False)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyePeakShavingSwitch(coordinator, api, "INV001")
        assert switch.is_on is False

    def test_is_on_none_when_no_data(self):
        """Test is_on returns None when coordinator data is None."""
        coordinator = _make_coordinator()
        coordinator.data = None
        api = _make_api()
        switch = DeyePeakShavingSwitch(coordinator, api, "INV001")
        assert switch.is_on is None

    @pytest.mark.asyncio
    async def test_turn_on_success(self):
        """Test turning on peak shaving sends correct API command."""
        data = _make_device_data(peak_shaving_enabled=False)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyePeakShavingSwitch(coordinator, api, "INV001")
        switch.hass = _make_hass()
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_on()

        api.set_device_config.assert_awaited_once_with(
            "INV001", {"peakShavingEnabled": True}
        )
        assert coordinator.data.peak_shaving_enabled is True

    @pytest.mark.asyncio
    async def test_turn_off_success(self):
        """Test turning off peak shaving sends correct API command."""
        data = _make_device_data(peak_shaving_enabled=True)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyePeakShavingSwitch(coordinator, api, "INV001")
        switch.hass = _make_hass()
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_off()

        api.set_device_config.assert_awaited_once_with(
            "INV001", {"peakShavingEnabled": False}
        )
        assert coordinator.data.peak_shaving_enabled is False

    @pytest.mark.asyncio
    async def test_turn_on_api_rejection_reverts(self):
        """Test that on API rejection, state is reverted and notification is raised."""
        data = _make_device_data(peak_shaving_enabled=False)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_device_config = AsyncMock(side_effect=Exception("API error"))
        switch = DeyePeakShavingSwitch(coordinator, api, "INV001")
        hass = _make_hass()
        switch.hass = hass
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_on()

        # State should be reverted to False (original)
        assert coordinator.data.peak_shaving_enabled is False
        # Persistent notification should be created
        hass.components.persistent_notification.async_create.assert_called_once()
        call_kwargs = hass.components.persistent_notification.async_create.call_args
        assert "Peak Shaving" in call_kwargs.kwargs.get("title", call_kwargs[1].get("title", ""))

    @pytest.mark.asyncio
    async def test_turn_off_api_rejection_reverts(self):
        """Test that on API rejection while turning off, state reverts to True."""
        data = _make_device_data(peak_shaving_enabled=True)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_device_config = AsyncMock(side_effect=Exception("API error"))
        switch = DeyePeakShavingSwitch(coordinator, api, "INV001")
        hass = _make_hass()
        switch.hass = hass
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_off()

        # State should be reverted to True (original)
        assert coordinator.data.peak_shaving_enabled is True


class TestAsyncSetupEntry:
    """Tests for the async_setup_entry platform function."""

    @pytest.mark.asyncio
    async def test_creates_three_switches_per_inverter(self):
        """Test that setup creates solar sell, peak shaving, TOU, and tariff switches per inverter."""
        hass = _make_hass()
        coordinator = _make_coordinator("INV001")
        api = _make_api()

        hass.data = {
            "deye_cloud": {
                "test_entry_id": {
                    "device_coordinators": {"INV001": coordinator},
                    "api": api,
                    "devices_metadata": {},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry_id"

        entities_added = []

        def mock_add_entities(entities):
            entities_added.extend(entities)

        await async_setup_entry(hass, entry, mock_add_entities)

        assert len(entities_added) == 4
        # Verify types
        assert isinstance(entities_added[0], DeyeSolarSellSwitch)
        assert isinstance(entities_added[1], DeyePeakShavingSwitch)
        assert isinstance(entities_added[2], DeyeTOUEnabledSwitch)
        assert isinstance(entities_added[3], DeyeTariffAutomationSwitch)

    @pytest.mark.asyncio
    async def test_creates_switches_for_multiple_inverters(self):
        """Test that setup creates switches for each inverter in the config."""
        hass = _make_hass()
        coordinator1 = _make_coordinator("INV001")
        coordinator2 = _make_coordinator("INV002")
        api = _make_api()

        hass.data = {
            "deye_cloud": {
                "test_entry_id": {
                    "device_coordinators": {
                        "INV001": coordinator1,
                        "INV002": coordinator2,
                    },
                    "api": api,
                    "devices_metadata": {},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry_id"

        entities_added = []

        def mock_add_entities(entities):
            entities_added.extend(entities)

        await async_setup_entry(hass, entry, mock_add_entities)

        # 4 switches per inverter × 2 inverters = 8
        assert len(entities_added) == 8

    @pytest.mark.asyncio
    async def test_creates_smart_load_switches_when_supported(self):
        """Test that setup creates smart load switches when inverter has smart load capability."""
        hass = _make_hass()
        coordinator = _make_coordinator("INV001")
        api = _make_api()

        device_meta = Device(
            device_sn="INV001",
            station_id="ST001",
            model_name="SUN-5K",
            firmware_version="1.0.0",
            rated_power_w=5000,
            phase_count=1,
            mppt_count=2,
            has_battery=True,
            has_smart_load=True,
            smart_load_channels=2,
        )

        hass.data = {
            "deye_cloud": {
                "test_entry_id": {
                    "device_coordinators": {"INV001": coordinator},
                    "api": api,
                    "devices_metadata": {"INV001": device_meta},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry_id"

        entities_added = []

        def mock_add_entities(entities):
            entities_added.extend(entities)

        await async_setup_entry(hass, entry, mock_add_entities)

        # 4 standard switches + 2 smart load switches = 6
        assert len(entities_added) == 6
        smart_load_switches = [e for e in entities_added if isinstance(e, DeyeSmartLoadSwitch)]
        assert len(smart_load_switches) == 2

    @pytest.mark.asyncio
    async def test_no_smart_load_switches_when_not_supported(self):
        """Test that no smart load switches are created when inverter lacks capability."""
        hass = _make_hass()
        coordinator = _make_coordinator("INV001")
        api = _make_api()

        device_meta = Device(
            device_sn="INV001",
            station_id="ST001",
            model_name="SUN-5K",
            firmware_version="1.0.0",
            rated_power_w=5000,
            phase_count=1,
            mppt_count=2,
            has_battery=True,
            has_smart_load=False,
            smart_load_channels=0,
        )

        hass.data = {
            "deye_cloud": {
                "test_entry_id": {
                    "device_coordinators": {"INV001": coordinator},
                    "api": api,
                    "devices_metadata": {"INV001": device_meta},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry_id"

        entities_added = []

        def mock_add_entities(entities):
            entities_added.extend(entities)

        await async_setup_entry(hass, entry, mock_add_entities)

        # Only the 4 standard switches
        assert len(entities_added) == 4
        smart_load_switches = [e for e in entities_added if isinstance(e, DeyeSmartLoadSwitch)]
        assert len(smart_load_switches) == 0

    @pytest.mark.asyncio
    async def test_no_smart_load_switches_when_no_metadata(self):
        """Test that no smart load switches are created when device metadata is missing."""
        hass = _make_hass()
        coordinator = _make_coordinator("INV001")
        api = _make_api()

        hass.data = {
            "deye_cloud": {
                "test_entry_id": {
                    "device_coordinators": {"INV001": coordinator},
                    "api": api,
                    "devices_metadata": {},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry_id"

        entities_added = []

        def mock_add_entities(entities):
            entities_added.extend(entities)

        await async_setup_entry(hass, entry, mock_add_entities)

        # Only the 4 standard switches
        assert len(entities_added) == 4


class TestDeyeTOUEnabledSwitch:
    """Tests for the DeyeTOUEnabledSwitch entity."""

    def test_unique_id(self):
        """Test that unique_id uses the device_sn and tou_enabled key."""
        coordinator = _make_coordinator("SN12345")
        api = _make_api()
        switch = DeyeTOUEnabledSwitch(coordinator, api, "SN12345")
        assert switch._attr_unique_id == "SN12345_tou_enabled"

    def test_name(self):
        """Test that the switch has the correct name."""
        coordinator = _make_coordinator()
        api = _make_api()
        switch = DeyeTOUEnabledSwitch(coordinator, api, "INV001")
        assert switch._attr_name == "TOU Schedule"

    def test_is_on_true(self):
        """Test is_on returns True when tou_enabled is True."""
        data = _make_device_data(tou_enabled=True)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyeTOUEnabledSwitch(coordinator, api, "INV001")
        assert switch.is_on is True

    def test_is_on_false(self):
        """Test is_on returns False when tou_enabled is False."""
        data = _make_device_data(tou_enabled=False)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyeTOUEnabledSwitch(coordinator, api, "INV001")
        assert switch.is_on is False

    def test_is_on_none_when_no_data(self):
        """Test is_on returns None when coordinator data is None."""
        coordinator = _make_coordinator()
        coordinator.data = None
        api = _make_api()
        switch = DeyeTOUEnabledSwitch(coordinator, api, "INV001")
        assert switch.is_on is None

    def test_is_on_uses_optimistic_state_when_set(self):
        """Test that optimistic state takes precedence over coordinator data."""
        data = _make_device_data(tou_enabled=True)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyeTOUEnabledSwitch(coordinator, api, "INV001")
        switch._optimistic_state = False
        assert switch.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on_calls_api(self):
        """Test turning on TOU sends correct API command with enabled=True."""
        data = _make_device_data(tou_enabled=False)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_tou_schedule = AsyncMock(return_value=True)
        switch = DeyeTOUEnabledSwitch(coordinator, api, "INV001")
        switch.hass = _make_hass()
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_on()

        api.set_tou_schedule.assert_awaited_once()
        call_args = api.set_tou_schedule.call_args
        assert call_args[0][0] == "INV001"
        schedule = call_args[0][1]
        assert isinstance(schedule, TOUSchedule)
        assert schedule.enabled is True

    @pytest.mark.asyncio
    async def test_turn_off_calls_api(self):
        """Test turning off TOU sends correct API command with enabled=False."""
        data = _make_device_data(tou_enabled=True)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_tou_schedule = AsyncMock(return_value=True)
        switch = DeyeTOUEnabledSwitch(coordinator, api, "INV001")
        switch.hass = _make_hass()
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_off()

        api.set_tou_schedule.assert_awaited_once()
        call_args = api.set_tou_schedule.call_args
        assert call_args[0][0] == "INV001"
        schedule = call_args[0][1]
        assert isinstance(schedule, TOUSchedule)
        assert schedule.enabled is False

    @pytest.mark.asyncio
    async def test_turn_on_preserves_existing_slots(self):
        """Test that toggling TOU on preserves the existing slot configuration."""
        slots = [
            TOUSlotData(
                slot_index=0,
                start_time="08:00",
                end_time="12:00",
                mode=TOUSlotMode.CHARGING,
                power_limit_w=3000,
            ),
            TOUSlotData(
                slot_index=1,
                start_time="18:00",
                end_time="22:00",
                mode=TOUSlotMode.DISCHARGING,
                power_limit_w=5000,
            ),
        ]
        data = _make_device_data(tou_enabled=False, tou_slots=slots)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_tou_schedule = AsyncMock(return_value=True)
        switch = DeyeTOUEnabledSwitch(coordinator, api, "INV001")
        switch.hass = _make_hass()
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_on()

        call_args = api.set_tou_schedule.call_args
        schedule = call_args[0][1]
        assert schedule.slots == slots

    @pytest.mark.asyncio
    async def test_optimistic_update_on_turn_on(self):
        """Test that optimistic state is set immediately on turn_on."""
        data = _make_device_data(tou_enabled=False)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_tou_schedule = AsyncMock(return_value=True)
        switch = DeyeTOUEnabledSwitch(coordinator, api, "INV001")
        states_written = []

        def track_state():
            states_written.append(switch.is_on)

        switch.hass = _make_hass()
        switch.async_write_ha_state = track_state

        await switch.async_turn_on()

        # First write is the optimistic update (True)
        assert states_written[0] is True

    @pytest.mark.asyncio
    async def test_revert_on_api_failure(self):
        """Test that state reverts when API call fails."""
        data = _make_device_data(tou_enabled=True)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_tou_schedule = AsyncMock(side_effect=Exception("API error"))
        switch = DeyeTOUEnabledSwitch(coordinator, api, "INV001")
        hass = _make_hass()
        switch.hass = hass
        states_written = []

        def track_state():
            states_written.append(switch.is_on)

        switch.async_write_ha_state = track_state

        await switch.async_turn_off()

        # First write: optimistic False, second write: reverted to True
        assert states_written[0] is False
        assert states_written[1] is True

    @pytest.mark.asyncio
    async def test_revert_on_api_failure_sends_notification(self):
        """Test that persistent notification is raised on API failure."""
        data = _make_device_data(tou_enabled=True)
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_tou_schedule = AsyncMock(side_effect=Exception("API error"))
        switch = DeyeTOUEnabledSwitch(coordinator, api, "INV001")
        hass = _make_hass()
        switch.hass = hass
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_off()

        hass.components.persistent_notification.async_create.assert_called_once()
        call_kwargs = hass.components.persistent_notification.async_create.call_args
        assert "TOU Schedule" in call_kwargs.kwargs.get("title", call_kwargs[1].get("title", ""))

    def test_handle_coordinator_update_clears_optimistic_state(self):
        """Test that coordinator update clears optimistic state."""
        coordinator = _make_coordinator()
        api = _make_api()
        switch = DeyeTOUEnabledSwitch(coordinator, api, "INV001")
        switch._optimistic_state = True

        switch._handle_coordinator_update()

        assert switch._optimistic_state is None

    def test_device_info(self):
        """Test that device_info links to the correct device."""
        coordinator = _make_coordinator("SN99999")
        api = _make_api()
        switch = DeyeTOUEnabledSwitch(coordinator, api, "SN99999")
        info = switch._attr_device_info
        assert info["identifiers"] == {("deye_cloud", "SN99999")}


class TestDeyeSmartLoadSwitch:
    """Tests for the DeyeSmartLoadSwitch entity."""

    def test_unique_id(self):
        """Test that unique_id uses device_sn and smart_load channel index."""
        coordinator = _make_coordinator("SN12345")
        api = _make_api()
        switch = DeyeSmartLoadSwitch(coordinator, api, "SN12345", channel=0)
        assert switch._attr_unique_id == "SN12345_smart_load_0"

    def test_unique_id_channel_1(self):
        """Test unique_id for second channel."""
        coordinator = _make_coordinator("SN12345")
        api = _make_api()
        switch = DeyeSmartLoadSwitch(coordinator, api, "SN12345", channel=1)
        assert switch._attr_unique_id == "SN12345_smart_load_1"

    def test_name_channel_0(self):
        """Test that channel 0 displays as Smart Load 1 (1-indexed for user)."""
        coordinator = _make_coordinator()
        api = _make_api()
        switch = DeyeSmartLoadSwitch(coordinator, api, "INV001", channel=0)
        assert switch._attr_name == "Smart Load 1"

    def test_name_channel_1(self):
        """Test that channel 1 displays as Smart Load 2 (1-indexed for user)."""
        coordinator = _make_coordinator()
        api = _make_api()
        switch = DeyeSmartLoadSwitch(coordinator, api, "INV001", channel=1)
        assert switch._attr_name == "Smart Load 2"

    def test_is_on_true(self):
        """Test is_on returns True when the channel state is True."""
        data = _make_device_data(smart_load_states=[True, False])
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyeSmartLoadSwitch(coordinator, api, "INV001", channel=0)
        assert switch.is_on is True

    def test_is_on_false(self):
        """Test is_on returns False when the channel state is False."""
        data = _make_device_data(smart_load_states=[True, False])
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyeSmartLoadSwitch(coordinator, api, "INV001", channel=1)
        assert switch.is_on is False

    def test_is_on_none_when_no_data(self):
        """Test is_on returns None when coordinator data is None."""
        coordinator = _make_coordinator()
        coordinator.data = None
        api = _make_api()
        switch = DeyeSmartLoadSwitch(coordinator, api, "INV001", channel=0)
        assert switch.is_on is None

    def test_is_on_none_when_channel_out_of_range(self):
        """Test is_on returns None when channel index exceeds state list."""
        data = _make_device_data(smart_load_states=[True])
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        switch = DeyeSmartLoadSwitch(coordinator, api, "INV001", channel=5)
        assert switch.is_on is None

    @pytest.mark.asyncio
    async def test_turn_on_success(self):
        """Test turning on smart load sends correct API command."""
        data = _make_device_data(smart_load_states=[False, True])
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_smart_load = AsyncMock(return_value=True)
        switch = DeyeSmartLoadSwitch(coordinator, api, "INV001", channel=0)
        switch.hass = _make_hass()
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_on()

        api.set_smart_load.assert_awaited_once_with("INV001", 0, True)
        # Optimistic update applied
        assert coordinator.data.smart_load_states[0] is True

    @pytest.mark.asyncio
    async def test_turn_off_success(self):
        """Test turning off smart load sends correct API command."""
        data = _make_device_data(smart_load_states=[True, True])
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_smart_load = AsyncMock(return_value=True)
        switch = DeyeSmartLoadSwitch(coordinator, api, "INV001", channel=1)
        switch.hass = _make_hass()
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_off()

        api.set_smart_load.assert_awaited_once_with("INV001", 1, False)
        assert coordinator.data.smart_load_states[1] is False

    @pytest.mark.asyncio
    async def test_turn_on_api_rejection_reverts(self):
        """Test that on API rejection, state is reverted and notification raised."""
        data = _make_device_data(smart_load_states=[False, True])
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_smart_load = AsyncMock(side_effect=Exception("API rejected"))
        switch = DeyeSmartLoadSwitch(coordinator, api, "INV001", channel=0)
        hass = _make_hass()
        switch.hass = hass
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_on()

        # State should be reverted to False (original)
        assert coordinator.data.smart_load_states[0] is False
        # Persistent notification should be created
        hass.components.persistent_notification.async_create.assert_called_once()
        call_kwargs = hass.components.persistent_notification.async_create.call_args
        assert "Smart Load" in call_kwargs.kwargs.get("title", call_kwargs[1].get("title", ""))

    @pytest.mark.asyncio
    async def test_turn_off_api_rejection_reverts(self):
        """Test that on API rejection while turning off, state reverts to True."""
        data = _make_device_data(smart_load_states=[True, False])
        coordinator = _make_coordinator(data=data)
        api = _make_api()
        api.set_smart_load = AsyncMock(side_effect=Exception("API rejected"))
        switch = DeyeSmartLoadSwitch(coordinator, api, "INV001", channel=0)
        hass = _make_hass()
        switch.hass = hass
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_off()

        # State should be reverted to True (original)
        assert coordinator.data.smart_load_states[0] is True

    def test_device_info(self):
        """Test that device_info links to the correct device."""
        coordinator = _make_coordinator("SN99999")
        api = _make_api()
        switch = DeyeSmartLoadSwitch(coordinator, api, "SN99999", channel=0)
        info = switch._attr_device_info
        assert info["identifiers"] == {("deye_cloud", "SN99999")}



class TestDeyeTariffAutomationSwitch:
    """Tests for the DeyeTariffAutomationSwitch entity."""

    def _make_switch(self, device_sn: str = "INV001", entry_id: str = "test_entry_id"):
        """Create a tariff automation switch with mocked dependencies."""
        coordinator = _make_coordinator(device_sn)
        hass = _make_hass()
        hass.data = {
            "deye_cloud": {
                entry_id: {
                    "device_coordinators": {device_sn: coordinator},
                }
            }
        }
        from custom_components.deye_cloud.switch import DeyeTariffAutomationSwitch

        switch = DeyeTariffAutomationSwitch(
            coordinator=coordinator,
            device_sn=device_sn,
            hass_obj=hass,
            entry_id=entry_id,
        )
        switch.hass = hass
        switch.async_write_ha_state = MagicMock()
        return switch, hass

    def test_unique_id(self):
        """Test that unique_id uses the device_sn and tariff_automation key."""
        switch, _ = self._make_switch("SN12345")
        assert switch._attr_unique_id == "SN12345_tariff_automation"

    def test_name(self):
        """Test that the switch has the correct name."""
        switch, _ = self._make_switch()
        assert switch._attr_name == "Tariff Automation"

    def test_icon(self):
        """Test that the switch has the correct icon."""
        switch, _ = self._make_switch()
        assert switch._attr_icon == "mdi:currency-usd"

    def test_default_state_is_off(self):
        """Test that the default state is off (disabled)."""
        switch, _ = self._make_switch()
        assert switch.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on(self):
        """Test turning on enables tariff automation."""
        switch, hass = self._make_switch()
        assert switch.is_on is False

        await switch.async_turn_on()

        assert switch.is_on is True
        switch.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_off(self):
        """Test turning off disables tariff automation."""
        switch, hass = self._make_switch()
        switch._is_on = True
        assert switch.is_on is True

        await switch.async_turn_off()

        assert switch.is_on is False
        switch.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_on_stores_state_in_hass_data(self):
        """Test that turn_on stores the enabled state in hass.data for TariffManager."""
        switch, hass = self._make_switch("INV001", "test_entry_id")

        await switch.async_turn_on()

        entry_data = hass.data["deye_cloud"]["test_entry_id"]
        assert "tariff_enabled" in entry_data
        assert entry_data["tariff_enabled"]["INV001"] is True

    @pytest.mark.asyncio
    async def test_turn_off_stores_state_in_hass_data(self):
        """Test that turn_off stores the disabled state in hass.data for TariffManager."""
        switch, hass = self._make_switch("INV001", "test_entry_id")
        switch._is_on = True

        await switch.async_turn_off()

        entry_data = hass.data["deye_cloud"]["test_entry_id"]
        assert "tariff_enabled" in entry_data
        assert entry_data["tariff_enabled"]["INV001"] is False

    def test_device_info(self):
        """Test that device_info links to the correct device."""
        switch, _ = self._make_switch("SN99999")
        info = switch._attr_device_info
        assert info["identifiers"] == {("deye_cloud", "SN99999")}

    @pytest.mark.asyncio
    async def test_does_not_call_api(self):
        """Test that toggling the switch does NOT call the Deye Cloud API."""
        coordinator = _make_coordinator("INV001")
        api = _make_api()
        hass = _make_hass()
        hass.data = {
            "deye_cloud": {
                "test_entry_id": {
                    "device_coordinators": {"INV001": coordinator},
                }
            }
        }
        from custom_components.deye_cloud.switch import DeyeTariffAutomationSwitch

        switch = DeyeTariffAutomationSwitch(
            coordinator=coordinator,
            device_sn="INV001",
            hass_obj=hass,
            entry_id="test_entry_id",
        )
        switch.hass = hass
        switch.async_write_ha_state = MagicMock()

        await switch.async_turn_on()
        await switch.async_turn_off()

        # No API calls should have been made
        api.set_device_config.assert_not_awaited()
        api.set_work_mode.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_inverters_independent_state(self):
        """Test that each inverter has independent tariff automation state."""
        coordinator1 = _make_coordinator("INV001")
        coordinator2 = _make_coordinator("INV002")
        hass = _make_hass()
        hass.data = {
            "deye_cloud": {
                "test_entry_id": {
                    "device_coordinators": {
                        "INV001": coordinator1,
                        "INV002": coordinator2,
                    },
                }
            }
        }
        from custom_components.deye_cloud.switch import DeyeTariffAutomationSwitch

        switch1 = DeyeTariffAutomationSwitch(
            coordinator=coordinator1,
            device_sn="INV001",
            hass_obj=hass,
            entry_id="test_entry_id",
        )
        switch1.hass = hass
        switch1.async_write_ha_state = MagicMock()

        switch2 = DeyeTariffAutomationSwitch(
            coordinator=coordinator2,
            device_sn="INV002",
            hass_obj=hass,
            entry_id="test_entry_id",
        )
        switch2.hass = hass
        switch2.async_write_ha_state = MagicMock()

        # Enable only the first inverter's tariff automation
        await switch1.async_turn_on()

        assert switch1.is_on is True
        assert switch2.is_on is False

        entry_data = hass.data["deye_cloud"]["test_entry_id"]
        assert entry_data["tariff_enabled"]["INV001"] is True
        assert "INV002" not in entry_data["tariff_enabled"]
