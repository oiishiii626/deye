"""Shared fixtures and module mocks for Deye Cloud tests."""

import sys
from unittest.mock import MagicMock

# Mock third-party modules that may not be installed in test env
third_party_mocks = {
    "aiohttp": MagicMock(),
    "voluptuous": MagicMock(),
}
for mod_name, mock_mod in third_party_mocks.items():
    if mod_name not in sys.modules:
        sys.modules[mod_name] = mock_mod

# Mock homeassistant modules for testing without full HA install
ha_modules = {
    "homeassistant": MagicMock(),
    "homeassistant.components": MagicMock(),
    "homeassistant.components.binary_sensor": MagicMock(),
    "homeassistant.components.event": MagicMock(),
    "homeassistant.components.frontend": MagicMock(),
    "homeassistant.components.sensor": MagicMock(),
    "homeassistant.components.switch": MagicMock(),
    "homeassistant.config_entries": MagicMock(),
    "homeassistant.const": MagicMock(),
    "homeassistant.core": MagicMock(),
    "homeassistant.data_entry_flow": MagicMock(),
    "homeassistant.exceptions": MagicMock(),
    "homeassistant.helpers": MagicMock(),
    "homeassistant.helpers.aiohttp_client": MagicMock(),
    "homeassistant.helpers.event": MagicMock(),
    "homeassistant.helpers.device_registry": MagicMock(),
    "homeassistant.helpers.entity": MagicMock(),
    "homeassistant.helpers.entity_platform": MagicMock(),
    "homeassistant.helpers.update_coordinator": MagicMock(),
    "homeassistant.helpers.issue_registry": MagicMock(),
}

# Set CONF_SCAN_INTERVAL to a string constant as HA does
ha_modules["homeassistant.const"].CONF_SCAN_INTERVAL = "scan_interval"

# Mock homeassistant.core.callback as a passthrough decorator
def _callback(func):
    """Mock HA callback decorator - just returns the function."""
    return func

ha_modules["homeassistant.core"].callback = _callback
ha_modules["homeassistant.core"].HomeAssistant = MagicMock

# Set up unit constants used by sensor platform
ha_modules["homeassistant.const"].PERCENTAGE = "%"
ha_modules["homeassistant.const"].UnitOfElectricCurrent = MagicMock()
ha_modules["homeassistant.const"].UnitOfElectricCurrent.AMPERE = "A"
ha_modules["homeassistant.const"].UnitOfElectricPotential = MagicMock()
ha_modules["homeassistant.const"].UnitOfElectricPotential.VOLT = "V"
ha_modules["homeassistant.const"].UnitOfEnergy = MagicMock()
ha_modules["homeassistant.const"].UnitOfEnergy.KILO_WATT_HOUR = "kWh"
ha_modules["homeassistant.const"].UnitOfFrequency = MagicMock()
ha_modules["homeassistant.const"].UnitOfFrequency.HERTZ = "Hz"
ha_modules["homeassistant.const"].UnitOfPower = MagicMock()
ha_modules["homeassistant.const"].UnitOfPower.WATT = "W"
ha_modules["homeassistant.const"].UnitOfTemperature = MagicMock()
ha_modules["homeassistant.const"].UnitOfTemperature.CELSIUS = "°C"


# Set up sensor module with proper classes
class _SensorDeviceClass:
    """Mock SensorDeviceClass enum."""
    POWER = "power"
    ENERGY = "energy"
    VOLTAGE = "voltage"
    CURRENT = "current"
    FREQUENCY = "frequency"
    TEMPERATURE = "temperature"
    BATTERY = "battery"


class _SensorStateClass:
    """Mock SensorStateClass enum."""
    MEASUREMENT = "measurement"
    TOTAL_INCREASING = "total_increasing"
    TOTAL = "total"


from dataclasses import dataclass as _dataclass


@_dataclass(kw_only=True)
class _SensorEntityDescription:
    """Mock SensorEntityDescription base dataclass."""
    key: str = ""
    translation_key: str | None = None
    name: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    native_unit_of_measurement: str | None = None


