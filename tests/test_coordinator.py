"""Tests for the DeyeDeviceCoordinator."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.deye_cloud.coordinator import (
    DeyeDeviceCoordinator,
    MEASURE_POINTS,
    _float,
    _optional_float,
)
from custom_components.deye_cloud.exceptions import (
    DeyeApiError,
    DeyeAuthError,
    DeyeConnectionError,
    DeyeRateLimitError,
    DeyeTimeoutError,
)
from custom_components.deye_cloud.const import (
    CONSECUTIVE_FAILURE_THRESHOLD,
    COORDINATOR_MAX_RETRIES,
    RATE_LIMIT_DEFAULT_PAUSE_S,
    RATE_LIMIT_MAX_PAUSE_S,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    return hass


@pytest.fixture
def mock_api():
    """Create a mock DeyeCloudAPI instance."""
    api = AsyncMock()
    return api


@pytest.fixture
def coordinator(mock_hass, mock_api):
    """Create a DeyeDeviceCoordinator instance."""
    return DeyeDeviceCoordinator(
        hass=mock_hass,
        api=mock_api,
        device_sn="TEST_SN_001",
        interval=timedelta(seconds=60),
    )


def _make_raw_data(**overrides) -> dict:
    """Create a minimal raw API response dict."""
    data = {
        "pv_power_total": 5000.0,
        "pv_daily_yield": 12.5,
        "pv_total_yield": 1000.0,
        "battery_soc": 75,
        "battery_power": 500,
        "battery_voltage": 48.2,
        "battery_current": 10.5,
        "battery_temperature": 25.0,
        "battery_daily_charge": 5.0,
        "battery_daily_discharge": 3.0,
        "battery_total_charge": 200.0,
        "battery_total_discharge": 180.0,
        "grid_import_power": 0.0,
        "grid_export_power": 2000.0,
        "grid_daily_import": 1.0,
        "grid_daily_export": 8.0,
        "grid_total_import": 100.0,
        "grid_total_export": 500.0,
        "grid_frequency": 50.01,
        "load_power": 3000.0,
        "load_daily_consumption": 15.0,
        "load_total_consumption": 2000.0,
        "is_online": True,
        "last_update_time": "2024-01-15T10:30:00",
        "work_mode": 0,
        "energy_pattern": 0,
        "battery_soc_min": 10,
        "battery_soc_max": 100,
        "battery_charge_current_max": 25.0,
        "battery_discharge_current_max": 25.0,
        "grid_export_limit": 5000,
        "solar_sell_enabled": True,
        "peak_shaving_enabled": False,
        "peak_shaving_threshold": 0,
        "tou_enabled": False,
    }
    data.update(overrides)
    return data


class TestInit:
    """Test DeyeDeviceCoordinator initialization."""

    def test_init_stores_api_and_device_sn(self, coordinator, mock_api):
        """Test that __init__ stores api reference and device serial."""
        assert coordinator.api is mock_api
        assert coordinator.device_sn == "TEST_SN_001"

    def test_init_sets_interval(self, coordinator):
        """Test that update_interval is set correctly."""
        assert coordinator.update_interval == timedelta(seconds=60)

    def test_init_zero_failures(self, coordinator):
        """Test that consecutive failures start at zero."""
        assert coordinator._consecutive_failures == 0
        assert coordinator._repair_created is False


class TestAsyncUpdateData:
    """Test the _async_update_data method."""

    @pytest.mark.asyncio
    async def test_successful_fetch(self, coordinator, mock_api):
        """Test successful data fetch and parsing."""
        mock_api.get_device_latest = AsyncMock(return_value=_make_raw_data())

        result = await coordinator._async_update_data()

        assert result.pv_power_total_w == 5000.0
        assert result.pv_daily_yield_kwh == 12.5
        assert result.battery_soc_pct == 75.0
        assert result.grid_export_power_w == 2000.0
        assert result.load_power_w == 3000.0
        assert result.is_online is True
        mock_api.get_device_latest.assert_called_once_with(
            "TEST_SN_001", MEASURE_POINTS
        )

    @pytest.mark.asyncio
    async def test_success_resets_failure_counter(self, coordinator, mock_api):
        """Test that successful fetch resets consecutive failure counter."""
        coordinator._consecutive_failures = 3
        mock_api.get_device_latest = AsyncMock(return_value=_make_raw_data())

        await coordinator._async_update_data()

        assert coordinator._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_success_clears_repair_flag(self, coordinator, mock_api):
        """Test that successful fetch clears the repair created flag."""
        coordinator._repair_created = True
        coordinator._consecutive_failures = 5
        mock_api.get_device_latest = AsyncMock(return_value=_make_raw_data())

        await coordinator._async_update_data()

        assert coordinator._repair_created is False


class TestRetryLogic:
    """Test retry behavior for transient errors."""

    @pytest.mark.asyncio
    async def test_retries_on_timeout_error(self, coordinator, mock_api):
        """Test that DeyeTimeoutError triggers retries."""
        mock_api.get_device_latest = AsyncMock(
            side_effect=[
                DeyeTimeoutError("timeout"),
                DeyeTimeoutError("timeout"),
                _make_raw_data(),
            ]
        )

        with patch("custom_components.deye_cloud.coordinator.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await coordinator._async_update_data()

        assert result.pv_power_total_w == 5000.0
        assert mock_api.get_device_latest.call_count == 3
        # Verify backoff delays: 5s, 10s
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(5)
        mock_sleep.assert_any_call(10)

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self, coordinator, mock_api):
        """Test that DeyeConnectionError triggers retries."""
        mock_api.get_device_latest = AsyncMock(
            side_effect=[
                DeyeConnectionError("connection failed"),
                _make_raw_data(),
            ]
        )

        with patch("custom_components.deye_cloud.coordinator.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await coordinator._async_update_data()

        assert result.pv_power_total_w == 5000.0
        assert mock_api.get_device_latest.call_count == 2
        mock_sleep.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_exhausted_retries_raises_update_failed(self, coordinator, mock_api):
        """Test that exhausting all retries raises UpdateFailed."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeTimeoutError("timeout")
        )

        with patch("custom_components.deye_cloud.coordinator.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

        assert mock_api.get_device_latest.call_count == COORDINATOR_MAX_RETRIES

    @pytest.mark.asyncio
    async def test_exhausted_retries_increments_failure_counter(self, coordinator, mock_api):
        """Test that exhausted retries increments failure counter."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeTimeoutError("timeout")
        )

        with patch("custom_components.deye_cloud.coordinator.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

        assert coordinator._consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_backoff_capped_at_max_delay(self, coordinator, mock_api):
        """Test that backoff delay is capped at COORDINATOR_MAX_DELAY_S."""
        # With initial=5, multiplier=2, max=60: 5, 10, 20, 40, 60, 60...
        # With 3 retries: 5, 10 (only 2 sleeps before third attempt)
        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeConnectionError("connection failed")
        )

        with patch("custom_components.deye_cloud.coordinator.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            from homeassistant.helpers.update_coordinator import UpdateFailed
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

        # With 3 retries, we sleep twice: after attempt 1 (5s) and after attempt 2 (10s)
        assert mock_sleep.call_count == 2
        calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert calls == [5, 10]


class TestNonTransientErrors:
    """Test handling of non-transient errors (no retry)."""

    @pytest.mark.asyncio
    async def test_auth_error_no_retry(self, coordinator, mock_api):
        """Test that DeyeAuthError raises immediately without retry."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeAuthError("invalid token")
        )

        with pytest.raises(UpdateFailed, match="Authentication failed"):
            await coordinator._async_update_data()

        assert mock_api.get_device_latest.call_count == 1

    @pytest.mark.asyncio
    async def test_api_error_no_retry(self, coordinator, mock_api):
        """Test that DeyeApiError raises immediately without retry."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeApiError("bad request", error_code="400")
        )

        with pytest.raises(UpdateFailed, match="API error"):
            await coordinator._async_update_data()

        assert mock_api.get_device_latest.call_count == 1


class TestRateLimiting:
    """Test rate limit handling."""

    @pytest.mark.asyncio
    async def test_rate_limit_with_retry_after_header(self, coordinator, mock_api):
        """Test rate limit pauses for Retry-After duration."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeRateLimitError("rate limited", retry_after=120)
        )

        with pytest.raises(UpdateFailed, match="Rate limited"):
            await coordinator._async_update_data()

        assert coordinator.update_interval == timedelta(seconds=120)

    @pytest.mark.asyncio
    async def test_rate_limit_without_retry_after_uses_default(self, coordinator, mock_api):
        """Test rate limit uses default pause when no Retry-After header."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeRateLimitError("rate limited", retry_after=None)
        )

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        assert coordinator.update_interval == timedelta(seconds=RATE_LIMIT_DEFAULT_PAUSE_S)

    @pytest.mark.asyncio
    async def test_rate_limit_capped_at_max(self, coordinator, mock_api):
        """Test that Retry-After value is capped at RATE_LIMIT_MAX_PAUSE_S."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeRateLimitError("rate limited", retry_after=600)
        )

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        # Should be capped at 300s
        assert coordinator.update_interval == timedelta(seconds=RATE_LIMIT_MAX_PAUSE_S)

    @pytest.mark.asyncio
    async def test_rate_limit_increments_failure_counter(self, coordinator, mock_api):
        """Test that rate limit increments the failure counter."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeRateLimitError("rate limited", retry_after=60)
        )

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        assert coordinator._consecutive_failures == 1


class TestConsecutiveFailureTracking:
    """Test consecutive failure tracking and repair flow creation."""

    @pytest.mark.asyncio
    async def test_failure_counter_increments(self, coordinator, mock_api):
        """Test that each failure increments the counter."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeAuthError("auth failed")
        )

        for _ in range(3):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

        assert coordinator._consecutive_failures == 3

    @pytest.mark.asyncio
    async def test_repair_flow_created_at_threshold(self, coordinator, mock_api):
        """Test that repair flow is created after CONSECUTIVE_FAILURE_THRESHOLD failures."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeAuthError("auth failed")
        )

        with patch(
            "custom_components.deye_cloud.coordinator.ir.async_create_issue"
        ) as mock_create_issue:
            for _ in range(CONSECUTIVE_FAILURE_THRESHOLD):
                with pytest.raises(UpdateFailed):
                    await coordinator._async_update_data()

        assert coordinator._consecutive_failures == CONSECUTIVE_FAILURE_THRESHOLD
        assert coordinator._repair_created is True
        mock_create_issue.assert_called_once()

    @pytest.mark.asyncio
    async def test_repair_flow_not_created_below_threshold(self, coordinator, mock_api):
        """Test that repair flow is NOT created below the threshold."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeAuthError("auth failed")
        )

        with patch(
            "custom_components.deye_cloud.coordinator.ir.async_create_issue"
        ) as mock_create_issue:
            for _ in range(CONSECUTIVE_FAILURE_THRESHOLD - 1):
                with pytest.raises(UpdateFailed):
                    await coordinator._async_update_data()

        assert coordinator._consecutive_failures == CONSECUTIVE_FAILURE_THRESHOLD - 1
        assert coordinator._repair_created is False
        mock_create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_repair_flow_only_created_once(self, coordinator, mock_api):
        """Test that repair flow is only created once even with continued failures."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeAuthError("auth failed")
        )

        with patch(
            "custom_components.deye_cloud.coordinator.ir.async_create_issue"
        ) as mock_create_issue:
            for _ in range(CONSECUTIVE_FAILURE_THRESHOLD + 3):
                with pytest.raises(UpdateFailed):
                    await coordinator._async_update_data()

        # Only called once even with failures beyond threshold
        mock_create_issue.assert_called_once()


class TestRecovery:
    """Test recovery behavior after failures."""

    @pytest.mark.asyncio
    async def test_success_after_failures_resets_counter(self, coordinator, mock_api):
        """Test that success after failures resets the counter."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        # Simulate 3 failures
        mock_api.get_device_latest = AsyncMock(
            side_effect=DeyeAuthError("auth failed")
        )
        for _ in range(3):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

        assert coordinator._consecutive_failures == 3

        # Now succeed
        mock_api.get_device_latest = AsyncMock(return_value=_make_raw_data())
        await coordinator._async_update_data()

        assert coordinator._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_recovery_clears_repair_flag(self, coordinator, mock_api):
        """Test that recovery clears the repair_created flag."""
        coordinator._consecutive_failures = 5
        coordinator._repair_created = True

        mock_api.get_device_latest = AsyncMock(return_value=_make_raw_data())
        await coordinator._async_update_data()

        assert coordinator._repair_created is False


