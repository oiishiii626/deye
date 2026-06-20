"""Tests for the TariffManager class."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.deye_cloud.models import (
    TariffCategory,
    TariffConfig,
    TariffPeriod,
    WorkMode,
)
from custom_components.deye_cloud.tariff import (
    TariffManager,
    TariffValidationError,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.async_create_task = MagicMock(side_effect=lambda coro: asyncio.ensure_future(coro))
    hass.components = MagicMock()
    hass.components.persistent_notification = MagicMock()
    hass.components.persistent_notification.async_create = MagicMock()
    return hass


@pytest.fixture
def mock_api():
    """Create a mock Deye Cloud API client."""
    api = MagicMock()
    api.set_work_mode = AsyncMock(return_value=True)
    api.set_device_config = AsyncMock(return_value=True)
    return api


@pytest.fixture
def basic_config():
    """Create a basic tariff configuration."""
    return TariffConfig(
        enabled=True,
        periods=[
            TariffPeriod(start_time="01:00", end_time="06:00", category=TariffCategory.CHEAP),
            TariffPeriod(start_time="07:00", end_time="09:00", category=TariffCategory.PEAK),
            TariffPeriod(start_time="09:00", end_time="17:00", category=TariffCategory.STANDARD),
            TariffPeriod(start_time="17:00", end_time="21:00", category=TariffCategory.PEAK),
            TariffPeriod(start_time="21:00", end_time="23:59", category=TariffCategory.STANDARD),
        ],
        default_work_mode=WorkMode.SELF_CONSUMPTION,
        charge_current=25.0,
        discharge_current=30.0,
    )


@pytest.fixture
def device_sn():
    """Return a test device serial number."""
    return "INV001TEST"


# ─── Validation Tests ─────────────────────────────────────────────────────────


class TestTariffValidation:
    """Tests for TariffConfig validation."""

    def test_valid_config_accepted(self, mock_hass, mock_api, device_sn, basic_config):
        """Valid configuration should not raise."""
        manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)
        assert manager.device_sn == device_sn
        assert manager.config == basic_config

    def test_empty_periods_accepted(self, mock_hass, mock_api, device_sn):
        """Empty periods list should be accepted."""
        config = TariffConfig(
            enabled=True,
            periods=[],
            default_work_mode=WorkMode.SELF_CONSUMPTION,
            charge_current=20.0,
            discharge_current=20.0,
        )
        manager = TariffManager(mock_hass, mock_api, device_sn, config)
        assert len(manager.config.periods) == 0

    def test_max_10_periods_accepted(self, mock_hass, mock_api, device_sn):
        """Exactly 10 periods should be accepted."""
        periods = []
        for i in range(10):
            start_h = i * 2
            end_h = i * 2 + 1
            periods.append(
                TariffPeriod(
                    start_time=f"{start_h:02d}:00",
                    end_time=f"{end_h:02d}:00",
                    category=TariffCategory.STANDARD,
                )
            )
        config = TariffConfig(
            enabled=True,
            periods=periods,
            default_work_mode=WorkMode.SELF_CONSUMPTION,
            charge_current=10.0,
            discharge_current=10.0,
        )
        manager = TariffManager(mock_hass, mock_api, device_sn, config)
        assert len(manager.config.periods) == 10

    def test_more_than_10_periods_rejected(self, mock_hass, mock_api, device_sn):
        """More than 10 periods should raise TariffValidationError."""
        periods = []
        for i in range(11):
            start_h = i * 2
            end_h = i * 2 + 1
            if end_h >= 24:
                end_h = 23
            periods.append(
                TariffPeriod(
                    start_time=f"{start_h:02d}:00",
                    end_time=f"{end_h:02d}:00",
                    category=TariffCategory.STANDARD,
                )
            )
        config = TariffConfig(
            enabled=True,
            periods=periods,
            default_work_mode=WorkMode.SELF_CONSUMPTION,
            charge_current=10.0,
            discharge_current=10.0,
        )
        with pytest.raises(TariffValidationError, match="Too many tariff periods"):
            TariffManager(mock_hass, mock_api, device_sn, config)

    def test_overlapping_periods_rejected(self, mock_hass, mock_api, device_sn):
        """Overlapping periods should raise TariffValidationError."""
        config = TariffConfig(
            enabled=True,
            periods=[
                TariffPeriod(start_time="01:00", end_time="06:00", category=TariffCategory.CHEAP),
                TariffPeriod(start_time="05:00", end_time="09:00", category=TariffCategory.PEAK),
            ],
            default_work_mode=WorkMode.SELF_CONSUMPTION,
            charge_current=20.0,
            discharge_current=20.0,
        )
        with pytest.raises(TariffValidationError, match="overlapping"):
            TariffManager(mock_hass, mock_api, device_sn, config)

    def test_invalid_start_time_format_rejected(self, mock_hass, mock_api, device_sn):
        """Invalid start time format should raise TariffValidationError."""
        config = TariffConfig(
            enabled=True,
            periods=[
                TariffPeriod(start_time="25:00", end_time="06:00", category=TariffCategory.CHEAP),
            ],
            default_work_mode=WorkMode.SELF_CONSUMPTION,
            charge_current=20.0,
            discharge_current=20.0,
        )
        with pytest.raises(TariffValidationError, match="Invalid start time"):
            TariffManager(mock_hass, mock_api, device_sn, config)

    def test_invalid_end_time_format_rejected(self, mock_hass, mock_api, device_sn):
        """Invalid end time format should raise TariffValidationError."""
        config = TariffConfig(
            enabled=True,
            periods=[
                TariffPeriod(start_time="01:00", end_time="99:99", category=TariffCategory.CHEAP),
            ],
            default_work_mode=WorkMode.SELF_CONSUMPTION,
            charge_current=20.0,
            discharge_current=20.0,
        )
        with pytest.raises(TariffValidationError, match="Invalid end time"):
            TariffManager(mock_hass, mock_api, device_sn, config)

    def test_single_period_accepted(self, mock_hass, mock_api, device_sn):
        """A single valid period should be accepted."""
        config = TariffConfig(
            enabled=True,
            periods=[
                TariffPeriod(start_time="01:00", end_time="06:00", category=TariffCategory.CHEAP),
            ],
            default_work_mode=WorkMode.SELF_CONSUMPTION,
            charge_current=20.0,
            discharge_current=20.0,
        )
        manager = TariffManager(mock_hass, mock_api, device_sn, config)
        assert len(manager.config.periods) == 1


# ─── Start/Stop Tests ─────────────────────────────────────────────────────────


class TestTariffStartStop:
    """Tests for TariffManager start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_registers_listeners(self, mock_hass, mock_api, device_sn, basic_config):
        """Starting should register time-based listeners."""
        with patch(
            "custom_components.deye_cloud.tariff.async_track_time_change"
        ) as mock_track:
            mock_track.return_value = MagicMock()  # unsub callable
            manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)
            await manager.async_start()

            # Should register one listener per period
            assert mock_track.call_count == len(basic_config.periods)
            assert manager.is_running is True

    @pytest.mark.asyncio
    async def test_start_disabled_config_does_not_register(
        self, mock_hass, mock_api, device_sn
    ):
        """Starting with disabled config should not register listeners."""
        config = TariffConfig(
            enabled=False,
            periods=[
                TariffPeriod(start_time="01:00", end_time="06:00", category=TariffCategory.CHEAP),
            ],
            default_work_mode=WorkMode.SELF_CONSUMPTION,
            charge_current=20.0,
            discharge_current=20.0,
        )
        with patch(
            "custom_components.deye_cloud.tariff.async_track_time_change"
        ) as mock_track:
            manager = TariffManager(mock_hass, mock_api, device_sn, config)
            await manager.async_start()

            mock_track.assert_not_called()
            assert manager.is_running is False

    @pytest.mark.asyncio
    async def test_stop_removes_listeners(self, mock_hass, mock_api, device_sn, basic_config):
        """Stopping should call unsub on all listeners."""
        unsub_mocks = [MagicMock() for _ in basic_config.periods]
        call_count = [0]

        def mock_track_side_effect(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            return unsub_mocks[idx]

        with patch(
            "custom_components.deye_cloud.tariff.async_track_time_change",
            side_effect=mock_track_side_effect,
        ):
            manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)
            await manager.async_start()
            await manager.async_stop()

            # All unsub functions should have been called
            for unsub in unsub_mocks:
                unsub.assert_called_once()
            assert manager.is_running is False

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self, mock_hass, mock_api, device_sn, basic_config):
        """Starting twice should not double-register listeners."""
        with patch(
            "custom_components.deye_cloud.tariff.async_track_time_change"
        ) as mock_track:
            mock_track.return_value = MagicMock()
            manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)
            await manager.async_start()
            await manager.async_start()

            # Should only register once
            assert mock_track.call_count == len(basic_config.periods)


