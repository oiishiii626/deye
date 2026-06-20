"""Service registration and handlers for the Deye Cloud integration."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, FORCE_REFRESH_COOLDOWN_S
from .exceptions import (
    DeyeApiError,
    DeyeAuthError,
    DeyeCloudError,
    DeyeConnectionError,
    DeyeTimeoutError,
)

_LOGGER = logging.getLogger(__name__)

# Service names
SERVICE_SEND_MODBUS_COMMAND = "send_modbus_command"
SERVICE_READ_CONTROL_STRATEGY = "read_control_strategy"
SERVICE_WRITE_CONTROL_STRATEGY = "write_control_strategy"
SERVICE_FORCE_REFRESH = "force_refresh"

# Parameter keys
ATTR_DEVICE_ID = "device_id"
ATTR_REGISTER_ADDRESS = "register_address"
ATTR_REGISTER_VALUE = "register_value"
ATTR_STRATEGY = "strategy"

# Validation constants
REGISTER_MIN = 0
REGISTER_MAX = 65535

# Timeout for API calls from services (seconds)
SERVICE_API_TIMEOUT = 30

# Track last force refresh time per device
_last_force_refresh: dict[str, float] = {}


def _get_api_and_coordinators(hass: HomeAssistant) -> tuple[Any, dict[str, Any]]:
    """Get the API client and device coordinators from hass.data.

    Returns:
        Tuple of (api, device_coordinators dict).

    Raises:
        HomeAssistantError: If the integration is not set up.
    """
    if DOMAIN not in hass.data:
        raise HomeAssistantError(
            f"Integration {DOMAIN} is not set up"
        )

    # Find the first (or only) config entry's data
    for entry_id, entry_data in hass.data[DOMAIN].items():
        if isinstance(entry_data, dict) and "api" in entry_data:
            return entry_data["api"], entry_data.get("device_coordinators", {})

    raise HomeAssistantError(
        f"Integration {DOMAIN} has no active config entry"
    )


def _validate_device_id(
    device_id: str, device_coordinators: dict[str, Any]
) -> None:
    """Validate that a device ID exists in the configured devices.

    Args:
        device_id: The device serial number to validate.
        device_coordinators: Dict of device_sn -> coordinator.

    Raises:
        HomeAssistantError: If the device ID is not found.
    """
    if device_id not in device_coordinators:
        available = list(device_coordinators.keys())
        raise HomeAssistantError(
            f"Device '{device_id}' not found. "
            f"Available devices: {available}"
        )


def _validate_register_address(address: int) -> None:
    """Validate register address is within valid range.

    Args:
        address: The register address to validate.

    Raises:
        HomeAssistantError: If the address is out of range.
    """
    if not isinstance(address, int) or address < REGISTER_MIN or address > REGISTER_MAX:
        raise HomeAssistantError(
            f"Parameter 'register_address' must be an integer between "
            f"{REGISTER_MIN} and {REGISTER_MAX}, got {address}"
        )


def _validate_register_value(value: int) -> None:
    """Validate register value is within valid range.

    Args:
        value: The register value to validate.

    Raises:
        HomeAssistantError: If the value is out of range.
    """
    if not isinstance(value, int) or value < REGISTER_MIN or value > REGISTER_MAX:
        raise HomeAssistantError(
            f"Parameter 'register_value' must be an integer between "
            f"{REGISTER_MIN} and {REGISTER_MAX}, got {value}"
        )


async def _async_call_api_with_timeout(
    coro, operation_name: str
) -> Any:
    """Call an API coroutine with a 30-second timeout.

    Args:
        coro: The awaitable API call.
        operation_name: Name of the operation for error messages.

    Returns:
        The result from the API call.

    Raises:
        HomeAssistantError: On timeout, API error, or auth error.
    """
    try:
        return await asyncio.wait_for(coro, timeout=SERVICE_API_TIMEOUT)
    except asyncio.TimeoutError as err:
        raise HomeAssistantError(
            f"Timeout: {operation_name} did not receive a response "
            f"within {SERVICE_API_TIMEOUT} seconds"
        ) from err
    except DeyeApiError as err:
        error_code = err.error_code or "unknown"
        raise HomeAssistantError(
            f"API error ({error_code}): {operation_name} failed - {err}"
        ) from err
    except DeyeAuthError as err:
        raise HomeAssistantError(
            f"Authentication error: {operation_name} failed - {err}"
        ) from err
    except DeyeTimeoutError as err:
        raise HomeAssistantError(
            f"Timeout: {operation_name} did not receive a response "
            f"within {SERVICE_API_TIMEOUT} seconds"
        ) from err
    except DeyeConnectionError as err:
        raise HomeAssistantError(
            f"Connection error: {operation_name} failed - {err}"
        ) from err
    except DeyeCloudError as err:
        raise HomeAssistantError(
            f"Error: {operation_name} failed - {err}"
        ) from err


async def async_handle_send_modbus_command(
    hass: HomeAssistant, call: ServiceCall
) -> dict:
    """Handle the send_modbus_command service call.

    Args:
        hass: The Home Assistant instance.
        call: The service call data.

    Returns:
        The response data from the Modbus command.

    Raises:
        HomeAssistantError: On validation failure, timeout, or API error.
    """
    device_id: str = call.data[ATTR_DEVICE_ID]
    register_address: int = call.data[ATTR_REGISTER_ADDRESS]
    register_value: int = call.data[ATTR_REGISTER_VALUE]

    # Validate parameters before API call
    _validate_register_address(register_address)
    _validate_register_value(register_value)

    api, device_coordinators = _get_api_and_coordinators(hass)
    _validate_device_id(device_id, device_coordinators)

    result = await _async_call_api_with_timeout(
        api.send_modbus_command(device_id, register_address, register_value),
        "send_modbus_command",
    )

    _LOGGER.debug(
        "Modbus command sent to %s: register=%d, value=%d, result=%s",
        device_id,
        register_address,
        register_value,
        result,
    )
    return result


async def async_handle_read_control_strategy(
    hass: HomeAssistant, call: ServiceCall
) -> dict:
    """Handle the read_control_strategy service call.

    Args:
        hass: The Home Assistant instance.
        call: The service call data.

    Returns:
        The strategy data from the API.

    Raises:
        HomeAssistantError: On validation failure, timeout, or API error.
    """
    device_id: str = call.data[ATTR_DEVICE_ID]

    api, device_coordinators = _get_api_and_coordinators(hass)
    _validate_device_id(device_id, device_coordinators)

    result = await _async_call_api_with_timeout(
        api.get_control_strategy(device_id),
        "read_control_strategy",
    )

    _LOGGER.debug("Control strategy for %s: %s", device_id, result)
    return result


async def async_handle_write_control_strategy(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    """Handle the write_control_strategy service call.

    Args:
        hass: The Home Assistant instance.
        call: The service call data.

    Raises:
        HomeAssistantError: On validation failure, timeout, or API error.
    """
    device_id: str = call.data[ATTR_DEVICE_ID]
    strategy: dict = call.data[ATTR_STRATEGY]

    if not isinstance(strategy, dict) or not strategy:
        raise HomeAssistantError(
            "Parameter 'strategy' must be a non-empty dictionary"
        )

    api, device_coordinators = _get_api_and_coordinators(hass)
    _validate_device_id(device_id, device_coordinators)

    await _async_call_api_with_timeout(
        api.set_control_strategy(device_id, strategy),
        "write_control_strategy",
    )

    _LOGGER.debug(
        "Control strategy written to %s: %s", device_id, strategy
    )


async def async_handle_force_refresh(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    """Handle the force_refresh service call.

    Triggers an immediate data refresh for a device, with a 10-second
    cooldown between calls per device.

    Args:
        hass: The Home Assistant instance.
        call: The service call data.

    Raises:
        HomeAssistantError: On validation failure or cooldown violation.
    """
    device_id: str = call.data[ATTR_DEVICE_ID]

    api, device_coordinators = _get_api_and_coordinators(hass)
    _validate_device_id(device_id, device_coordinators)

    # Enforce cooldown
    now = time.time()
    last_refresh = _last_force_refresh.get(device_id, 0.0)
    elapsed = now - last_refresh

    if elapsed < FORCE_REFRESH_COOLDOWN_S:
        remaining = FORCE_REFRESH_COOLDOWN_S - elapsed
        raise HomeAssistantError(
            f"Force refresh for device '{device_id}' is on cooldown. "
            f"Please wait {remaining:.1f} seconds before retrying."
        )

    # Trigger the coordinator refresh
    coordinator = device_coordinators[device_id]
    _last_force_refresh[device_id] = now

    try:
        await asyncio.wait_for(
            coordinator.async_request_refresh(),
            timeout=SERVICE_API_TIMEOUT,
        )
    except asyncio.TimeoutError as err:
        raise HomeAssistantError(
            f"Timeout: force_refresh for device '{device_id}' did not complete "
            f"within {SERVICE_API_TIMEOUT} seconds"
        ) from err

    _LOGGER.debug("Force refresh triggered for device %s", device_id)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register all Deye Cloud services.

    Args:
        hass: The Home Assistant instance.
    """

    async def handle_send_modbus(call: ServiceCall) -> None:
        """Wrapper for send_modbus_command service."""
        await async_handle_send_modbus_command(hass, call)

    async def handle_read_strategy(call: ServiceCall) -> None:
        """Wrapper for read_control_strategy service."""
        await async_handle_read_control_strategy(hass, call)

    async def handle_write_strategy(call: ServiceCall) -> None:
        """Wrapper for write_control_strategy service."""
        await async_handle_write_control_strategy(hass, call)

    async def handle_force_refresh(call: ServiceCall) -> None:
        """Wrapper for force_refresh service."""
        await async_handle_force_refresh(hass, call)

    # Register services with voluptuous schema validation
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MODBUS_COMMAND,
        handle_send_modbus,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): str,
                vol.Required(ATTR_REGISTER_ADDRESS): int,
                vol.Required(ATTR_REGISTER_VALUE): int,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_READ_CONTROL_STRATEGY,
        handle_read_strategy,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_WRITE_CONTROL_STRATEGY,
        handle_write_strategy,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): str,
                vol.Required(ATTR_STRATEGY): dict,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCE_REFRESH,
        handle_force_refresh,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DEVICE_ID): str,
            }
        ),
    )

    _LOGGER.debug("Deye Cloud services registered")


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister all Deye Cloud services.

    Args:
        hass: The Home Assistant instance.
    """
    hass.services.async_remove(DOMAIN, SERVICE_SEND_MODBUS_COMMAND)
    hass.services.async_remove(DOMAIN, SERVICE_READ_CONTROL_STRATEGY)
    hass.services.async_remove(DOMAIN, SERVICE_WRITE_CONTROL_STRATEGY)
    hass.services.async_remove(DOMAIN, SERVICE_FORCE_REFRESH)

    _LOGGER.debug("Deye Cloud services unregistered")