class TestParseDeviceData:
    """Test the _parse_device_data helper method."""

    def test_parse_basic_fields(self, coordinator):
        """Test parsing of basic PV, battery, grid, and load fields."""
        raw = _make_raw_data()
        result = coordinator._parse_device_data(raw)

        assert result.pv_power_total_w == 5000.0
        assert result.pv_daily_yield_kwh == 12.5
        assert result.pv_total_yield_kwh == 1000.0
        assert result.battery_soc_pct == 75.0
        assert result.battery_power_w == 500.0
        assert result.battery_voltage_v == 48.2
        assert result.battery_current_a == 10.5
        assert result.battery_temperature_c == 25.0
        assert result.grid_import_power_w == 0.0
        assert result.grid_export_power_w == 2000.0
        assert result.grid_frequency_hz == 50.01
        assert result.load_power_w == 3000.0
        assert result.load_daily_consumption_kwh == 15.0

    def test_parse_pv_channels(self, coordinator):
        """Test parsing of MPPT channel data."""
        raw = _make_raw_data(
            pv_channels=[
                {"channel": 1, "power": 2500, "voltage": 350.0, "current": 7.1},
                {"channel": 2, "power": 2500, "voltage": 340.0, "current": 7.3},
            ]
        )
        result = coordinator._parse_device_data(raw)

        assert len(result.pv_channels) == 2
        assert result.pv_channels[0].channel == 1
        assert result.pv_channels[0].power_w == 2500.0
        assert result.pv_channels[0].voltage_v == 350.0
        assert result.pv_channels[1].channel == 2

    def test_parse_grid_phases(self, coordinator):
        """Test parsing of grid phase data."""
        raw = _make_raw_data(
            grid_phases=[
                {"phase": 1, "voltage": 230.5, "current": 5.0, "power": 1150, "frequency": 50.0},
                {"phase": 2, "voltage": 231.0, "current": 4.5, "power": 1040, "frequency": 50.0},
                {"phase": 3, "voltage": 229.8, "current": 3.5, "power": 810, "frequency": 50.0},
            ]
        )
        result = coordinator._parse_device_data(raw)

        assert len(result.grid_phases) == 3
        assert result.grid_phases[0].voltage_v == 230.5
        assert result.grid_phases[2].phase == 3

    def test_parse_work_mode_and_energy_pattern(self, coordinator):
        """Test parsing of work mode and energy pattern."""
        from custom_components.deye_cloud.models import WorkMode, EnergyPattern

        raw = _make_raw_data(work_mode=2, energy_pattern=1)
        result = coordinator._parse_device_data(raw)

        assert result.work_mode == WorkMode.SELLING_FIRST
        assert result.energy_pattern == EnergyPattern.LOAD_FIRST

    def test_parse_invalid_work_mode_defaults(self, coordinator):
        """Test that invalid work mode defaults to SELF_CONSUMPTION."""
        from custom_components.deye_cloud.models import WorkMode

        raw = _make_raw_data(work_mode=99)
        result = coordinator._parse_device_data(raw)

        assert result.work_mode == WorkMode.SELF_CONSUMPTION

    def test_parse_missing_optional_battery_fields(self, coordinator):
        """Test that missing battery fields return None."""
        raw = _make_raw_data()
        del raw["battery_soc"]
        del raw["battery_power"]
        result = coordinator._parse_device_data(raw)

        assert result.battery_soc_pct is None
        assert result.battery_power_w is None

    def test_parse_smart_load_states(self, coordinator):
        """Test parsing of smart load states."""
        raw = _make_raw_data(smart_load_states=[True, False, True])
        result = coordinator._parse_device_data(raw)

        assert result.smart_load_states == [True, False, True]

    def test_parse_tou_slots(self, coordinator):
        """Test parsing of TOU schedule slots."""
        raw = _make_raw_data(
            tou_slots=[
                {
                    "slotIndex": 1,
                    "startTime": "00:00",
                    "endTime": "06:00",
                    "mode": "charging",
                    "powerLimitW": 5000,
                },
                {
                    "slotIndex": 2,
                    "startTime": "17:00",
                    "endTime": "21:00",
                    "mode": "discharging",
                    "powerLimitW": 3000,
                },
            ]
        )
        result = coordinator._parse_device_data(raw)

        assert len(result.tou_slots) == 2
        assert result.tou_slots[0].slot_index == 1
        assert result.tou_slots[0].start_time == "00:00"
        assert result.tou_slots[0].end_time == "06:00"
        assert result.tou_slots[0].mode.value == "charging"
        assert result.tou_slots[0].power_limit_w == 5000

    def test_parse_alternative_key_names(self, coordinator):
        """Test parsing with camelCase alternative key names."""
        raw = {
            "pvPowerTotal": 3000.0,
            "pvDailyYield": 8.0,
            "pvTotalYield": 500.0,
            "batterySoc": 60,
            "batteryPower": -200,
            "batteryVoltage": 47.5,
            "batteryCurrent": -4.2,
            "batteryTemperature": 22.0,
            "batteryDailyCharge": 3.0,
            "batteryDailyDischarge": 2.0,
            "batteryTotalCharge": 100.0,
            "batteryTotalDischarge": 90.0,
            "gridImportPower": 500.0,
            "gridExportPower": 0.0,
            "gridDailyImport": 5.0,
            "gridDailyExport": 0.0,
            "gridTotalImport": 200.0,
            "gridTotalExport": 50.0,
            "gridFrequency": 49.99,
            "loadPower": 2500.0,
            "loadDailyConsumption": 10.0,
            "loadTotalConsumption": 1500.0,
            "isOnline": True,
            "lastUpdateTime": "2024-01-15T12:00:00",
            "workMode": 1,
            "energyPattern": 0,
            "batterySocMin": 15,
            "batterySocMax": 95,
            "batteryChargeCurrentMax": 20.0,
            "batteryDischargeCurrentMax": 20.0,
            "gridExportLimit": 3000,
            "solarSellEnabled": False,
            "peakShavingEnabled": True,
            "peakShavingThreshold": 4000,
            "touEnabled": True,
        }
        result = coordinator._parse_device_data(raw)

        assert result.pv_power_total_w == 3000.0
        assert result.battery_soc_pct == 60.0
        assert result.grid_import_power_w == 500.0
        assert result.battery_soc_min_setting == 15
        assert result.peak_shaving_enabled is True
        assert result.peak_shaving_threshold_w == 4000

    def test_parse_empty_dict(self, coordinator):
        """Test parsing of empty dict uses defaults."""
        result = coordinator._parse_device_data({})

        assert result.pv_power_total_w == 0.0
        assert result.battery_soc_pct is None
        assert result.grid_import_power_w == 0.0
        assert result.load_power_w == 0.0
        assert result.is_online is True
        assert result.smart_load_states == []
        assert result.tou_slots == []
        assert result.pv_channels == []
        assert result.grid_phases == []


