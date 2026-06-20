"""Tests for the Deye Cloud TOU time slot entities (time.py)."""

from __future__ import annotations

import asyncio
from datetime import time as dt_time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.deye_cloud.models import (
    DeviceData,
    TOUSchedule,
    TOUSlotData,
    TOUSlotMode,
)
from custom_components.deye_cloud.time import (
    NUM_TOU_SLOTS,
    DeyeTOUEndTimeEntity,
    DeyeTOUModeSelectEntity,
    DeyeTOUPowerLimitEntity,
    DeyeTOUStartTimeEntity,
    _build_current_slots,
    _get_slot_data,
    _validate_schedule,
    async_setup_entry,
)


# --- Fixtures ---


def _make_coordinator(
    device_sn: str = "TEST123",
    rated_power_w: int = 5000,
    tou_slots: list[TOUSlotData] | None = None,
    tou_enabled: bool = True,
) -> MagicMock:
    """Create a mock coordinator with TOU slot data."""
    coordinator = MagicMock()
    coordinator.device_sn = device_sn
    coordinator.rated_power_w = rated_power_w
    coordinator.last_update_success = True
    coordinator.async_request_refresh = AsyncMock()

    api = AsyncMock()
    api.set_tou_schedule = AsyncMock(return_value=True)
    coordinator.api = api

    if tou_slots is None:
        tou_slots = [
            TOUSlotData(
                slot_index=1,
                start_time="06:00",
                end_time="09:00",
                mode=TOUSlotMode.CHARGING,
                power_limit_w=3000,
            ),
            TOUSlotData(
                slot_index=2,
                start_time="17:00",
                end_time="21:00",
                mode=TOUSlotMode.DISCHARGING,
                power_limit_w=4000,
            ),
            TOUSlotData(
                slot_index=3,
                start_time="00:00",
                end_time="00:00",
                mode=TOUSlotMode.DISABLED,
                power_limit_w=0,
            ),
        ]

    data = MagicMock(spec=DeviceData)
    data.tou_slots = tou_slots
    data.tou_enabled = tou_enabled
    coordinator.data = data

    return coordinator


# --- Tests for _validate_schedule ---


class TestValidateSchedule:
    """Tests for the _validate_schedule helper."""

    def test_valid_non_overlapping_slots(self):
        """Valid schedule with non-overlapping enabled slots passes."""
        slots = [
            TOUSlotData(1, "06:00", "09:00", TOUSlotMode.CHARGING, 3000),
            TOUSlotData(2, "17:00", "21:00", TOUSlotMode.DISCHARGING, 4000),
            TOUSlotData(3, "09:00", "12:00", TOUSlotMode.CHARGING, 2000),
        ]
        assert _validate_schedule(slots) is None

    def test_disabled_slots_ignored(self):
        """Disabled slots are ignored during validation."""
        slots = [
            TOUSlotData(1, "06:00", "09:00", TOUSlotMode.CHARGING, 3000),
            TOUSlotData(2, "07:00", "10:00", TOUSlotMode.DISABLED, 0),
        ]
        assert _validate_schedule(slots) is None

    def test_overlapping_enabled_slots(self):
        """Overlapping enabled slots are rejected."""
        slots = [
            TOUSlotData(1, "06:00", "09:00", TOUSlotMode.CHARGING, 3000),
            TOUSlotData(2, "08:00", "12:00", TOUSlotMode.DISCHARGING, 4000),
        ]
        error = _validate_schedule(slots)
        assert error is not None
        assert "overlap" in error.lower()

    def test_end_before_start_rejected(self):
        """Slot with end <= start is rejected."""
        slots = [
            TOUSlotData(1, "09:00", "06:00", TOUSlotMode.CHARGING, 3000),
        ]
        error = _validate_schedule(slots)
        assert error is not None
        assert "after start" in error.lower()

    def test_end_equal_start_rejected(self):
        """Slot with end == start is rejected."""
        slots = [
            TOUSlotData(1, "09:00", "09:00", TOUSlotMode.CHARGING, 3000),
        ]
        error = _validate_schedule(slots)
        assert error is not None

    def test_empty_schedule_valid(self):
        """Empty schedule is valid."""
        assert _validate_schedule([]) is None

    def test_all_disabled_valid(self):
        """Schedule with all disabled slots is valid."""
        slots = [
            TOUSlotData(1, "00:00", "00:00", TOUSlotMode.DISABLED, 0),
            TOUSlotData(2, "00:00", "00:00", TOUSlotMode.DISABLED, 0),
        ]
        assert _validate_schedule(slots) is None