# ─── Period Transition Tests ──────────────────────────────────────────────────


class TestTariffTransitions:
    """Tests for tariff period transition handling."""

    @pytest.mark.asyncio
    async def test_cheap_rate_switches_to_grid_charging(
        self, mock_hass, mock_api, device_sn, basic_config
    ):
        """Cheap rate entry should set grid-charging mode and max charge current."""
        manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)

        cheap_period = basic_config.periods[0]  # 01:00-06:00 CHEAP
        await manager._handle_period_transition(cheap_period)

        # Should call set_work_mode with TIME_OF_USE (grid charging)
        mock_api.set_work_mode.assert_called_once_with(
            device_sn, WorkMode.TIME_OF_USE.value
        )
        # Should set max charge current
        mock_api.set_device_config.assert_called_once_with(
            device_sn, {"batteryChargeCurrent": 25.0}
        )
        assert manager.current_category == TariffCategory.CHEAP

    @pytest.mark.asyncio
    async def test_peak_rate_switches_to_battery_discharge(
        self, mock_hass, mock_api, device_sn, basic_config
    ):
        """Peak rate entry should set battery-discharge mode and max discharge current."""
        manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)

        peak_period = basic_config.periods[1]  # 07:00-09:00 PEAK
        await manager._handle_period_transition(peak_period)

        # Should call set_work_mode with SELLING_FIRST (battery discharge)
        mock_api.set_work_mode.assert_called_once_with(
            device_sn, WorkMode.SELLING_FIRST.value
        )
        # Should set max discharge current
        mock_api.set_device_config.assert_called_once_with(
            device_sn, {"batteryDischargeCurrent": 30.0}
        )
        assert manager.current_category == TariffCategory.PEAK

    @pytest.mark.asyncio
    async def test_standard_rate_restores_default_mode(
        self, mock_hass, mock_api, device_sn, basic_config
    ):
        """Standard rate entry should restore the default work mode."""
        manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)

        standard_period = basic_config.periods[2]  # 09:00-17:00 STANDARD
        await manager._handle_period_transition(standard_period)

        # Should call set_work_mode with default (SELF_CONSUMPTION)
        mock_api.set_work_mode.assert_called_once_with(
            device_sn, WorkMode.SELF_CONSUMPTION.value
        )
        # Should NOT modify charge/discharge current
        mock_api.set_device_config.assert_not_called()
        assert manager.current_category == TariffCategory.STANDARD

    @pytest.mark.asyncio
    async def test_transition_fires_ha_event(
        self, mock_hass, mock_api, device_sn, basic_config
    ):
        """Period transition should fire an HA event with all required fields."""
        manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)
        manager._current_category = TariffCategory.STANDARD

        peak_period = basic_config.periods[1]  # 07:00-09:00 PEAK
        await manager._handle_period_transition(peak_period)

        # Verify event was fired
        mock_hass.bus.async_fire.assert_called_once()
        call_args = mock_hass.bus.async_fire.call_args
        event_type = call_args[0][0]
        event_data = call_args[0][1]

        assert event_type == "deye_cloud_tariff_transition"
        assert event_data["device_id"] == device_sn
        assert event_data["previous_category"] == "standard"
        assert event_data["new_category"] == "peak"
        assert "timestamp" in event_data

    @pytest.mark.asyncio
    async def test_transition_event_contains_device_id(
        self, mock_hass, mock_api, device_sn, basic_config
    ):
        """Transition event must contain the device ID."""
        manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)
        cheap_period = basic_config.periods[0]
        await manager._handle_period_transition(cheap_period)

        event_data = mock_hass.bus.async_fire.call_args[0][1]
        assert event_data["device_id"] == device_sn

    @pytest.mark.asyncio
    async def test_transition_event_contains_timestamp(
        self, mock_hass, mock_api, device_sn, basic_config
    ):
        """Transition event must contain a timestamp."""
        manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)
        cheap_period = basic_config.periods[0]
        await manager._handle_period_transition(cheap_period)

        event_data = mock_hass.bus.async_fire.call_args[0][1]
        # Verify timestamp is a valid ISO format string
        timestamp = event_data["timestamp"]
        datetime.fromisoformat(timestamp)  # Should not raise


