"""Tests for the Deye Cloud event platform."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from custom_components.deye_cloud.event import (
    EVENT_TYPE_ALERT,
    EVENT_TYPE_ALERT_RESOLVED,
    DeyeAlertEventEntity,
    DeyeStationAlertEventEntity,
    async_setup_entry,
)
from custom_components.deye_cloud.models import AlertData, DeviceData


def _make_device_data(alerts: list[AlertData] | None = None) -> DeviceData:
    """Create a minimal DeviceData with given alerts."""
    return DeviceData(
        pv_power_total_w=1000.0,
        pv_daily_yield_kwh=5.0,
        pv_total_yield_kwh=100.0,
        active_alerts=alerts or [],
    )


def _make_alert(
    alert_type: str = "overvoltage",
    severity: str = "warning",
    timestamp: datetime | None = None,
    message: str = "Voltage too high",
    is_active: bool = True,
) -> AlertData:
    """Create an AlertData with defaults."""
    return AlertData(
        alert_type=alert_type,
        severity=severity,
        timestamp=timestamp or datetime(2024, 1, 15, 10, 30, 0),
        message=message,
        is_active=is_active,
    )


def _make_coordinator(device_sn: str = "SN123456", data: DeviceData | None = None):
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.device_sn = device_sn
    coordinator.data = data or _make_device_data()
    return coordinator


class TestDeyeAlertEventEntity:
    """Tests for the DeyeAlertEventEntity class."""

    def test_init_sets_unique_id(self):
        """Test that unique_id is set based on device serial."""
        coordinator = _make_coordinator("SN123456")
        entity = DeyeAlertEventEntity(coordinator, "SN123456")
        assert entity._attr_unique_id == "SN123456_alerts"

    def test_init_sets_event_types(self):
        """Test that event types are configured."""
        coordinator = _make_coordinator("SN123456")
        entity = DeyeAlertEventEntity(coordinator, "SN123456")
        assert EVENT_TYPE_ALERT in entity._attr_event_types
        assert EVENT_TYPE_ALERT_RESOLVED in entity._attr_event_types

    def test_device_info_links_to_inverter(self):
        """Test device_info contains the correct identifiers."""
        coordinator = _make_coordinator("SN123456")
        entity = DeyeAlertEventEntity(coordinator, "SN123456")
        info = entity.device_info
        assert ("deye_cloud", "SN123456") in info["identifiers"]

    def test_new_alert_fires_event(self):
        """Test that a new alert fires an alert event."""
        alert = _make_alert()
        coordinator = _make_coordinator(data=_make_device_data(alerts=[alert]))
        entity = DeyeAlertEventEntity(coordinator, "SN123456")
        # No previous alerts
        entity._previous_alerts = []

        entity._handle_coordinator_update()

        assert len(entity._fired_events) == 1
        event = entity._fired_events[0]
        assert event["event_type"] == EVENT_TYPE_ALERT
        assert event["event_attributes"]["alert_type"] == "overvoltage"
        assert event["event_attributes"]["severity"] == "warning"
        assert event["event_attributes"]["timestamp"] == alert.timestamp.isoformat()
        assert event["event_attributes"]["message"] == "Voltage too high"

    def test_resolved_alert_fires_resolution_event(self):
        """Test that a resolved alert fires a resolution event."""
        alert = _make_alert()
        coordinator = _make_coordinator(data=_make_device_data(alerts=[]))
        entity = DeyeAlertEventEntity(coordinator, "SN123456")
        # Previously had one alert
        entity._previous_alerts = [alert]

        entity._handle_coordinator_update()

        assert len(entity._fired_events) == 1
        event = entity._fired_events[0]
        assert event["event_type"] == EVENT_TYPE_ALERT_RESOLVED
        assert event["event_attributes"]["alert_type"] == "overvoltage"
        assert "resolution_timestamp" in event["event_attributes"]

    def test_no_change_fires_no_event(self):
        """Test that no events fire when alerts haven't changed."""
        alert = _make_alert()
        coordinator = _make_coordinator(data=_make_device_data(alerts=[alert]))
        entity = DeyeAlertEventEntity(coordinator, "SN123456")
        entity._previous_alerts = [alert]

        entity._handle_coordinator_update()

        assert not hasattr(entity, "_fired_events") or len(entity._fired_events) == 0

    def test_multiple_new_alerts_fire_multiple_events(self):
        """Test that multiple new alerts each fire their own event."""
        alert1 = _make_alert(alert_type="overvoltage", timestamp=datetime(2024, 1, 15, 10, 0))
        alert2 = _make_alert(alert_type="overcurrent", timestamp=datetime(2024, 1, 15, 11, 0))
        coordinator = _make_coordinator(data=_make_device_data(alerts=[alert1, alert2]))
        entity = DeyeAlertEventEntity(coordinator, "SN123456")
        entity._previous_alerts = []

        entity._handle_coordinator_update()

        assert len(entity._fired_events) == 2
        types = [e["event_attributes"]["alert_type"] for e in entity._fired_events]
        assert "overvoltage" in types
        assert "overcurrent" in types

    def test_coordinator_data_none_no_event(self):
        """Test that no events fire when coordinator data is None."""
        coordinator = _make_coordinator()
        coordinator.data = None
        entity = DeyeAlertEventEntity(coordinator, "SN123456")
        entity._previous_alerts = [_make_alert()]

        entity._handle_coordinator_update()

        assert not hasattr(entity, "_fired_events") or len(entity._fired_events) == 0

    def test_previous_alerts_updated_after_processing(self):
        """Test that _previous_alerts is updated after event processing."""
        alert = _make_alert()
        coordinator = _make_coordinator(data=_make_device_data(alerts=[alert]))
        entity = DeyeAlertEventEntity(coordinator, "SN123456")
        entity._previous_alerts = []

        entity._handle_coordinator_update()

        assert len(entity._previous_alerts) == 1
        assert entity._previous_alerts[0].alert_type == "overvoltage"