# --- Tests for DeyeTOUStartTimeEntity ---


class TestDeyeTOUStartTimeEntity:
    """Tests for the TOU start time entity."""

    def test_native_value_from_coordinator(self):
        """Start time reads from coordinator slot data."""
        coordinator = _make_coordinator()
        entity = DeyeTOUStartTimeEntity(coordinator, "TEST123", 1)
        assert entity.native_value == dt_time(6, 0)

    def test_native_value_missing_slot(self):
        """Returns 00:00 when slot not in coordinator data."""
        coordinator = _make_coordinator()
        entity = DeyeTOUStartTimeEntity(coordinator, "TEST123", 6)
        assert entity.native_value == dt_time(0, 0)

    def test_native_value_no_data(self):
        """Returns 00:00 when coordinator has no data."""
        coordinator = _make_coordinator()
        coordinator.data = None
        entity = DeyeTOUStartTimeEntity(coordinator, "TEST123", 1)
        assert entity.native_value == dt_time(0, 0)

    def test_unique_id(self):
        """Unique ID includes device SN and slot index."""
        coordinator = _make_coordinator()
        entity = DeyeTOUStartTimeEntity(coordinator, "TEST123", 3)
        assert entity._attr_unique_id == "TEST123_tou_slot_3_start"

    @pytest.mark.asyncio
    async def test_set_value_valid(self):
        """Setting a valid start time sends schedule to API."""
        coordinator = _make_coordinator()
        entity = DeyeTOUStartTimeEntity(coordinator, "TEST123", 1)

        await entity.async_set_value(dt_time(5, 30))

        coordinator.api.set_tou_schedule.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_value_causes_overlap_rejected(self):
        """Setting a start time that causes overlap raises error."""
        coordinator = _make_coordinator(
            tou_slots=[
                TOUSlotData(1, "06:00", "09:00", TOUSlotMode.CHARGING, 3000),
                TOUSlotData(2, "10:00", "14:00", TOUSlotMode.DISCHARGING, 4000),
            ]
        )
        entity = DeyeTOUStartTimeEntity(coordinator, "TEST123", 1)

        # Setting start to 09:30 with end at 09:00 means end < start → error
        # But let's create a true overlap scenario: change slot 1 start to 11:00
        # with end 09:00 → end < start → rejected
        from homeassistant.exceptions import HomeAssistantError as HAError

        with pytest.raises(Exception):
            await entity.async_set_value(dt_time(11, 0))

        coordinator.api.set_tou_schedule.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_value_api_failure_raises(self):
        """API failure raises HomeAssistantError."""
        coordinator = _make_coordinator(
            tou_slots=[
                TOUSlotData(1, "06:00", "09:00", TOUSlotMode.DISABLED, 3000),
            ]
        )
        coordinator.api.set_tou_schedule = AsyncMock(side_effect=Exception("API error"))
        entity = DeyeTOUStartTimeEntity(coordinator, "TEST123", 1)

        with pytest.raises(Exception):
            await entity.async_set_value(dt_time(5, 0))


# --- Tests for DeyeTOUEndTimeEntity ---


class TestDeyeTOUEndTimeEntity:
    """Tests for the TOU end time entity."""

    def test_native_value_from_coordinator(self):
        """End time reads from coordinator slot data."""
        coordinator = _make_coordinator()
        entity = DeyeTOUEndTimeEntity(coordinator, "TEST123", 1)
        assert entity.native_value == dt_time(9, 0)

    def test_native_value_missing_slot(self):
        """Returns 00:00 when slot not in coordinator data."""
        coordinator = _make_coordinator()
        entity = DeyeTOUEndTimeEntity(coordinator, "TEST123", 6)
        assert entity.native_value == dt_time(0, 0)

    def test_unique_id(self):
        """Unique ID includes device SN and slot index."""
        coordinator = _make_coordinator()
        entity = DeyeTOUEndTimeEntity(coordinator, "TEST123", 2)
        assert entity._attr_unique_id == "TEST123_tou_slot_2_end"

    @pytest.mark.asyncio
    async def test_set_value_valid(self):
        """Setting a valid end time sends schedule to API."""
        coordinator = _make_coordinator()
        entity = DeyeTOUEndTimeEntity(coordinator, "TEST123", 1)

        await entity.async_set_value(dt_time(10, 0))

        coordinator.api.set_tou_schedule.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_value_end_before_start_rejected(self):
        """Setting end time before start time raises error."""
        coordinator = _make_coordinator(
            tou_slots=[
                TOUSlotData(1, "09:00", "12:00", TOUSlotMode.CHARGING, 3000),
            ]
        )
        entity = DeyeTOUEndTimeEntity(coordinator, "TEST123", 1)

        with pytest.raises(Exception):
            await entity.async_set_value(dt_time(8, 0))

        coordinator.api.set_tou_schedule.assert_not_called()


