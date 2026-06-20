"""TariffManager for automated tariff-based inverter mode switching."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from .api import DeyeCloudAPI
from .const import (
    DOMAIN,
    MAX_TARIFF_PERIODS,
    TARIFF_MODE_SWITCH_DELAY_S,
    TARIFF_MODE_SWITCH_MAX_RETRIES,
)
from .helpers import check_time_periods_overlap, validate_time_format
from .models import TariffCategory, TariffConfig, TariffPeriod, WorkMode

_LOGGER = logging.getLogger(__name__)

# Work modes used for tariff transitions
_GRID_CHARGING_MODE = WorkMode.TIME_OF_USE
_BATTERY_DISCHARGE_MODE = WorkMode.SELLING_FIRST


class TariffValidationError(Exception):
    """Raised when tariff configuration is invalid."""


class TariffManager:
    """Manages tariff-based automation for a single inverter.

    Listens to time events and triggers inverter mode switches based on
    user-defined tariff periods. On cheap-rate entry switches to grid-charging,
    on peak-rate entry switches to battery-discharge, and on standard-rate
    entry restores the user-configured default work mode.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: DeyeCloudAPI,
        device_sn: str,
        config: TariffConfig,
    ) -> None:
        """Initialize TariffManager.

        Args:
            hass: The Home Assistant instance.
            api: The Deye Cloud API client.
            device_sn: The inverter serial number.
            config: The tariff configuration.

        Raises:
            TariffValidationError: If the configuration is invalid.
        """
        self._hass = hass
        self._api = api
        self._device_sn = device_sn
        self._config = config
        self._listeners: list[Any] = []
        self._current_category: TariffCategory | None = None
        self._running = False

        # Validate configuration on init
        self._validate_config(config)

    @property
    def device_sn(self) -> str:
        """Return the device serial number."""
        return self._device_sn

    @property
    def config(self) -> TariffConfig:
        """Return the current tariff configuration."""
        return self._config

    @property
    def current_category(self) -> TariffCategory | None:
        """Return the current active tariff category."""
        return self._current_category

    @property
    def is_running(self) -> bool:
        """Return whether the manager is actively listening."""
        return self._running

    def _validate_config(self, config: TariffConfig) -> None:
        """Validate tariff configuration.

        Checks:
        - Maximum 10 periods
        - No overlapping periods
        - Valid time formats

        Args:
            config: The tariff configuration to validate.

        Raises:
            TariffValidationError: If validation fails.
        """
        if len(config.periods) > MAX_TARIFF_PERIODS:
            raise TariffValidationError(
                f"Too many tariff periods: {len(config.periods)} "
                f"(maximum {MAX_TARIFF_PERIODS})"
            )

        # Validate time formats
        for period in config.periods:
            if not validate_time_format(period.start_time):
                raise TariffValidationError(
                    f"Invalid start time format: '{period.start_time}'. "
                    f"Expected HH:MM."
                )
            if not validate_time_format(period.end_time):
                raise TariffValidationError(
                    f"Invalid end time format: '{period.end_time}'. "
                    f"Expected HH:MM."
                )

        # Check for overlaps
        if config.periods:
            period_tuples = [
                (p.start_time, p.end_time) for p in config.periods
            ]
            if check_time_periods_overlap(period_tuples):
                raise TariffValidationError(
                    "Tariff periods contain overlapping time ranges"
                )

    async def async_start(self) -> None:
        """Register time-based listeners for all configured period transitions.

        Sets up listeners that fire at the start time of each tariff period.
        Also determines the current active period on start.
        """
        if self._running:
            return

        if not self._config.enabled:
            _LOGGER.debug(
                "Tariff automation disabled for device %s, not starting",
                self._device_sn,
            )
            return

        # Register time-based listeners for each period start
        for period in self._config.periods:
            hour, minute = self._parse_time(period.start_time)
            unsub = async_track_time_change(
                self._hass,
                self._create_period_callback(period),
                hour=hour,
                minute=minute,
                second=0,
            )
            self._listeners.append(unsub)

        # Determine current active period
        self._current_category = self._get_current_category()
        self._running = True

        _LOGGER.info(
            "TariffManager started for device %s with %d periods, "
            "current category: %s",
            self._device_sn,
            len(self._config.periods),
            self._current_category,
        )

    async def async_stop(self) -> None:
        """Remove all listeners and stop the manager."""
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()
        self._running = False

        _LOGGER.info(
            "TariffManager stopped for device %s", self._device_sn
        )

    def _create_period_callback(self, period: TariffPeriod):
        """Create a callback for a specific period transition.

        Args:
            period: The tariff period that triggers this callback.

        Returns:
            An async callback function for the time listener.
        """

        @callback
        def _time_listener(now: datetime) -> None:
            """Handle time event for period transition."""
            self._hass.async_create_task(
                self._handle_period_transition(period)
            )

        return _time_listener

    async def _handle_period_transition(self, new_period: TariffPeriod) -> None:
        """Switch inverter mode for the new tariff period.

        Fires an HA event with transition details and applies the
        appropriate work mode based on the period category.

        Args:
            new_period: The new tariff period being entered.
        """
        previous_category = self._current_category
        new_category = new_period.category
        self._current_category = new_category
        timestamp = datetime.now().isoformat()

        # Fire HA event for the transition
        self._hass.bus.async_fire(
            "deye_cloud_tariff_transition",
            {
                "device_id": self._device_sn,
                "previous_category": str(previous_category) if previous_category else None,
                "new_category": str(new_category),
                "timestamp": timestamp,
            },
        )

        _LOGGER.info(
            "Tariff transition for device %s: %s → %s",
            self._device_sn,
            previous_category,
            new_category,
        )

        # Apply the mode switch based on category
        success = await self._apply_mode_with_retry(new_category)
        if not success:
            _LOGGER.error(
                "Failed to apply tariff mode switch for device %s "
                "after %d retries (category: %s)",
                self._device_sn,
                TARIFF_MODE_SWITCH_MAX_RETRIES,
                new_category,
            )
            # Raise persistent notification on exhaustion
            self._hass.components.persistent_notification.async_create(
                title="Deye Cloud: Tariff Mode Switch Failed",
                message=(
                    f"Failed to switch inverter {self._device_sn} to "
                    f"{new_category} mode after {TARIFF_MODE_SWITCH_MAX_RETRIES} "
                    f"retries. Please check the inverter connection and try "
                    f"manually switching the work mode."
                ),
                notification_id=f"deye_tariff_failure_{self._device_sn}",
            )

    async def _apply_mode_with_retry(self, category: TariffCategory) -> bool:
        """Apply mode switch with retry logic.

        Retries failed mode switches up to TARIFF_MODE_SWITCH_MAX_RETRIES
        times at TARIFF_MODE_SWITCH_DELAY_S intervals.

        Args:
            category: The tariff category to switch to.

        Returns:
            True if the mode switch succeeded, False if all retries exhausted.
        """
        for attempt in range(TARIFF_MODE_SWITCH_MAX_RETRIES):
            try:
                await self._apply_mode(category)
                return True
            except Exception as err:  # noqa: BLE001
                if attempt < TARIFF_MODE_SWITCH_MAX_RETRIES - 1:
                    _LOGGER.warning(
                        "Mode switch attempt %d/%d failed for device %s "
                        "(category: %s): %s. Retrying in %ds...",
                        attempt + 1,
                        TARIFF_MODE_SWITCH_MAX_RETRIES,
                        self._device_sn,
                        category,
                        err,
                        TARIFF_MODE_SWITCH_DELAY_S,
                    )
                    await asyncio.sleep(TARIFF_MODE_SWITCH_DELAY_S)
                else:
                    _LOGGER.error(
                        "Mode switch attempt %d/%d failed for device %s "
                        "(category: %s): %s. All retries exhausted.",
                        attempt + 1,
                        TARIFF_MODE_SWITCH_MAX_RETRIES,
                        self._device_sn,
                        category,
                        err,
                    )
        return False

    async def _apply_mode(self, category: TariffCategory) -> None:
        """Apply the work mode for a given tariff category.

        Args:
            category: The tariff category.

        Raises:
            Exception: If the API call fails.
        """
        if category == TariffCategory.CHEAP:
            # Switch to grid-charging mode at max charge current
            await self._api.set_work_mode(
                self._device_sn, _GRID_CHARGING_MODE.value
            )
            await self._api.set_device_config(
                self._device_sn,
                {"batteryChargeCurrent": self._config.charge_current},
            )
            _LOGGER.debug(
                "Applied CHEAP mode for device %s: work_mode=%s, "
                "charge_current=%s",
                self._device_sn,
                _GRID_CHARGING_MODE.name,
                self._config.charge_current,
            )

        elif category == TariffCategory.PEAK:
            # Switch to battery-discharge mode at max discharge current
            await self._api.set_work_mode(
                self._device_sn, _BATTERY_DISCHARGE_MODE.value
            )
            await self._api.set_device_config(
                self._device_sn,
                {"batteryDischargeCurrent": self._config.discharge_current},
            )
            _LOGGER.debug(
                "Applied PEAK mode for device %s: work_mode=%s, "
                "discharge_current=%s",
                self._device_sn,
                _BATTERY_DISCHARGE_MODE.name,
                self._config.discharge_current,
            )

        elif category == TariffCategory.STANDARD:
            # Restore user-configured default work mode
            await self._api.set_work_mode(
                self._device_sn, self._config.default_work_mode.value
            )
            _LOGGER.debug(
                "Applied STANDARD mode for device %s: restored default "
                "work_mode=%s",
                self._device_sn,
                self._config.default_work_mode.name,
            )

    def _get_current_category(self) -> TariffCategory | None:
        """Determine the current active tariff category based on current time.

        Returns:
            The current TariffCategory, or None if not in any defined period.
        """
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute

        for period in self._config.periods:
            start_minutes = self._time_to_minutes(period.start_time)
            end_minutes = self._time_to_minutes(period.end_time)

            # Only handle non-wrapping periods (end > start)
            if end_minutes > start_minutes:
                if start_minutes <= current_minutes < end_minutes:
                    return period.category

        return None

    @staticmethod
    def _parse_time(time_str: str) -> tuple[int, int]:
        """Parse a HH:MM time string into hour and minute.

        Args:
            time_str: A valid HH:MM time string.

        Returns:
            Tuple of (hour, minute).
        """
        parts = time_str.split(":")
        return int(parts[0]), int(parts[1])

    @staticmethod
    def _time_to_minutes(time_str: str) -> int:
        """Convert a HH:MM time string to minutes since midnight.

        Args:
            time_str: A valid HH:MM time string.

        Returns:
            Minutes since midnight.
        """
        parts = time_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])
