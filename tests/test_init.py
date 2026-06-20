"""Tests for Deye Cloud integration __init__.py (async_setup_entry / async_unload_entry)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta

from custom_components.deye_cloud import (
    async_setup_entry,
    async_unload_entry,
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_INVERTERS,
    CONF_STATIONS,
    CONF_TARIFF_PERIODS,
)
from custom_components.deye_cloud.const import DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS


@pytest.fixture
def mock_hass():
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


@pytest.fixture
def mock_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id_123"
    entry.data = {
        CONF_APP_ID: "test_app_id",
        CONF_APP_SECRET: "test_app_secret",
        "scan_interval": 60,
        CONF_INVERTERS: ["SN001", "SN002"],
        CONF_STATIONS: ["STATION_1"],
    }
    entry.options = {}
    entry.async_on_unload = MagicMock()
    entry.add_update_listener = MagicMock()
    return entry


@pytest.fixture
def mock_api():
    """Create a mock DeyeCloudAPI."""
    api = AsyncMock()
    api.authenticate = AsyncMock(return_value="test_token")
    return api


@pytest.fixture
def mock_coordinator():
    """Create a mock DeyeDeviceCoordinator."""
    coord = MagicMock()
    coord.async_config_entry_first_refresh = AsyncMock()
    return coord


@pytest.mark.asyncio
async def test_async_setup_entry_creates_coordinators(
    mock_hass, mock_entry, mock_api, mock_coordinator
):
    """Test that async_setup_entry creates coordinators for each inverter."""
    mock_forecast_coord = MagicMock()
    mock_forecast_coord.async_config_entry_first_refresh = AsyncMock()

    with (
        patch(
            "custom_components.deye_cloud.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.deye_cloud.DeyeCloudAPI",
            return_value=mock_api,
        ),
        patch(
            "custom_components.deye_cloud.DeyeDeviceCoordinator",
            return_value=mock_coordinator,
        ) as mock_coord_cls,
        patch(
            "custom_components.deye_cloud.forecast.ForecastCoordinator",
            return_value=mock_forecast_coord,
        ),
    ):
        result = await async_setup_entry(mock_hass, mock_entry)

    assert result is True
    # Should authenticate
    mock_api.authenticate.assert_awaited_once()
    # Should create 2 coordinators (one per inverter)
    assert mock_coord_cls.call_count == 2
    # Should call first refresh for each coordinator
    assert mock_coordinator.async_config_entry_first_refresh.await_count == 2
    # Should forward entry setup to all platforms
    mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        mock_entry, PLATFORMS
    )


@pytest.mark.asyncio
async def test_async_setup_entry_stores_data(
    mock_hass, mock_entry, mock_api, mock_coordinator
):
    """Test that async_setup_entry stores coordinators in hass.data."""
    mock_forecast_coord = MagicMock()
    mock_forecast_coord.async_config_entry_first_refresh = AsyncMock()

    with (
        patch(
            "custom_components.deye_cloud.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.deye_cloud.DeyeCloudAPI",
            return_value=mock_api,
        ),
        patch(
            "custom_components.deye_cloud.DeyeDeviceCoordinator",
            return_value=mock_coordinator,
        ),
        patch(
            "custom_components.deye_cloud.forecast.ForecastCoordinator",
            return_value=mock_forecast_coord,
        ),
    ):
        await async_setup_entry(mock_hass, mock_entry)

    assert DOMAIN in mock_hass.data
    assert mock_entry.entry_id in mock_hass.data[DOMAIN]
    entry_data = mock_hass.data[DOMAIN][mock_entry.entry_id]
    assert "api" in entry_data
    assert "device_coordinators" in entry_data
    assert "forecast_coordinators" in entry_data
    assert "tariff_managers" in entry_data
    # 2 inverters configured
    assert len(entry_data["device_coordinators"]) == 2
    assert "SN001" in entry_data["device_coordinators"]
    assert "SN002" in entry_data["device_coordinators"]


@pytest.mark.asyncio
async def test_async_setup_entry_uses_default_scan_interval(
    mock_hass, mock_api, mock_coordinator
):
    """Test that async_setup_entry uses default scan interval when not specified."""
    entry = MagicMock()
    entry.entry_id = "test_entry_no_interval"
    entry.data = {
        CONF_APP_ID: "test_app_id",
        CONF_APP_SECRET: "test_app_secret",
        CONF_INVERTERS: ["SN001"],
        CONF_STATIONS: [],
    }
    entry.options = {}

    with (
        patch(
            "custom_components.deye_cloud.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.deye_cloud.DeyeCloudAPI",
            return_value=mock_api,
        ),
        patch(
            "custom_components.deye_cloud.DeyeDeviceCoordinator",
            return_value=mock_coordinator,
        ) as mock_coord_cls,
    ):
        result = await async_setup_entry(mock_hass, entry)

    assert result is True
    # Verify coordinator was created with default interval
    call_kwargs = mock_coord_cls.call_args_list[0][1]
    assert call_kwargs["interval"] == timedelta(seconds=DEFAULT_SCAN_INTERVAL)


@pytest.mark.asyncio
async def test_async_setup_entry_no_inverters(mock_hass, mock_api):
    """Test setup with no inverters configured."""
    entry = MagicMock()
    entry.entry_id = "test_no_inverters"
    entry.data = {
        CONF_APP_ID: "test_app_id",
        CONF_APP_SECRET: "test_app_secret",
        CONF_INVERTERS: [],
        CONF_STATIONS: [],
    }
    entry.options = {}

    with (
        patch(
            "custom_components.deye_cloud.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.deye_cloud.DeyeCloudAPI",
            return_value=mock_api,
        ),
    ):
        result = await async_setup_entry(mock_hass, entry)

    assert result is True
    assert DOMAIN in mock_hass.data
    entry_data = mock_hass.data[DOMAIN][entry.entry_id]
    assert len(entry_data["device_coordinators"]) == 0


@pytest.mark.asyncio
async def test_async_unload_entry_success(mock_hass, mock_entry):
    """Test that async_unload_entry cleans up properly."""
    # Set up hass.data as if setup was already done
    mock_hass.data[DOMAIN] = {
        mock_entry.entry_id: {
            "api": MagicMock(),
            "device_coordinators": {"SN001": MagicMock()},
            "forecast_coordinators": {},
            "tariff_managers": {},
        }
    }

    result = await async_unload_entry(mock_hass, mock_entry)

    assert result is True
    # Platform unload should have been called
    mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(
        mock_entry, PLATFORMS
    )
    # Entry data should be cleaned up
    assert mock_entry.entry_id not in mock_hass.data.get(DOMAIN, {})


@pytest.mark.asyncio
async def test_async_unload_entry_stops_tariff_managers(mock_hass, mock_entry):
    """Test that async_unload_entry stops tariff managers."""
    mock_tariff_manager = MagicMock()
    mock_tariff_manager.async_stop = AsyncMock()

    mock_hass.data[DOMAIN] = {
        mock_entry.entry_id: {
            "api": MagicMock(),
            "device_coordinators": {"SN001": MagicMock()},
            "forecast_coordinators": {},
            "tariff_managers": {"SN001": mock_tariff_manager},
        }
    }

    result = await async_unload_entry(mock_hass, mock_entry)

    assert result is True
    mock_tariff_manager.async_stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_unload_entry_platform_failure(mock_hass, mock_entry):
    """Test that async_unload_entry returns False if platform unload fails."""
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
    mock_hass.data[DOMAIN] = {
        mock_entry.entry_id: {
            "api": MagicMock(),
            "device_coordinators": {},
            "forecast_coordinators": {},
            "tariff_managers": {},
        }
    }

    result = await async_unload_entry(mock_hass, mock_entry)

    assert result is False
    # Data should NOT be cleaned up on failure
    assert mock_entry.entry_id in mock_hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_setup_entry_forecast_import_error(
    mock_hass, mock_entry, mock_api, mock_coordinator
):
    """Test that missing forecast module is handled gracefully."""
    with (
        patch(
            "custom_components.deye_cloud.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.deye_cloud.DeyeCloudAPI",
            return_value=mock_api,
        ),
        patch(
            "custom_components.deye_cloud.DeyeDeviceCoordinator",
            return_value=mock_coordinator,
        ),
        patch.dict("sys.modules", {"custom_components.deye_cloud.forecast": None}),
    ):
        # Force the ImportError path by removing the forecast module
        result = await async_setup_entry(mock_hass, mock_entry)

    assert result is True
    # Forecast coordinators should be empty (import failed gracefully)
    entry_data = mock_hass.data[DOMAIN][mock_entry.entry_id]
    assert len(entry_data["forecast_coordinators"]) == 0


@pytest.mark.asyncio
async def test_async_unload_entry_cleans_domain_when_empty(mock_hass, mock_entry):
    """Test that DOMAIN key is removed from hass.data when last entry is unloaded."""
    mock_hass.data[DOMAIN] = {
        mock_entry.entry_id: {
            "api": MagicMock(),
            "device_coordinators": {},
            "forecast_coordinators": {},
            "tariff_managers": {},
        }
    }

    await async_unload_entry(mock_hass, mock_entry)

    # Domain should be fully removed when empty
    assert DOMAIN not in mock_hass.data
