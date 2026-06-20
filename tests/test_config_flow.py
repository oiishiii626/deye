"""Tests for the Deye Cloud config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.deye_cloud.config_flow import (
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_INVERTERS,
    CONF_STATIONS,
    DeyeCloudConfigFlow,
)
from custom_components.deye_cloud.const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from custom_components.deye_cloud.exceptions import DeyeAuthError, DeyeConnectionError
from custom_components.deye_cloud.models import Device, Station

from homeassistant.const import CONF_SCAN_INTERVAL


def _make_station(station_id: str = "st1", name: str = "Home") -> Station:
    """Create a test station."""
    return Station(
        station_id=station_id,
        name=name,
        latitude=51.5,
        longitude=-0.12,
        rated_capacity_kwp=10.0,
    )


def _make_device(device_sn: str = "SN001", station_id: str = "st1") -> Device:
    """Create a test device."""
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
def mock_api():
    """Create a mock DeyeCloudAPI."""
    with patch(
        "custom_components.deye_cloud.config_flow.DeyeCloudAPI"
    ) as mock_cls:
        api_instance = AsyncMock()
        api_instance.authenticate = AsyncMock(return_value="test_token")
        api_instance.get_station_list = AsyncMock(
            return_value=[_make_station()]
        )
        api_instance.get_device_list = AsyncMock(
            return_value=[_make_device()]
        )
        mock_cls.return_value = api_instance
        yield api_instance


@pytest.fixture
def mock_hass():
    """Create a minimal mock hass for ConfigFlow."""
    hass = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[])
    return hass


@pytest.fixture
def flow(mock_hass):
    """Create a config flow instance with mocked hass."""
    flow = DeyeCloudConfigFlow()
    flow.hass = mock_hass
    # Mock the unique ID methods
    flow.async_set_unique_id = AsyncMock(return_value=None)
    flow._abort_if_unique_id_configured = MagicMock()
    return flow


class TestUserStep:
    """Test the user (credentials) step."""

    @pytest.mark.asyncio
    async def test_shows_form_on_first_call(self, flow):
        """Test that step_user shows the form when no input is provided."""
        result = await flow.async_step_user(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert result["errors"] == {}

    @pytest.mark.asyncio
    async def test_invalid_auth_shows_error(self, flow):
        """Test that invalid credentials shows error and stays on form."""
        with patch(
            "custom_components.deye_cloud.config_flow.DeyeCloudAPI"
        ) as mock_cls:
            api = AsyncMock()
            api.authenticate = AsyncMock(side_effect=DeyeAuthError("Invalid"))
            mock_cls.return_value = api

            result = await flow.async_step_user(
                user_input={
                    CONF_APP_ID: "bad_id",
                    CONF_APP_SECRET: "bad_secret",
                    CONF_SCAN_INTERVAL: 60,
                }
            )

        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert result["errors"]["base"] == "invalid_auth"

    @pytest.mark.asyncio
    async def test_connection_error_shows_error(self, flow):
        """Test that connection failure shows error and stays on form."""
        with patch(
            "custom_components.deye_cloud.config_flow.DeyeCloudAPI"
        ) as mock_cls:
            api = AsyncMock()
            api.authenticate = AsyncMock(
                side_effect=DeyeConnectionError("Cannot connect")
            )
            mock_cls.return_value = api

            result = await flow.async_step_user(
                user_input={
                    CONF_APP_ID: "my_id",
                    CONF_APP_SECRET: "my_secret",
                    CONF_SCAN_INTERVAL: 60,
                }
            )

        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert result["errors"]["base"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_no_devices_aborts(self, flow):
        """Test that finding zero stations/devices aborts the flow."""
        with patch(
            "custom_components.deye_cloud.config_flow.DeyeCloudAPI"
        ) as mock_cls:
            api = AsyncMock()
            api.authenticate = AsyncMock(return_value="token")
            api.get_station_list = AsyncMock(return_value=[])
            mock_cls.return_value = api

            result = await flow.async_step_user(
                user_input={
                    CONF_APP_ID: "my_id",
                    CONF_APP_SECRET: "my_secret",
                    CONF_SCAN_INTERVAL: 60,
                }
            )

        assert result["type"] == "abort"
        assert result["reason"] == "no_devices"

    @pytest.mark.asyncio
    async def test_successful_auth_proceeds_to_select_devices(self, flow, mock_api):
        """Test that successful auth advances to device selection step."""
        result = await flow.async_step_user(
            user_input={
                CONF_APP_ID: "good_id",
                CONF_APP_SECRET: "good_secret",
                CONF_SCAN_INTERVAL: 60,
            }
        )

        assert result["type"] == "form"
        assert result["step_id"] == "select_devices"

    @pytest.mark.asyncio
    async def test_duplicate_app_id_aborts(self, flow):
        """Test that duplicate app_id config entry is aborted."""
        from homeassistant.data_entry_flow import AbortFlow

        flow._abort_if_unique_id_configured = MagicMock(
            side_effect=AbortFlow("already_configured")
        )

        with pytest.raises(AbortFlow) as exc_info:
            await flow.async_step_user(
                user_input={
                    CONF_APP_ID: "existing_id",
                    CONF_APP_SECRET: "secret",
                    CONF_SCAN_INTERVAL: 60,
                }
            )

        assert exc_info.value.reason == "already_configured"


class TestSelectDevicesStep:
    """Test the device selection step."""

    @pytest.mark.asyncio
    async def test_shows_device_selection_form(self, flow, mock_api):
        """Test that select_devices step shows a form with discovered devices."""
        # First go through user step to populate stations/devices
        await flow.async_step_user(
            user_input={
                CONF_APP_ID: "my_id",
                CONF_APP_SECRET: "my_secret",
                CONF_SCAN_INTERVAL: 60,
            }
        )

        # Now call select_devices with no input to verify the form
        result = await flow.async_step_select_devices(user_input=None)

        assert result["type"] == "form"
        assert result["step_id"] == "select_devices"

    @pytest.mark.asyncio
    async def test_creates_entry_with_selected_devices(self, flow, mock_api):
        """Test that selecting devices creates a config entry."""
        # Go through user step
        await flow.async_step_user(
            user_input={
                CONF_APP_ID: "my_id",
                CONF_APP_SECRET: "my_secret",
                CONF_SCAN_INTERVAL: 90,
            }
        )

        # Select devices
        result = await flow.async_step_select_devices(
            user_input={
                CONF_INVERTERS: ["SN001"],
                CONF_STATIONS: ["st1"],
            }
        )

        assert result["type"] == "create_entry"
        assert result["title"] == "Deye Cloud (my_id)"
        assert result["data"][CONF_APP_ID] == "my_id"
        assert result["data"][CONF_APP_SECRET] == "my_secret"
        assert result["data"][CONF_SCAN_INTERVAL] == 90
        assert result["data"][CONF_INVERTERS] == ["SN001"]
        assert result["data"][CONF_STATIONS] == ["st1"]

    @pytest.mark.asyncio
    async def test_no_selection_shows_error(self, flow, mock_api):
        """Test that selecting nothing shows a no_devices error."""
        # Go through user step
        await flow.async_step_user(
            user_input={
                CONF_APP_ID: "my_id",
                CONF_APP_SECRET: "my_secret",
                CONF_SCAN_INTERVAL: 60,
            }
        )

        # Select nothing
        result = await flow.async_step_select_devices(
            user_input={
                CONF_INVERTERS: [],
                CONF_STATIONS: [],
            }
        )

        assert result["type"] == "form"
        assert result["step_id"] == "select_devices"
        assert result["errors"]["base"] == "no_devices"

    @pytest.mark.asyncio
    async def test_multiple_stations_and_devices(self, flow):
        """Test discovery of multiple stations each with multiple devices."""
        station1 = _make_station("st1", "Home")
        station2 = _make_station("st2", "Office")
        device1 = _make_device("SN001", "st1")
        device2 = _make_device("SN002", "st1")
        device3 = _make_device("SN003", "st2")

        with patch(
            "custom_components.deye_cloud.config_flow.DeyeCloudAPI"
        ) as mock_cls:
            api = AsyncMock()
            api.authenticate = AsyncMock(return_value="token")
            api.get_station_list = AsyncMock(return_value=[station1, station2])
            api.get_device_list = AsyncMock(
                side_effect=lambda sid: [device1, device2] if sid == "st1" else [device3]
            )
            mock_cls.return_value = api

            await flow.async_step_user(
                user_input={
                    CONF_APP_ID: "my_id",
                    CONF_APP_SECRET: "my_secret",
                    CONF_SCAN_INTERVAL: 60,
                }
            )

        # Select only some devices
        result = await flow.async_step_select_devices(
            user_input={
                CONF_INVERTERS: ["SN001", "SN003"],
                CONF_STATIONS: ["st1"],
            }
        )

        assert result["type"] == "create_entry"
        assert result["data"][CONF_INVERTERS] == ["SN001", "SN003"]
        assert result["data"][CONF_STATIONS] == ["st1"]
