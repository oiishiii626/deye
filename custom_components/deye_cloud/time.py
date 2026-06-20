"""Time platform for the Deye Cloud integration."""

from __future__ import annotations

import logging
from datetime import time as dt_time

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DeyeDeviceCoordinator
from .models import TOUSchedule, TOUSlotData, TOUSlotMode

_LOGGER = logging.getLogger(__name__)

NUM_TOU_SLOTS = 6


def _get_slot_data(coordinator: DeyeDeviceCoordinator, slot_index: int) -> TOUSlotData | None:
    """Get TOU slot data for a given slot index from coordinator."""
    if coordinator.data is None:
        return None
    tou_slots = coordinator.data.tou_slots
    if not tou_slots:
        return None
    for slot in tou_slots:
        if slot.slot_index == slot_index:
            return slot
    return None


def _build_current_slots(coordinator: DeyeDeviceCoordinator) -> list[TOUSlotData]:
    """Build a list of current TOU slots from coordinator data."""
    if coordinator.data is None:
        return []
    return list(coordinator.data.tou_slots) if coordinator.data.tou_slots else []


def _validate_schedule(slots: list[TOUSlotData]) -> str | None:
    """Validate a TOU schedule for time period conflicts.

    Returns None if valid, or an error message string if invalid.
    """
    # Filter to only enabled (non-disabled) slots
    enabled_slots = [s for s in slots if s.mode != TOUSlotMode.DISABLED]

    for slot in enabled_slots:
        # Check end > start
        start_minutes = _time_str_to_minutes(slot.start_time)
        end_minutes = _time_str_to_minutes(slot.end_time)
        if end_minutes <= start_minutes:
            return f"Slot {slot.slot_index}: end time must be after start time."

    # Check for overlaps between enabled slots
    for i in range(len(enabled_slots)):
        for j in range(i + 1, len(enabled_slots)):
            s1_start = _time_str_to_minutes(enabled_slots[i].start_time)
            s1_end = _time_str_to_minutes(enabled_slots[i].end_time)
            s2_start = _time_str_to_minutes(enabled_slots[j].start_time)
            s2_end = _time_str_to_minutes(enabled_slots[j].end_time)

            if s1_start < s2_end and s2_start < s1_end:
                return (
                    f"Slots {enabled_slots[i].slot_index} and "
                    f"{enabled_slots[j].slot_index} overlap."
                )

    return None


def _time_str_to_minutes(time_str: str) -> int:
    """Convert HH:MM string to minutes since midnight."""
    parts = time_str.split(":")
    return int(parts[0]) * 60 + int(parts[1])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Deye Cloud time entities from a config entry.

    Creates time, mode select, and power limit entities for TOU slots.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    device_coordinators: dict[str, DeyeDeviceCoordinator] = data["device_coordinators"]

    entities: list = []
    for device_sn, coordinator in device_coordinators.items():
        rated_power_w = getattr(coordinator, "rated_power_w", 5000) or 5000

        for slot_idx in range(1, NUM_TOU_SLOTS + 1):
            entities.append(DeyeTOUStartTimeEntity(coordinator, device_sn, slot_idx))
            entities.append(DeyeTOUEndTimeEntity(coordinator, device_sn, slot_idx))
            entities.append(DeyeTOUModeSelectEntity(coordinator, device_sn, slot_idx))
            entities.append(
                DeyeTOUPowerLimitEntity(coordinator, device_sn, slot_idx, rated_power_w)
            )

    async_add_entities(entities)


class DeyeTOUStartTimeEntity(CoordinatorEntity[DeyeDeviceCoordinator], TimeEntity):
    """Time entity for a TOU slot start time."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        device_sn: str,
        slot_index: int,
    ) -> None:
        """Initialize the TOU start time entity."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._slot_index = slot_index
        self._attr_unique_id = f"{device_sn}_tou_slot_{slot_index}_start"
        self._attr_name = f"TOU Slot {slot_index} Start"

    @property
    def native_value(self) -> dt_time:
        """Return the current start time value."""
        slot = _get_slot_data(self.coordinator, self._slot_index)
        if slot is None:
            return dt_time(0, 0)
        try:
            parts = slot.start_time.split(":")
            return dt_time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return dt_time(0, 0)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(identifiers={(DOMAIN, self._device_sn)})

    async def async_set_value(self, value: dt_time) -> None:
        """Set the start time via API."""
        new_start = f"{value.hour:02d}:{value.minute:02d}"
        slots = _build_current_slots(self.coordinator)

        # Update or create the slot
        found = False
        for slot in slots:
            if slot.slot_index == self._slot_index:
                slot.start_time = new_start
                found = True
                break
        if not found:
            slots.append(
                TOUSlotData(self._slot_index, new_start, "00:00", TOUSlotMode.DISABLED, 0)
            )

        # Validate
        error = _validate_schedule(slots)
        if error:
            raise Exception(error)

        # Send to API
        tou_enabled = self.coordinator.data.tou_enabled if self.coordinator.data else False
        schedule = TOUSchedule(enabled=tou_enabled, slots=slots)
        await self.coordinator.api.set_tou_schedule(self._device_sn, schedule)
        await self.coordinator.async_request_refresh()


