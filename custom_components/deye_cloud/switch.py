"""Switch platform for the Deye Cloud integration."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DeyeDeviceCoordinator
from .helpers import generate_unique_id
from .models import Device, TOUSchedule

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Deye Cloud switch entities from a config entry.

    Creates switch entities for solar sell, peak shaving, TOU schedule,
    tariff automation, and smart load per inverter.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    device_coordinators: dict[str, DeyeDeviceCoordinator] = data["device_coordinators"]
    devices_metadata = data.get("devices_metadata", {})
    api = data.get("api")

    entities: list = []
    for device_sn, coordinator in device_coordinators.items():
        # Standard switches for all inverters
        entities.append(DeyeSolarSellSwitch(coordinator, api, device_sn))
        entities.append(DeyePeakShavingSwitch(coordinator, api, device_sn))
        entities.append(DeyeTOUEnabledSwitch(coordinator, api, device_sn))
        entities.append(DeyeTariffAutomationSwitch(
            coordinator=coordinator,
            device_sn=device_sn,
            hass_obj=None,
            entry_id=entry.entry_id,
        ))

        # Smart load switches - conditional on device capability
        device: Device | None = devices_metadata.get(device_sn)
        if device is not None and device.has_smart_load and device.smart_load_channels > 0:
            for channel in range(device.smart_load_channels):
                entities.append(
                    DeyeSmartLoadSwitch(coordinator, api, device_sn, channel)
                )

    async_add_entities(entities)


class DeyeSolarSellSwitch(CoordinatorEntity[DeyeDeviceCoordinator], SwitchEntity):
    """Switch entity for solar sell control."""

    _attr_has_entity_name = True
    _attr_name = "Solar Sell"

    def __init__(self, coordinator: DeyeDeviceCoordinator, api, device_sn: str) -> None:
        """Initialize the solar sell switch."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._api = api
        self._attr_unique_id = generate_unique_id(device_sn, "solar_sell")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if solar sell is enabled."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.solar_sell_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on solar sell via API."""
        previous = self.coordinator.data.solar_sell_enabled
        self.coordinator.data.solar_sell_enabled = True
        self.async_write_ha_state()

        try:
            await self._api.set_device_config(
                self._device_sn, {"solarSellEnabled": True}
            )
        except Exception as err:
            self.coordinator.data.solar_sell_enabled = previous
            self.async_write_ha_state()
            self.hass.components.persistent_notification.async_create(
                f"Solar Sell reverted due to API error: {err}",
                title="Deye Cloud: Solar Sell",
            )

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off solar sell via API."""
        previous = self.coordinator.data.solar_sell_enabled
        self.coordinator.data.solar_sell_enabled = False
        self.async_write_ha_state()

        try:
            await self._api.set_device_config(
                self._device_sn, {"solarSellEnabled": False}
            )
        except Exception as err:
            self.coordinator.data.solar_sell_enabled = previous
            self.async_write_ha_state()
            self.hass.components.persistent_notification.async_create(
                f"Solar Sell reverted due to API error: {err}",
                title="Deye Cloud: Solar Sell",
            )


class DeyePeakShavingSwitch(CoordinatorEntity[DeyeDeviceCoordinator], SwitchEntity):
    """Switch entity for peak shaving control."""

    _attr_has_entity_name = True
    _attr_name = "Peak Shaving"

    def __init__(self, coordinator: DeyeDeviceCoordinator, api, device_sn: str) -> None:
        """Initialize the peak shaving switch."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._api = api
        self._attr_unique_id = generate_unique_id(device_sn, "peak_shaving")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if peak shaving is enabled."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.peak_shaving_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on peak shaving via API."""
        previous = self.coordinator.data.peak_shaving_enabled
        self.coordinator.data.peak_shaving_enabled = True
        self.async_write_ha_state()

        try:
            await self._api.set_device_config(
                self._device_sn, {"peakShavingEnabled": True}
            )
        except Exception as err:
            self.coordinator.data.peak_shaving_enabled = previous
            self.async_write_ha_state()
            self.hass.components.persistent_notification.async_create(
                f"Peak Shaving reverted due to API error: {err}",
                title="Deye Cloud: Peak Shaving",
            )

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off peak shaving via API."""
        previous = self.coordinator.data.peak_shaving_enabled
        self.coordinator.data.peak_shaving_enabled = False
        self.async_write_ha_state()

        try:
            await self._api.set_device_config(
                self._device_sn, {"peakShavingEnabled": False}
            )
        except Exception as err:
            self.coordinator.data.peak_shaving_enabled = previous
            self.async_write_ha_state()
            self.hass.components.persistent_notification.async_create(
                f"Peak Shaving reverted due to API error: {err}",
                title="Deye Cloud: Peak Shaving",
            )


class DeyeTOUEnabledSwitch(CoordinatorEntity[DeyeDeviceCoordinator], SwitchEntity):
    """Switch entity for TOU schedule enable/disable."""

    _attr_has_entity_name = True
    _attr_name = "TOU Schedule"

    def __init__(self, coordinator: DeyeDeviceCoordinator, api, device_sn: str) -> None:
        """Initialize the TOU enabled switch."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._api = api
        self._attr_unique_id = f"{device_sn}_tou_enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
        )
        self._optimistic_state: bool | None = None

    @property
    def is_on(self) -> bool | None:
        """Return True if TOU schedule is enabled."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.tou_enabled

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic state on coordinator update."""
        self._optimistic_state = None

    async def async_turn_on(self, **kwargs) -> None:
        """Enable TOU schedule via API."""
        # Optimistic update
        self._optimistic_state = True
        self.async_write_ha_state()

        # Build schedule with existing slots
        slots = self.coordinator.data.tou_slots if self.coordinator.data else []
        schedule = TOUSchedule(enabled=True, slots=list(slots))

        try:
            await self._api.set_tou_schedule(self._device_sn, schedule)
            self._optimistic_state = None
        except Exception as err:
            # Revert
            self._optimistic_state = None
            self.async_write_ha_state()
            self.hass.components.persistent_notification.async_create(
                f"TOU Schedule toggle reverted due to API error: {err}",
                title="Deye Cloud: TOU Schedule",
            )

    async def async_turn_off(self, **kwargs) -> None:
        """Disable TOU schedule via API."""
        # Optimistic update
        self._optimistic_state = False
        self.async_write_ha_state()

        # Build schedule with existing slots
        slots = self.coordinator.data.tou_slots if self.coordinator.data else []
        schedule = TOUSchedule(enabled=False, slots=list(slots))

        try:
            await self._api.set_tou_schedule(self._device_sn, schedule)
            self._optimistic_state = None
        except Exception as err:
            # Revert
            self._optimistic_state = None
            self.async_write_ha_state()
            self.hass.components.persistent_notification.async_create(
                f"TOU Schedule toggle reverted due to API error: {err}",
                title="Deye Cloud: TOU Schedule",
            )


