"""Tests for the Deye Cloud repair flow handlers."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from custom_components.deye_cloud.repairs import (
    AUTO_DISMISS_CLEAR_CYCLES,
    OFFLINE_THRESHOLD,
    DeyeRepairManager,
    RepairCondition,
    RepairState,
)
from custom_components.deye_cloud.const import CONSECUTIVE_FAILURE_THRESHOLD, DOMAIN


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return MagicMock()


@pytest.fixture
def repair_manager(mock_hass):
    """Create a DeyeRepairManager for testing."""
    return DeyeRepairManager(hass=mock_hass, device_sn="TEST_SN_001")


class TestRepairState:
    """Tests for RepairState dataclass."""

    def test_issue_id_format(self):
        """Issue ID follows {condition}_{device_sn} pattern."""
        state = RepairState(
            condition=RepairCondition.INVALID_CREDENTIALS,
            device_sn="SN123",
        )
        assert state.issue_id == "invalid_credentials_SN123"

    def test_issue_id_consecutive_failures(self):
        """Issue ID for consecutive failures condition."""
        state = RepairState(
            condition=RepairCondition.CONSECUTIVE_FAILURES,
            device_sn="INV456",
        )
        assert state.issue_id == "consecutive_failures_INV456"

    def test_issue_id_inverter_offline(self):
        """Issue ID for inverter offline condition."""
        state = RepairState(
            condition=RepairCondition.INVERTER_OFFLINE,
            device_sn="DEV789",
        )
        assert state.issue_id == "inverter_offline_DEV789"

    def test_issue_id_firmware_update(self):
        """Issue ID for firmware update condition."""
        state = RepairState(
            condition=RepairCondition.FIRMWARE_UPDATE,
            device_sn="FW001",
        )
        assert state.issue_id == "firmware_update_FW001"


class TestInvalidCredentials:
    """Tests for invalid credentials repair flow."""

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_creates_repair_on_invalid_credentials(self, mock_ir, mock_hass):
        """Repair is created when credentials are invalid."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.ERROR = "error"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN001")

        manager.report_invalid_credentials()

        mock_ir.async_create_issue.assert_called_once_with(
            mock_hass,
            DOMAIN,
            "invalid_credentials_SN001",
            is_fixable=True,
            is_persistent=True,
            severity="error",
            translation_key="invalid_credentials",
            translation_placeholders={
                "device_sn": "SN001",
            },
        )

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_deduplicates_invalid_credentials(self, mock_ir, mock_hass):
        """Only one repair is created for repeated invalid credential reports."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.ERROR = "error"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN001")

        manager.report_invalid_credentials()
        manager.report_invalid_credentials()
        manager.report_invalid_credentials()

        # Should only create once
        assert mock_ir.async_create_issue.call_count == 1

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_check_credentials_valid_clears(self, mock_ir, mock_hass):
        """Credentials becoming valid increments clear counter."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.ERROR = "error"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN001")

        manager.report_invalid_credentials()
        manager.check_credentials_valid(is_valid=True)
        manager.check_credentials_valid(is_valid=True)

        mock_ir.async_delete_issue.assert_called_once_with(
            mock_hass, DOMAIN, "invalid_credentials_SN001"
        )


