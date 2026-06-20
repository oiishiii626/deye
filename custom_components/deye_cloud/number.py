"""Number platform for the Deye Cloud integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DeyeDeviceCoordinator
from .models import Device

_LOGGER = logging.getLogger(__name__)


@dataclass
class BatteryNumberDescription:
    """Description of a battery number entity."""

    key: str
    name: str
    unit: str
    step: float
    min_attr: str  # attribute name on Device for min bound
    max_attr: str  # attribute name on Device for max bound
    data_attr: str  # attribute name on DeviceData for current value
    api_param: str  # API parameter name for set_device_config


BATTERY_NUMBER_DESCRIPTIONS = [
    BatteryNumberDescription(
        key="battery_soc_min",
        name="Battery Min SOC",
        unit="%",
        step=1.0,
        min_attr="battery_soc_min",
        max_attr="battery_soc_max",
        data_attr="battery_soc_min_setting",
        api_param="batterySocMin",
    ),
    BatteryNumberDescription(
        key="battery_soc_max",
        name="Battery Max SOC",
        unit="%",
        step=1.0,
        min_attr="battery_soc_min",
        max_attr="battery_soc_max",
        data_attr="battery_soc_max_setting",
        api_param="batterySocMax",
    ),
    BatteryNumberDescription(
        key="battery_charge_current_max",
        name="Battery Max Charge Current",
        unit="A",
        step=0.1,
        min_attr="_zero",
        max_attr="battery_charge_current_max",
        data_attr="battery_charge_current_setting",
        api_param="batteryChargeCurrentMax",
    ),
    BatteryNumberDescription(
        key="battery_discharge_current_max",
        name="Battery Max Discharge Current",
        unit="A",
        step=0.1,
        min_attr="_zero",
        max_attr="battery_discharge_current_max",
        data_attr="battery_discharge_current_setting",
        api_param="batteryDischargeCurrentMax",
    ),
]


@dataclass
class GridNumberDescription:
    """Description of a grid number entity."""

    key: str
    name: str
    unit: str
    step: float
    data_attr: str
    api_param: str


GRID_NUMBER_DESCRIPTIONS = [
    GridNumberDescription(
        key="grid_export_limit",
        name="Grid Export Limit",
        unit="W",
        step=1.0,
        data_attr="grid_export_limit_w",
        api_param="gridExportLimit",
    ),
    GridNumberDescription(
        key="peak_shaving_threshold",
        name="Peak Shaving Threshold",
        unit="W",
        step=1.0,
        data_attr="peak_shaving_threshold_w",
        api_param="peakShavingThreshold",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Deye Cloud number entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    device_coordinators: dict[str, DeyeDeviceCoordinator] = data["device_coordinators"]
    devices_metadata = data.get("devices_metadata", {})

    entities: list = []
    for device_sn, coordinator in device_coordinators.items():
        device = devices_metadata.get(device_sn)

        # Battery number entities
        for desc in BATTERY_NUMBER_DESCRIPTIONS:
            entities.append(
                DeyeBatteryNumberEntity(
                    coordinator=coordinator,
                    description=desc,
                    device_sn=device_sn,
                    device=device,
                )
            )

        # Grid number entities
        for desc in GRID_NUMBER_DESCRIPTIONS:
            entities.append(
                DeyeGridNumberEntity(
                    coordinator=coordinator,
                    description=desc,
                    device_sn=device_sn,
                    device=device,
                )
            )

    async_add_entities(entities)


class DeyeBatteryNumberEntity(CoordinatorEntity[DeyeDeviceCoordinator], NumberEntity):
    """Number entity for Deye Cloud battery settings."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        description: BatteryNumberDescription,
        device_sn: str,
        device: Device | None,
    ) -> None:
        """Initialize the battery number entity."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._description = description
        self._device = device
        self._optimistic_value: float | None = None

        self._attr_unique_id = f"{device_sn}_{description.key}"
        self._attr_name = description.name
        self._attr_native_unit_of_measurement = description.unit
        self._attr_native_step = description.step

        # Set bounds from device metadata
        if device is not None:
            if description.min_attr == "_zero":
                self._attr_native_min_value = 0.0
            else:
                self._attr_native_min_value = float(
                    getattr(device, description.min_attr, 0)
                )
            self._attr_native_max_value = float(
                getattr(device, description.max_attr, 100)
            )
        else:
            self._attr_native_min_value = 0.0
            self._attr_native_max_value = 100.0

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if self._device is None:
            return False
        if self.coordinator.data is None:
            return False
        return True

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if self._optimistic_value is not None:
            return self._optimistic_value
        if self.coordinator.data is None:
            return None
        value = getattr(self.coordinator.data, self._description.data_attr, None)
        return float(value) if value is not None else None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link this entity to the inverter device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_sn)},
        )

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic value on coordinator update."""
        self._optimistic_value = None

    async def async_set_native_value(self, value: float) -> None:
        """Set the number value via API."""
        # Validate bounds
        if value < self._attr_native_min_value or value > self._attr_native_max_value:
            self.hass.components.persistent_notification.async_create(
                f"Value {value} is out of range "
                f"[{self._attr_native_min_value}, {self._attr_native_max_value}] "
                f"for {self._description.name}.",
                title=f"Deye Cloud: {self._description.name}",
            )
            return

        # Optimistic update
        self._optimistic_value = value

        try:
            await self.coordinator.api.set_device_config(
                self._device_sn, {self._description.api_param: value}
            )
            # Success - clear optimistic value (coordinator will update)
            self._optimistic_value = None
        except Exception as err:
            # Revert optimistic update
            self._optimistic_value = None
            self.hass.components.persistent_notification.async_create(
                f"Setting {self._description.name} reverted due to API error: {err}",
                title=f"Deye Cloud: {self._description.name}",
            )