# --- Tests for DeyeTOUModeSelectEntity ---


class TestDeyeTOUModeSelectEntity:
    """Tests for the TOU mode select entity."""

    def test_current_option_from_coordinator(self):
        """Mode reads from coordinator slot data."""
        coordinator = _make_coordinator()
        entity = DeyeTOUModeSelectEntity(coordinator, "TEST123", 1)
        assert entity.current_option == "charging"

    def test_current_option_missing_slot(self):
        """Returns 'disabled' when slot not in coordinator data."""
        coordinator = _make_coordinator()
        entity = DeyeTOUModeSelectEntity(coordinator, "TEST123", 6)
        assert entity.current_option == "disabled"

    def test_options_list(self):
        """Options include all three modes."""
        coordinator = _make_coordinator()
        entity = DeyeTOUModeSelectEntity(coordinator, "TEST123", 1)
        assert "charging" in entity._attr_options
        assert "discharging" in entity._attr_options
        assert "disabled" in entity._attr_options

    def test_unique_id(self):
        """Unique ID includes device SN and slot index."""
        coordinator = _make_coordinator()
        entity = DeyeTOUModeSelectEntity(coordinator, "TEST123", 2)
        assert entity._attr_unique_id == "TEST123_tou_slot_2_mode"

    @pytest.mark.asyncio
    async def test_select_option_valid(self):
        """Selecting a valid option sends schedule to API."""
        coordinator = _make_coordinator(
            tou_slots=[
                TOUSlotData(1, "06:00", "09:00", TOUSlotMode.DISABLED, 3000),
            ]
        )
        entity = DeyeTOUModeSelectEntity(coordinator, "TEST123", 1)

        await entity.async_select_option("charging")

        coordinator.api.set_tou_schedule.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_option_invalid_mode(self):
        """Selecting an invalid mode raises error."""
        coordinator = _make_coordinator()
        entity = DeyeTOUModeSelectEntity(coordinator, "TEST123", 1)

        with pytest.raises(Exception):
            await entity.async_select_option("invalid_mode")

    @pytest.mark.asyncio
    async def test_enabling_overlapping_slot_rejected(self):
        """Enabling a slot that would overlap raises error."""
        coordinator = _make_coordinator(
            tou_slots=[
                TOUSlotData(1, "06:00", "09:00", TOUSlotMode.CHARGING, 3000),
                TOUSlotData(2, "08:00", "12:00", TOUSlotMode.DISABLED, 4000),
            ]
        )
        entity = DeyeTOUModeSelectEntity(coordinator, "TEST123", 2)

        with pytest.raises(Exception):
            await entity.async_select_option("discharging")

        coordinator.api.set_tou_schedule.assert_not_called()


# --- Tests for DeyeTOUPowerLimitEntity ---


