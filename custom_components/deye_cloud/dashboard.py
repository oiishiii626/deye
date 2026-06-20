"""Lovelace dashboard registration for the Deye Cloud integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.components.frontend import async_register_built_in_panel

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PATH = "deye-cloud"
DASHBOARD_TITLE = "Deye Cloud"
DASHBOARD_ICON = "mdi:solar-power"
DASHBOARD_YAML_PATH = Path(__file__).parent / "lovelace" / "dashboard.yaml"
DASHBOARD_REGISTERED_KEY = f"{DOMAIN}_dashboard_registered"


async def async_register_dashboard(hass: HomeAssistant) -> None:
    """Register the Deye Cloud Lovelace dashboard in the sidebar.

    This registers a Lovelace panel using the built-in HA storage mode
    dashboard approach, making it available in the sidebar after integration
    setup or Home Assistant restart.
    """
    if hass.data.get(DASHBOARD_REGISTERED_KEY):
        _LOGGER.debug("Deye Cloud dashboard already registered, skipping")
        return

    try:
        # Use the lovelace component to create a dashboard
        lovelace = hass.data.get("lovelace")
        if lovelace is None:
            _LOGGER.warning(
                "Lovelace component not available, cannot register dashboard"
            )
            return

        # Check if dashboard already exists
        dashboards = lovelace.dashboards
        if DASHBOARD_URL_PATH in dashboards:
            _LOGGER.debug("Deye Cloud dashboard already exists in lovelace")
            hass.data[DASHBOARD_REGISTERED_KEY] = True
            return

        # Read the dashboard YAML config
        dashboard_config = _load_dashboard_config()
        if dashboard_config is None:
            _LOGGER.warning("Failed to load dashboard YAML configuration")
            return

        # Create the dashboard using lovelace storage
        await lovelace.async_create_dashboard(
            url_path=DASHBOARD_URL_PATH,
            config={
                "mode": "yaml",
                "title": DASHBOARD_TITLE,
                "icon": DASHBOARD_ICON,
                "show_in_sidebar": True,
                "require_admin": False,
                "filename": str(DASHBOARD_YAML_PATH),
            },
        )

        hass.data[DASHBOARD_REGISTERED_KEY] = True
        _LOGGER.info("Deye Cloud dashboard registered in sidebar")

    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "Could not register Deye Cloud dashboard. "
            "You can manually add it via Settings > Dashboards"
        )


def _load_dashboard_config() -> dict | None:
    """Load and validate the dashboard YAML configuration file.

    Returns:
        The parsed YAML as a dict, or None if loading fails.
    """
    try:
        import yaml

        if not DASHBOARD_YAML_PATH.exists():
            _LOGGER.error(
                "Dashboard YAML not found at %s", DASHBOARD_YAML_PATH
            )
            return None

        with open(DASHBOARD_YAML_PATH, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if not isinstance(config, dict):
            _LOGGER.error("Dashboard YAML is not a valid mapping")
            return None

        # Validate minimal structure
        if "views" not in config:
            _LOGGER.error("Dashboard YAML missing 'views' key")
            return None

        return config

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Error loading dashboard YAML: %s", err)
        return None


def get_dashboard_config_path() -> Path:
    """Return the path to the dashboard YAML configuration.

    Useful for tests and diagnostics.
    """
    return DASHBOARD_YAML_PATH