class TestConsecutiveFailures:
    """Tests for consecutive polling failures repair flow."""

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_creates_repair_at_threshold(self, mock_ir, mock_hass):
        """Repair is created when failure count reaches threshold."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.ERROR = "error"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN002")

        manager.check_consecutive_failures(CONSECUTIVE_FAILURE_THRESHOLD)

        mock_ir.async_create_issue.assert_called_once()
        call_kwargs = mock_ir.async_create_issue.call_args[1]
        assert call_kwargs["translation_key"] == "consecutive_poll_failures"
        assert call_kwargs["translation_placeholders"]["failure_count"] == str(
            CONSECUTIVE_FAILURE_THRESHOLD
        )

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_no_repair_below_threshold(self, mock_ir, mock_hass):
        """No repair is created below the failure threshold."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.ERROR = "error"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN002")

        manager.check_consecutive_failures(CONSECUTIVE_FAILURE_THRESHOLD - 1)

        mock_ir.async_create_issue.assert_not_called()

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_clears_when_failures_drop(self, mock_ir, mock_hass):
        """Repair is dismissed when failures drop below threshold."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.ERROR = "error"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN002")

        # Create repair
        manager.check_consecutive_failures(CONSECUTIVE_FAILURE_THRESHOLD)

        # Clear condition for 2 cycles
        manager.check_consecutive_failures(0)
        manager.check_consecutive_failures(0)

        mock_ir.async_delete_issue.assert_called_once_with(
            mock_hass, DOMAIN, "consecutive_failures_SN002"
        )


class TestInverterOffline:
    """Tests for inverter offline > 1 hour repair flow."""

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_no_repair_for_short_offline(self, mock_ir, mock_hass):
        """No repair when offline duration is less than 1 hour."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.WARNING = "warning"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN003")

        now = datetime(2024, 1, 1, 12, 0, 0)
        # First report offline
        manager.check_offline_status(is_online=False, now=now)

        # 30 minutes later
        later = now + timedelta(minutes=30)
        manager.check_offline_status(is_online=False, now=later)

        mock_ir.async_create_issue.assert_not_called()

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_creates_repair_after_1_hour_offline(self, mock_ir, mock_hass):
        """Repair is created when inverter is offline for more than 1 hour."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.WARNING = "warning"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN003")

        now = datetime(2024, 1, 1, 12, 0, 0)
        manager.check_offline_status(is_online=False, now=now)

        # 61 minutes later - exceeds threshold
        later = now + timedelta(minutes=61)
        manager.check_offline_status(is_online=False, now=later)

        mock_ir.async_create_issue.assert_called_once()
        call_kwargs = mock_ir.async_create_issue.call_args[1]
        assert call_kwargs["translation_key"] == "inverter_offline"

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_dismisses_when_back_online(self, mock_ir, mock_hass):
        """Repair is dismissed when inverter comes back online."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.WARNING = "warning"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN003")

        now = datetime(2024, 1, 1, 12, 0, 0)
        manager.check_offline_status(is_online=False, now=now)

        # 2 hours later - repair should be created
        later = now + timedelta(hours=2)
        manager.check_offline_status(is_online=False, now=later)

        assert mock_ir.async_create_issue.call_count == 1

        # Back online - need 2 clear cycles
        manager.check_offline_status(is_online=True, now=later + timedelta(minutes=1))
        manager.check_offline_status(is_online=True, now=later + timedelta(minutes=2))

        mock_ir.async_delete_issue.assert_called_once_with(
            mock_hass, DOMAIN, "inverter_offline_SN003"
        )

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_resets_offline_timer_when_online(self, mock_ir, mock_hass):
        """Offline timer resets when inverter goes back online briefly."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.WARNING = "warning"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN003")

        now = datetime(2024, 1, 1, 12, 0, 0)
        # Offline for 50 minutes
        manager.check_offline_status(is_online=False, now=now)
        manager.check_offline_status(
            is_online=False, now=now + timedelta(minutes=50)
        )

        # Comes back online
        manager.check_offline_status(
            is_online=True, now=now + timedelta(minutes=51)
        )

        # Goes offline again
        new_offline_start = now + timedelta(minutes=52)
        manager.check_offline_status(is_online=False, now=new_offline_start)

        # 30 minutes of new offline period - should not trigger
        manager.check_offline_status(
            is_online=False, now=new_offline_start + timedelta(minutes=30)
        )

        mock_ir.async_create_issue.assert_not_called()


class TestFirmwareUpdate:
    """Tests for firmware update available repair flow."""

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_creates_repair_for_firmware_update(self, mock_ir, mock_hass):
        """Repair is created when firmware update is reported."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.WARNING = "warning"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN004")

        manager.check_firmware_update(has_update=True, current_version="1.2.3")

        mock_ir.async_create_issue.assert_called_once()
        call_kwargs = mock_ir.async_create_issue.call_args[1]
        assert call_kwargs["translation_key"] == "firmware_update_available"
        assert call_kwargs["translation_placeholders"]["current_version"] == "1.2.3"

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_no_repair_when_no_update(self, mock_ir, mock_hass):
        """No repair when no firmware update is available."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.WARNING = "warning"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN004")

        manager.check_firmware_update(has_update=False, current_version="1.2.3")

        mock_ir.async_create_issue.assert_not_called()

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_dismisses_after_firmware_updated(self, mock_ir, mock_hass):
        """Repair is dismissed when firmware update no longer reported."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.WARNING = "warning"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN004")

        # Report firmware update
        manager.check_firmware_update(has_update=True, current_version="1.2.3")

        # 2 cycles with no update available
        manager.check_firmware_update(has_update=False, current_version="1.3.0")
        manager.check_firmware_update(has_update=False, current_version="1.3.0")

        mock_ir.async_delete_issue.assert_called_once_with(
            mock_hass, DOMAIN, "firmware_update_SN004"
        )


