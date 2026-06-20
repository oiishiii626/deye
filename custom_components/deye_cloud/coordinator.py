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

        Args:
            raw: The raw data dictionary from the API response.

        Returns:
            A populated DeviceData instance.
        """
        # Parse MPPT channel data
        pv_channels: list[MPPTChannelData] = []
        raw_channels = raw.get("pv_channels") or raw.get("pvChannels") or []
        for ch in raw_channels:
            pv_channels.append(
                MPPTChannelData(
                    channel=int(ch.get("channel", 0)),
                    power_w=float(ch.get("power", ch.get("powerW", 0.0))),
                    voltage_v=float(ch.get("voltage", ch.get("voltageV", 0.0))),
                    current_a=float(ch.get("current", ch.get("currentA", 0.0))),
                )
            )

        # Parse grid phase data
        grid_phases: list[PhaseData] = []
        raw_phases = raw.get("grid_phases") or raw.get("gridPhases") or []
        for ph in raw_phases:
            grid_phases.append(
                PhaseData(
                    phase=int(ph.get("phase", 0)),
                    voltage_v=float(ph.get("voltage", ph.get("voltageV", 0.0))),
                    current_a=float(ph.get("current", ph.get("currentA", 0.0))),
                    power_w=float(ph.get("power", ph.get("powerW", 0.0))),
                    frequency_hz=float(
                        ph.get("frequency", ph.get("frequencyHz", 0.0))
                    ),
                )
            )

        # Parse active alerts
        active_alerts: list[AlertData] = []
        raw_alerts = raw.get("active_alerts") or raw.get("activeAlerts") or []
        for alert in raw_alerts:
            timestamp_raw = alert.get("timestamp", "")
            try:
                timestamp = datetime.fromisoformat(str(timestamp_raw))
            except (ValueError, TypeError):
                timestamp = datetime.now()

            active_alerts.append(
                AlertData(
                    alert_type=str(alert.get("alertType", alert.get("type", ""))),
                    severity=str(alert.get("severity", "info")),
                    timestamp=timestamp,
                    message=str(alert.get("message", "")),
                    is_active=bool(alert.get("isActive", True)),
                )
            )

        # Parse smart load states
        raw_smart_loads = raw.get("smart_load_states") or raw.get("smartLoadStates") or []
        smart_load_states: list[bool] = [bool(s) for s in raw_smart_loads]

        # Parse TOU slots
        tou_slots: list[TOUSlotData] = []
        raw_tou = raw.get("tou_slots") or raw.get("touSlots") or []
        for slot in raw_tou:
            try:
                mode = TOUSlotMode(str(slot.get("mode", "disabled")))
            except ValueError:
                mode = TOUSlotMode.DISABLED
            tou_slots.append(
                TOUSlotData(
                    slot_index=int(slot.get("slotIndex", slot.get("slot_index", 0))),
                    start_time=str(slot.get("startTime", slot.get("start_time", "00:00"))),
                    end_time=str(slot.get("endTime", slot.get("end_time", "00:00"))),
                    mode=mode,
                    power_limit_w=int(slot.get("powerLimitW", slot.get("power_limit_w", 0))),
                )
            )

        # Parse last update time
        last_update_raw = raw.get("last_update_time") or raw.get("lastUpdateTime")
        if last_update_raw:
            try:
                last_update_time = datetime.fromisoformat(str(last_update_raw))
            except (ValueError, TypeError):
                last_update_time = datetime.now()
        else:
            last_update_time = datetime.now()

        # Parse work mode
        work_mode_raw = raw.get("work_mode") or raw.get("workMode")
        try:
            work_mode = WorkMode(int(work_mode_raw)) if work_mode_raw is not None else WorkMode.SELF_CONSUMPTION
        except (ValueError, TypeError):
            work_mode = WorkMode.SELF_CONSUMPTION

        # Parse energy pattern
        energy_pattern_raw = raw.get("energy_pattern") or raw.get("energyPattern")
        try:
            energy_pattern = EnergyPattern(int(energy_pattern_raw)) if energy_pattern_raw is not None else EnergyPattern.BATTERY_FIRST
        except (ValueError, TypeError):
            energy_pattern = EnergyPattern.BATTERY_FIRST

        return DeviceData(
            # PV
            pv_power_total_w=_float(raw, "pv_power_total", "pvPowerTotal"),
            pv_daily_yield_kwh=_float(raw, "pv_daily_yield", "pvDailyYield"),
            pv_total_yield_kwh=_float(raw, "pv_total_yield", "pvTotalYield"),
            pv_channels=pv_channels,
            # Battery
            battery_soc_pct=_optional_float(raw, "battery_soc", "batterySoc"),
            battery_power_w=_optional_float(raw, "battery_power", "batteryPower"),
            battery_voltage_v=_optional_float(raw, "battery_voltage", "batteryVoltage"),
            battery_current_a=_optional_float(raw, "battery_current", "batteryCurrent"),
            battery_temperature_c=_optional_float(raw, "battery_temperature", "batteryTemperature"),
            battery_daily_charge_kwh=_optional_float(raw, "battery_daily_charge", "batteryDailyCharge"),
            battery_daily_discharge_kwh=_optional_float(raw, "battery_daily_discharge", "batteryDailyDischarge"),
            battery_total_charge_kwh=_optional_float(raw, "battery_total_charge", "batteryTotalCharge"),
            battery_total_discharge_kwh=_optional_float(raw, "battery_total_discharge", "batteryTotalDischarge"),
            # Grid
            grid_import_power_w=_float(raw, "grid_import_power", "gridImportPower"),
            grid_export_power_w=_float(raw, "grid_export_power", "gridExportPower"),
            grid_daily_import_kwh=_float(raw, "grid_daily_import", "gridDailyImport"),
            grid_daily_export_kwh=_float(raw, "grid_daily_export", "gridDailyExport"),
            grid_total_import_kwh=_float(raw, "grid_total_import", "gridTotalImport"),
            grid_total_export_kwh=_float(raw, "grid_total_export", "gridTotalExport"),
            grid_frequency_hz=_float(raw, "grid_frequency", "gridFrequency"),
            grid_phases=grid_phases,
            # Load
            load_power_w=_float(raw, "load_power", "loadPower"),
            load_daily_consumption_kwh=_float(raw, "load_daily_consumption", "loadDailyConsumption"),
            load_total_consumption_kwh=_float(raw, "load_total_consumption", "loadTotalConsumption"),
            # Status
            is_online=bool(raw.get("is_online", raw.get("isOnline", True))),
            last_update_time=last_update_time,
            active_alerts=active_alerts,
            # Configuration readback
            work_mode=work_mode,
            energy_pattern=energy_pattern,
            battery_soc_min_setting=int(
                raw.get("battery_soc_min", raw.get("batterySocMin", 10))
            ),
            battery_soc_max_setting=int(
                raw.get("battery_soc_max", raw.get("batterySocMax", 100))
            ),
            battery_charge_current_setting=float(
                raw.get("battery_charge_current_max", raw.get("batteryChargeCurrentMax", 0.0))
            ),
            battery_discharge_current_setting=float(
                raw.get("battery_discharge_current_max", raw.get("batteryDischargeCurrentMax", 0.0))
            ),
            grid_export_limit_w=int(
                raw.get("grid_export_limit", raw.get("gridExportLimit", 0))
            ),
            solar_sell_enabled=bool(
                raw.get("solar_sell_enabled", raw.get("solarSellEnabled", False))
            ),
            peak_shaving_enabled=bool(
                raw.get("peak_shaving_enabled", raw.get("peakShavingEnabled", False))
            ),
            peak_shaving_threshold_w=int(
                raw.get("peak_shaving_threshold", raw.get("peakShavingThreshold", 0))
            ),
            smart_load_states=smart_load_states,
            tou_enabled=bool(raw.get("tou_enabled", raw.get("touEnabled", False))),
            tou_slots=tou_slots,
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