class _SensorEntity:
    """Mock SensorEntity base."""
    entity_description = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)


ha_modules["homeassistant.components.sensor"].SensorDeviceClass = _SensorDeviceClass
ha_modules["homeassistant.components.sensor"].SensorEntity = _SensorEntity
ha_modules["homeassistant.components.sensor"].SensorEntityDescription = _SensorEntityDescription
ha_modules["homeassistant.components.sensor"].SensorStateClass = _SensorStateClass


# Set up binary sensor module with proper classes
class _BinarySensorDeviceClass:
    """Mock BinarySensorDeviceClass enum."""
    CONNECTIVITY = "connectivity"


class _BinarySensorEntity:
    """Mock BinarySensorEntity base."""
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)


ha_modules["homeassistant.components.binary_sensor"].BinarySensorDeviceClass = _BinarySensorDeviceClass
ha_modules["homeassistant.components.binary_sensor"].BinarySensorEntity = _BinarySensorEntity


# Set up helpers.entity module
class _DeviceInfo(dict):
    """Mock DeviceInfo that behaves like a dict."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


ha_modules["homeassistant.helpers.entity"].DeviceInfo = _DeviceInfo


# Set up CoordinatorEntity mock
class _CoordinatorEntity:
    """Mock CoordinatorEntity base class."""

    def __init__(self, coordinator):
        self.coordinator = coordinator

    def __class_getitem__(cls, item):
        return cls

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)


ha_modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = _CoordinatorEntity


# Mock BinarySensorDeviceClass enum
class _BinarySensorDeviceClass:
    """Mock BinarySensorDeviceClass."""
    CONNECTIVITY = "connectivity"
    BATTERY = "battery"
    POWER = "power"


class _BinarySensorEntity:
    """Mock BinarySensorEntity base class."""
    _attr_device_class = None
    _attr_has_entity_name = False
    _attr_name = None

    @property
    def device_class(self):
        return self._attr_device_class

    @property
    def unique_id(self):
        return self._attr_unique_id


ha_modules["homeassistant.components.binary_sensor"].BinarySensorDeviceClass = _BinarySensorDeviceClass
ha_modules["homeassistant.components.binary_sensor"].BinarySensorEntity = _BinarySensorEntity


# Mock SensorDeviceClass enum
class _SensorDeviceClass:
    """Mock SensorDeviceClass."""
    POWER = "power"
    ENERGY = "energy"
    VOLTAGE = "voltage"
    CURRENT = "current"
    FREQUENCY = "frequency"
    TEMPERATURE = "temperature"
    BATTERY = "battery"
    TIMESTAMP = "timestamp"


# Mock SensorStateClass enum
class _SensorStateClass:
    """Mock SensorStateClass."""
    MEASUREMENT = "measurement"
    TOTAL_INCREASING = "total_increasing"
    TOTAL = "total"


class _SensorEntity:
    """Mock SensorEntity base class."""
    _attr_device_class = None
    _attr_state_class = None
    _attr_native_unit_of_measurement = None
    _attr_has_entity_name = False
    _attr_name = None
    _attr_unique_id = None

    @property
    def device_class(self):
        return self._attr_device_class

    @property
    def state_class(self):
        return self._attr_state_class

    @property
    def native_unit_of_measurement(self):
        return self._attr_native_unit_of_measurement

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def name(self):
        return self._attr_name

    @property
    def should_poll(self):
        return True

    @property
    def available(self):
        return True

    @property
    def extra_state_attributes(self):
        return {}

    def async_write_ha_state(self):
        """Mock state write."""

    async def async_added_to_hass(self):
        """Mock added to hass."""

    def async_on_remove(self, remove_callback):
        """Mock on_remove registration."""


ha_modules["homeassistant.components.sensor"].SensorDeviceClass = _SensorDeviceClass
ha_modules["homeassistant.components.sensor"].SensorStateClass = _SensorStateClass
ha_modules["homeassistant.components.sensor"].SensorEntity = _SensorEntity


# Mock UnitOfPower and UnitOfEnergy
ha_modules["homeassistant.const"].UnitOfPower = MagicMock()
ha_modules["homeassistant.const"].UnitOfPower.WATT = "W"
ha_modules["homeassistant.const"].UnitOfEnergy = MagicMock()
ha_modules["homeassistant.const"].UnitOfEnergy.KILO_WATT_HOUR = "kWh"


# Mock CoordinatorEntity
class _CoordinatorEntity:
    """Mock CoordinatorEntity base class."""

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self) -> bool:
        """Return True if coordinator has data."""
        return self.coordinator.last_update_success

    def _handle_coordinator_update(self) -> None:
        """Mock coordinator update handler."""
        pass

    def async_write_ha_state(self):
        """Mock state write."""
        pass


ha_modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = _CoordinatorEntity


# Mock DeviceInfo as a simple dict-like class
class _DeviceInfo(dict):
    """Mock DeviceInfo."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