class DeyeTariffAutomationSwitch(CoordinatorEntity[DeyeDeviceCoordinator], SwitchEntity):
    """Switch entity for tariff automation control.

    This switch is local-only (no API call). It stores its state in hass.data
    so the TariffManager can read it to decide whether to automate mode switches.
    """

    _attr_has_entity_name = True
    _attr_name = "Tariff Automation"
    _attr_icon = "mdi:currency-usd"

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        device_sn: str,
        hass_obj=None,
        entry_id: str | None = None,
        **kwargs,
    ) -> None:
        """Initialize the tariff automation switch."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._entry_id = entry_id
        self._hass_obj = hass_obj
        self._attr_unique_id = f"{device_sn}_tariff_automation"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
        )
        self._is_on: bool = False

    @property
    def is_on(self) -> bool | None:
        """Return True if tariff automation is enabled."""
        return self._is_on

    def _store_state(self, enabled: bool) -> None:
        """Store the tariff enabled state in hass.data for TariffManager."""
        hass = self._hass_obj or getattr(self, "hass", None)
        if hass is None or self._entry_id is None:
            return
        entry_data = hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        if "tariff_enabled" not in entry_data:
            entry_data["tariff_enabled"] = {}
        entry_data["tariff_enabled"][self._device_sn] = enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable tariff automation."""
        self._is_on = True
        self._store_state(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable tariff automation."""
        self._is_on = False
        self._store_state(False)
        self.async_write_ha_state()


class DeyeSmartLoadSwitch(CoordinatorEntity[DeyeDeviceCoordinator], SwitchEntity):
    """Switch entity for smart load channel control."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: DeyeDeviceCoordinator, api, device_sn: str, channel: int
    ) -> None:
        """Initialize the smart load switch."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._api = api
        self._channel = channel
        self._attr_unique_id = f"{device_sn}_smart_load_{channel}"
        self._attr_name = f"Smart Load {channel + 1}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if the smart load channel is on."""
        if self.coordinator.data is None:
            return None
        states = self.coordinator.data.smart_load_states
        if not states or self._channel >= len(states):
            return None
        return states[self._channel]

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the smart load channel via API."""
        # Optimistic update
        if self.coordinator.data and self._channel < len(self.coordinator.data.smart_load_states):
            self.coordinator.data.smart_load_states[self._channel] = True
        self.async_write_ha_state()

        try:
            await self._api.set_smart_load(self._device_sn, self._channel, True)
        except Exception as err:
            # Revert
            if self.coordinator.data and self._channel < len(self.coordinator.data.smart_load_states):
                self.coordinator.data.smart_load_states[self._channel] = False
            self.async_write_ha_state()
            self.hass.components.persistent_notification.async_create(
                f"Smart Load {self._channel + 1} reverted due to API error: {err}",
                title=f"Deye Cloud: Smart Load {self._channel + 1}",
            )

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the smart load channel via API."""
        previous = None
        if self.coordinator.data and self._channel < len(self.coordinator.data.smart_load_states):
            previous = self.coordinator.data.smart_load_states[self._channel]
            self.coordinator.data.smart_load_states[self._channel] = False
        self.async_write_ha_state()

        try:
            await self._api.set_smart_load(self._device_sn, self._channel, False)
        except Exception as err:
            # Revert
            if previous is not None and self.coordinator.data and self._channel < len(self.coordinator.data.smart_load_states):
                self.coordinator.data.smart_load_states[self._channel] = previous
            self.async_write_ha_state()
            self.hass.components.persistent_notification.async_create(
                f"Smart Load {self._channel + 1} reverted due to API error: {err}",
                title=f"Deye Cloud: Smart Load {self._channel + 1}",
            )
