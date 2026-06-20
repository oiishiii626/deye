"""Tests for the DeyeCloudAPI client."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.deye_cloud.api import BASE_URL, DeyeCloudAPI
from custom_components.deye_cloud.exceptions import (
    DeyeApiError,
    DeyeAuthError,
    DeyeConnectionError,
    DeyeRateLimitError,
    DeyeTimeoutError,
)
from custom_components.deye_cloud.models import TOUSchedule, TOUSlotData, TOUSlotMode


@pytest.fixture
def mock_session():
    """Create a mock aiohttp ClientSession."""
    return MagicMock(spec=aiohttp.ClientSession)


@pytest.fixture
def api(mock_session):
    """Create a DeyeCloudAPI instance with mock session."""
    return DeyeCloudAPI(mock_session, "test_app_id", "test_app_secret")


def _make_response(status=200, json_data=None, headers=None):
    """Create a mock response context manager."""
    response = AsyncMock()
    response.status = status
    response.json = AsyncMock(return_value=json_data or {})
    response.headers = headers or {}

    # Make it usable as async context manager
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestInit:
    """Test DeyeCloudAPI initialization."""

    def test_init_stores_credentials(self, mock_session):
        """Test that __init__ stores session, app_id, and app_secret."""
        api = DeyeCloudAPI(mock_session, "my_app_id", "my_secret")
        assert api._session is mock_session
        assert api._app_id == "my_app_id"
        assert api._app_secret == "my_secret"

    def test_init_no_token(self, api):
        """Test that token is initially None."""
        assert api.access_token is None
        assert api.token_expiry == 0.0


class TestAuthenticate:
    """Test the authenticate() method."""

    @pytest.mark.asyncio
    async def test_successful_authentication(self, api, mock_session):
        """Test successful token retrieval."""
        json_data = {
            "code": 0,
            "data": {
                "accessToken": "test_token_123",
                "expiresIn": 7200,
            },
        }
        mock_session.post = MagicMock(return_value=_make_response(200, json_data))

        token = await api.authenticate()

        assert token == "test_token_123"
        assert api.access_token == "test_token_123"
        assert api.token_expiry > time.time()

    @pytest.mark.asyncio
    async def test_auth_invalid_credentials_http_401(self, api, mock_session):
        """Test that HTTP 401 raises DeyeAuthError."""
        json_data = {"code": 401, "msg": "Unauthorized"}
        mock_session.post = MagicMock(return_value=_make_response(401, json_data))

        with pytest.raises(DeyeAuthError):
            await api.authenticate()

    @pytest.mark.asyncio
    async def test_auth_api_level_error(self, api, mock_session):
        """Test that non-zero API code raises appropriate error."""
        json_data = {"code": 1001, "msg": "Invalid AppId"}
        mock_session.post = MagicMock(return_value=_make_response(200, json_data))

        with pytest.raises(DeyeApiError):
            await api.authenticate()

    @pytest.mark.asyncio
    async def test_auth_timeout(self, api, mock_session):
        """Test that timeout raises DeyeTimeoutError."""
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=cm)

        with pytest.raises(DeyeTimeoutError):
            await api.authenticate()

    @pytest.mark.asyncio
    async def test_auth_connection_error(self, api, mock_session):
        """Test that connection error raises DeyeConnectionError."""
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientConnectorError(
                MagicMock(), OSError("Connection refused")
            )
        )
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=cm)

        with pytest.raises(DeyeConnectionError):
            await api.authenticate()

    @pytest.mark.asyncio
    async def test_auth_no_token_in_response(self, api, mock_session):
        """Test that missing token in response raises DeyeAuthError."""
        json_data = {"code": 0, "data": {}}
        mock_session.post = MagicMock(return_value=_make_response(200, json_data))

        with pytest.raises(DeyeAuthError, match="no access token"):
            await api.authenticate()


class TestEnsureToken:
    """Test the _ensure_token() method."""

    @pytest.mark.asyncio
    async def test_valid_token_no_refresh(self, api, mock_session):
        """Test that a valid token does not trigger refresh."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600  # Expires in 1 hour

        await api._ensure_token()
        # No calls should be made
        mock_session.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_token_near_expiry_refreshes(self, api, mock_session):
        """Test that token within 60s of expiry triggers refresh."""
        api._access_token = "old_token"
        api._token_expiry = time.time() + 30  # Within 60s window

        json_data = {
            "code": 0,
            "data": {"accessToken": "new_token", "expiresIn": 7200},
        }
        mock_session.post = MagicMock(return_value=_make_response(200, json_data))

        await api._ensure_token()

        assert api.access_token == "new_token"

    @pytest.mark.asyncio
    async def test_no_token_triggers_refresh(self, api, mock_session):
        """Test that missing token triggers authentication."""
        json_data = {
            "code": 0,
            "data": {"accessToken": "fresh_token", "expiresIn": 7200},
        }
        mock_session.post = MagicMock(return_value=_make_response(200, json_data))

        await api._ensure_token()

        assert api.access_token == "fresh_token"

    @pytest.mark.asyncio
    async def test_retry_with_backoff_on_timeout(self, api, mock_session):
        """Test exponential backoff on transient failures."""
        # First two attempts fail with timeout, third succeeds
        success_response = _make_response(
            200, {"code": 0, "data": {"accessToken": "retry_token", "expiresIn": 7200}}
        )

        timeout_cm = AsyncMock()
        timeout_cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        timeout_cm.__aexit__ = AsyncMock(return_value=False)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return timeout_cm
            return success_response

        mock_session.post = MagicMock(side_effect=side_effect)

        with patch("custom_components.deye_cloud.api.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await api._ensure_token()

        assert api.access_token == "retry_token"
        # Should have slept twice (between attempts 1-2 and 2-3)
        assert mock_sleep.call_count == 2
        # First delay: 2s, second delay: 4s
        mock_sleep.assert_any_call(2)
        mock_sleep.assert_any_call(4)

    @pytest.mark.asyncio
    async def test_auth_error_no_retry(self, api, mock_session):
        """Test that auth errors are raised immediately without retry."""
        json_data = {"code": 401, "msg": "Unauthorized"}
        mock_session.post = MagicMock(return_value=_make_response(401, json_data))

        with pytest.raises(DeyeAuthError):
            await api._ensure_token()

        # Should only be called once - no retry on auth errors
        assert mock_session.post.call_count == 1

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self, api, mock_session):
        """Test that DeyeAuthError is raised after all retries fail."""
        timeout_cm = AsyncMock()
        timeout_cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        timeout_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=timeout_cm)

        with patch("custom_components.deye_cloud.api.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(DeyeAuthError, match="failed after 3 attempts"):
                await api._ensure_token()

        assert mock_session.post.call_count == 3


class TestRequest:
    """Test the _request() method."""

    @pytest.mark.asyncio
    async def test_successful_request(self, api, mock_session):
        """Test a successful authenticated request."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {"code": 0, "data": {"devices": []}}
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        result = await api._request("POST", "/v1.0/device/list", payload={"stationId": "123"})

        assert result == response_data
        mock_session.request.assert_called_once()
        call_kwargs = mock_session.request.call_args
        assert "Bearer valid_token" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_request_includes_token_header(self, api, mock_session):
        """Test that request includes Authorization header with token."""
        api._access_token = "my_token"
        api._token_expiry = time.time() + 3600

        response_data = {"code": 0, "data": {}}
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        await api._request("POST", "/v1.0/station/list")

        call_args = mock_session.request.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer my_token"

    @pytest.mark.asyncio
    async def test_401_triggers_single_retry(self, api, mock_session):
        """Test that 401 response triggers token refresh and one retry."""
        api._access_token = "expired_token"
        api._token_expiry = time.time() + 3600

        # First request returns 401, then auth succeeds, then retry succeeds
        auth_response = _make_response(
            200, {"code": 0, "data": {"accessToken": "new_token", "expiresIn": 7200}}
        )
        success_response = _make_response(200, {"code": 0, "data": {"result": "ok"}})
        fail_response = _make_response(401, {"code": 401, "msg": "Unauthorized"})

        request_calls = []

        def request_side_effect(*args, **kwargs):
            request_calls.append((args, kwargs))
            if len(request_calls) == 1:
                return fail_response
            return success_response

        mock_session.request = MagicMock(side_effect=request_side_effect)
        mock_session.post = MagicMock(return_value=auth_response)

        result = await api._request("POST", "/v1.0/device/list")

        assert result == {"code": 0, "data": {"result": "ok"}}

    @pytest.mark.asyncio
    async def test_401_no_infinite_retry(self, api, mock_session):
        """Test that 401 on retry does not loop infinitely."""
        api._access_token = "bad_token"
        api._token_expiry = time.time() + 3600

        fail_response = _make_response(401, {"code": 401, "msg": "Unauthorized"})
        auth_response = _make_response(
            200, {"code": 0, "data": {"accessToken": "still_bad", "expiresIn": 7200}}
        )

        mock_session.request = MagicMock(return_value=fail_response)
        mock_session.post = MagicMock(return_value=auth_response)

        with pytest.raises(DeyeAuthError):
            await api._request("POST", "/v1.0/device/list")

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, api, mock_session):
        """Test that 429 response raises DeyeRateLimitError."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(429, {}, headers={"Retry-After": "120"})
        )

        with pytest.raises(DeyeRateLimitError) as exc_info:
            await api._request("POST", "/v1.0/device/list")

        assert exc_info.value.retry_after == 120

    @pytest.mark.asyncio
    async def test_api_error_non_401(self, api, mock_session):
        """Test that non-401 4xx raises DeyeApiError."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(400, {"code": 1001, "msg": "Bad request"})
        )

        with pytest.raises(DeyeApiError) as exc_info:
            await api._request("POST", "/v1.0/device/list")

        assert exc_info.value.error_code is not None

    @pytest.mark.asyncio
    async def test_timeout_raises_error(self, api, mock_session):
        """Test that request timeout raises DeyeTimeoutError."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        timeout_cm = AsyncMock()
        timeout_cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        timeout_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.request = MagicMock(return_value=timeout_cm)

        with pytest.raises(DeyeTimeoutError):
            await api._request("POST", "/v1.0/device/list")

    @pytest.mark.asyncio
    async def test_connection_error(self, api, mock_session):
        """Test that connection errors raise DeyeConnectionError."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        conn_cm = AsyncMock()
        conn_cm.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientConnectorError(
                MagicMock(), OSError("Connection refused")
            )
        )
        conn_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.request = MagicMock(return_value=conn_cm)

        with pytest.raises(DeyeConnectionError):
            await api._request("POST", "/v1.0/device/list")

    @pytest.mark.asyncio
    async def test_ensures_token_before_request(self, api, mock_session):
        """Test that _request calls _ensure_token before making the request."""
        # No token set - _ensure_token should authenticate first
        auth_response = _make_response(
            200, {"code": 0, "data": {"accessToken": "auto_token", "expiresIn": 7200}}
        )
        success_response = _make_response(200, {"code": 0, "data": {}})

        mock_session.post = MagicMock(return_value=auth_response)
        mock_session.request = MagicMock(return_value=success_response)

        result = await api._request("POST", "/v1.0/station/list")

        # authenticate() should have been called via _ensure_token
        mock_session.post.assert_called_once()
        assert api.access_token == "auto_token"


class TestGetStationList:
    """Test the get_station_list() method."""

    @pytest.mark.asyncio
    async def test_successful_station_list(self, api, mock_session):
        """Test successful station list retrieval."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {
            "code": 0,
            "data": {
                "stationList": [
                    {
                        "id": "station_001",
                        "name": "Home Solar",
                        "latitude": 51.5074,
                        "longitude": -0.1278,
                        "ratedCapacity": 10.5,
                    },
                    {
                        "id": "station_002",
                        "name": "Office Solar",
                        "latitude": 48.8566,
                        "longitude": 2.3522,
                        "ratedCapacity": 25.0,
                    },
                ]
            },
        }
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        stations = await api.get_station_list()

        assert len(stations) == 2
        assert stations[0].station_id == "station_001"
        assert stations[0].name == "Home Solar"
        assert stations[0].latitude == 51.5074
        assert stations[0].longitude == -0.1278
        assert stations[0].rated_capacity_kwp == 10.5
        assert stations[1].station_id == "station_002"
        assert stations[1].name == "Office Solar"

    @pytest.mark.asyncio
    async def test_empty_station_list(self, api, mock_session):
        """Test that empty station list returns empty list gracefully."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {"code": 0, "data": {"stationList": []}}
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        stations = await api.get_station_list()

        assert stations == []

    @pytest.mark.asyncio
    async def test_station_list_with_alternative_field_names(self, api, mock_session):
        """Test parsing with alternative API field names."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {
            "code": 0,
            "data": {
                "stationList": [
                    {
                        "stationId": "alt_station",
                        "stationName": "Alt Name",
                        "lat": 40.0,
                        "lng": -74.0,
                        "installedCapacity": 5.0,
                    }
                ]
            },
        }
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        stations = await api.get_station_list()

        assert len(stations) == 1
        assert stations[0].station_id == "alt_station"
        assert stations[0].name == "Alt Name"
        assert stations[0].latitude == 40.0
        assert stations[0].longitude == -74.0
        assert stations[0].rated_capacity_kwp == 5.0

    @pytest.mark.asyncio
    async def test_station_list_missing_data_field(self, api, mock_session):
        """Test handling when data field is missing or unexpected format."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {"code": 0, "data": {}}
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        stations = await api.get_station_list()

        assert stations == []

    @pytest.mark.asyncio
    async def test_station_list_null_stationlist(self, api, mock_session):
        """Test handling when stationList is None."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {"code": 0, "data": {"stationList": None}}
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        stations = await api.get_station_list()

        assert stations == []

    @pytest.mark.asyncio
    async def test_station_list_defaults_for_missing_fields(self, api, mock_session):
        """Test that missing optional fields use sensible defaults."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {
            "code": 0,
            "data": {
                "stationList": [
                    {
                        "id": "minimal_station",
                    }
                ]
            },
        }
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        stations = await api.get_station_list()

        assert len(stations) == 1
        assert stations[0].station_id == "minimal_station"
        assert stations[0].name == ""
        assert stations[0].latitude == 0.0
        assert stations[0].longitude == 0.0
        assert stations[0].rated_capacity_kwp == 0.0


class TestGetDeviceList:
    """Test the get_device_list() method."""

    @pytest.mark.asyncio
    async def test_successful_device_list(self, api, mock_session):
        """Test successful device list retrieval."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {
            "code": 0,
            "data": {
                "deviceList": [
                    {
                        "deviceSn": "SN123456",
                        "modelName": "SUN-8K-SG04LP3",
                        "firmwareVersion": "1.2.3",
                        "ratedPower": 8000,
                        "phaseCount": 3,
                        "mpptCount": 2,
                        "hasBattery": True,
                        "hasSmartLoad": True,
                        "smartLoadChannels": 2,
                        "supportedWorkModes": [0, 1, 2, 3],
                        "supportedEnergyPatterns": [0, 1],
                        "batterySocMin": 10,
                        "batterySocMax": 100,
                        "batteryChargeCurrentMax": 25.0,
                        "batteryDischargeCurrentMax": 25.0,
                    }
                ]
            },
        }
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        devices = await api.get_device_list("station_001")

        assert len(devices) == 1
        device = devices[0]
        assert device.device_sn == "SN123456"
        assert device.station_id == "station_001"
        assert device.model_name == "SUN-8K-SG04LP3"
        assert device.firmware_version == "1.2.3"
        assert device.rated_power_w == 8000
        assert device.phase_count == 3
        assert device.mppt_count == 2
        assert device.has_battery is True
        assert device.has_smart_load is True
        assert device.smart_load_channels == 2
        assert len(device.supported_work_modes) == 4
        assert len(device.supported_energy_patterns) == 2
        assert device.battery_soc_min == 10
        assert device.battery_soc_max == 100
        assert device.battery_charge_current_max == 25.0
        assert device.battery_discharge_current_max == 25.0

    @pytest.mark.asyncio
    async def test_empty_device_list(self, api, mock_session):
        """Test that empty device list returns empty list gracefully."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {"code": 0, "data": {"deviceList": []}}
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        devices = await api.get_device_list("station_001")

        assert devices == []

    @pytest.mark.asyncio
    async def test_device_list_with_alternative_field_names(self, api, mock_session):
        """Test parsing with alternative API field names."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {
            "code": 0,
            "data": {
                "deviceList": [
                    {
                        "sn": "ALT_SN",
                        "model": "SUN-5K",
                        "fwVersion": "2.0.0",
                        "ratedPowerW": 5000,
                        "phases": 1,
                        "mpptChannels": 2,
                        "batteryEnabled": True,
                        "smartLoadEnabled": False,
                        "smartLoadCount": 0,
                        "supportedWorkModes": [0, 1],
                        "supportedEnergyPatterns": [0],
                        "socMin": 15,
                        "socMax": 95,
                        "chargeCurrentMax": 20.0,
                        "dischargeCurrentMax": 20.0,
                    }
                ]
            },
        }
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        devices = await api.get_device_list("station_002")

        assert len(devices) == 1
        device = devices[0]
        assert device.device_sn == "ALT_SN"
        assert device.station_id == "station_002"
        assert device.model_name == "SUN-5K"
        assert device.firmware_version == "2.0.0"
        assert device.rated_power_w == 5000
        assert device.phase_count == 1
        assert device.mppt_count == 2
        assert device.has_battery is True
        assert device.has_smart_load is False
        assert device.smart_load_channels == 0
        assert device.battery_soc_min == 15
        assert device.battery_soc_max == 95
        assert device.battery_charge_current_max == 20.0
        assert device.battery_discharge_current_max == 20.0

    @pytest.mark.asyncio
    async def test_device_list_defaults_for_missing_fields(self, api, mock_session):
        """Test that missing optional fields use sensible defaults."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {
            "code": 0,
            "data": {
                "deviceList": [
                    {
                        "deviceSn": "MINIMAL_SN",
                    }
                ]
            },
        }
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        devices = await api.get_device_list("station_001")

        assert len(devices) == 1
        device = devices[0]
        assert device.device_sn == "MINIMAL_SN"
        assert device.station_id == "station_001"
        assert device.model_name == ""
        assert device.firmware_version == ""
        assert device.rated_power_w == 0
        assert device.phase_count == 1  # Sensible default
        assert device.mppt_count == 1  # Sensible default
        assert device.has_battery is False
        assert device.has_smart_load is False
        assert device.smart_load_channels == 0
        assert device.supported_work_modes == []
        assert device.supported_energy_patterns == []
        assert device.battery_soc_min == 10  # Default
        assert device.battery_soc_max == 100  # Default
        assert device.battery_charge_current_max == 0.0
        assert device.battery_discharge_current_max == 0.0

    @pytest.mark.asyncio
    async def test_device_list_invalid_work_modes_skipped(self, api, mock_session):
        """Test that invalid work mode values are skipped gracefully."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {
            "code": 0,
            "data": {
                "deviceList": [
                    {
                        "deviceSn": "SN_MODES",
                        "supportedWorkModes": [0, 99, 1, "invalid", 2],
                        "supportedEnergyPatterns": [0, 55, 1, None],
                    }
                ]
            },
        }
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        devices = await api.get_device_list("station_001")

        assert len(devices) == 1
        device = devices[0]
        # Only valid modes should be included
        from custom_components.deye_cloud.models import EnergyPattern, WorkMode

        assert device.supported_work_modes == [
            WorkMode.SELF_CONSUMPTION,
            WorkMode.TIME_OF_USE,
            WorkMode.SELLING_FIRST,
        ]
        assert device.supported_energy_patterns == [
            EnergyPattern.BATTERY_FIRST,
            EnergyPattern.LOAD_FIRST,
        ]

    @pytest.mark.asyncio
    async def test_device_list_passes_station_id_in_payload(self, api, mock_session):
        """Test that station_id is passed in the request payload."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {"code": 0, "data": {"deviceList": []}}
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        await api.get_device_list("my_station_123")

        call_args = mock_session.request.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json", {})
        assert payload == {"stationId": "my_station_123"}

    @pytest.mark.asyncio
    async def test_device_list_null_devicelist(self, api, mock_session):
        """Test handling when deviceList is None."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {"code": 0, "data": {"deviceList": None}}
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        devices = await api.get_device_list("station_001")

        assert devices == []

    @pytest.mark.asyncio
    async def test_device_list_multiple_devices(self, api, mock_session):
        """Test retrieving multiple devices from a single station."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {
            "code": 0,
            "data": {
                "deviceList": [
                    {"deviceSn": "SN_001", "modelName": "Model A", "ratedPower": 5000},
                    {"deviceSn": "SN_002", "modelName": "Model B", "ratedPower": 8000},
                    {"deviceSn": "SN_003", "modelName": "Model C", "ratedPower": 10000},
                ]
            },
        }
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        devices = await api.get_device_list("station_multi")

        assert len(devices) == 3
        assert devices[0].device_sn == "SN_001"
        assert devices[0].rated_power_w == 5000
        assert devices[1].device_sn == "SN_002"
        assert devices[1].rated_power_w == 8000
        assert devices[2].device_sn == "SN_003"
        assert devices[2].rated_power_w == 10000
        # All devices should have the correct station_id
        for device in devices:
            assert device.station_id == "station_multi"



class TestGetDeviceLatest:
    """Test the get_device_latest() method."""

    @pytest.mark.asyncio
    async def test_successful_get_device_latest(self, api, mock_session):
        """Test successful retrieval of latest device data."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {
            "code": 0,
            "data": {
                "pv_power": 3500,
                "battery_soc": 85,
                "grid_power": -200,
            },
        }
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        result = await api.get_device_latest("INV001", ["pv_power", "battery_soc", "grid_power"])

        assert result == {"pv_power": 3500, "battery_soc": 85, "grid_power": -200}
        call_args = mock_session.request.call_args
        assert call_args[0][0] == "POST"
        assert "/v1.0/device/latest" in call_args[0][1]
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["deviceSn"] == "INV001"
        assert payload["measurePoints"] == ["pv_power", "battery_soc", "grid_power"]

    @pytest.mark.asyncio
    async def test_get_device_latest_api_error(self, api, mock_session):
        """Test that API error is raised on failure."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 1001, "msg": "Device not found"})
        )

        with pytest.raises(DeyeApiError):
            await api.get_device_latest("INVALID_SN", ["pv_power"])

    @pytest.mark.asyncio
    async def test_get_device_latest_empty_data(self, api, mock_session):
        """Test handling of response with no data field."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 0})
        )

        result = await api.get_device_latest("INV001", ["pv_power"])
        assert result == {}