class TestAutoDismissal:
    """Tests for auto-dismissal behavior."""

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_requires_2_clear_cycles(self, mock_ir, mock_hass):
        """Repair requires exactly 2 clear cycles before dismissal."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.ERROR = "error"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN005")

        manager.report_invalid_credentials()

        # 1 clear cycle - not enough
        manager.clear_condition(RepairCondition.INVALID_CREDENTIALS)
        mock_ir.async_delete_issue.assert_not_called()

        # 2nd clear cycle - should dismiss
        manager.clear_condition(RepairCondition.INVALID_CREDENTIALS)
        mock_ir.async_delete_issue.assert_called_once()

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_clear_counter_resets_on_recurrence(self, mock_ir, mock_hass):
        """Clear counter resets if condition reappears before dismissal."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.ERROR = "error"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN005")

        manager.report_invalid_credentials()

        # 1 clear cycle
        manager.clear_condition(RepairCondition.INVALID_CREDENTIALS)

        # Condition reappears - resets counter
        manager.report_invalid_credentials()

        # 1 clear cycle again - not enough
        manager.clear_condition(RepairCondition.INVALID_CREDENTIALS)
        mock_ir.async_delete_issue.assert_not_called()

        # 2nd clear cycle - now dismisses
        manager.clear_condition(RepairCondition.INVALID_CREDENTIALS)
        mock_ir.async_delete_issue.assert_called_once()

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_no_dismiss_for_inactive_condition(self, mock_ir, mock_hass):
        """Clearing a condition that was never active does nothing."""
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN005")

        manager.clear_condition(RepairCondition.FIRMWARE_UPDATE)
        manager.clear_condition(RepairCondition.FIRMWARE_UPDATE)

        mock_ir.async_delete_issue.assert_not_called()


class TestDeduplication:
    """Tests for one repair per condition per device."""

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_separate_conditions_separate_repairs(self, mock_ir, mock_hass):
        """Different conditions create separate repairs for same device."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.ERROR = "error"
        mock_ir.IssueSeverity.WARNING = "warning"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN006")

        manager.report_invalid_credentials()
        manager.check_firmware_update(has_update=True, current_version="1.0.0")

        assert mock_ir.async_create_issue.call_count == 2

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_separate_devices_separate_repairs(self, mock_ir, mock_hass):
        """Same condition on different devices creates separate repairs."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.ERROR = "error"
        manager1 = DeyeRepairManager(hass=mock_hass, device_sn="SN_A")
        manager2 = DeyeRepairManager(hass=mock_hass, device_sn="SN_B")

        manager1.report_invalid_credentials()
        manager2.report_invalid_credentials()

        assert mock_ir.async_create_issue.call_count == 2
        # Verify different issue_ids
        calls = mock_ir.async_create_issue.call_args_list
        assert calls[0][0][2] == "invalid_credentials_SN_A"
        assert calls[1][0][2] == "invalid_credentials_SN_B"


class TestGetActiveRepairs:
    """Tests for retrieving active repair states."""

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_get_active_repairs_empty(self, mock_ir, mock_hass):
        """Returns empty list when no repairs are active."""
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN007")

        assert manager.get_active_repairs() == []

    @patch("custom_components.deye_cloud.repairs.ir")
    def test_get_active_repairs_with_issues(self, mock_ir, mock_hass):
        """Returns active repair states."""
        mock_ir.IssueSeverity = MagicMock()
        mock_ir.IssueSeverity.ERROR = "error"
        mock_ir.IssueSeverity.WARNING = "warning"
        manager = DeyeRepairManager(hass=mock_hass, device_sn="SN007")

        manager.report_invalid_credentials()
        manager.check_firmware_update(has_update=True, current_version="2.0.0")

        active = manager.get_active_repairs()
        assert len(active) == 2
        conditions = {r.condition for r in active}
        assert RepairCondition.INVALID_CREDENTIALS in conditions
        assert RepairCondition.FIRMWARE_UPDATE in conditions