class TestDeyeTOUPowerLimitEntity:
    """Tests for the TOU power limit number entity."""

    def test_native_value_from_coordinator(self):
        """Power limit reads from coordinator slot data."""
        coordinator = _make_coordinator()
        entity = DeyeTOUPowerLimitEntity(coordinator, "TEST123", 1, 5000)
        assert entity.native_value == 3000.0

    def test_native_value_missing_slot(self):
        """Returns 0.0 when slot not in coordinator data."""
        coordinator = _make_coordinator()
        entity = DeyeTOUPowerLimitEntity(coordinator, "TEST123", 6, 5000)
        assert entity.native_value == 0.0

    def test_max_value_from_rated_power(self):
        """Max value is set to rated power."""
        coordinator = _make_coordinator(rated_power_w=8000)
        entity = DeyeTOUPowerLimitEntity(coordinator, "TEST123", 1, 8000)
        assert entity._attr_native_max_value == 8000.0

    def test_min_value_is_zero(self):
        """Min value is 0."""
        coordinator = _make_coordinator()
        entity = DeyeTOUPowerLimitEntity(coordinator, "TEST123", 1, 5000)
        assert entity._attr_native_min_value == 0.0

    def test_step_is_one(self):
        """Step size is 1W."""
        coordinator = _make_coordinator()
        entity = DeyeTOUPowerLimitEntity(coordinator, "TEST123", 1, 5000)
        assert entity._attr_native_step == 1.0

    def test_unique_id(self):
        """Unique ID includes device SN and slot index."""
        coordinator = _make_coordinator()
        entity = DeyeTOUPowerLimitEntity(coordinator, "TEST123", 3, 5000)
        assert entity._attr_unique_id == "TEST123_tou_slot_3_power_limit"

    @pytest.mark.asyncio
    async def test_set_value_valid(self):
        """Setting a valid power limit sends schedule to API."""
        coordinator = _make_coordinator()
        entity = DeyeTOUPowerLimitEntity(coordinator, "TEST123", 1, 5000)

        await entity.async_set_native_value(4000.0)

        coordinator.api.set_tou_schedule.assert_called_once()
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_value_exceeds_max_rejected(self):
        """Setting value above rated power raises error."""
        coordinator = _make_coordinator()
        entity = DeyeTOUPowerLimitEntity(coordinator, "TEST123", 1, 5000)

        with pytest.raises(Exception):
            await entity.async_set_native_value(6000.0)

        coordinator.api.set_tou_schedule.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_value_negative_rejected(self):
        """Setting negative value raises error."""
        coordinator = _make_coordinator()
        entity = DeyeTOUPowerLimitEntity(coordinator, "TEST123", 1, 5000)

        with pytest.raises(Exception):
            await entity.async_set_native_value(-100.0)

        coordinator.api.set_tou_schedule.assert_not_called()


# --- Tests for async_setup_entry ---


class TestAsyncSetupEntry:
    """Tests for the platform setup entry."""

    @pytest.mark.asyncio
    async def test_creates_entities_for_all_slots(self):
        """Setup creates 4 entities per slot × 6 slots per device."""
        coordinator = _make_coordinator()
        hass = MagicMock()
        hass.data = {
            "deye_cloud": {
                "test_entry": {
                    "device_coordinators": {"TEST123": coordinator},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry"

        added_entities: list = []

        def capture_entities(entities):
            added_entities.extend(entities)

        await async_setup_entry(hass, entry, capture_entities)

        # 4 entities per slot (start, end, mode, power) × 6 slots = 24
        assert len(added_entities) == NUM_TOU_SLOTS * 4

    @pytest.mark.asyncio
    async def test_creates_entities_for_multiple_devices(self):
        """Setup creates entities for each configured device."""
        coordinator1 = _make_coordinator(device_sn="DEV001", rated_power_w=5000)
        coordinator2 = _make_coordinator(device_sn="DEV002", rated_power_w=8000)

        hass = MagicMock()
        hass.data = {
            "deye_cloud": {
                "test_entry": {
                    "device_coordinators": {
                        "DEV001": coordinator1,
                        "DEV002": coordinator2,
                    },
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry"

        added_entities: list = []

        def capture_entities(entities):
            added_entities.extend(entities)

        await async_setup_entry(hass, entry, capture_entities)

        # 4 entities per slot × 6 slots × 2 devices = 48
        assert len(added_entities) == NUM_TOU_SLOTS * 4 * 2


# --- Tests for _get_slot_data ---


class TestGetSlotData:
    """Tests for the _get_slot_data helper."""

    def test_returns_matching_slot(self):
        """Returns the slot with matching index."""
        coordinator = _make_coordinator()
        slot = _get_slot_data(coordinator, 1)
        assert slot is not None
        assert slot.slot_index == 1
        assert slot.start_time == "06:00"

    def test_returns_none_for_missing_slot(self):
        """Returns None when slot index not found."""
        coordinator = _make_coordinator()
        slot = _get_slot_data(coordinator, 99)
        assert slot is None

    def test_returns_none_when_no_data(self):
        """Returns None when coordinator data is None."""
        coordinator = _make_coordinator()
        coordinator.data = None
        slot = _get_slot_data(coordinator, 1)
        assert slot is None


# --- Tests for _build_current_slots ---


class TestBuildCurrentSlots:
    """Tests for the _build_current_slots helper."""

    def test_returns_copy_of_slots(self):
        """Returns a list of current slots."""
        coordinator = _make_coordinator()
        slots = _build_current_slots(coordinator)
        assert len(slots) == 3
        assert slots[0].slot_index == 1

    def test_returns_empty_when_no_data(self):
        """Returns empty list when coordinator data is None."""
        coordinator = _make_coordinator()
        coordinator.data = None
        slots = _build_current_slots(coordinator)
        assert slots == []