class TestSetDeviceConfig:
    """Test the set_device_config() method."""

    @pytest.mark.asyncio
    async def test_successful_set_device_config(self, api, mock_session):
        """Test successful device configuration update."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 0, "data": {}})
        )

        params = {"batterySocMin": 20, "gridExportLimit": 5000}
        result = await api.set_device_config("INV001", params)

        assert result is True
        call_args = mock_session.request.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["deviceSn"] == "INV001"
        assert payload["batterySocMin"] == 20
        assert payload["gridExportLimit"] == 5000

    @pytest.mark.asyncio
    async def test_set_device_config_api_error(self, api, mock_session):
        """Test that API error is raised on config failure."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 1002, "msg": "Invalid parameter"})
        )

        with pytest.raises(DeyeApiError):
            await api.set_device_config("INV001", {"invalidParam": 999})


class TestSetWorkMode:
    """Test the set_work_mode() method."""

    @pytest.mark.asyncio
    async def test_successful_set_work_mode(self, api, mock_session):
        """Test successful work mode change."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 0, "data": {}})
        )

        result = await api.set_work_mode("INV001", 1)

        assert result is True
        call_args = mock_session.request.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["deviceSn"] == "INV001"
        assert payload["workMode"] == 1

    @pytest.mark.asyncio
    async def test_set_work_mode_api_error(self, api, mock_session):
        """Test that API error is raised for invalid mode."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 1003, "msg": "Unsupported mode"})
        )

        with pytest.raises(DeyeApiError):
            await api.set_work_mode("INV001", 99)


