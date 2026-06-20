"""Diagnostics platform for the Deye Cloud integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# Keys whose values should be redacted in diagnostics output
REDACT_KEYS = frozenset(
    {
        "secret",
        "password",
        "token",
        "app_id",
        "app_secret",
        "appid",
        "appsecret",
        "access_token",
        "accesstoken",
    }
)

REDACTED = "**REDACTED**"


def _redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive values from a configuration dictionary.

    Any key whose lowercase form contains one of the REDACT_KEYS substrings
    will have its value replaced with **REDACTED**.

    Args:
        config: The raw configuration dictionary.

    Returns:
        A new dictionary with sensitive values redacted.
    """
    redacted: dict[str, Any] = {}
    for key, value in config.items():
        key_lower = key.lower()
        if any(redact_key in key_lower for redact_key in REDACT_KEYS):
            redacted[key] = REDACTED
        elif isinstance(value, dict):
            redacted[key] = _redact_config(value)
        else:
            redacted[key] = value
    return redacted


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics data for a Deye Cloud config entry.

    Output includes:
    - Redacted configuration (AppId/AppSecret/tokens → **REDACTED**)
    - Current entity states from coordinators
    - Last API response data (if available)
    - Error counts from coordinator metadata

    Args:
        hass: The Home Assistant instance.
        entry: The config entry to generate diagnostics for.

    Returns:
        A dictionary serializable to JSON for download.
    """
    # Redacted configuration
    redacted_data = _redact_config(dict(entry.data))
    redacted_options = _redact_config(dict(entry.options))

    # Gather coordinator info
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    device_coordinators = entry_data.get("device_coordinators", {})
    forecast_coordinators = entry_data.get("forecast_coordinators", {})

    # Entity states from device coordinators
    entity_states: dict[str, Any] = {}
    error_counts: dict[str, Any] = {}
    last_api_response: dict[str, Any] = {}

    for device_sn, coordinator in device_coordinators.items():
        # Current data state
        if coordinator.data is not None:
            try:
                from dataclasses import asdict

                entity_states[device_sn] = asdict(coordinator.data)
            except (TypeError, ValueError):
                entity_states[device_sn] = str(coordinator.data)
        else:
            entity_states[device_sn] = None

        # Error counts
        error_counts[device_sn] = {
            "consecutive_failures": getattr(
                coordinator, "_consecutive_failures", 0
            ),
            "repair_created": getattr(coordinator, "_repair_created", False),
            "last_update_success": coordinator.last_update_success,
        }

        # Last API response (stored by coordinator if available)
        if hasattr(coordinator, "_last_raw_response"):
            last_api_response[device_sn] = coordinator._last_raw_response
        else:
            last_api_response[device_sn] = "not_tracked"

    # Forecast coordinator states
    forecast_states: dict[str, Any] = {}
    for station_id, forecast_coord in forecast_coordinators.items():
        if forecast_coord.data is not None:
            try:
                from dataclasses import asdict

                forecast_states[station_id] = asdict(forecast_coord.data)
            except (TypeError, ValueError):
                forecast_states[station_id] = str(forecast_coord.data)
        else:
            forecast_states[station_id] = None

    return {
        "config": redacted_data,
        "options": redacted_options,
        "entity_states": entity_states,
        "forecast_states": forecast_states,
        "last_api_response": last_api_response,
        "error_counts": error_counts,
    }
