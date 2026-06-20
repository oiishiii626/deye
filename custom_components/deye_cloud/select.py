"""Select platform for the Deye Cloud integration."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DeyeDeviceCoordinator
from .models import Device, EnergyPattern, WorkMode

_LOGGER = logging.getLogger(__name__)


WORK_MODE_NAMES = {
    WorkMode.SELF_CONSUMPTION: "Self Consumption",
    WorkMode.TIME_OF_USE: "Time of Use",
    WorkMode.SELLING_FIRST: "Selling First",
    WorkMode.ZERO_EXPORT: "Zero Export",
}

ENERGY_PATTERN_NAMES = {
    EnergyPattern.BATTERY_FIRST: "Battery First",
    EnergyPattern.LOAD_FIRST: "Load First",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Deye Cloud select entities from a config entry.

    Creates select entities for work mode and energy pattern per inverter,
    based on the device's supported modes reported by the API.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    device_coordinators: dict[str, DeyeDeviceCoordinator] = data["device_coordinators"]
    devices_metadata = data.get("devices_metadata", {})
    api = data.get("api")

    entities: list = []
    for device_sn, coordinator in device_coordinators.items():
        device: Device | None = devices_metadata.get(device_sn)
        if device is None:
            continue

        # Work mode select
        if device.supported_work_modes:
            entities.append(
                DeyeWorkModeSelect(
                    coordinator=coordinator,
                    api=api,
                    device_sn=device_sn,
                    supported_modes=device.supported_work_modes,
                )
            )

        # Energy pattern select
        if device.supported_energy_patterns:
            entities.append(
                DeyeEnergyPatternSelect(
                    coordinator=coordinator,
                    api=api,
                    device_sn=device_sn,
                    supported_patterns=device.supported_energy_patterns,
                )
            )

    async_add_entities(entities)


class DeyeWorkModeSelect(CoordinatorEntity[DeyeDeviceCoordinator], SelectEntity):
    """Select entity for Deye Cloud inverter work mode."""

    _attr_has_entity_name = True
    _attr_name = "Work Mode"

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        api,
        device_sn: str,
        supported_modes: list[WorkMode],
    ) -> None:
        """Initialize the work mode select entity."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._api = api
        self._supported_modes = supported_modes
        self._attr_unique_id = f"{device_sn}_work_mode"
        self._attr_options = [WORK_MODE_NAMES[m] for m in supported_modes]

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        if self.coordinator.data is None:
            return None
        mode = self.coordinator.data.work_mode
        return WORK_MODE_NAMES.get(mode)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link this entity to the inverter device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_sn)},
        )

    async def async_select_option(self, option: str) -> None:
        """Select a work mode option via API."""
        # Find the mode enum value for this option name
        target_mode: WorkMode | None = None
        for mode, name in WORK_MODE_NAMES.items():
            if name == option:
                target_mode = mode
                break

        if target_mode is None:
            _LOGGER.warning("Unknown work mode option: %s", option)
            return

        # Save previous value for rollback
        previous_mode = self.coordinator.data.work_mode

        # Optimistic update
        self.coordinator.data.work_mode = target_mode
        self.async_write_ha_state()

        try:
            await self._api.set_work_mode(self._device_sn, int(target_mode))
        except Exception as err:
            # Revert optimistic update
            self.coordinator.data.work_mode = previous_mode
            self.async_write_ha_state()
            self.hass.components.persistent_notification.async_create(
                f"Setting Work Mode reverted due to API error: {err}",
                title="Deye Cloud: Work Mode",
            )


class DeyeEnergyPatternSelect(CoordinatorEntity[DeyeDeviceCoordinator], SelectEntity):
    """Select entity for Deye Cloud inverter energy pattern."""

    _attr_has_entity_name = True
    _attr_name = "Energy Pattern"

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        api,
        device_sn: str,
        supported_patterns: list[EnergyPattern],
    ) -> None:
        """Initialize the energy pattern select entity."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._api = api
        self._supported_patterns = supported_patterns
        self._attr_unique_id = f"{device_sn}_energy_pattern"
        self._attr_options = [ENERGY_PATTERN_NAMES[p] for p in supported_patterns]

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        if self.coordinator.data is None:
            return None
        pattern = self.coordinator.data.energy_pattern
        return ENERGY_PATTERN_NAMES.get(pattern)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link this entity to the inverter device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_sn)},
        )

    async def async_select_option(self, option: str) -> None:
        """Select an energy pattern option via API."""
        # Find the pattern enum value for this option name
        target_pattern: EnergyPattern | None = None
        for pattern, name in ENERGY_PATTERN_NAMES.items():
            if name == option:
                target_pattern = pattern
                break

        if target_pattern is None:
            _LOGGER.warning("Unknown energy pattern option: %s", option)
            return

        # Save previous value for rollback
        previous_pattern = self.coordinator.data.energy_pattern

        # Optimistic update
        self.coordinator.data.energy_pattern = target_pattern
        self.async_write_ha_state()

        try:
            await self._api.set_energy_pattern(self._device_sn, int(target_pattern))
        except Exception as err:
            # Revert optimistic update
            self.coordinator.data.energy_pattern = previous_pattern
            self.async_write_ha_state()
            self.hass.components.persistent_notification.async_create(
                f"Setting Energy Pattern reverted due to API error: {err}",
                title="Deye Cloud: Energy Pattern",
            )