class TestSetEnergyPattern:
    """Test the set_energy_pattern() method."""

    @pytest.mark.asyncio
    async def test_successful_set_energy_pattern(self, api, mock_session):
        """Test successful energy pattern change."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 0, "data": {}})
        )

        result = await api.set_energy_pattern("INV001", 0)

        assert result is True
        call_args = mock_session.request.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["deviceSn"] == "INV001"
        assert payload["energyPattern"] == 0

    @pytest.mark.asyncio
    async def test_set_energy_pattern_api_error(self, api, mock_session):
        """Test that API error is raised on failure."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 1004, "msg": "Pattern rejected"})
        )

        with pytest.raises(DeyeApiError):
            await api.set_energy_pattern("INV001", 5)


class TestSetTouSchedule:
    """Test the set_tou_schedule() method."""

    @pytest.mark.asyncio
    async def test_successful_set_tou_schedule(self, api, mock_session):
        """Test successful TOU schedule update."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 0, "data": {}})
        )

        schedule = TOUSchedule(
            enabled=True,
            slots=[
                TOUSlotData(
                    slot_index=0,
                    start_time="00:00",
                    end_time="06:00",
                    mode=TOUSlotMode.CHARGING,
                    power_limit_w=3000,
                ),
                TOUSlotData(
                    slot_index=1,
                    start_time="06:00",
                    end_time="22:00",
                    mode=TOUSlotMode.DISCHARGING,
                    power_limit_w=5000,
                ),
            ],
        )
        result = await api.set_tou_schedule("INV001", schedule)

        assert result is True
        call_args = mock_session.request.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["deviceSn"] == "INV001"
        assert payload["enabled"] is True
        assert len(payload["slots"]) == 2
        assert payload["slots"][0]["slotIndex"] == 0
        assert payload["slots"][0]["startTime"] == "00:00"
        assert payload["slots"][0]["endTime"] == "06:00"
        assert payload["slots"][0]["mode"] == "charging"
        assert payload["slots"][0]["powerLimitW"] == 3000
        assert payload["slots"][1]["slotIndex"] == 1
        assert payload["slots"][1]["mode"] == "discharging"

    @pytest.mark.asyncio
    async def test_set_tou_schedule_empty_slots(self, api, mock_session):
        """Test TOU schedule with no slots (disable)."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 0, "data": {}})
        )

        schedule = TOUSchedule(enabled=False, slots=[])
        result = await api.set_tou_schedule("INV001", schedule)

        assert result is True
        call_args = mock_session.request.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["enabled"] is False
        assert payload["slots"] == []