# ─── Retry Tests ──────────────────────────────────────────────────────────────


class TestTariffRetry:
    """Tests for retry logic on failed mode switches."""

    @pytest.mark.asyncio
    async def test_retry_on_api_failure(self, mock_hass, mock_api, device_sn, basic_config):
        """Should retry 3 times on API failure."""
        mock_api.set_work_mode = AsyncMock(
            side_effect=[Exception("API error"), Exception("API error"), True]
        )

        manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)

        with patch("custom_components.deye_cloud.tariff.asyncio.sleep", new_callable=AsyncMock):
            result = await manager._apply_mode_with_retry(TariffCategory.CHEAP)

        assert result is True
        assert mock_api.set_work_mode.call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_returns_false(
        self, mock_hass, mock_api, device_sn, basic_config
    ):
        """Should return False when all retries are exhausted."""
        mock_api.set_work_mode = AsyncMock(side_effect=Exception("API error"))

        manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)

        with patch("custom_components.deye_cloud.tariff.asyncio.sleep", new_callable=AsyncMock):
            result = await manager._apply_mode_with_retry(TariffCategory.CHEAP)

        assert result is False
        assert mock_api.set_work_mode.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_uses_30s_intervals(self, mock_hass, mock_api, device_sn, basic_config):
        """Retry delays should be 30 seconds."""
        mock_api.set_work_mode = AsyncMock(side_effect=Exception("API error"))

        manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)

        with patch(
            "custom_components.deye_cloud.tariff.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            await manager._apply_mode_with_retry(TariffCategory.CHEAP)

        # Should sleep 30s between retries (2 sleeps for 3 attempts)
        assert mock_sleep.call_count == 2
        for call in mock_sleep.call_args_list:
            assert call[0][0] == 30

    @pytest.mark.asyncio
    async def test_exhausted_retries_trigger_notification(
        self, mock_hass, mock_api, device_sn, basic_config
    ):
        """Exhausted retries should create a persistent notification."""
        mock_api.set_work_mode = AsyncMock(side_effect=Exception("API error"))

        manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)

        with patch("custom_components.deye_cloud.tariff.asyncio.sleep", new_callable=AsyncMock):
            await manager._handle_period_transition(basic_config.periods[0])

        # Persistent notification should be created
        mock_hass.components.persistent_notification.async_create.assert_called_once()
        call_kwargs = mock_hass.components.persistent_notification.async_create.call_args[1]
        assert device_sn in call_kwargs["message"]
        assert "notification_id" in call_kwargs

    @pytest.mark.asyncio
    async def test_success_on_first_try_no_retry(
        self, mock_hass, mock_api, device_sn, basic_config
    ):
        """Successful first attempt should not trigger retries."""
        manager = TariffManager(mock_hass, mock_api, device_sn, basic_config)

        with patch(
            "custom_components.deye_cloud.tariff.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            result = await manager._apply_mode_with_retry(TariffCategory.CHEAP)

        assert result is True
        mock_sleep.assert_not_called()


# ─── Current Category Detection Tests ────────────────────────────────────────


class TestCurrentCategoryDetection:
    """Tests for determining the current active tariff category."""

    def test_detects_current_cheap_period(self, mock_hass, mock_api, device_sn):
        """Should detect cheap period when time falls within it."""
        config = TariffConfig(
            enabled=True,
            periods=[
                TariffPeriod(start_time="00:00", end_time="23:59", category=TariffCategory.CHEAP),
            ],
            default_work_mode=WorkMode.SELF_CONSUMPTION,
            charge_current=20.0,
            discharge_current=20.0,
        )
        manager = TariffManager(mock_hass, mock_api, device_sn, config)
        # Since 00:00 to 23:59 covers all day, current category should be CHEAP
        assert manager._get_current_category() == TariffCategory.CHEAP

    def test_returns_none_when_no_matching_period(self, mock_hass, mock_api, device_sn):
        """Should return None when current time is not in any period."""
        # Use a period that's very unlikely to match the test execution time
        config = TariffConfig(
            enabled=True,
            periods=[],
            default_work_mode=WorkMode.SELF_CONSUMPTION,
            charge_current=20.0,
            discharge_current=20.0,
        )
        manager = TariffManager(mock_hass, mock_api, device_sn, config)
        assert manager._get_current_category() is None


# ─── Helper Method Tests ──────────────────────────────────────────────────────


class TestHelperMethods:
    """Tests for TariffManager helper methods."""

    def test_parse_time(self):
        """Should correctly parse HH:MM strings."""
        assert TariffManager._parse_time("00:00") == (0, 0)
        assert TariffManager._parse_time("12:30") == (12, 30)
        assert TariffManager._parse_time("23:59") == (23, 59)
        assert TariffManager._parse_time("07:05") == (7, 5)

    def test_time_to_minutes(self):
        """Should correctly convert HH:MM to minutes since midnight."""
        assert TariffManager._time_to_minutes("00:00") == 0
        assert TariffManager._time_to_minutes("01:00") == 60
        assert TariffManager._time_to_minutes("12:30") == 750
        assert TariffManager._time_to_minutes("23:59") == 1439