ha_modules["homeassistant.helpers.entity"].DeviceInfo = _DeviceInfo


class _UpdateFailed(Exception):
    """Mock UpdateFailed exception."""
    pass


class _HomeAssistantError(Exception):
    """Mock HomeAssistantError exception."""
    pass


class _MockDataUpdateCoordinator:
    """Mock DataUpdateCoordinator base class."""

    def __init__(self, hass, logger, *, name: str, update_interval=None):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self.last_update_success = True

    async def async_config_entry_first_refresh(self):
        """Mock first refresh."""
        try:
            self.data = await self._async_update_data()
            self.last_update_success = True
        except _UpdateFailed:
            self.last_update_success = False
            raise

    async def async_refresh(self):
        """Refresh data."""
        try:
            self.data = await self._async_update_data()
            self.last_update_success = True
        except _UpdateFailed:
            self.last_update_success = False
            raise

    async def _async_update_data(self):
        """Override in subclass."""
        raise NotImplementedError


# Allow subscripting DataUpdateCoordinator[T]
class _SubscriptableCoordinator:
    """Allow DataUpdateCoordinator[DeviceData] syntax."""

    def __class_getitem__(cls, item):
        return _MockDataUpdateCoordinator

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)


# Make DataUpdateCoordinator subscriptable by using a metaclass approach
class _CoordinatorMeta(type):
    def __getitem__(cls, item):
        return _MockDataUpdateCoordinator


class DataUpdateCoordinatorSubscriptable(_MockDataUpdateCoordinator, metaclass=_CoordinatorMeta):
    """DataUpdateCoordinator that supports [] syntax."""
    pass


ha_modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = DataUpdateCoordinatorSubscriptable
ha_modules["homeassistant.helpers.update_coordinator"].UpdateFailed = _UpdateFailed
ha_modules["homeassistant.exceptions"].HomeAssistantError = _HomeAssistantError


class _IssueSeverity:
    """Mock IssueSeverity enum."""
    ERROR = "error"
    WARNING = "warning"
    CRITICAL = "critical"


ha_modules["homeassistant.helpers.issue_registry"].IssueSeverity = _IssueSeverity
ha_modules["homeassistant.helpers.issue_registry"].async_create_issue = MagicMock()
ha_modules["homeassistant.helpers.issue_registry"].async_delete_issue = MagicMock()


class _MockConfigFlowResult(dict):
    """A dict subclass to mimic ConfigFlowResult."""
    pass


