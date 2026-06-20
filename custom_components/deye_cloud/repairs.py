"""Repair flow handlers for the Deye Cloud integration.

Manages creation, tracking, and auto-dismissal of HA repair issues
for various error conditions detected during polling.

Trigger conditions:
- Invalid credentials (after token refresh fails)
- 5+ consecutive polling failures
- Inverter offline > 1 hour
- Firmware update reported by the API

Each repair includes a problem description, actionable resolution step,
and verification reference. Auto-dismisses when condition clears within
2 polling cycles. Deduplicates via unique issue_id per condition per device.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Number of consecutive clear polls required before auto-dismissing a repair
AUTO_DISMISS_CLEAR_CYCLES = 2

# Duration threshold for inverter offline condition
OFFLINE_THRESHOLD = timedelta(hours=1)


class RepairCondition(StrEnum):
    """Repair condition identifiers."""

    INVALID_CREDENTIALS = "invalid_credentials"
    CONSECUTIVE_FAILURES = "consecutive_failures"
    INVERTER_OFFLINE = "inverter_offline"
    FIRMWARE_UPDATE = "firmware_update"


@dataclass
class RepairState:
    """Tracks the state of a single repair condition for a device."""

    condition: RepairCondition
    device_sn: str
    is_active: bool = False
    clear_counter: int = 0
    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def issue_id(self) -> str:
        """Generate the unique issue_id for this repair."""
        return f"{self.condition}_{self.device_sn}"


class DeyeRepairManager:
    """Manages repair flow issues for a single Deye inverter device.

    Tracks conditions that should trigger HA repair issues, handles
    deduplication (one repair per condition per device), and auto-dismisses
    when the condition clears for 2 consecutive polling cycles.
    """

    def __init__(self, hass: HomeAssistant, device_sn: str) -> None:
        """Initialize the repair manager.

        Args:
            hass: The Home Assistant instance.
            device_sn: The device serial number this manager tracks.
        """
        self.hass = hass
        self.device_sn = device_sn
        self._repairs: dict[RepairCondition, RepairState] = {}
        self._offline_since: datetime | None = None

    def report_invalid_credentials(self) -> None:
        """Report that credentials are invalid (token refresh exhausted).

        Creates a repair suggesting the user re-enter credentials
        in the integration config flow.
        """
        self._create_or_refresh_repair(
            condition=RepairCondition.INVALID_CREDENTIALS,
            severity=ir.IssueSeverity.ERROR,
            translation_key="invalid_credentials",
            translation_placeholders={
                "device_sn": self.device_sn,
            },
        )

    def report_consecutive_failures(self, failure_count: int) -> None:
        """Report 5+ consecutive polling failures.

        Args:
            failure_count: The current number of consecutive failures.
        """
        self._create_or_refresh_repair(
            condition=RepairCondition.CONSECUTIVE_FAILURES,
            severity=ir.IssueSeverity.ERROR,
            translation_key="consecutive_poll_failures",
            translation_placeholders={
                "device_sn": self.device_sn,
                "failure_count": str(failure_count),
            },
        )

    def report_inverter_offline(self, offline_since: datetime) -> None:
        """Report that the inverter has been offline for more than 1 hour.

        Args:
            offline_since: When the inverter first went offline.
        """
        self._create_or_refresh_repair(
            condition=RepairCondition.INVERTER_OFFLINE,
            severity=ir.IssueSeverity.WARNING,
            translation_key="inverter_offline",
            translation_placeholders={
                "device_sn": self.device_sn,
                "offline_since": offline_since.isoformat(),
            },
        )

    def report_firmware_update(self, current_version: str = "") -> None:
        """Report that a firmware update is available.

        Args:
            current_version: The current firmware version string.
        """
        self._create_or_refresh_repair(
            condition=RepairCondition.FIRMWARE_UPDATE,
            severity=ir.IssueSeverity.WARNING,
            translation_key="firmware_update_available",
            translation_placeholders={
                "device_sn": self.device_sn,
                "current_version": current_version,
            },
        )

    def clear_condition(self, condition: RepairCondition) -> None:
        """Signal that a condition is no longer present.

        Increments the clear counter. If the condition has been clear
        for AUTO_DISMISS_CLEAR_CYCLES consecutive calls, the repair
        is dismissed.

        Args:
            condition: The repair condition that has cleared.
        """
        state = self._repairs.get(condition)
        if state is None or not state.is_active:
            return

        state.clear_counter += 1
        _LOGGER.debug(
            "Condition %s for device %s clear count: %d/%d",
            condition,
            self.device_sn,
            state.clear_counter,
            AUTO_DISMISS_CLEAR_CYCLES,
        )

        if state.clear_counter >= AUTO_DISMISS_CLEAR_CYCLES:
            self._dismiss_repair(condition)

    def check_offline_status(
        self, is_online: bool, now: datetime | None = None
    ) -> None:
        """Check inverter online/offline status and manage repair accordingly.

        Should be called every polling cycle with the current online status.

        Args:
            is_online: Whether the inverter is currently online.
            now: Current timestamp (defaults to utcnow if not provided).
        """
        if now is None:
            now = datetime.now(UTC)

        if is_online:
            # Inverter is back online
            self._offline_since = None
            self.clear_condition(RepairCondition.INVERTER_OFFLINE)
        else:
            # Inverter is offline
            if self._offline_since is None:
                self._offline_since = now

            offline_duration = now - self._offline_since
            if offline_duration >= OFFLINE_THRESHOLD:
                self.report_inverter_offline(self._offline_since)

    def check_consecutive_failures(self, failure_count: int) -> None:
        """Check consecutive failure count and manage repair accordingly.

        Args:
            failure_count: Current consecutive failure count.
        """
        from .const import CONSECUTIVE_FAILURE_THRESHOLD

        if failure_count >= CONSECUTIVE_FAILURE_THRESHOLD:
            self.report_consecutive_failures(failure_count)
        else:
            self.clear_condition(RepairCondition.CONSECUTIVE_FAILURES)

    def check_credentials_valid(self, is_valid: bool) -> None:
        """Check credential validity and manage repair accordingly.

        Args:
            is_valid: Whether credentials are currently valid.
        """
        if not is_valid:
            self.report_invalid_credentials()
        else:
            self.clear_condition(RepairCondition.INVALID_CREDENTIALS)

    def check_firmware_update(
        self, has_update: bool, current_version: str = ""
    ) -> None:
        """Check firmware update status and manage repair accordingly.

        Args:
            has_update: Whether a firmware update is available.
            current_version: The current firmware version.
        """
        if has_update:
            self.report_firmware_update(current_version)
        else:
            self.clear_condition(RepairCondition.FIRMWARE_UPDATE)

    def get_active_repairs(self) -> list[RepairState]:
        """Return all currently active repair states."""
        return [s for s in self._repairs.values() if s.is_active]

    def _create_or_refresh_repair(
        self,
        condition: RepairCondition,
        severity: str,
        translation_key: str,
        translation_placeholders: dict[str, str],
    ) -> None:
        """Create a new repair issue or refresh an existing one.

        Deduplicates: only one repair per condition per device at a time.
        Resets the clear counter when the condition reappears.

        Args:
            condition: The repair condition type.
            severity: Issue severity level.
            translation_key: Translation key for the repair description.
            translation_placeholders: Placeholder values for the translation.
        """
        state = self._repairs.get(condition)

        if state is None:
            state = RepairState(
                condition=condition,
                device_sn=self.device_sn,
            )
            self._repairs[condition] = state

        # Reset clear counter since the condition is present
        state.clear_counter = 0

        if not state.is_active:
            # Create the repair issue
            state.is_active = True
            state.created_at = datetime.now(UTC)
            _LOGGER.warning(
                "Creating repair issue for condition %s on device %s",
                condition,
                self.device_sn,
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                state.issue_id,
                is_fixable=True,
                is_persistent=True,
                severity=severity,
                translation_key=translation_key,
                translation_placeholders=translation_placeholders,
            )

    def _dismiss_repair(self, condition: RepairCondition) -> None:
        """Dismiss an active repair issue.

        Args:
            condition: The repair condition to dismiss.
        """
        state = self._repairs.get(condition)
        if state is None:
            return

        if state.is_active:
            _LOGGER.info(
                "Dismissing repair issue for condition %s on device %s "
                "(cleared for %d cycles)",
                condition,
                self.device_sn,
                state.clear_counter,
            )
            ir.async_delete_issue(self.hass, DOMAIN, state.issue_id)
            state.is_active = False
            state.clear_counter = 0
            state.created_at = None
