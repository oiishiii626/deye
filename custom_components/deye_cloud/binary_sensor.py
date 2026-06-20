"""Binary sensor platform for the Deye Cloud integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DeyeDeviceCoordinator
from .models import DeviceData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Deye Cloud binary sensors from a config entry.

    Creates one online/offline binary sensor per inverter.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    device_coordinators: dict[str, DeyeDeviceCoordinator] = data["device_coordinators"]

    entities: list[DeyeOnlineBinarySensor] = [
        DeyeOnlineBinarySensor(coordinator, device_sn)
        for device_sn, coordinator in device_coordinators.items()
    ]

    async_add_entities(entities)


class DeyeOnlineBinarySensor(CoordinatorEntity[DeyeDeviceCoordinator], BinarySensorEntity):
    """Binary sensor indicating inverter online/offline status."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_name = "Online Status"

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        device_sn: str,
    ) -> None:
        """Initialize the binary sensor.

        Args:
            coordinator: The device data coordinator.
            device_sn: The device serial number.
        """
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._attr_unique_id = f"{device_sn}_online_status"

    @property
    def is_on(self) -> bool | None:
        """Return True if the inverter is online."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.is_online

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link this entity to the inverter device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_sn)},
        )