class TestDeyeStationAlertEventEntity:
    """Tests for the DeyeStationAlertEventEntity class."""

    def test_init_sets_unique_id(self):
        """Test that unique_id is set based on station ID."""
        coordinator = _make_coordinator()
        entity = DeyeStationAlertEventEntity(
            coordinator, "STATION001", "My Station", [coordinator]
        )
        assert entity._attr_unique_id == "STATION001_station_alerts"

    def test_device_info_links_to_station(self):
        """Test that device_info links to station device."""
        coordinator = _make_coordinator()
        entity = DeyeStationAlertEventEntity(
            coordinator, "STATION001", "My Station", [coordinator]
        )
        info = entity.device_info
        assert ("deye_cloud", "STATION001") in info["identifiers"]
        assert info["name"] == "My Station"

    def test_station_alert_includes_station_id(self):
        """Test that station alert events include the station identifier."""
        alert = _make_alert()
        coordinator = _make_coordinator(data=_make_device_data(alerts=[alert]))
        entity = DeyeStationAlertEventEntity(
            coordinator, "STATION001", "My Station", [coordinator]
        )
        entity._previous_alerts = {}

        entity._handle_coordinator_update()

        assert len(entity._fired_events) == 1
        event = entity._fired_events[0]
        assert event["event_type"] == EVENT_TYPE_ALERT
        assert event["event_attributes"]["station_id"] == "STATION001"
        assert event["event_attributes"]["alert_type"] == "overvoltage"

    def test_station_resolution_includes_station_id(self):
        """Test that station resolution events include the station identifier."""
        alert = _make_alert()
        coordinator = _make_coordinator(data=_make_device_data(alerts=[]))
        entity = DeyeStationAlertEventEntity(
            coordinator, "STATION001", "My Station", [coordinator]
        )
        entity._previous_alerts = {coordinator.device_sn: [alert]}

        entity._handle_coordinator_update()

        assert len(entity._fired_events) == 1
        event = entity._fired_events[0]
        assert event["event_type"] == EVENT_TYPE_ALERT_RESOLVED
        assert event["event_attributes"]["station_id"] == "STATION001"
        assert event["event_attributes"]["alert_type"] == "overvoltage"

    def test_station_multi_coordinator_alerts(self):
        """Test that station entity aggregates alerts from multiple coordinators."""
        alert1 = _make_alert(alert_type="overvoltage", timestamp=datetime(2024, 1, 15, 10, 0))
        alert2 = _make_alert(alert_type="overcurrent", timestamp=datetime(2024, 1, 15, 11, 0))

        coord1 = _make_coordinator("SN001", _make_device_data(alerts=[alert1]))
        coord2 = _make_coordinator("SN002", _make_device_data(alerts=[alert2]))

        entity = DeyeStationAlertEventEntity(
            coord1, "STATION001", "My Station", [coord1, coord2]
        )
        entity._previous_alerts = {}

        entity._handle_coordinator_update()

        assert len(entity._fired_events) == 2
        types = [e["event_attributes"]["alert_type"] for e in entity._fired_events]
        assert "overvoltage" in types
        assert "overcurrent" in types


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_creates_entities_for_each_inverter(self):
        """Test that one alert entity is created per inverter."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry"

        coord1 = _make_coordinator("SN001")
        coord2 = _make_coordinator("SN002")

        hass.data = {
            "deye_cloud": {
                "test_entry": {
                    "device_coordinators": {"SN001": coord1, "SN002": coord2},
                    "station_devices_map": {},
                    "stations_metadata": {},
                }
            }
        }

        entities = []
        async_add_entities = lambda e: entities.extend(e)

        await async_setup_entry(hass, entry, async_add_entities)

        inverter_entities = [
            e for e in entities if isinstance(e, DeyeAlertEventEntity)
        ]
        assert len(inverter_entities) == 2

    @pytest.mark.asyncio
    async def test_creates_station_entities(self):
        """Test that one station alert entity is created per station."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry"

        coord1 = _make_coordinator("SN001")

        hass.data = {
            "deye_cloud": {
                "test_entry": {
                    "device_coordinators": {"SN001": coord1},
                    "station_devices_map": {"STATION001": ["SN001"]},
                    "stations_metadata": {
                        "STATION001": {"name": "My Station"}
                    },
                }
            }
        }

        entities = []
        async_add_entities = lambda e: entities.extend(e)

        await async_setup_entry(hass, entry, async_add_entities)

        station_entities = [
            e for e in entities if isinstance(e, DeyeStationAlertEventEntity)
        ]
        assert len(station_entities) == 1
        assert station_entities[0]._station_id == "STATION001"
