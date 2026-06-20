"""Tests for the DeyeForecastCoordinator."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.deye_cloud.forecast import (
    DeyeForecastCoordinator,
    compute_tilt_azimuth_correction,
    estimate_power_w,
)
from custom_components.deye_cloud.models import ForecastData, HourlyForecast


# ─── Unit tests for helper functions ──────────────────────────────────────────


class TestComputeTiltAzimuthCorrection:
    """Tests for the tilt/azimuth correction factor."""

    def test_south_facing_flat_panel(self):
        """Flat panel (0 tilt) facing south should give ~1.0."""
        result = compute_tilt_azimuth_correction(0, 180)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_south_facing_30deg_tilt(self):
        """30° tilt south-facing - typical installation."""
        result = compute_tilt_azimuth_correction(30, 180)
        # cos(30°) ≈ 0.866, azimuth deviation = 0 → factor ≈ 0.866
        assert 0.8 <= result <= 1.0

    def test_vertical_panel(self):
        """90° tilt (vertical) should give a lower correction."""
        result = compute_tilt_azimuth_correction(90, 180)
        # cos(90°) ≈ 0 → factor should be clamped to minimum
        assert result == pytest.approx(0.1, abs=0.05)

    def test_north_facing_panel(self):
        """North-facing panel (azimuth=0) should be penalized."""
        result = compute_tilt_azimuth_correction(30, 0)
        # Large azimuth deviation from south
        assert result < compute_tilt_azimuth_correction(30, 180)

    def test_east_facing_panel(self):
        """East-facing panel (azimuth=90) partial penalty."""
        result = compute_tilt_azimuth_correction(30, 90)
        south_result = compute_tilt_azimuth_correction(30, 180)
        assert result < south_result

    def test_result_always_positive(self):
        """Correction factor should always be >= 0.1."""
        for tilt in range(0, 91, 10):
            for azimuth in range(0, 361, 30):
                result = compute_tilt_azimuth_correction(tilt, azimuth)
                assert result >= 0.1
                assert result <= 1.0


class TestEstimatePowerW:
    """Tests for the power estimation formula."""

    def test_zero_irradiance(self):
        """No sun should produce no power."""
        result = estimate_power_w(0, 25.0, 0.75, 0.9)
        assert result == 0.0

    def test_standard_conditions(self):
        """1000 W/m² on 25 m² at 75% efficiency with 0.9 tilt correction."""
        result = estimate_power_w(1000, 25.0, 0.75, 0.9)
        expected = 1000 * 25.0 * 0.75 * 0.9  # 16875 W
        assert result == pytest.approx(expected)

    def test_typical_5kw_system(self):
        """Typical 5kW system: rated_power/0.2 = 25 m², 500 W/m² irradiance."""
        panel_area = 5.0 / 0.2  # 25 m²
        result = estimate_power_w(500, panel_area, 0.75, 0.87)
        # 500 * 25 * 0.75 * 0.87 = 8156.25 W
        expected = 500 * 25 * 0.75 * 0.87
        assert result == pytest.approx(expected, rel=0.01)

    def test_never_negative(self):
        """Power should never be negative even with weird inputs."""
        result = estimate_power_w(-100, 25.0, 0.75, 0.9)
        assert result == 0.0

    def test_zero_panel_area(self):
        """Zero panel area should produce zero power."""
        result = estimate_power_w(500, 0.0, 0.75, 0.9)
        assert result == 0.0


# ─── Tests for DeyeForecastCoordinator ────────────────────────────────────────


def _make_open_meteo_response(
    hours: int = 48,
    base_time: datetime | None = None,
    irradiance_pattern: list[float] | None = None,
) -> dict:
    """Create a mock Open-Meteo API response.

    Args:
        hours: Number of hours of forecast data.
        base_time: Starting time for the forecast.
        irradiance_pattern: Custom irradiance values. If None, generates
            a sine-wave daylight pattern.

    Returns:
        Mock response dict matching Open-Meteo format.
    """
    if base_time is None:
        base_time = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    times = []
    radiation = []

    for h in range(hours):
        ts = base_time + timedelta(hours=h)
        times.append(ts.strftime("%Y-%m-%dT%H:%M"))

        if irradiance_pattern is not None and h < len(irradiance_pattern):
            radiation.append(irradiance_pattern[h])
        else:
            # Simple daylight pattern: peak at noon (hour 12), zero at night
            hour_of_day = ts.hour
            if 6 <= hour_of_day <= 18:
                # Sine pattern peaking at noon
                factor = math.sin(math.pi * (hour_of_day - 6) / 12)
                radiation.append(round(800 * factor, 1))
            else:
                radiation.append(0.0)

    return {
        "hourly": {
            "time": times,
            "shortwave_radiation": radiation,
        }
    }


@pytest.fixture
def mock_hass():
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    return hass


@pytest.fixture
def mock_session():
    """Create a mock aiohttp ClientSession."""
    session = MagicMock()
    return session


@pytest.fixture
def coordinator(mock_hass, mock_session):
    """Create a DeyeForecastCoordinator with typical values."""
    return DeyeForecastCoordinator(
        hass=mock_hass,
        session=mock_session,
        latitude=52.52,
        longitude=13.41,
        panel_tilt=30.0,
        panel_azimuth=180.0,
        efficiency=0.75,
        rated_power_kw=5.0,
    )


class TestDeyeForecastCoordinatorInit:
    """Tests for coordinator initialization."""

    def test_panel_area_calculation(self, coordinator):
        """Panel area = rated_power_kw / 0.2."""
        assert coordinator.panel_area_m2 == pytest.approx(25.0)

    def test_panel_area_10kw(self, mock_hass, mock_session):
        """10 kW system → 50 m² panel area."""
        coord = DeyeForecastCoordinator(
            hass=mock_hass,
            session=mock_session,
            latitude=0,
            longitude=0,
            panel_tilt=30,
            panel_azimuth=180,
            efficiency=0.75,
            rated_power_kw=10.0,
        )
        assert coord.panel_area_m2 == pytest.approx(50.0)

    def test_tilt_correction_stored(self, coordinator):
        """Tilt correction is pre-computed and accessible."""
        assert 0.1 <= coordinator.tilt_correction <= 1.0

    def test_update_interval_60min(self, coordinator):
        """Poll interval should be 60 minutes."""
        assert coordinator.update_interval == timedelta(minutes=60)


class TestDeyeForecastCoordinatorUpdate:
    """Tests for the _async_update_data method."""

    @pytest.mark.asyncio
    async def test_successful_fetch(self, coordinator, mock_session):
        """Successful API call returns ForecastData with is_stale=False."""
        now = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        mock_response = _make_open_meteo_response(base_time=now)

        response_mock = AsyncMock()
        response_mock.status = 200
        response_mock.json = AsyncMock(return_value=mock_response)
        response_mock.text = AsyncMock(return_value="")

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=response_mock)
        context_manager.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=context_manager)

        result = await coordinator._async_update_data()

        assert isinstance(result, ForecastData)
        assert result.is_stale is False
        assert result.forecast_today_kwh >= 0
        assert result.forecast_tomorrow_kwh >= 0
        assert result.current_hour_power_w >= 0
        assert isinstance(result.hourly_forecast, list)
        assert result.last_successful_update is not None

    @pytest.mark.asyncio
    async def test_api_failure_no_previous_data(self, coordinator, mock_session):
        """API failure with no previous data raises UpdateFailed."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        response_mock = AsyncMock()
        response_mock.status = 500
        response_mock.text = AsyncMock(return_value="Internal Server Error")

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=response_mock)
        context_manager.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=context_manager)

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_api_failure_retains_stale_data(self, coordinator, mock_session):
        """API failure with previous data returns stale data."""
        # First, do a successful fetch
        now = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        mock_response = _make_open_meteo_response(base_time=now)

        response_mock = AsyncMock()
        response_mock.status = 200
        response_mock.json = AsyncMock(return_value=mock_response)
        response_mock.text = AsyncMock(return_value="")

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=response_mock)
        context_manager.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=context_manager)

        first_result = await coordinator._async_update_data()
        assert first_result.is_stale is False

        # Now simulate API failure
        response_mock_fail = AsyncMock()
        response_mock_fail.status = 503
        response_mock_fail.text = AsyncMock(return_value="Service Unavailable")

        context_manager_fail = AsyncMock()
        context_manager_fail.__aenter__ = AsyncMock(return_value=response_mock_fail)
        context_manager_fail.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=context_manager_fail)

        stale_result = await coordinator._async_update_data()

        assert stale_result.is_stale is True
        assert stale_result.forecast_today_kwh == first_result.forecast_today_kwh
        assert stale_result.forecast_tomorrow_kwh == first_result.forecast_tomorrow_kwh
        assert stale_result.last_successful_update == first_result.last_successful_update

    @pytest.mark.asyncio
    async def test_hourly_forecast_limited_to_24(self, coordinator, mock_session):
        """Hourly forecast list should contain at most 24 entries."""
        now = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        mock_response = _make_open_meteo_response(hours=48, base_time=now)

        response_mock = AsyncMock()
        response_mock.status = 200
        response_mock.json = AsyncMock(return_value=mock_response)
        response_mock.text = AsyncMock(return_value="")

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=response_mock)
        context_manager.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=context_manager)

        result = await coordinator._async_update_data()
        assert len(result.hourly_forecast) <= 24

    @pytest.mark.asyncio
    async def test_hourly_forecast_entries_structure(self, coordinator, mock_session):
        """Each HourlyForecast entry has required fields."""
        now = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        mock_response = _make_open_meteo_response(hours=48, base_time=now)

        response_mock = AsyncMock()
        response_mock.status = 200
        response_mock.json = AsyncMock(return_value=mock_response)
        response_mock.text = AsyncMock(return_value="")

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=response_mock)
        context_manager.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=context_manager)

        result = await coordinator._async_update_data()

        for entry in result.hourly_forecast:
            assert isinstance(entry, HourlyForecast)
            assert isinstance(entry.timestamp, datetime)
            assert isinstance(entry.estimated_power_w, float)
            assert entry.estimated_power_w >= 0
            assert isinstance(entry.irradiance_wm2, float)
            assert entry.irradiance_wm2 >= 0

    @pytest.mark.asyncio
    async def test_today_tomorrow_energy_non_negative(self, coordinator, mock_session):
        """Today and tomorrow energy forecasts should be non-negative."""
        now = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        mock_response = _make_open_meteo_response(hours=48, base_time=now)

        response_mock = AsyncMock()
        response_mock.status = 200
        response_mock.json = AsyncMock(return_value=mock_response)
        response_mock.text = AsyncMock(return_value="")

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=response_mock)
        context_manager.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=context_manager)

        result = await coordinator._async_update_data()
        assert result.forecast_today_kwh >= 0
        assert result.forecast_tomorrow_kwh >= 0

    @pytest.mark.asyncio
    async def test_null_irradiance_treated_as_zero(self, coordinator, mock_session):
        """Null irradiance values in API response are treated as 0."""
        now = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # Include None values in radiation data
        irradiance = [None, None, None, 100.0, 200.0, None] + [0.0] * 42
        mock_response = _make_open_meteo_response(
            hours=48, base_time=now, irradiance_pattern=irradiance
        )

        response_mock = AsyncMock()
        response_mock.status = 200
        response_mock.json = AsyncMock(return_value=mock_response)
        response_mock.text = AsyncMock(return_value="")

        context_manager = AsyncMock()
        context_manager.__aenter__ = AsyncMock(return_value=response_mock)
        context_manager.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=context_manager)

        result = await coordinator._async_update_data()
        # Should not crash; values should be non-negative
        assert result.forecast_today_kwh >= 0
        assert result.is_stale is False


