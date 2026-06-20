"""Data models and type definitions for the Deye Cloud integration."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Optional


class WorkMode(IntEnum):
    """Inverter work mode."""

    SELF_CONSUMPTION = 0
    TIME_OF_USE = 1
    SELLING_FIRST = 2
    ZERO_EXPORT = 3


class EnergyPattern(IntEnum):
    """Battery energy pattern."""

    BATTERY_FIRST = 0
    LOAD_FIRST = 1


class TariffCategory(StrEnum):
    """Tariff rate category."""

    CHEAP = "cheap"
    STANDARD = "standard"
    PEAK = "peak"


class TOUSlotMode(StrEnum):
    """Time-of-Use slot operating mode."""

    CHARGING = "charging"
    DISCHARGING = "discharging"
    DISABLED = "disabled"


@dataclass
class Station:
    """Represents a Deye Cloud station (physical site)."""

    station_id: str
    name: str
    latitude: float
    longitude: float
    rated_capacity_kwp: float


@dataclass
class Device:
    """Represents a Deye inverter device."""

    device_sn: str
    station_id: str
    model_name: str
    firmware_version: str
    rated_power_w: int
    phase_count: int  # 1 or 3
    mppt_count: int  # Number of MPPT channels
    has_battery: bool
    has_smart_load: bool
    smart_load_channels: int
    supported_work_modes: list[WorkMode] = field(default_factory=list)
    supported_energy_patterns: list[EnergyPattern] = field(default_factory=list)
    battery_soc_min: int = 10
    battery_soc_max: int = 100
    battery_charge_current_max: float = 0.0
    battery_discharge_current_max: float = 0.0


@dataclass
class MPPTChannelData:
    """Data for a single MPPT channel."""

    channel: int
    power_w: float
    voltage_v: float
    current_a: float


@dataclass
class PhaseData:
    """Data for a single AC phase."""

    phase: int  # 1, 2, or 3
    voltage_v: float
    current_a: float
    power_w: float
    frequency_hz: float


@dataclass
class AlertData:
    """Inverter alert information."""

    alert_type: str
    severity: str
    timestamp: datetime
    message: str
    is_active: bool


@dataclass
class TOUSlotData:
    """Time-of-Use schedule slot."""

    slot_index: int
    start_time: str  # "HH:MM"
    end_time: str  # "HH:MM"
    mode: TOUSlotMode
    power_limit_w: int


@dataclass
class TariffPeriod:
    """A user-defined tariff rate period."""

    start_time: str  # "HH:MM"
    end_time: str  # "HH:MM"
    category: TariffCategory


@dataclass
class TariffConfig:
    """Complete tariff configuration for automation."""

    enabled: bool
    periods: list[TariffPeriod] = field(default_factory=list)
    default_work_mode: WorkMode = WorkMode.SELF_CONSUMPTION
    charge_current: float = 0.0
    discharge_current: float = 0.0


@dataclass
class HourlyForecast:
    """Single hour forecast entry."""

    timestamp: datetime
    estimated_power_w: float
    irradiance_wm2: float


@dataclass
class ForecastData:
    """Solar forecast data from Open-Meteo."""

    forecast_today_kwh: float
    forecast_tomorrow_kwh: float
    current_hour_power_w: float
    hourly_forecast: list[HourlyForecast] = field(default_factory=list)
    last_successful_update: datetime = field(default_factory=datetime.now)
    is_stale: bool = False


@dataclass
class TOUSchedule:
    """Complete TOU schedule for API submission."""

    enabled: bool
    slots: list[TOUSlotData] = field(default_factory=list)


@dataclass
class DeviceData:
    """Parsed latest data from Deye Cloud API for one inverter."""

    # PV
    pv_power_total_w: float
    pv_daily_yield_kwh: float
    pv_total_yield_kwh: float
    pv_channels: list[MPPTChannelData] = field(default_factory=list)

    # Battery
    battery_soc_pct: Optional[float] = None
    battery_power_w: Optional[float] = None  # + charging, - discharging
    battery_voltage_v: Optional[float] = None
    battery_current_a: Optional[float] = None
    battery_temperature_c: Optional[float] = None
    battery_daily_charge_kwh: Optional[float] = None
    battery_daily_discharge_kwh: Optional[float] = None
    battery_total_charge_kwh: Optional[float] = None
    battery_total_discharge_kwh: Optional[float] = None

    # Grid
    grid_import_power_w: float = 0.0
    grid_export_power_w: float = 0.0
    grid_daily_import_kwh: float = 0.0
    grid_daily_export_kwh: float = 0.0
    grid_total_import_kwh: float = 0.0
    grid_total_export_kwh: float = 0.0
    grid_frequency_hz: float = 0.0
    grid_phases: list[PhaseData] = field(default_factory=list)

    # Load
    load_power_w: float = 0.0
    load_daily_consumption_kwh: float = 0.0
    load_total_consumption_kwh: float = 0.0

    # Status
    is_online: bool = True
    last_update_time: datetime = field(default_factory=datetime.now)
    active_alerts: list[AlertData] = field(default_factory=list)

    # Configuration readback
    work_mode: WorkMode = WorkMode.SELF_CONSUMPTION
    energy_pattern: EnergyPattern = EnergyPattern.BATTERY_FIRST
    battery_soc_min_setting: int = 10
    battery_soc_max_setting: int = 100
    battery_charge_current_setting: float = 0.0
    battery_discharge_current_setting: float = 0.0
    grid_export_limit_w: int = 0
    solar_sell_enabled: bool = False
    peak_shaving_enabled: bool = False
    peak_shaving_threshold_w: int = 0
    smart_load_states: list[bool] = field(default_factory=list)
    tou_enabled: bool = False
    tou_slots: list[TOUSlotData] = field(default_factory=list)
