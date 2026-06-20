"""ForecastCoordinator for solar irradiance forecasts via Open-Meteo API."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_PANEL_AZIMUTH,
    DEFAULT_PANEL_TILT,
    DEFAULT_SYSTEM_EFFICIENCY,
    DOMAIN,
    FORECAST_UPDATE_INTERVAL_MINUTES,
)
from .models import ForecastData, HourlyForecast

_LOGGER = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def compute_tilt_azimuth_correction(
    panel_tilt_deg: float, panel_azimuth_deg: float
) -> float:
    """Compute a simplified tilt/azimuth correction factor.

    Uses a cos-based model:
      correction = cos(tilt) * (1 - 0.5 * abs(cos(azimuth_rad)))

    Where azimuth is measured from south (180° = south-facing = optimal).
    The factor ranges roughly between 0.5 and 1.0 for typical installations.

    Args:
        panel_tilt_deg: Panel tilt angle in degrees (0 = flat, 90 = vertical).
        panel_azimuth_deg: Panel azimuth in degrees (0 = North, 180 = South).

    Returns:
        A correction factor between 0 and 1.
    """
    tilt_rad = math.radians(panel_tilt_deg)
    # Azimuth deviation from south (180°)
    azimuth_deviation_deg = abs(panel_azimuth_deg - 180.0)
    azimuth_deviation_rad = math.radians(azimuth_deviation_deg)

    # cos(tilt) penalizes steep tilts; azimuth deviation penalizes non-south
    correction = math.cos(tilt_rad) * (
        1.0 - 0.5 * (1.0 - math.cos(azimuth_deviation_rad))
    )
    # Clamp to [0.1, 1.0] to avoid zero or negative values
    return max(0.1, min(1.0, correction))


def estimate_power_w(
    irradiance_wm2: float,
    panel_area_m2: float,
    efficiency: float,
    tilt_correction: float,
) -> float:
    """Estimate solar power output in watts.

    Formula: irradiance × panel_area × efficiency × tilt_correction

    Args:
        irradiance_wm2: Solar irradiance in W/m².
        panel_area_m2: Total panel area in m².
        efficiency: System efficiency factor (0.5-0.95).
        tilt_correction: Tilt/azimuth correction factor (0-1).

    Returns:
        Estimated power output in watts. Never negative.
    """
    power = irradiance_wm2 * panel_area_m2 * efficiency * tilt_correction
    return max(0.0, power)


class DeyeForecastCoordinator(DataUpdateCoordinator[ForecastData]):
    """Coordinator polling Open-Meteo for solar irradiance forecasts."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        latitude: float,
        longitude: float,
        panel_tilt: float,
        panel_azimuth: float,
        efficiency: float,
        rated_power_kw: float,
    ) -> None:
        """Initialize the forecast coordinator.

        Args:
            hass: The Home Assistant instance.
            session: An aiohttp ClientSession for HTTP requests.
            latitude: Station latitude for Open-Meteo API.
            longitude: Station longitude for Open-Meteo API.
            panel_tilt: Panel tilt angle in degrees (0-90).
            panel_azimuth: Panel azimuth in degrees (0-360).
            efficiency: System efficiency factor (0.5-0.95).
            rated_power_kw: Rated power of the system in kW.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_forecast_{latitude}_{longitude}",
            update_interval=timedelta(minutes=FORECAST_UPDATE_INTERVAL_MINUTES),
        )
        self._session = session
        self._latitude = latitude
        self._longitude = longitude
        self._panel_tilt = panel_tilt
        self._panel_azimuth = panel_azimuth
        self._efficiency = efficiency
        self._rated_power_kw = rated_power_kw
        # Panel area: rated_power_kw / 0.2 (assuming ~200 W/m² peak)
        self._panel_area_m2 = rated_power_kw / 0.2
        self._tilt_correction = compute_tilt_azimuth_correction(
            panel_tilt, panel_azimuth
        )
        self._last_successful_data: ForecastData | None = None

    @property
    def panel_area_m2(self) -> float:
        """Return the computed panel area in m²."""
        return self._panel_area_m2

    @property
    def tilt_correction(self) -> float:
        """Return the tilt/azimuth correction factor."""
        return self._tilt_correction

    async def _async_update_data(self) -> ForecastData:
        """Fetch hourly irradiance from Open-Meteo and compute estimated production.

        On success: returns fresh ForecastData with is_stale=False.
        On failure: returns last successful data with is_stale=True.
                    If no previous data exists, raises UpdateFailed.

        Returns:
            ForecastData with forecast values.

        Raises:
            UpdateFailed: When API fails and no previous data is available.
        """
        try:
            raw_data = await self._fetch_open_meteo()
            forecast_data = self._compute_forecast(raw_data)
            self._last_successful_data = forecast_data
            return forecast_data
        except Exception as err:
            _LOGGER.warning(
                "Open-Meteo API request failed: %s. Retaining last values.",
                err,
            )
            if self._last_successful_data is not None:
                # Retain last values but mark as stale
                stale_data = ForecastData(
                    forecast_today_kwh=self._last_successful_data.forecast_today_kwh,
                    forecast_tomorrow_kwh=self._last_successful_data.forecast_tomorrow_kwh,
                    current_hour_power_w=self._last_successful_data.current_hour_power_w,
                    hourly_forecast=self._last_successful_data.hourly_forecast,
                    last_successful_update=self._last_successful_data.last_successful_update,
                    is_stale=True,
                )
                return stale_data
            raise UpdateFailed(
                f"Open-Meteo API failed and no previous data available: {err}"
            ) from err

    async def _fetch_open_meteo(self) -> dict[str, Any]:
        """Fetch hourly shortwave radiation forecast from Open-Meteo.

        Returns:
            The raw JSON response from Open-Meteo API.

        Raises:
            aiohttp.ClientError: On connection or HTTP errors.
            ValueError: On unexpected response format.
        """
        params = {
            "latitude": str(self._latitude),
            "longitude": str(self._longitude),
            "hourly": "shortwave_radiation",
            "forecast_days": "2",
            "timezone": "auto",
        }

        url = f"{OPEN_METEO_URL}?{'&'.join(f'{k}={v}' for k, v in params.items())}"

        async with self._session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise ValueError(
                    f"Open-Meteo API returned HTTP {response.status}: {text}"
                )
            data = await response.json()

        # Validate response structure
        hourly = data.get("hourly")
        if not hourly:
            raise ValueError("Open-Meteo response missing 'hourly' data")

        times = hourly.get("time", [])
        radiation = hourly.get("shortwave_radiation", [])
        if not times or not radiation:
            raise ValueError(
                "Open-Meteo response missing time or radiation data"
            )

        return data

    def _compute_forecast(self, raw_data: dict[str, Any]) -> ForecastData:
        """Compute forecast data from Open-Meteo raw response.

        Estimates production for each hour, aggregates today/tomorrow totals,
        and identifies current hour power.

        Args:
            raw_data: The raw Open-Meteo API response.

        Returns:
            Computed ForecastData.
        """
        hourly = raw_data["hourly"]
        times = hourly["time"]
        radiation_values = hourly["shortwave_radiation"]

        now = datetime.now(timezone.utc)
        today_date = now.date()
        tomorrow_date = today_date + timedelta(days=1)

        today_energy_wh = 0.0
        tomorrow_energy_wh = 0.0
        current_hour_power_w = 0.0
        hourly_forecasts: list[HourlyForecast] = []

        for i, time_str in enumerate(times):
            if i >= len(radiation_values):
                break

            irradiance = radiation_values[i]
            if irradiance is None:
                irradiance = 0.0

            # Parse the timestamp
            try:
                # Open-Meteo returns ISO format timestamps like "2024-01-15T10:00"
                ts = datetime.fromisoformat(time_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            # Estimate power for this hour
            power_w = estimate_power_w(
                irradiance_wm2=float(irradiance),
                panel_area_m2=self._panel_area_m2,
                efficiency=self._efficiency,
                tilt_correction=self._tilt_correction,
            )

            # Each hour contributes power_w * 1h = power_w Wh to daily total
            ts_date = ts.date()
            if ts_date == today_date:
                today_energy_wh += power_w
            elif ts_date == tomorrow_date:
                tomorrow_energy_wh += power_w

            # Check if this is the current hour
            if (
                ts.date() == now.date()
                and ts.hour == now.hour
            ):
                current_hour_power_w = power_w

            # Build hourly forecast list (next 24 hours from now)
            if ts >= now and len(hourly_forecasts) < 24:
                hourly_forecasts.append(
                    HourlyForecast(
                        timestamp=ts,
                        estimated_power_w=power_w,
                        irradiance_wm2=float(irradiance),
                    )
                )

        return ForecastData(
            forecast_today_kwh=round(today_energy_wh / 1000.0, 2),
            forecast_tomorrow_kwh=round(tomorrow_energy_wh / 1000.0, 2),
            current_hour_power_w=round(current_hour_power_w, 1),
            hourly_forecast=hourly_forecasts,
            last_successful_update=now,
            is_stale=False,
        )


class ForecastCoordinator(DeyeForecastCoordinator):
    """Convenience wrapper that accepts a config entry for setup from __init__.py.

    This subclass extracts configuration from the config entry and station
    metadata to initialize the forecast coordinator.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        station_id: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize from config entry.

        Args:
            hass: The Home Assistant instance.
            station_id: The station ID to retrieve GPS coordinates for.
            entry: The config entry containing forecast configuration.
        """
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(hass)

        # Get station coordinates from entry data or options
        stations_data = entry.data.get("stations_metadata", {})
        station_info = stations_data.get(station_id, {})
        latitude = station_info.get("latitude", 0.0)
        longitude = station_info.get("longitude", 0.0)

        # Get forecast config from options or data
        options = entry.options if hasattr(entry, "options") and entry.options else {}
        panel_tilt = float(options.get("panel_tilt", entry.data.get("panel_tilt", DEFAULT_PANEL_TILT)))
        panel_azimuth = float(options.get("panel_azimuth", entry.data.get("panel_azimuth", DEFAULT_PANEL_AZIMUTH)))
        efficiency = float(options.get("system_efficiency", entry.data.get("system_efficiency", DEFAULT_SYSTEM_EFFICIENCY)))
        rated_power_kw = float(station_info.get("rated_capacity_kwp", entry.data.get("rated_power_kw", 5.0)))

        super().__init__(
            hass=hass,
            session=session,
            latitude=latitude,
            longitude=longitude,
            panel_tilt=panel_tilt,
            panel_azimuth=panel_azimuth,
            efficiency=efficiency,
            rated_power_kw=rated_power_kw,
        )
