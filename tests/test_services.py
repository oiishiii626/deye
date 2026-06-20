"""Tests for the Deye Cloud services module."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.deye_cloud.const import DOMAIN, FORCE_REFRESH_COOLDOWN_S
from custom_components.deye_cloud.exceptions import (
    DeyeApiError,
    DeyeAuthError,
    DeyeConnectionError,
    DeyeTimeoutError,
)
from custom_components.deye_cloud.services import (
    ATTR_DEVICE_ID,
    ATTR_REGISTER_ADDRESS,
    ATTR_REGISTER_VALUE,
    ATTR_STRATEGY,
    SERVICE_FORCE_REFRESH,
    SERVICE_READ_CONTROL_STRATEGY,
    SERVICE_SEND_MODBUS_COMMAND,
    SERVICE_WRITE_CONTROL_STRATEGY,
    _last_force_refresh,
    _validate_device_id,
    _validate_register_address,
    _validate_register_value,
    async_handle_force_refresh,
    async_handle_read_control_strategy,
    async_handle_send_modbus_command,
    async_handle_write_control_strategy,
    async_register_services,
    async_unregister_services,
)

# Import HomeAssistantError from conftest mock
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def mock_api():
    """Create a mock DeyeCloudAPI."""
    api = AsyncMock()
    api.send_modbus_command = AsyncMock(return_value={"status": "ok"})
    api.get_control_strategy = AsyncMock(
        return_value={"workMode": 1, "chargeCurrentLimit": 25}
    )
    api.set_control_strategy = AsyncMock(return_value=True)
    return api


@pytest.fixture
def mock_coordinator():
    """Create a mock DeyeDeviceCoordinator."""
    coordinator = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


@pytest.fixture
def mock_hass(mock_api, mock_coordinator):
    """Create a mock Home Assistant instance with integration data."""
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "test_entry_id": {
                "api": mock_api,
                "device_coordinators": {
                    "SN12345": mock_coordinator,
                    "SN67890": mock_coordinator,
                },
            }
        }
    }
    hass.services = MagicMock()
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    return hass


@pytest.fixture
def mock_service_call():
    """Factory to create mock service calls."""

    def _make_call(data: dict):
        call = MagicMock()
        call.data = data
        return call

    return _make_call


@pytest.fixture(autouse=True)
def reset_cooldown():
    """Reset the force refresh cooldown state before each test."""
    _last_force_refresh.clear()
    yield
    _last_force_refresh.clear()


# ─── Validation Tests ─────────────────────────────────────────────────────


class TestValidateRegisterAddress:
    """Tests for register address validation."""

    def test_valid_min(self):
        """Address 0 is valid."""
        _validate_register_address(0)  # Should not raise

    def test_valid_max(self):
        """Address 65535 is valid."""
        _validate_register_address(65535)  # Should not raise

    def test_valid_middle(self):
        """Address 1000 is valid."""
        _validate_register_address(1000)  # Should not raise

    def test_negative_raises(self):
        """Negative address raises HomeAssistantError."""
        with pytest.raises(HomeAssistantError, match="register_address"):
            _validate_register_address(-1)

    def test_over_max_raises(self):
        """Address > 65535 raises HomeAssistantError."""
        with pytest.raises(HomeAssistantError, match="register_address"):
            _validate_register_address(65536)


class TestValidateRegisterValue:
    """Tests for register value validation."""

    def test_valid_min(self):
        """Value 0 is valid."""
        _validate_register_value(0)  # Should not raise

    def test_valid_max(self):
        """Value 65535 is valid."""
        _validate_register_value(65535)  # Should not raise

    def test_negative_raises(self):
        """Negative value raises HomeAssistantError."""
        with pytest.raises(HomeAssistantError, match="register_value"):
            _validate_register_value(-1)

    def test_over_max_raises(self):
        """Value > 65535 raises HomeAssistantError."""
        with pytest.raises(HomeAssistantError, match="register_value"):
            _validate_register_value(65536)


class TestValidateDeviceId:
    """Tests for device ID validation."""

    def test_valid_device(self):
        """Known device ID does not raise."""
        _validate_device_id("SN12345", {"SN12345": MagicMock()})

    def test_unknown_device_raises(self):
        """Unknown device ID raises HomeAssistantError."""
        with pytest.raises(HomeAssistantError, match="not found"):
            _validate_device_id("UNKNOWN", {"SN12345": MagicMock()})


# ─── Send Modbus Command Tests ────────────────────────────────────────────


class TestSendModbusCommand:
    """Tests for the send_modbus_command service handler."""

    @pytest.mark.asyncio
    async def test_success(self, mock_hass, mock_api, mock_service_call):
        """Successful modbus command returns API result."""
        call = mock_service_call(
            {
                ATTR_DEVICE_ID: "SN12345",
                ATTR_REGISTER_ADDRESS: 100,
                ATTR_REGISTER_VALUE: 42,
            }
        )
        result = await async_handle_send_modbus_command(mock_hass, call)
        assert result == {"status": "ok"}
        mock_api.send_modbus_command.assert_called_once_with("SN12345", 100, 42)

    @pytest.mark.asyncio
    async def test_invalid_register_address(self, mock_hass, mock_service_call):
        """Invalid register address raises before API call."""
        call = mock_service_call(
            {
                ATTR_DEVICE_ID: "SN12345",
                ATTR_REGISTER_ADDRESS: 70000,
                ATTR_REGISTER_VALUE: 1,
            }
        )
        with pytest.raises(HomeAssistantError, match="register_address"):
            await async_handle_send_modbus_command(mock_hass, call)

    @pytest.mark.asyncio
    async def test_invalid_register_value(self, mock_hass, mock_service_call):
        """Invalid register value raises before API call."""
        call = mock_service_call(
            {
                ATTR_DEVICE_ID: "SN12345",
                ATTR_REGISTER_ADDRESS: 100,
                ATTR_REGISTER_VALUE: -5,
            }
        )
        with pytest.raises(HomeAssistantError, match="register_value"):
            await async_handle_send_modbus_command(mock_hass, call)

    @pytest.mark.asyncio
    async def test_unknown_device(self, mock_hass, mock_service_call):
        """Unknown device ID raises HomeAssistantError."""
        call = mock_service_call(
            {
                ATTR_DEVICE_ID: "NONEXISTENT",
                ATTR_REGISTER_ADDRESS: 100,
                ATTR_REGISTER_VALUE: 1,
            }
        )
        with pytest.raises(HomeAssistantError, match="not found"):
            await async_handle_send_modbus_command(mock_hass, call)

    @pytest.mark.asyncio
    async def test_api_error_includes_code(self, mock_hass, mock_api, mock_service_call):
        """API error includes error code and operation name."""
        mock_api.send_modbus_command = AsyncMock(
            side_effect=DeyeApiError("Device busy", error_code="E4001")
        )
        call = mock_service_call(
            {
                ATTR_DEVICE_ID: "SN12345",
                ATTR_REGISTER_ADDRESS: 100,
                ATTR_REGISTER_VALUE: 1,
            }
        )
        with pytest.raises(HomeAssistantError, match="E4001") as exc_info:
            await async_handle_send_modbus_command(mock_hass, call)
        assert "send_modbus_command" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_timeout_raises(self, mock_hass, mock_api, mock_service_call):
        """Timeout raises HomeAssistantError with timeout message."""
        mock_api.send_modbus_command = AsyncMock(
            side_effect=DeyeTimeoutError("Request timed out")
        )
        call = mock_service_call(
            {
                ATTR_DEVICE_ID: "SN12345",
                ATTR_REGISTER_ADDRESS: 100,
                ATTR_REGISTER_VALUE: 1,
            }
        )
        with pytest.raises(HomeAssistantError, match="[Tt]imeout"):
            await async_handle_send_modbus_command(mock_hass, call)


# ─── Read Control Strategy Tests ──────────────────────────────────────────


class TestReadControlStrategy:
    """Tests for the read_control_strategy service handler."""

    @pytest.mark.asyncio
    async def test_success(self, mock_hass, mock_api, mock_service_call):
        """Successful read returns strategy data."""
        call = mock_service_call({ATTR_DEVICE_ID: "SN12345"})
        result = await async_handle_read_control_strategy(mock_hass, call)
        assert result == {"workMode": 1, "chargeCurrentLimit": 25}
        mock_api.get_control_strategy.assert_called_once_with("SN12345")

    @pytest.mark.asyncio
    async def test_unknown_device(self, mock_hass, mock_service_call):
        """Unknown device ID raises HomeAssistantError."""
        call = mock_service_call({ATTR_DEVICE_ID: "NONEXISTENT"})
        with pytest.raises(HomeAssistantError, match="not found"):
            await async_handle_read_control_strategy(mock_hass, call)

    @pytest.mark.asyncio
    async def test_api_error(self, mock_hass, mock_api, mock_service_call):
        """API error is wrapped in HomeAssistantError with code."""
        mock_api.get_control_strategy = AsyncMock(
            side_effect=DeyeApiError("Forbidden", error_code="E403")
        )
        call = mock_service_call({ATTR_DEVICE_ID: "SN12345"})
        with pytest.raises(HomeAssistantError, match="E403") as exc_info:
            await async_handle_read_control_strategy(mock_hass, call)
        assert "read_control_strategy" in str(exc_info.value)


# ─── Write Control Strategy Tests ─────────────────────────────────────────


class TestWriteControlStrategy:
    """Tests for the write_control_strategy service handler."""

    @pytest.mark.asyncio
    async def test_success(self, mock_hass, mock_api, mock_service_call):
        """Successful write calls API with correct params."""
        strategy = {"workMode": 2, "dischargePower": 3000}
        call = mock_service_call(
            {ATTR_DEVICE_ID: "SN12345", ATTR_STRATEGY: strategy}
        )
        await async_handle_write_control_strategy(mock_hass, call)
        mock_api.set_control_strategy.assert_called_once_with("SN12345", strategy)

    @pytest.mark.asyncio
    async def test_empty_strategy_raises(self, mock_hass, mock_service_call):
        """Empty strategy dict raises HomeAssistantError."""
        call = mock_service_call(
            {ATTR_DEVICE_ID: "SN12345", ATTR_STRATEGY: {}}
        )
        with pytest.raises(HomeAssistantError, match="non-empty"):
            await async_handle_write_control_strategy(mock_hass, call)

    @pytest.mark.asyncio
    async def test_unknown_device(self, mock_hass, mock_service_call):
        """Unknown device ID raises HomeAssistantError."""
        call = mock_service_call(
            {ATTR_DEVICE_ID: "NONEXISTENT", ATTR_STRATEGY: {"mode": 1}}
        )
        with pytest.raises(HomeAssistantError, match="not found"):
            await async_handle_write_control_strategy(mock_hass, call)

    @pytest.mark.asyncio
    async def test_api_error(self, mock_hass, mock_api, mock_service_call):
        """API error includes error code and operation name."""
        mock_api.set_control_strategy = AsyncMock(
            side_effect=DeyeApiError("Invalid params", error_code="E5001")
        )
        call = mock_service_call(
            {ATTR_DEVICE_ID: "SN12345", ATTR_STRATEGY: {"mode": 1}}
        )
        with pytest.raises(HomeAssistantError, match="E5001") as exc_info:
            await async_handle_write_control_strategy(mock_hass, call)
        assert "write_control_strategy" in str(exc_info.value)


# ─── Force Refresh Tests ──────────────────────────────────────────────────


class TestForceRefresh:
    """Tests for the force_refresh service handler."""

    @pytest.mark.asyncio
    async def test_success(self, mock_hass, mock_coordinator, mock_service_call):
        """Successful force refresh triggers coordinator refresh."""
        call = mock_service_call({ATTR_DEVICE_ID: "SN12345"})
        await async_handle_force_refresh(mock_hass, call)
        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_cooldown_enforced(self, mock_hass, mock_coordinator, mock_service_call):
        """Second call within cooldown period raises HomeAssistantError."""
        call = mock_service_call({ATTR_DEVICE_ID: "SN12345"})

        # First call succeeds
        await async_handle_force_refresh(mock_hass, call)

        # Second call within cooldown fails
        with pytest.raises(HomeAssistantError, match="cooldown"):
            await async_handle_force_refresh(mock_hass, call)

    @pytest.mark.asyncio
    async def test_cooldown_expires(self, mock_hass, mock_coordinator, mock_service_call):
        """Call after cooldown period succeeds."""
        call = mock_service_call({ATTR_DEVICE_ID: "SN12345"})

        # First call
        await async_handle_force_refresh(mock_hass, call)

        # Simulate cooldown expiry by manipulating the timestamp
        _last_force_refresh["SN12345"] = time.time() - FORCE_REFRESH_COOLDOWN_S - 1

        # Second call should succeed
        mock_coordinator.async_request_refresh.reset_mock()
        await async_handle_force_refresh(mock_hass, call)
        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_different_devices_independent_cooldown(
        self, mock_hass, mock_coordinator, mock_service_call
    ):
        """Cooldown is per-device, not global."""
        call_a = mock_service_call({ATTR_DEVICE_ID: "SN12345"})
        call_b = mock_service_call({ATTR_DEVICE_ID: "SN67890"})

        # Refresh device A
        await async_handle_force_refresh(mock_hass, call_a)

        # Refresh device B should still work
        await async_handle_force_refresh(mock_hass, call_b)

    @pytest.mark.asyncio
    async def test_unknown_device(self, mock_hass, mock_service_call):
        """Unknown device ID raises HomeAssistantError."""
        call = mock_service_call({ATTR_DEVICE_ID: "NONEXISTENT"})
        with pytest.raises(HomeAssistantError, match="not found"):
            await async_handle_force_refresh(mock_hass, call)


# ─── Service Registration Tests ───────────────────────────────────────────


class TestServiceRegistration:
    """Tests for service registration and unregistration."""

    @pytest.mark.asyncio
    async def test_register_services(self, mock_hass):
        """All four services are registered."""
        await async_register_services(mock_hass)
        assert mock_hass.services.async_register.call_count == 4

        # Verify each service was registered
        registered_services = [
            call.args[1]
            for call in mock_hass.services.async_register.call_args_list
        ]
        assert SERVICE_SEND_MODBUS_COMMAND in registered_services
        assert SERVICE_READ_CONTROL_STRATEGY in registered_services
        assert SERVICE_WRITE_CONTROL_STRATEGY in registered_services
        assert SERVICE_FORCE_REFRESH in registered_services

    @pytest.mark.asyncio
    async def test_unregister_services(self, mock_hass):
        """All four services are unregistered."""
        await async_unregister_services(mock_hass)
        assert mock_hass.services.async_remove.call_count == 4

        removed_services = [
            call.args[1]
            for call in mock_hass.services.async_remove.call_args_list
        ]
        assert SERVICE_SEND_MODBUS_COMMAND in removed_services
        assert SERVICE_READ_CONTROL_STRATEGY in removed_services
        assert SERVICE_WRITE_CONTROL_STRATEGY in removed_services
        assert SERVICE_FORCE_REFRESH in removed_services


# ─── Integration Not Setup Tests ──────────────────────────────────────────


class TestIntegrationNotSetup:
    """Tests for when integration is not set up."""

    @pytest.mark.asyncio
    async def test_no_domain_in_hass_data(self, mock_service_call):
        """Raises when DOMAIN not in hass.data."""
        hass = MagicMock()
        hass.data = {}
        call = mock_service_call({ATTR_DEVICE_ID: "SN12345"})
        with pytest.raises(HomeAssistantError, match="not set up"):
            await async_handle_read_control_strategy(hass, call)

    @pytest.mark.asyncio
    async def test_no_config_entry(self, mock_service_call):
        """Raises when no active config entry found."""
        hass = MagicMock()
        hass.data = {DOMAIN: {"entry_id": "not_a_dict_with_api"}}
        call = mock_service_call({ATTR_DEVICE_ID: "SN12345"})
        with pytest.raises(HomeAssistantError, match="no active config entry"):
            await async_handle_read_control_strategy(hass, call)


# ─── Auth Error Tests ─────────────────────────────────────────────────────


class TestAuthErrors:
    """Tests for authentication error handling in services."""

    @pytest.mark.asyncio
    async def test_auth_error_raises_ha_error(
        self, mock_hass, mock_api, mock_service_call
    ):
        """DeyeAuthError is wrapped in HomeAssistantError."""
        mock_api.get_control_strategy = AsyncMock(
            side_effect=DeyeAuthError("Token expired")
        )
        call = mock_service_call({ATTR_DEVICE_ID: "SN12345"})
        with pytest.raises(HomeAssistantError, match="[Aa]uthentication"):
            await async_handle_read_control_strategy(mock_hass, call)

    @pytest.mark.asyncio
    async def test_connection_error_raises_ha_error(
        self, mock_hass, mock_api, mock_service_call
    ):
        """DeyeConnectionError is wrapped in HomeAssistantError."""
        mock_api.send_modbus_command = AsyncMock(
            side_effect=DeyeConnectionError("DNS lookup failed")
        )
        call = mock_service_call(
            {
                ATTR_DEVICE_ID: "SN12345",
                ATTR_REGISTER_ADDRESS: 100,
                ATTR_REGISTER_VALUE: 1,
            }
        )
        with pytest.raises(HomeAssistantError, match="[Cc]onnection"):
            await async_handle_send_modbus_command(mock_hass, call)
