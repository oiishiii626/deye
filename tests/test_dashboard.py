"""Tests for the Deye Cloud dashboard registration and YAML config."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

# Ensure the frontend mock is in place before importing dashboard
if "homeassistant.components.frontend" not in sys.modules:
    sys.modules["homeassistant.components.frontend"] = MagicMock()

from custom_components.deye_cloud.dashboard import (
    DASHBOARD_ICON,
    DASHBOARD_TITLE,
    DASHBOARD_URL_PATH,
    DASHBOARD_YAML_PATH,
    DASHBOARD_REGISTERED_KEY,
    async_register_dashboard,
    get_dashboard_config_path,
    _load_dashboard_config,
)
from custom_components.deye_cloud.const import DOMAIN


class TestDashboardYAMLStructure:
    """Test that the dashboard YAML configuration is valid and complete."""

    def setup_method(self):
        """Load the dashboard YAML for tests."""
        assert DASHBOARD_YAML_PATH.exists(), (
            f"Dashboard YAML not found at {DASHBOARD_YAML_PATH}"
        )
        with open(DASHBOARD_YAML_PATH, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

    def test_yaml_is_valid_mapping(self):
        """Dashboard YAML must parse as a dict."""
        assert isinstance(self.config, dict)

    def test_yaml_has_title(self):
        """Dashboard config must have a title."""
        assert "title" in self.config
        assert self.config["title"] == "Deye Cloud"

    def test_yaml_has_views(self):
        """Dashboard config must contain a views list."""
        assert "views" in self.config
        assert isinstance(self.config["views"], list)
        assert len(self.config["views"]) >= 5

    def test_power_flow_view_exists(self):
        """First view should be the Power Flow Card view."""
        views = self.config["views"]
        power_flow_view = views[0]
        assert power_flow_view["title"] == "Power Flow"
        assert power_flow_view["path"] == "power-flow"

    def test_power_flow_view_has_cards(self):
        """Power Flow view must have cards for PV, Battery, Grid, Load."""
        power_flow_view = self.config["views"][0]
        assert "cards" in power_flow_view
        assert len(power_flow_view["cards"]) >= 1

        # Check that instantaneous power entities are referenced
        all_entities = _extract_all_entities(power_flow_view)
        # Must reference PV, Battery, Grid, and Load power sensors
        assert any("pv_power" in e for e in all_entities)
        assert any("battery_power" in e or "battery" in e for e in all_entities)
        assert any("grid" in e for e in all_entities)
        assert any("load_power" in e for e in all_entities)

    def test_summary_view_exists(self):
        """Summary statistics view must exist."""
        views = self.config["views"]
        summary_view = views[1]
        assert summary_view["title"] == "Summary"
        assert summary_view["path"] == "summary"

    def test_summary_view_has_production_consumption(self):
        """Summary view must reference daily/total production and consumption."""
        summary_view = self.config["views"][1]
        all_entities = _extract_all_entities(summary_view)

        # Daily and total production
        assert any("pv_daily_yield" in e for e in all_entities)
        assert any("pv_total_yield" in e for e in all_entities)

        # Daily and total consumption
        assert any("load_daily_consumption" in e or "daily_consumption" in e for e in all_entities)
        assert any("load_total_consumption" in e or "total_consumption" in e for e in all_entities)

    def test_summary_view_has_self_consumption_ratios(self):
        """Summary view must reference self-consumption and self-sufficiency ratios."""
        summary_view = self.config["views"][1]
        all_entities = _extract_all_entities(summary_view)

        assert any("self_consumption" in e for e in all_entities)
        assert any("self_sufficiency" in e for e in all_entities)

    def test_charts_view_exists(self):
        """Historical charts view must exist."""
        views = self.config["views"]
        charts_view = views[2]
        assert charts_view["title"] == "Charts"
        assert charts_view["path"] == "charts"

    def test_charts_view_has_history_graph(self):
        """Charts view must have a 24h power profile history graph."""
        charts_view = self.config["views"][2]
        cards = charts_view["cards"]

        # Find history-graph card with 24h display
        history_cards = [c for c in cards if c.get("type") == "history-graph"]
        assert len(history_cards) >= 1

        # Should show 24 hours
        assert any(c.get("hours_to_show") == 24 for c in history_cards)

    def test_charts_view_has_statistics_graphs(self):
        """Charts view must have 7-day bar charts."""
        charts_view = self.config["views"][2]
        cards = charts_view["cards"]

        # Find statistics-graph cards
        stat_cards = [c for c in cards if c.get("type") == "statistics-graph"]
        assert len(stat_cards) >= 2  # At least generation and consumption

    def test_settings_view_exists(self):
        """Settings/controls view must exist."""
        views = self.config["views"]
        settings_view = views[3]
        assert settings_view["title"] == "Settings"
        assert settings_view["path"] == "settings"

    def test_settings_view_has_writable_controls(self):
        """Settings view must expose all writable controls."""
        settings_view = self.config["views"][3]
        all_entities = _extract_all_entities(settings_view)

        # Work mode and energy pattern
        assert any("work_mode" in e for e in all_entities)
        assert any("energy_pattern" in e for e in all_entities)

        # Battery settings
        assert any("battery_soc_min" in e for e in all_entities)
        assert any("battery_soc_max" in e for e in all_entities)
        assert any("battery_charge_current" in e or "charge_current" in e for e in all_entities)
        assert any("battery_discharge_current" in e or "discharge_current" in e for e in all_entities)

        # Grid settings
        assert any("grid_export_limit" in e or "export_limit" in e for e in all_entities)
        assert any("solar_sell" in e for e in all_entities)

        # Smart load
        assert any("smart_load" in e for e in all_entities)

        # TOU
        assert any("tou" in e for e in all_entities)

    def test_diagnostics_view_exists(self):
        """Diagnostics view must exist."""
        views = self.config["views"]
        diagnostics_view = views[4]
        assert diagnostics_view["title"] == "Diagnostics"
        assert diagnostics_view["path"] == "diagnostics"

    def test_diagnostics_view_has_required_info(self):
        """Diagnostics view must show status, last update, firmware, and diagnostics download."""
        diagnostics_view = self.config["views"][4]
        all_entities = _extract_all_entities(diagnostics_view)
        all_content = _extract_all_content(diagnostics_view)

        # Online status
        assert any("online" in e for e in all_entities)

        # Last update
        assert any("last_update" in e for e in all_entities)

        # Firmware version (can be in markdown card or entity attributes)
        assert any("firmware" in c.lower() for c in all_content)

        # Diagnostics download link
        assert any("diagnostics" in c.lower() for c in all_content)

    def test_all_views_have_icons(self):
        """Each view must have an icon defined."""
        for view in self.config["views"]:
            assert "icon" in view, f"View '{view.get('title')}' missing icon"


class TestDashboardRegistration:
    """Test dashboard registration logic."""

    @pytest.mark.asyncio
    async def test_register_dashboard_skips_if_already_registered(self):
        """Should skip registration if already registered."""
        hass = MagicMock()
        hass.data = {DASHBOARD_REGISTERED_KEY: True}

        await async_register_dashboard(hass)

        # Should not attempt to access lovelace
        assert DASHBOARD_REGISTERED_KEY in hass.data

    @pytest.mark.asyncio
    async def test_register_dashboard_handles_no_lovelace(self):
        """Should handle missing lovelace component gracefully."""
        hass = MagicMock()
        # Use a dict that does NOT have the "lovelace" key
        hass.data = {}

        # Should not raise - lovelace key missing means None from .get()
        await async_register_dashboard(hass)

    @pytest.mark.asyncio
    async def test_register_dashboard_handles_exception(self):
        """Should handle exceptions gracefully during registration."""
        hass = MagicMock()
        # Set up data with lovelace that raises when accessed
        mock_lovelace = MagicMock()
        # Make dashboards property raise an exception
        type(mock_lovelace).dashboards = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("Unexpected error"))
        )
        hass.data = {"lovelace": mock_lovelace}

        # Should not raise - exception is caught internally
        await async_register_dashboard(hass)

    @pytest.mark.asyncio
    async def test_register_dashboard_skips_existing_dashboard(self):
        """Should skip if dashboard URL path already exists."""
        hass = MagicMock()

        mock_lovelace = MagicMock()
        mock_lovelace.dashboards = {DASHBOARD_URL_PATH: MagicMock()}

        # Set up data dict with lovelace present
        hass.data = {"lovelace": mock_lovelace}

        await async_register_dashboard(hass)

        # Should mark as registered without creating a new dashboard
        assert hass.data[DASHBOARD_REGISTERED_KEY] is True
        mock_lovelace.async_create_dashboard.assert_not_called()


class TestDashboardConfigLoader:
    """Test the YAML config loader."""

    def test_load_dashboard_config_returns_dict(self):
        """Loader should return a valid dict with views."""
        config = _load_dashboard_config()
        assert config is not None
        assert isinstance(config, dict)
        assert "views" in config

    def test_get_dashboard_config_path(self):
        """Helper should return the correct path."""
        path = get_dashboard_config_path()
        assert path == DASHBOARD_YAML_PATH
        assert path.name == "dashboard.yaml"
        assert "lovelace" in str(path)


class TestDashboardConstants:
    """Test dashboard module constants."""

    def test_url_path(self):
        """URL path should be a simple slug."""
        assert DASHBOARD_URL_PATH == "deye-cloud"

    def test_title(self):
        """Title should be the integration name."""
        assert DASHBOARD_TITLE == "Deye Cloud"

    def test_icon(self):
        """Icon should be a valid MDI icon."""
        assert DASHBOARD_ICON.startswith("mdi:")


def _extract_all_entities(view: dict) -> list[str]:
    """Recursively extract all entity IDs from a view configuration."""
    entities = []
    if isinstance(view, dict):
        for key, value in view.items():
            if key == "entity" and isinstance(value, str):
                entities.append(value)
            elif key == "entities" and isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        entities.append(item)
                    elif isinstance(item, dict) and "entity" in item:
                        entities.append(item["entity"])
            else:
                entities.extend(_extract_all_entities(value))
    elif isinstance(view, list):
        for item in view:
            entities.extend(_extract_all_entities(item))
    return entities


def _extract_all_content(view: dict) -> list[str]:
    """Recursively extract all 'content' fields from a view (markdown cards)."""
    contents = []
    if isinstance(view, dict):
        for key, value in view.items():
            if key == "content" and isinstance(value, str):
                contents.append(value)
            else:
                contents.extend(_extract_all_content(value))
    elif isinstance(view, list):
        for item in view:
            contents.extend(_extract_all_content(item))
    return contents