class TestDeyeForecastCoordinatorComputeLogic:
    """Tests for the production estimation logic in _compute_forecast."""

    def test_compute_forecast_zero_irradiance(self, coordinator):
        """All zero irradiance yields zero energy."""
        now = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        response = _make_open_meteo_response(
            hours=48,
            base_time=now,
            irradiance_pattern=[0.0] * 48,
        )

        result = coordinator._compute_forecast(response)
        assert result.forecast_today_kwh == 0.0
        assert result.forecast_tomorrow_kwh == 0.0
        assert result.current_hour_power_w == 0.0

    def test_compute_forecast_constant_irradiance(self, coordinator):
        """Constant 500 W/m² for all 24 hours of today."""
        now = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # 24 hours today at 500 W/m², 24 hours tomorrow at 500 W/m²
        response = _make_open_meteo_response(
            hours=48,
            base_time=now,
            irradiance_pattern=[500.0] * 48,
        )

        result = coordinator._compute_forecast(response)

        # Expected per-hour power: 500 * 25 * 0.75 * tilt_correction
        expected_power = estimate_power_w(
            500.0, coordinator.panel_area_m2, 0.75, coordinator.tilt_correction
        )
        # 24 hours at that power → energy in kWh
        expected_today_kwh = round(expected_power * 24 / 1000, 2)
        assert result.forecast_today_kwh == pytest.approx(expected_today_kwh, rel=0.01)
        assert result.forecast_tomorrow_kwh == pytest.approx(expected_today_kwh, rel=0.01)