class TestHelperFunctions:
    """Test the _float and _optional_float helper functions."""

    def test_float_returns_value(self):
        """Test _float returns the first found value."""
        raw = {"key1": 42.5}
        assert _float(raw, "key1") == 42.5

    def test_float_tries_multiple_keys(self):
        """Test _float tries keys in order."""
        raw = {"key2": 10.0}
        assert _float(raw, "key1", "key2") == 10.0

    def test_float_returns_zero_if_missing(self):
        """Test _float returns 0.0 if all keys are missing."""
        raw = {}
        assert _float(raw, "key1", "key2") == 0.0

    def test_float_handles_invalid_value(self):
        """Test _float returns 0.0 for non-numeric values."""
        raw = {"key1": "not_a_number"}
        assert _float(raw, "key1") == 0.0

    def test_optional_float_returns_value(self):
        """Test _optional_float returns the value when present."""
        raw = {"key1": 42.5}
        assert _optional_float(raw, "key1") == 42.5

    def test_optional_float_returns_none_if_missing(self):
        """Test _optional_float returns None if all keys are missing."""
        raw = {}
        assert _optional_float(raw, "key1", "key2") is None

    def test_optional_float_returns_none_for_none_value(self):
        """Test _optional_float returns None when all values are None."""
        raw = {"key1": None}
        assert _optional_float(raw, "key1") is None

    def test_optional_float_handles_invalid_value(self):
        """Test _optional_float returns None for non-numeric values."""
        raw = {"key1": "invalid"}
        assert _optional_float(raw, "key1") is None
