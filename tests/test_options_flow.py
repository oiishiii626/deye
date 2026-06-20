"""Tests for the Deye Cloud options flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.deye_cloud.config_flow import (
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_INVERTERS,
    CONF_PANEL_AZIMUTH,
    CONF_PANEL_TILT,
    CONF_SYSTEM_EFFICIENCY,
    CONF_TARIFF_PERIODS,
    DeyeCloudOptionsFlowHandler,
)
from custom_components.deye_cloud.const import (
    DEFAULT_PANEL_AZIMUTH,
    DEFAULT_PANEL_TILT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SYSTEM_EFFICIENCY,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from custom_components.deye_cloud.exceptions import DeyeAuthError, DeyeConnectionError
from custom_components.deye_cloud.models import Device, Station

from homeassistant.const import CONF_SCAN_INTERVAL


def _make_station(station_id: str = "st1", name: str = "Home") -> Station:
    return Station(
        station_id=station_id,
        name=name,
        latitude=51.5,
        longitude=-0.12,
        rated_capacity_kwp=10.0,
    )


def _make_device(device_sn: str = "SN001", station_id: str = "st1") -> Device:
    return Device(
        device_sn=device_sn,
        station_id=station_id,
        model_name="SUN-8K-SG04LP3",
        firmware_version="1.0.0",
        rated_power_w=8000,
        phase_count=3,
        mppt_count=2,
        has_battery=True,
        has_smart_load=False,
        smart_load_channels=0,
    )


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.data = {
        CONF_APP_ID: "test_app_id",
        CONF_APP_SECRET: "test_app_secret",
        CONF_SCAN_INTERVAL: 60,
        CONF_INVERTERS: ["SN001"],
    }
    entry.options = {}
    return entry


@pytest.fixture
def options_flow(mock_config_entry):
    """Create an options flow handler instance."""
    flow = DeyeCloudOptionsFlowHandler(mock_config_entry)
    flow.hass = MagicMock()
    flow.hass.config_entries = MagicMock()
    flow.hass.config_entries.async_update_entry = MagicMock()
    return flow


class TestInitStep:
    """Test the init step (polling interval + forecast settings)."""

    @pytest.mark.asyncio
    async def test_shows_form_with_defaults(self, options_flow):
        """Test that init step shows form with current/default values."""
        result = await options_flow.async_step_init(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "init"
        assert result["errors"] == {}

    @pytest.mark.asyncio
    async def test_valid_input_proceeds_to_menu(self, options_flow):
        """Test valid options proceed to the menu step."""
        result = await options_flow.async_step_init(
            user_input={
                CONF_SCAN_INTERVAL: 120,
                CONF_PANEL_TILT: 45,
                CONF_PANEL_AZIMUTH: 200,
                CONF_SYSTEM_EFFICIENCY: 0.8,
            }
        )

        assert result["type"] == "menu"
        assert result["step_id"] == "menu"

    @pytest.mark.asyncio
    async def test_saves_options_correctly(self, options_flow):
        """Test that valid input saves all options."""
        await options_flow.async_step_init(
            user_input={
                CONF_SCAN_INTERVAL: 120,
                CONF_PANEL_TILT: 45,
                CONF_PANEL_AZIMUTH: 200,
                CONF_SYSTEM_EFFICIENCY: 0.8,
            }
        )

        assert options_flow.options[CONF_SCAN_INTERVAL] == 120
        assert options_flow.options[CONF_PANEL_TILT] == 45
        assert options_flow.options[CONF_PANEL_AZIMUTH] == 200
        assert options_flow.options[CONF_SYSTEM_EFFICIENCY] == 0.8

    @pytest.mark.asyncio
    async def test_efficiency_below_minimum_shows_error(self, options_flow):
        """Test that efficiency below 0.5 shows error."""
        result = await options_flow.async_step_init(
            user_input={
                CONF_SCAN_INTERVAL: 60,
                CONF_PANEL_TILT: 30,
                CONF_PANEL_AZIMUTH: 180,
                CONF_SYSTEM_EFFICIENCY: 0.3,
            }
        )

        assert result["type"] == "form"
        assert result["step_id"] == "init"
        assert CONF_SYSTEM_EFFICIENCY in result["errors"]

    @pytest.mark.asyncio
    async def test_efficiency_above_maximum_shows_error(self, options_flow):
        """Test that efficiency above 0.95 shows error."""
        result = await options_flow.async_step_init(
            user_input={
                CONF_SCAN_INTERVAL: 60,
                CONF_PANEL_TILT: 30,
                CONF_PANEL_AZIMUTH: 180,
                CONF_SYSTEM_EFFICIENCY: 0.99,
            }
        )

        assert result["type"] == "form"
        assert result["step_id"] == "init"
        assert CONF_SYSTEM_EFFICIENCY in result["errors"]


class TestDevicesStep:
    """Test the devices selection step."""

    @pytest.mark.asyncio
    async def test_shows_form_with_discovered_devices(self, options_flow):
        """Test that devices step shows a form after API discovery."""
        with patch(
            "custom_components.deye_cloud.config_flow.DeyeCloudAPI"
        ) as mock_cls:
            api = AsyncMock()
            api.authenticate = AsyncMock(return_value="token")
            api.get_station_list = AsyncMock(return_value=[_make_station()])
            api.get_device_list = AsyncMock(return_value=[_make_device()])
            mock_cls.return_value = api

            result = await options_flow.async_step_devices(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "devices"

    @pytest.mark.asyncio
    async def test_selecting_devices_saves_and_returns_to_menu(self, options_flow):
        """Test that selecting inverters saves and goes back to menu."""
        result = await options_flow.async_step_devices(
            user_input={CONF_INVERTERS: ["SN001", "SN002"]}
        )

        assert result["type"] == "menu"
        assert options_flow.options[CONF_INVERTERS] == ["SN001", "SN002"]

    @pytest.mark.asyncio
    async def test_no_selection_shows_error(self, options_flow):
        """Test that empty selection shows an error."""
        with patch(
            "custom_components.deye_cloud.config_flow.DeyeCloudAPI"
        ) as mock_cls:
            api = AsyncMock()
            api.authenticate = AsyncMock(return_value="token")
            api.get_station_list = AsyncMock(return_value=[_make_station()])
            api.get_device_list = AsyncMock(return_value=[_make_device()])
            mock_cls.return_value = api

            result = await options_flow.async_step_devices(
                user_input={CONF_INVERTERS: []}
            )

        assert result["type"] == "form"
        assert result["step_id"] == "devices"
        assert result["errors"]["base"] == "no_devices"

    @pytest.mark.asyncio
    async def test_api_failure_falls_back_to_current(self, options_flow):
        """Test that API failure uses currently configured inverters."""
        with patch(
            "custom_components.deye_cloud.config_flow.DeyeCloudAPI"
        ) as mock_cls:
            api = AsyncMock()
            api.authenticate = AsyncMock(
                side_effect=DeyeConnectionError("unreachable")
            )
            mock_cls.return_value = api

            result = await options_flow.async_step_devices(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "devices"


class TestCredentialsStep:
    """Test the credentials update step."""

    @pytest.mark.asyncio
    async def test_shows_form_with_current_credentials(self, options_flow):
        """Test that credentials step shows form."""
        result = await options_flow.async_step_credentials(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "credentials"

    @pytest.mark.asyncio
    async def test_valid_credentials_updates_entry(self, options_flow):
        """Test that valid new credentials update the config entry."""
        with patch(
            "custom_components.deye_cloud.config_flow.DeyeCloudAPI"
        ) as mock_cls:
            api = AsyncMock()
            api.authenticate = AsyncMock(return_value="new_token")
            mock_cls.return_value = api

            result = await options_flow.async_step_credentials(
                user_input={
                    CONF_APP_ID: "new_app_id",
                    CONF_APP_SECRET: "new_secret",
                }
            )

        assert result["type"] == "menu"
        options_flow.hass.config_entries.async_update_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_credentials_shows_error(self, options_flow):
        """Test that invalid credentials show auth error."""
        with patch(
            "custom_components.deye_cloud.config_flow.DeyeCloudAPI"
        ) as mock_cls:
            api = AsyncMock()
            api.authenticate = AsyncMock(side_effect=DeyeAuthError("Invalid"))
            mock_cls.return_value = api

            result = await options_flow.async_step_credentials(
                user_input={
                    CONF_APP_ID: "bad_id",
                    CONF_APP_SECRET: "bad_secret",
                }
            )

        assert result["type"] == "form"
        assert result["step_id"] == "credentials"
        assert result["errors"]["base"] == "invalid_auth"

    @pytest.mark.asyncio
    async def test_connection_error_shows_error(self, options_flow):
        """Test that connection failure shows cannot_connect error."""
        with patch(
            "custom_components.deye_cloud.config_flow.DeyeCloudAPI"
        ) as mock_cls:
            api = AsyncMock()
            api.authenticate = AsyncMock(
                side_effect=DeyeConnectionError("fail")
            )
            mock_cls.return_value = api

            result = await options_flow.async_step_credentials(
                user_input={
                    CONF_APP_ID: "id",
                    CONF_APP_SECRET: "secret",
                }
            )

        assert result["type"] == "form"
        assert result["step_id"] == "credentials"
        assert result["errors"]["base"] == "cannot_connect"


class TestTariffStep:
    """Test the tariff period configuration step."""

    @pytest.mark.asyncio
    async def test_shows_form(self, options_flow):
        """Test that tariff step shows a form."""
        result = await options_flow.async_step_tariff(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "tariff"

    @pytest.mark.asyncio
    async def test_valid_periods_saved(self, options_flow):
        """Test that valid tariff periods are saved."""
        periods = [
            {"start_time": "00:00", "end_time": "06:00", "category": "cheap"},
            {"start_time": "06:00", "end_time": "17:00", "category": "standard"},
        ]
        result = await options_flow.async_step_tariff(
            user_input={CONF_TARIFF_PERIODS: periods}
        )

        assert result["type"] == "menu"
        assert options_flow.options[CONF_TARIFF_PERIODS] == periods

    @pytest.mark.asyncio
    async def test_too_many_periods_shows_error(self, options_flow):
        """Test that more than 10 periods shows error."""
        periods = [
            {"start_time": f"{i:02d}:00", "end_time": f"{i:02d}:30", "category": "cheap"}
            for i in range(11)
        ]
        result = await options_flow.async_step_tariff(
            user_input={CONF_TARIFF_PERIODS: periods}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "tariff"
        assert result["errors"][CONF_TARIFF_PERIODS] == "too_many_periods"

    @pytest.mark.asyncio
    async def test_end_before_start_shows_error(self, options_flow):
        """Test that end time <= start time shows invalid_period error."""
        periods = [
            {"start_time": "10:00", "end_time": "08:00", "category": "peak"},
        ]
        result = await options_flow.async_step_tariff(
            user_input={CONF_TARIFF_PERIODS: periods}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "tariff"
        assert result["errors"][CONF_TARIFF_PERIODS] == "invalid_period"

    @pytest.mark.asyncio
    async def test_overlapping_periods_shows_error(self, options_flow):
        """Test that overlapping periods show overlapping_periods error."""
        periods = [
            {"start_time": "08:00", "end_time": "12:00", "category": "peak"},
            {"start_time": "10:00", "end_time": "14:00", "category": "standard"},
        ]
        result = await options_flow.async_step_tariff(
            user_input={CONF_TARIFF_PERIODS: periods}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "tariff"
        assert result["errors"][CONF_TARIFF_PERIODS] == "overlapping_periods"

    @pytest.mark.asyncio
    async def test_empty_periods_accepted(self, options_flow):
        """Test that empty period list is accepted."""
        result = await options_flow.async_step_tariff(
            user_input={CONF_TARIFF_PERIODS: []}
        )

        assert result["type"] == "menu"
        assert options_flow.options[CONF_TARIFF_PERIODS] == []

    @pytest.mark.asyncio
    async def test_invalid_time_format_shows_error(self, options_flow):
        """Test that invalid time format shows error."""
        periods = [
            {"start_time": "invalid", "end_time": "12:00", "category": "peak"},
        ]
        result = await options_flow.async_step_tariff(
            user_input={CONF_TARIFF_PERIODS: periods}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "tariff"
        assert result["errors"][CONF_TARIFF_PERIODS] == "invalid_period"


class TestFinishStep:
    """Test the finish step."""

    @pytest.mark.asyncio
    async def test_creates_entry_with_all_options(self, options_flow):
        """Test that finish creates an entry with accumulated options."""
        # Simulate having gone through init step
        options_flow.options.update({
            CONF_SCAN_INTERVAL: 120,
            CONF_PANEL_TILT: 45,
            CONF_PANEL_AZIMUTH: 200,
            CONF_SYSTEM_EFFICIENCY: 0.8,
        })

        result = await options_flow.async_step_finish(user_input=None)

        assert result["type"] == "create_entry"
        assert result["data"][CONF_SCAN_INTERVAL] == 120
        assert result["data"][CONF_PANEL_TILT] == 45
        assert result["data"][CONF_PANEL_AZIMUTH] == 200
        assert result["data"][CONF_SYSTEM_EFFICIENCY] == 0.8