class DeyeGridNumberEntity(CoordinatorEntity[DeyeDeviceCoordinator], NumberEntity):
    """Number entity for Deye Cloud grid control settings."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        description: GridNumberDescription,
        device_sn: str,
        device: Device | None,
    ) -> None:
        """Initialize the grid number entity."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._description = description
        self._device = device
        self._optimistic_value: float | None = None

        self._attr_unique_id = f"{device_sn}_{description.key}"
        self._attr_name = description.name
        self._attr_native_unit_of_measurement = description.unit
        self._attr_native_step = description.step
        self._attr_native_min_value = 0.0

        # Max value is rated power of the inverter
        rated_power = None
        if device is not None and device.rated_power_w:
            rated_power = device.rated_power_w
        elif hasattr(coordinator, "rated_power_w") and coordinator.rated_power_w:
            rated_power = coordinator.rated_power_w

        if rated_power:
            self._attr_native_max_value = float(rated_power)
        else:
            self._attr_native_max_value = 0.0

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Need rated_power to know valid range
        rated_power = None
        if self._device is not None and self._device.rated_power_w:
            rated_power = self._device.rated_power_w
        elif hasattr(self.coordinator, "rated_power_w") and self.coordinator.rated_power_w:
            rated_power = self.coordinator.rated_power_w
        return rated_power is not None and rated_power > 0

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if self._optimistic_value is not None:
            return self._optimistic_value
        if self.coordinator.data is None:
            return None
        value = getattr(self.coordinator.data, self._description.data_attr, None)
        return float(value) if value is not None else None

    @property
    def native_max_value(self) -> float:
        """Return the max value from rated power."""
        rated_power = None
        if self._device is not None and self._device.rated_power_w:
            rated_power = self._device.rated_power_w
        elif hasattr(self.coordinator, "rated_power_w") and self.coordinator.rated_power_w:
            rated_power = self.coordinator.rated_power_w
        return float(rated_power) if rated_power else 0.0

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic value on coordinator update."""
        self._optimistic_value = None

    async def async_set_native_value(self, value: float) -> None:
        """Set the number value via API."""
        max_val = self.native_max_value

        # Validate bounds
        if value < 0 or value > max_val:
            self.hass.components.persistent_notification.async_create(
                f"Value {value} is out of range [0, {max_val}] "
                f"for {self._description.name}.",
                title=f"Deye Cloud: {self._description.name}",
            )
            return

        # Optimistic update
        self._optimistic_value = value

        try:
            await self.coordinator.api.set_device_config(
                self._device_sn, {self._description.api_param: int(value)}
            )
            # Success - clear optimistic value
            self._optimistic_value = None
        except Exception as err:
            # Revert optimistic update
            self._optimistic_value = None
            self.hass.components.persistent_notification.async_create(
                f"Setting {self._description.name} reverted due to API error: {err}",
                title=f"Deye Cloud: {self._description.name}",
            )