class _MockAbortFlow(Exception):
    """Mock AbortFlow exception."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class _MockConfigFlow:
    """Mock base ConfigFlow class."""

    VERSION = 1

    def __init_subclass__(cls, *, domain: str = "", **kwargs):
        """Accept domain keyword like real ConfigFlow."""
        super().__init_subclass__(**kwargs)
        cls.DOMAIN = domain

    def __init__(self):
        self.hass = None
        self._unique_id = None

    async def async_set_unique_id(self, unique_id):
        self._unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        pass

    def async_show_form(self, *, step_id, data_schema=None, errors=None):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
        }

    def async_create_entry(self, *, title, data):
        return {
            "type": "create_entry",
            "title": title,
            "data": data,
        }

    def async_abort(self, *, reason):
        return {
            "type": "abort",
            "reason": reason,
        }


class _MockOptionsFlowWithConfigEntry:
    """Mock OptionsFlowWithConfigEntry base class."""

    def __init__(self, config_entry):
        self.config_entry = config_entry
        self.hass = None
        self.options = dict(config_entry.options) if isinstance(config_entry.options, dict) else {}

    def async_show_form(self, *, step_id, data_schema=None, errors=None):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
        }

    def async_show_menu(self, *, step_id, menu_options):
        return {
            "type": "menu",
            "step_id": step_id,
            "menu_options": menu_options,
        }

    def async_create_entry(self, *, title, data):
        return {
            "type": "create_entry",
            "title": title,
            "data": data,
        }


# Assign mock classes to proper module paths
ha_modules["homeassistant.config_entries"].ConfigFlow = _MockConfigFlow
ha_modules["homeassistant.config_entries"].ConfigFlowResult = _MockConfigFlowResult
ha_modules["homeassistant.config_entries"].ConfigEntry = MagicMock
ha_modules["homeassistant.config_entries"].OptionsFlowWithConfigEntry = _MockOptionsFlowWithConfigEntry
ha_modules["homeassistant.data_entry_flow"].AbortFlow = _MockAbortFlow

# Set up select module with SelectEntity mock
class _SelectEntity:
    """Mock SelectEntity base class."""
    _attr_has_entity_name = False
    _attr_name = None
    _attr_unique_id = None
    _attr_options: list[str] = []
    _attr_current_option: str | None = None
    _attr_icon: str | None = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    @property
    def current_option(self) -> str | None:
        return self._attr_current_option

    @property
    def options(self) -> list[str]:
        return self._attr_options

    async def async_select_option(self, option: str) -> None:
        """Override in subclass."""

    def async_write_ha_state(self):
        """Mock state write."""


ha_modules["homeassistant.components.select"] = MagicMock()
ha_modules["homeassistant.components.select"].SelectEntity = _SelectEntity


# Set up number module with NumberEntity mock
ha_modules["homeassistant.components.number"] = MagicMock()


class _NumberDeviceClass:
    """Mock NumberDeviceClass enum."""
    POWER = "power"
    CURRENT = "current"
    BATTERY = "battery"
    TEMPERATURE = "temperature"


class _NumberMode:
    """Mock NumberMode enum."""
    BOX = "box"
    SLIDER = "slider"
    AUTO = "auto"


class _NumberEntity:
    """Mock NumberEntity base class."""
    _attr_device_class = None
    _attr_has_entity_name = False
    _attr_name = None
    _attr_unique_id = None
    _attr_native_unit_of_measurement = None
    _attr_native_min_value = None
    _attr_native_max_value = None
    _attr_native_step = None
    _attr_mode = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def native_min_value(self):
        return self._attr_native_min_value

    @property
    def native_max_value(self):
        return self._attr_native_max_value

    @property
    def native_step(self):
        return self._attr_native_step

    def async_write_ha_state(self):
        """Mock state write."""


ha_modules["homeassistant.components.number"].NumberDeviceClass = _NumberDeviceClass
ha_modules["homeassistant.components.number"].NumberEntity = _NumberEntity
ha_modules["homeassistant.components.number"].NumberMode = _NumberMode


# Set up switch module with SwitchEntity mock
class _SwitchEntity:
    """Mock SwitchEntity base class."""
    _attr_has_entity_name = False
    _attr_name = None
    _attr_unique_id = None
    _attr_icon = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    @property
    def is_on(self):
        return None

    def async_write_ha_state(self):
        """Mock state write."""

    async def async_turn_on(self, **kwargs):
        """Turn on."""

    async def async_turn_off(self, **kwargs):
        """Turn off."""


ha_modules["homeassistant.components.switch"] = MagicMock()
ha_modules["homeassistant.components.switch"].SwitchEntity = _SwitchEntity


# Set up event module with EventEntity mock
class _EventEntity:
    """Mock EventEntity base class."""
    _attr_has_entity_name = False
    _attr_name = None
    _attr_unique_id = None
    _attr_event_types: list[str] = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def _trigger_event(self, event_type: str, event_attributes: dict | None = None):
        """Mock triggering an event - stores for test inspection."""
        if not hasattr(self, "_fired_events"):
            self._fired_events = []
        self._fired_events.append({
            "event_type": event_type,
            "event_attributes": event_attributes or {},
        })


ha_modules["homeassistant.components.event"].EventEntity = _EventEntity


# Set up time module with TimeEntity mock
from datetime import time as _dt_time

ha_modules["homeassistant.components.time"] = MagicMock()


class _TimeEntity:
    """Mock TimeEntity base class."""
    _attr_has_entity_name = False
    _attr_name = None
    _attr_unique_id = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    @property
    def native_value(self) -> _dt_time | None:
        return None

    async def async_set_value(self, value: _dt_time) -> None:
        """Override in subclass."""

    def async_write_ha_state(self):
        """Mock state write."""


ha_modules["homeassistant.components.time"].TimeEntity = _TimeEntity


# Set up switch module with SwitchEntity mock
class _SwitchEntity:
    """Mock SwitchEntity base class."""
    _attr_has_entity_name = False
    _attr_name = None
    _attr_unique_id = None
    _attr_device_info = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def async_write_ha_state(self):
        """Mock state write."""

    @property
    def is_on(self) -> bool | None:
        return None


ha_modules["homeassistant.components.switch"].SwitchEntity = _SwitchEntity


# Mock DeviceInfo on device_registry (used by sensor.py)
ha_modules["homeassistant.helpers.device_registry"].DeviceInfo = _DeviceInfo


# Set up number module with proper classes
class _NumberDeviceClass:
    """Mock NumberDeviceClass enum."""
    CURRENT = "current"
    POWER = "power"
    ENERGY = "energy"
    VOLTAGE = "voltage"
    TEMPERATURE = "temperature"


class _NumberMode:
    """Mock NumberMode enum."""
    AUTO = "auto"
    BOX = "box"
    SLIDER = "slider"


class _NumberEntity:
    """Mock NumberEntity base class."""
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_native_min_value: float = 0.0
    _attr_native_max_value: float = 100.0
    _attr_native_step: float = 1.0
    _attr_mode = "auto"
    _attr_has_entity_name = False
    _attr_name = None
    _attr_unique_id = None

    @property
    def device_class(self):
        return self._attr_device_class

    @property
    def native_unit_of_measurement(self):
        return self._attr_native_unit_of_measurement

    @property
    def native_min_value(self):
        return self._attr_native_min_value

    @property
    def native_max_value(self):
        return self._attr_native_max_value

    @property
    def native_step(self):
        return self._attr_native_step

    @property
    def mode(self):
        return self._attr_mode

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def name(self):
        return self._attr_name

    def async_write_ha_state(self):
        """Mock state write."""

    async def async_set_native_value(self, value: float) -> None:
        """Override in subclass."""


ha_modules["homeassistant.components.number"] = MagicMock()
ha_modules["homeassistant.components.number"].NumberDeviceClass = _NumberDeviceClass
ha_modules["homeassistant.components.number"].NumberEntity = _NumberEntity
ha_modules["homeassistant.components.number"].NumberMode = _NumberMode


# Patch sys.modules BEFORE any test imports
for mod_name, mock_mod in ha_modules.items():
    if mod_name not in sys.modules:
        sys.modules[mod_name] = mock_mod
