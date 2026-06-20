"""Tests for the Deye Cloud diagnostics platform."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import asdict

from custom_components.deye_cloud.diagnostics import (
    REDACTED,
    REDACT_KEYS,
    _redact_config,
    async_get_config_entry_diagnostics,
)
from custom_components.deye_cloud.models import DeviceData, WorkMode, EnergyPattern


class TestRedactConfig:
    """Tests for _redact_config credential redaction."""

    def test_redacts_app_secret(self):
        """Sensitive keys containing 'app_secret' are redacted."""
        config = {"app_secret": "my-super-secret-value", "station_id": "S1"}
        result = _redact_config(config)
        assert result["app_secret"] == REDACTED
        assert result["station_id"] == "S1"

    def test_redacts_app_id(self):
        """Sensitive keys containing 'app_id' are redacted."""
        config = {"app_id": "12345", "scan_interval": 60}
        result = _redact_config(config)
        assert result["app_id"] == REDACTED
        assert result["scan_interval"] == 60

    def test_redacts_token(self):
        """Sensitive keys containing 'token' are redacted."""
        config = {"access_token": "abc123token", "device_sn": "INV001"}
        result = _redact_config(config)
        assert result["access_token"] == REDACTED
        assert result["device_sn"] == "INV001"

    def test_redacts_password(self):
        """Sensitive keys containing 'password' are redacted."""
        config = {"password": "hunter2", "username": "admin"}
        result = _redact_config(config)
        assert result["password"] == REDACTED
        assert result["username"] == "admin"

    def test_redacts_secret_in_key_name(self):
        """Any key with 'secret' substring is redacted."""
        config = {"my_secret_value": "hidden", "public_data": "visible"}
        result = _redact_config(config)
        assert result["my_secret_value"] == REDACTED
        assert result["public_data"] == "visible"

    def test_case_insensitive_redaction(self):
        """Redaction is case-insensitive for key matching."""
        config = {
            "APP_SECRET": "secret1",
            "App_Id": "id1",
            "Token": "tok1",
        }
        result = _redact_config(config)
        assert result["APP_SECRET"] == REDACTED
        assert result["App_Id"] == REDACTED
        assert result["Token"] == REDACTED

    def test_nested_dict_redaction(self):
        """Nested dictionaries are recursively redacted."""
        config = {
            "credentials": {
                "app_id": "12345",
                "app_secret": "secret-val",
            },
            "options": {
                "scan_interval": 60,
            },
        }
        result = _redact_config(config)
        assert result["credentials"]["app_id"] == REDACTED
        assert result["credentials"]["app_secret"] == REDACTED
        assert result["options"]["scan_interval"] == 60

    def test_empty_config(self):
        """Empty config returns empty dict."""
        assert _redact_config({}) == {}

    def test_non_sensitive_keys_preserved(self):
        """Non-sensitive keys pass through unchanged."""
        config = {
            "scan_interval": 60,
            "inverters": ["INV001", "INV002"],
            "stations": ["S1"],
        }
        result = _redact_config(config)
        assert result == config

    def test_redacted_value_is_string(self):
        """Redacted values are always the REDACTED string constant."""
        config = {"app_secret": 12345}  # numeric value
        result = _redact_config(config)
        assert result["app_secret"] == REDACTED
        assert isinstance(result["app_secret"], str)


class TestAsyncGetConfigEntryDiagnostics:
    """Tests for the full diagnostics function."""

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.data = {}
        return hass

    @pytest.fixture
    def mock_entry(self):
        """Create a mock config entry."""
        entry = MagicMock()
        entry.entry_id = "test_entry_123"
        entry.data = {
            "app_id": "my-app-id",
            "app_secret": "my-app-secret",
            "scan_interval": 60,
            "inverters": ["INV001"],
            "stations": ["S1"],
        }
        entry.options = {
            "scan_interval": 120,
        }
        return entry

    @pytest.fixture
    def mock_coordinator(self):
        """Create a mock device coordinator with data."""
        coord = MagicMock()
        coord.data = DeviceData(
            pv_power_total_w=1500.0,
            pv_daily_yield_kwh=8.5,
            pv_total_yield_kwh=1200.0,
        )
        coord._consecutive_failures = 0
        coord._repair_created = False
        coord.last_update_success = True
        return coord

    @pytest.mark.asyncio
    async def test_config_is_redacted(self, mock_hass, mock_entry):
        """Config output has sensitive fields redacted."""
        mock_hass.data = {"deye_cloud": {mock_entry.entry_id: {
            "device_coordinators": {},
            "forecast_coordinators": {},
        }}}

        result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

        assert result["config"]["app_id"] == REDACTED
        assert result["config"]["app_secret"] == REDACTED
        assert result["config"]["scan_interval"] == 60
        assert result["config"]["inverters"] == ["INV001"]

    @pytest.mark.asyncio
    async def test_entity_states_included(self, mock_hass, mock_entry, mock_coordinator):
        """Entity states from coordinators are included in output."""
        mock_hass.data = {"deye_cloud": {mock_entry.entry_id: {
            "device_coordinators": {"INV001": mock_coordinator},
            "forecast_coordinators": {},
        }}}

        result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

        assert "INV001" in result["entity_states"]
        state = result["entity_states"]["INV001"]
        assert state["pv_power_total_w"] == 1500.0
        assert state["pv_daily_yield_kwh"] == 8.5

    @pytest.mark.asyncio
    async def test_error_counts_included(self, mock_hass, mock_entry, mock_coordinator):
        """Error counts from coordinator metadata are included."""
        mock_coordinator._consecutive_failures = 3
        mock_coordinator._repair_created = True
        mock_coordinator.last_update_success = False

        mock_hass.data = {"deye_cloud": {mock_entry.entry_id: {
            "device_coordinators": {"INV001": mock_coordinator},
            "forecast_coordinators": {},
        }}}

        result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

        assert result["error_counts"]["INV001"]["consecutive_failures"] == 3
        assert result["error_counts"]["INV001"]["repair_created"] is True
        assert result["error_counts"]["INV001"]["last_update_success"] is False

    @pytest.mark.asyncio
    async def test_no_entry_data(self, mock_hass, mock_entry):
        """Diagnostics handles missing entry data gracefully."""
        mock_hass.data = {}

        result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

        assert result["config"]["app_id"] == REDACTED
        assert result["entity_states"] == {}
        assert result["error_counts"] == {}

    @pytest.mark.asyncio
    async def test_coordinator_with_none_data(self, mock_hass, mock_entry):
        """Diagnostics handles coordinator with None data."""
        coord = MagicMock()
        coord.data = None
        coord._consecutive_failures = 0
        coord._repair_created = False
        coord.last_update_success = False

        mock_hass.data = {"deye_cloud": {mock_entry.entry_id: {
            "device_coordinators": {"INV001": coord},
            "forecast_coordinators": {},
        }}}

        result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

        assert result["entity_states"]["INV001"] is None

    @pytest.mark.asyncio
    async def test_last_api_response_not_tracked(self, mock_hass, mock_entry, mock_coordinator):
        """When coordinator doesn't store last raw response, reports 'not_tracked'."""
        # Remove the _last_raw_response attribute if it exists
        if hasattr(mock_coordinator, "_last_raw_response"):
            del mock_coordinator._last_raw_response
        mock_coordinator.configure_mock(**{"_last_raw_response": AttributeError})
        # Use spec to ensure hasattr returns False
        coord = MagicMock(spec=["data", "_consecutive_failures", "_repair_created", "last_update_success"])
        coord.data = DeviceData(
            pv_power_total_w=100.0,
            pv_daily_yield_kwh=1.0,
            pv_total_yield_kwh=10.0,
        )
        coord._consecutive_failures = 0
        coord._repair_created = False
        coord.last_update_success = True

        mock_hass.data = {"deye_cloud": {mock_entry.entry_id: {
            "device_coordinators": {"INV001": coord},
            "forecast_coordinators": {},
        }}}

        result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

        assert result["last_api_response"]["INV001"] == "not_tracked"

    @pytest.mark.asyncio
    async def test_options_are_redacted(self, mock_hass, mock_entry):
        """Options with sensitive keys are also redacted."""
        mock_entry.options = {
            "scan_interval": 120,
            "app_secret": "new-secret",
        }
        mock_hass.data = {"deye_cloud": {mock_entry.entry_id: {
            "device_coordinators": {},
            "forecast_coordinators": {},
        }}}

        result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

        assert result["options"]["scan_interval"] == 120
        assert result["options"]["app_secret"] == REDACTED

    @pytest.mark.asyncio
    async def test_multiple_coordinators(self, mock_hass, mock_entry):
        """Diagnostics handles multiple device coordinators."""
        coord1 = MagicMock()
        coord1.data = DeviceData(
            pv_power_total_w=1000.0,
            pv_daily_yield_kwh=5.0,
            pv_total_yield_kwh=500.0,
        )
        coord1._consecutive_failures = 0
        coord1._repair_created = False
        coord1.last_update_success = True

        coord2 = MagicMock()
        coord2.data = DeviceData(
            pv_power_total_w=2000.0,
            pv_daily_yield_kwh=10.0,
            pv_total_yield_kwh=1000.0,
        )
        coord2._consecutive_failures = 2
        coord2._repair_created = False
        coord2.last_update_success = True

        mock_hass.data = {"deye_cloud": {mock_entry.entry_id: {
            "device_coordinators": {"INV001": coord1, "INV002": coord2},
            "forecast_coordinators": {},
        }}}

        result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

        assert "INV001" in result["entity_states"]
        assert "INV002" in result["entity_states"]
        assert result["error_counts"]["INV001"]["consecutive_failures"] == 0
        assert result["error_counts"]["INV002"]["consecutive_failures"] == 2