class TestSetSmartLoad:
    """Test the set_smart_load() method."""

    @pytest.mark.asyncio
    async def test_successful_set_smart_load_on(self, api, mock_session):
        """Test enabling a smart load channel."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 0, "data": {}})
        )

        result = await api.set_smart_load("INV001", 1, True)

        assert result is True
        call_args = mock_session.request.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["deviceSn"] == "INV001"
        assert payload["channel"] == 1
        assert payload["on"] is True

    @pytest.mark.asyncio
    async def test_successful_set_smart_load_off(self, api, mock_session):
        """Test disabling a smart load channel."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 0, "data": {}})
        )

        result = await api.set_smart_load("INV001", 2, False)

        assert result is True
        call_args = mock_session.request.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["channel"] == 2
        assert payload["on"] is False

    @pytest.mark.asyncio
    async def test_set_smart_load_api_error(self, api, mock_session):
        """Test that API error is raised on failure."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 1005, "msg": "Channel not available"})
        )

        with pytest.raises(DeyeApiError):
            await api.set_smart_load("INV001", 5, True)


class TestSendModbusCommand:
    """Test the send_modbus_command() method."""

    @pytest.mark.asyncio
    async def test_successful_modbus_command(self, api, mock_session):
        """Test successful Modbus command."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {
            "code": 0,
            "data": {"register": 100, "value": 42, "status": "ok"},
        }
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        result = await api.send_modbus_command("INV001", 100, 42)

        assert result == {"register": 100, "value": 42, "status": "ok"}
        call_args = mock_session.request.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["deviceSn"] == "INV001"
        assert payload["register"] == 100
        assert payload["value"] == 42

    @pytest.mark.asyncio
    async def test_modbus_command_api_error(self, api, mock_session):
        """Test that API error is raised on Modbus failure."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 1006, "msg": "Register read-only"})
        )

        with pytest.raises(DeyeApiError):
            await api.send_modbus_command("INV001", 50, 999)


class TestGetControlStrategy:
    """Test the get_control_strategy() method."""

    @pytest.mark.asyncio
    async def test_successful_get_strategy(self, api, mock_session):
        """Test successful strategy retrieval."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        response_data = {
            "code": 0,
            "data": {
                "workMode": 1,
                "energyPattern": 0,
                "batterySocMin": 15,
            },
        }
        mock_session.request = MagicMock(
            return_value=_make_response(200, response_data)
        )

        result = await api.get_control_strategy("INV001")

        assert result == {"workMode": 1, "energyPattern": 0, "batterySocMin": 15}
        call_args = mock_session.request.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["deviceSn"] == "INV001"

    @pytest.mark.asyncio
    async def test_get_strategy_api_error(self, api, mock_session):
        """Test that API error is raised on failure."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 1007, "msg": "Device offline"})
        )

        with pytest.raises(DeyeApiError):
            await api.get_control_strategy("INV001")


class TestSetControlStrategy:
    """Test the set_control_strategy() method."""

    @pytest.mark.asyncio
    async def test_successful_set_strategy(self, api, mock_session):
        """Test successful strategy update."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 0, "data": {}})
        )

        strategy = {
            "workMode": 2,
            "energyPattern": 1,
            "batterySocMin": 20,
            "gridExportLimit": 3000,
        }
        result = await api.set_control_strategy("INV001", strategy)

        assert result is True
        call_args = mock_session.request.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["deviceSn"] == "INV001"
        assert payload["workMode"] == 2
        assert payload["energyPattern"] == 1
        assert payload["batterySocMin"] == 20
        assert payload["gridExportLimit"] == 3000

    @pytest.mark.asyncio
    async def test_set_strategy_api_error(self, api, mock_session):
        """Test that API error is raised on failure."""
        api._access_token = "valid_token"
        api._token_expiry = time.time() + 3600

        mock_session.request = MagicMock(
            return_value=_make_response(200, {"code": 1008, "msg": "Strategy rejected"})
        )

        with pytest.raises(DeyeApiError):
            await api.set_control_strategy("INV001", {"invalidKey": True})
