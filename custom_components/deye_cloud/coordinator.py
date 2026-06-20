"""DataUpdateCoordinator for the Deye Cloud integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DeyeCloudAPI
from .const import (
    CONSECUTIVE_FAILURE_THRESHOLD,
    COORDINATOR_BACKOFF_MULTIPLIER,
    COORDINATOR_INITIAL_DELAY_S,
    COORDINATOR_MAX_DELAY_S,
    COORDINATOR_MAX_RETRIES,
    DOMAIN,
    RATE_LIMIT_DEFAULT_PAUSE_S,
    RATE_LIMIT_MAX_PAUSE_S,
)
from .exceptions import (
    DeyeApiError,
    DeyeAuthError,
    DeyeConnectionError,
    DeyeRateLimitError,
    DeyeTimeoutError,
)
from .models import (
    AlertData,
    DeviceData,
    EnergyPattern,
    MPPTChannelData,
    PhaseData,
    TOUSlotData,
    TOUSlotMode,
    WorkMode,
)

_LOGGER = logging.getLogger(__name__)

# Measure points to request from the API
MEASURE_POINTS = [
    "pv_power_total",
    "pv_daily_yield",
    "pv_total_yield",
    "battery_soc",
    "battery_power",
    "battery_voltage",
    "battery_current",
    "battery_temperature",
    "battery_daily_charge",
    "battery_daily_discharge",
    "battery_total_charge",
    "battery_total_discharge",
    "grid_import_power",
    "grid_export_power",
    "grid_daily_import",
    "grid_daily_export",
    "grid_total_import",
    "grid_total_export",
    "grid_frequency",
    "load_power",
    "load_daily_consumption",
    "load_total_consumption",
    "is_online",
    "last_update_time",
    "work_mode",
    "energy_pattern",
    "battery_soc_min",
    "battery_soc_max",
    "battery_charge_current_max",
    "battery_discharge_current_max",
    "grid_export_limit",
    "solar_sell_enabled",
    "peak_shaving_enabled",
    "peak_shaving_threshold",
    "tou_enabled",
    "pv_channels",
    "grid_phases",
    "smart_load_states",
    "tou_slots",
    "active_alerts",
]


class DeyeDeviceCoordinator(DataUpdateCoordinator[DeviceData]):
    """Coordinator polling a single Deye inverter."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: DeyeCloudAPI,
        device_sn: str,
        interval: timedelta,
        device_name: str | None = None,
        model_name: str | None = None,
        firmware_version: str | None = None,
        rated_power_w: int | None = None,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: The Home Assistant instance.
            api: The Deye Cloud API client.
            device_sn: The device serial number to poll.
            interval: The polling interval.
            device_name: Human-readable device name (model or user-defined).
            model_name: The inverter model name.
            firmware_version: The inverter firmware version.
            rated_power_w: The inverter rated power in watts.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device_sn}",
            update_interval=interval,
        )
        self.api = api
        self.device_sn = device_sn
        self.device_name = device_name or f"Deye {device_sn}"
        self.model_name = model_name
        self.firmware_version = firmware_version
        self.rated_power_w = rated_power_w
        self._consecutive_failures: int = 0
        self._repair_created: bool = False

    async def _async_update_data(self) -> DeviceData:
        """Fetch latest data from Deye Cloud API for this device.

        Implements retry logic with exponential backoff for transient errors,
        rate limit handling for HTTP 429, and consecutive failure tracking.

        Returns:
            Parsed DeviceData from the API response.

        Raises:
            UpdateFailed: When all retries are exhausted or a non-transient error occurs.
        """
        try:
            data = await self._fetch_with_retries()
        except DeyeRateLimitError as err:
            # Handle rate limiting by adjusting next poll interval
            pause_seconds = self._get_rate_limit_pause(err.retry_after)
            _LOGGER.warning(
                "Rate limited for device %s, pausing for %ds",
                self.device_sn,
                pause_seconds,
            )
            # Schedule next update after the rate limit pause
            self.update_interval = timedelta(seconds=pause_seconds)
            self._record_failure()
            raise UpdateFailed(
                f"Rate limited, pausing for {pause_seconds}s"
            ) from err
        except DeyeAuthError as err:
            # Non-transient auth error - raise immediately
            self._record_failure()
            raise UpdateFailed(
                f"Authentication failed for device {self.device_sn}: {err}"
            ) from err
        except DeyeApiError as err:
            # Non-transient API error - raise immediately
            self._record_failure()
            raise UpdateFailed(
                f"API error for device {self.device_sn}: {err}"
            ) from err
        except UpdateFailed:
            # Retries exhausted from _fetch_with_retries
            self._record_failure()
            raise

        # Success - reset failure counter and any modified interval
        self._on_success()
        return data

    async def _fetch_with_retries(self) -> DeviceData:
        """Fetch device data with retry logic for transient errors.

        Retries up to COORDINATOR_MAX_RETRIES times with exponential backoff
        on DeyeTimeoutError and DeyeConnectionError.

        Returns:
            Parsed DeviceData from the API response.

        Raises:
            UpdateFailed: When all retries are exhausted.
            DeyeRateLimitError: On HTTP 429 (handled by caller).
            DeyeAuthError: On authentication failure (non-transient).
            DeyeApiError: On API errors (non-transient).
        """
        delay = COORDINATOR_INITIAL_DELAY_S
        last_error: Exception | None = None

        for attempt in range(COORDINATOR_MAX_RETRIES):
            try:
                raw = await self.api.get_device_latest(
                    self.device_sn, MEASURE_POINTS
                )
                return self._parse_device_data(raw)
            except (DeyeTimeoutError, DeyeConnectionError) as err:
                last_error = err
                if attempt < COORDINATOR_MAX_RETRIES - 1:
                    _LOGGER.debug(
                        "Transient error for device %s (attempt %d/%d), "
                        "retrying in %ds: %s",
                        self.device_sn,
                        attempt + 1,
                        COORDINATOR_MAX_RETRIES,
                        delay,
                        err,
                    )
                    await asyncio.sleep(delay)
                    delay = min(
                        delay * COORDINATOR_BACKOFF_MULTIPLIER,
                        COORDINATOR_MAX_DELAY_S,
                    )
                else:
                    _LOGGER.warning(
                        "All %d retries exhausted for device %s: %s",
                        COORDINATOR_MAX_RETRIES,
                        self.device_sn,
                        err,
                    )
            except (DeyeRateLimitError, DeyeAuthError, DeyeApiError):
                # Non-transient or special errors - don't retry, propagate
                raise

        raise UpdateFailed(
            f"Failed to fetch data for device {self.device_sn} after "
            f"{COORDINATOR_MAX_RETRIES} retries: {last_error}"
        )

    def _get_rate_limit_pause(self, retry_after: int | None) -> int:
        """Calculate the pause duration for rate limiting.

        Args:
            retry_after: The Retry-After header value in seconds, or None.

        Returns:
            The number of seconds to pause, capped at RATE_LIMIT_MAX_PAUSE_S.
        """
        if retry_after is not None:
            return min(retry_after, RATE_LIMIT_MAX_PAUSE_S)
        return RATE_LIMIT_DEFAULT_PAUSE_S

    def _record_failure(self) -> None:
        """Record a consecutive failure and create repair if threshold reached."""
        self._consecutive_failures += 1
        _LOGGER.debug(
            "Consecutive failure %d for device %s",
            self._consecutive_failures,
            self.device_sn,
        )
        if (
            self._consecutive_failures >= CONSECUTIVE_FAILURE_THRESHOLD
            and not self._repair_created
        ):
            self._create_repair_flow()

    def _on_success(self) -> None:
        """Handle successful data fetch - reset failure tracking."""
        if self._consecutive_failures > 0:
            _LOGGER.info(
                "Device %s recovered after %d consecutive failures",
                self.device_sn,
                self._consecutive_failures,
            )
        self._consecutive_failures = 0
        self._repair_created = False

    def _create_repair_flow(self) -> None:
        """Create a Repair Flow entry for persistent connectivity issues."""
        _LOGGER.warning(
            "Device %s has failed %d consecutive times, creating repair flow",
            self.device_sn,
            self._consecutive_failures,
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"persistent_failure_{self.device_sn}",
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="persistent_connectivity_failure",
            translation_placeholders={
                "device_sn": self.device_sn,
                "failure_count": str(self._consecutive_failures),
            },
        )
        self._repair_created = True

    def _parse_device_data(self, raw: dict[str, Any]) -> DeviceData:
        """Parse raw API response into a DeviceData model.

        The Deye API returns data as a flat key-value list in 'dataList'.
        We first convert it to a lookup dict, then map known keys to our model.

        Args:
            raw: The raw data dictionary from the API response (one device entry).

        Returns:
            A populated DeviceData instance.
        """
        # Convert flat dataList [{key, value, unit}, ...] into a lookup dict
        data_lookup: dict[str, str] = {}
        for item in raw.get("dataList", []):
            key = item.get("key", "")
            value = item.get("value", "")
            if key:
                data_lookup[key] = value

        # Device state: 1 = online
        is_online = raw.get("deviceState", 0) == 1
        collection_time = raw.get("collectionTime", 0)

        # Helper to get float from data_lookup
        def _val(key: str, default: float = 0.0) -> float:
            v = data_lookup.get(key)
            if v is None:
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        def _opt_val(key: str) -> float | None:
            v = data_lookup.get(key)
            if v is None:
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        # Parse MPPT channels from known keys (DCPowerPV1, DCVoltagePV1, DCCurrentPV1, etc.)
        pv_channels: list[MPPTChannelData] = []
        for ch in range(1, 5):  # Support up to 4 MPPT channels
            power_key = f"DCPowerPV{ch}"
            voltage_key = f"DCVoltagePV{ch}"
            current_key = f"DCCurrentPV{ch}"
            if power_key in data_lookup or voltage_key in data_lookup:
                pv_channels.append(
                    MPPTChannelData(
                        channel=ch,
                        power_w=_val(power_key),
                        voltage_v=_val(voltage_key),
                        current_a=_val(current_key),
                    )
                )

        # Parse grid phases (ACVoltageRUA, ACCurrentRUA, etc.)
        grid_phases: list[PhaseData] = []
        phase_labels = [("RUA", 1), ("SVB", 2), ("TWC", 3)]
        for label, phase_num in phase_labels:
            v_key = f"ACVoltage{label}"
            c_key = f"ACCurrent{label}"
            if v_key in data_lookup:
                grid_phases.append(
                    PhaseData(
                        phase=phase_num,
                        voltage_v=_val(v_key),
                        current_a=_val(c_key),
                        power_w=_val(f"InverterOutputPowerL{phase_num}L{phase_num}", 0.0),
                        frequency_hz=_val(f"ACOutputFrequency{label[0]}", _val("GridFrequency")),
                    )
                )

        # Parse last update time from collectionTime (unix timestamp)
        if collection_time:
            last_update_time = datetime.fromtimestamp(collection_time)
        else:
            last_update_time = datetime.now()

        return DeviceData(
            # PV
            pv_power_total_w=_val("TotalDCInputPower"),
            pv_daily_yield_kwh=_val("DailyActiveProduction"),
            pv_total_yield_kwh=_val("TotalActiveProduction"),
            pv_channels=pv_channels,
            # Battery
            battery_soc_pct=_opt_val("BatterySOC"),
            battery_power_w=_opt_val("BatteryPower"),
            battery_voltage_v=_opt_val("BatteryVoltage"),
            battery_current_a=_opt_val("BatteryCurrent"),
            battery_temperature_c=_opt_val("BatteryTemperature"),
            battery_daily_charge_kwh=_opt_val("DailyBatteryCharge"),
            battery_daily_discharge_kwh=_opt_val("DailyBatteryDischarge"),
            battery_total_charge_kwh=_opt_val("CumulativeBatteryCharge"),
            battery_total_discharge_kwh=_opt_val("CumulativeBatteryDischarge"),
            # Grid
            grid_import_power_w=_val("CumulativeEnergyPurchased", 0.0) if not data_lookup.get("TotalGridPower") else max(0.0, _val("TotalGridPower")),
            grid_export_power_w=max(0.0, -_val("TotalGridPower")) if _val("TotalGridPower") < 0 else 0.0,
            grid_daily_import_kwh=_val("DailyEnergyPurchased"),
            grid_daily_export_kwh=_val("DailyGridFeedIn"),
            grid_total_import_kwh=_val("CumulativeEnergyPurchased"),
            grid_total_export_kwh=_val("CumulativeGridFeedIn"),
            grid_frequency_hz=_val("GridFrequency", _val("ACOutputFrequencyR")),
            grid_phases=grid_phases,
            # Load
            load_power_w=_val("TotalConsumptionPower", _val("InverterOutputPowerL1L2")),
            load_daily_consumption_kwh=_val("DailyConsumption"),
            load_total_consumption_kwh=_val("CumulativeConsumption"),
            # Status
            is_online=is_online,
            last_update_time=last_update_time,
            active_alerts=[],
            # Configuration (may not be available from device/latest)
            work_mode=WorkMode.SELF_CONSUMPTION,
            energy_pattern=EnergyPattern.BATTERY_FIRST,
            battery_soc_min_setting=10,
            battery_soc_max_setting=100,
            battery_charge_current_setting=0.0,
            battery_discharge_current_setting=0.0,
            grid_export_limit_w=0,
            solar_sell_enabled=False,
            peak_shaving_enabled=False,
            peak_shaving_threshold_w=0,
            smart_load_states=[],
            tou_enabled=False,
            tou_slots=[],
        )


def _float(raw: dict[str, Any], *keys: str) -> float:
    """Extract a float value from the raw dict, trying multiple key names.

    Args:
        raw: The raw data dictionary.
        *keys: Key names to try in order.

    Returns:
        The float value, or 0.0 if not found.
    """
    for key in keys:
        value = raw.get(key)
        if value is not None:
            try:
                return float(value)
            except (ValueError, TypeError):
                continue
    return 0.0


def _optional_float(raw: dict[str, Any], *keys: str) -> float | None:
    """Extract an optional float value from the raw dict.

    Args:
        raw: The raw data dictionary.
        *keys: Key names to try in order.

    Returns:
        The float value, or None if not found or all values are None.
    """
    for key in keys:
        value = raw.get(key)
        if value is not None:
            try:
                return float(value)
            except (ValueError, TypeError):
                continue
    return None