class DeyeTOUEndTimeEntity(CoordinatorEntity[DeyeDeviceCoordinator], TimeEntity):
    """Time entity for a TOU slot end time."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        device_sn: str,
        slot_index: int,
    ) -> None:
        """Initialize the TOU end time entity."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._slot_index = slot_index
        self._attr_unique_id = f"{device_sn}_tou_slot_{slot_index}_end"
        self._attr_name = f"TOU Slot {slot_index} End"

    @property
    def native_value(self) -> dt_time:
        """Return the current end time value."""
        slot = _get_slot_data(self.coordinator, self._slot_index)
        if slot is None:
            return dt_time(0, 0)
        try:
            parts = slot.end_time.split(":")
            return dt_time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return dt_time(0, 0)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(identifiers={(DOMAIN, self._device_sn)})

    async def async_set_value(self, value: dt_time) -> None:
        """Set the end time via API."""
        new_end = f"{value.hour:02d}:{value.minute:02d}"
        slots = _build_current_slots(self.coordinator)

        # Update or create the slot
        found = False
        for slot in slots:
            if slot.slot_index == self._slot_index:
                slot.end_time = new_end
                found = True
                break
        if not found:
            slots.append(
                TOUSlotData(self._slot_index, "00:00", new_end, TOUSlotMode.DISABLED, 0)
            )

        # Validate
        error = _validate_schedule(slots)
        if error:
            raise Exception(error)

        # Send to API
        tou_enabled = self.coordinator.data.tou_enabled if self.coordinator.data else False
        schedule = TOUSchedule(enabled=tou_enabled, slots=slots)
        await self.coordinator.api.set_tou_schedule(self._device_sn, schedule)
        await self.coordinator.async_request_refresh()


class DeyeTOUModeSelectEntity(CoordinatorEntity[DeyeDeviceCoordinator], SelectEntity):
    """Select entity for a TOU slot mode."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        device_sn: str,
        slot_index: int,
    ) -> None:
        """Initialize the TOU mode select entity."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._slot_index = slot_index
        self._attr_unique_id = f"{device_sn}_tou_slot_{slot_index}_mode"
        self._attr_name = f"TOU Slot {slot_index} Mode"
        self._attr_options = [
            TOUSlotMode.CHARGING,
            TOUSlotMode.DISCHARGING,
            TOUSlotMode.DISABLED,
        ]

    @property
    def current_option(self) -> str:
        """Return the current mode."""
        slot = _get_slot_data(self.coordinator, self._slot_index)
        if slot is None:
            return TOUSlotMode.DISABLED
        return slot.mode

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(identifiers={(DOMAIN, self._device_sn)})

    async def async_select_option(self, option: str) -> None:
        """Set the slot mode via API."""
        # Validate option
        valid_modes = [TOUSlotMode.CHARGING, TOUSlotMode.DISCHARGING, TOUSlotMode.DISABLED]
        if option not in valid_modes:
            raise Exception(f"Invalid mode: {option}")

        slots = _build_current_slots(self.coordinator)

        # Update the slot mode
        found = False
        for slot in slots:
            if slot.slot_index == self._slot_index:
                slot.mode = TOUSlotMode(option)
                found = True
                break
        if not found:
            slots.append(
                TOUSlotData(self._slot_index, "00:00", "00:00", TOUSlotMode(option), 0)
            )

        # Validate
        error = _validate_schedule(slots)
        if error:
            raise Exception(error)

        # Send to API
        tou_enabled = self.coordinator.data.tou_enabled if self.coordinator.data else False
        schedule = TOUSchedule(enabled=tou_enabled, slots=slots)
        await self.coordinator.api.set_tou_schedule(self._device_sn, schedule)
        await self.coordinator.async_request_refresh()


class DeyeTOUPowerLimitEntity(CoordinatorEntity[DeyeDeviceCoordinator], NumberEntity):
    """Number entity for a TOU slot power limit."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = "W"

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        device_sn: str,
        slot_index: int,
        rated_power_w: int,
    ) -> None:
        """Initialize the TOU power limit entity."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._slot_index = slot_index
        self._rated_power_w = rated_power_w
        self._attr_unique_id = f"{device_sn}_tou_slot_{slot_index}_power_limit"
        self._attr_name = f"TOU Slot {slot_index} Power Limit"
        self._attr_native_min_value = 0.0
        self._attr_native_max_value = float(rated_power_w)
        self._attr_native_step = 1.0

    @property
    def native_value(self) -> float:
        """Return the current power limit value."""
        slot = _get_slot_data(self.coordinator, self._slot_index)
        if slot is None:
            return 0.0
        return float(slot.power_limit_w)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(identifiers={(DOMAIN, self._device_sn)})

    async def async_set_native_value(self, value: float) -> None:
        """Set the power limit via API."""
        # Validate bounds
        if value < 0 or value > self._rated_power_w:
            raise Exception(
                f"Power limit {value}W is out of range [0, {self._rated_power_w}]"
            )

        slots = _build_current_slots(self.coordinator)

        # Update the slot power limit
        found = False
        for slot in slots:
            if slot.slot_index == self._slot_index:
                slot.power_limit_w = int(value)
                found = True
                break
        if not found:
            slots.append(
                TOUSlotData(self._slot_index, "00:00", "00:00", TOUSlotMode.DISABLED, int(value))
            )

        # Send to API
        tou_enabled = self.coordinator.data.tou_enabled if self.coordinator.data else False
        schedule = TOUSchedule(enabled=tou_enabled, slots=slots)
        await self.coordinator.api.set_tou_schedule(self._device_sn, schedule)
        await self.coordinator.async_request_refresh()
