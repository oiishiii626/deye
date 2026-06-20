"""Event platform for the Deye Cloud integration."""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DeyeDeviceCoordinator
from .models import AlertData

_LOGGER = logging.getLogger(__name__)

EVENT_TYPE_ALERT = "alert"
EVENT_TYPE_ALERT_RESOLVED = "alert_resolved"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Deye Cloud event entities from a config entry.

    Creates an event entity per inverter for alert notifications,
    and a station-level event entity per station.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    device_coordinators: dict[str, DeyeDeviceCoordinator] = data["device_coordinators"]
    station_devices_map: dict[str, list[str]] = data.get("station_devices_map", {})
    stations_metadata: dict[str, dict] = data.get("stations_metadata", {})

    entities: list = []

    # Create per-inverter alert entities
    for device_sn, coordinator in device_coordinators.items():
        entities.append(DeyeAlertEventEntity(coordinator, device_sn))

    # Create per-station alert entities
    for station_id, device_sns in station_devices_map.items():
        station_meta = stations_metadata.get(station_id, {})
        station_name = station_meta.get("name", f"Station {station_id}")
        station_coordinators = [
            device_coordinators[sn]
            for sn in device_sns
            if sn in device_coordinators
        ]
        if station_coordinators:
            entities.append(
                DeyeStationAlertEventEntity(
                    station_coordinators[0],
                    station_id,
                    station_name,
                    station_coordinators,
                )
            )

    async_add_entities(entities)


class DeyeAlertEventEntity(CoordinatorEntity[DeyeDeviceCoordinator], EventEntity):
    """Event entity for Deye Cloud inverter alerts."""

    _attr_has_entity_name = True
    _attr_name = "Inverter Alert"
    _attr_event_types = [EVENT_TYPE_ALERT, EVENT_TYPE_ALERT_RESOLVED]

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        device_sn: str,
    ) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._attr_unique_id = f"{device_sn}_alerts"
        self._previous_alerts: list[AlertData] = []

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link this entity to the inverter device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_sn)},
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data is None:
            return

        current_alerts = self.coordinator.data.active_alerts or []

        # Detect new alerts
        previous_types = {a.alert_type for a in self._previous_alerts}
        for alert in current_alerts:
            if alert.alert_type not in previous_types:
                self._trigger_event(
                    EVENT_TYPE_ALERT,
                    {
                        "alert_type": alert.alert_type,
                        "severity": alert.severity,
                        "timestamp": alert.timestamp.isoformat(),
                        "message": alert.message,
                    },
                )

        # Detect resolved alerts
        current_types = {a.alert_type for a in current_alerts}
        for alert in self._previous_alerts:
            if alert.alert_type not in current_types:
                self._trigger_event(
                    EVENT_TYPE_ALERT_RESOLVED,
                    {
                        "alert_type": alert.alert_type,
                        "resolution_timestamp": datetime.now().isoformat(),
                    },
                )

        self._previous_alerts = list(current_alerts)


class DeyeStationAlertEventEntity(CoordinatorEntity[DeyeDeviceCoordinator], EventEntity):
    """Event entity for station-level alerts aggregated from all inverters."""

    _attr_has_entity_name = True
    _attr_name = "Station Alert"
    _attr_event_types = [EVENT_TYPE_ALERT, EVENT_TYPE_ALERT_RESOLVED]

    def __init__(
        self,
        coordinator: DeyeDeviceCoordinator,
        station_id: str,
        station_name: str,
        coordinators: list[DeyeDeviceCoordinator],
    ) -> None:
        """Initialize the station event entity."""
        super().__init__(coordinator)
        self._station_id = station_id
        self._station_name = station_name
        self._coordinators = coordinators
        self._attr_unique_id = f"{station_id}_station_alerts"
        self._previous_alerts: dict[str, list[AlertData]] = {}

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link this entity to the station device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._station_id)},
            name=self._station_name,
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinators."""
        for coord in self._coordinators:
            if coord.data is None:
                continue

            device_sn = coord.device_sn
            current_alerts = coord.data.active_alerts or []
            previous_alerts = self._previous_alerts.get(device_sn, [])

            # Detect new alerts
            previous_types = {a.alert_type for a in previous_alerts}
            for alert in current_alerts:
                if alert.alert_type not in previous_types:
                    self._trigger_event(
                        EVENT_TYPE_ALERT,
                        {
                            "station_id": self._station_id,
                            "alert_type": alert.alert_type,
                            "severity": alert.severity,
                            "timestamp": alert.timestamp.isoformat(),
                            "message": alert.message,
                        },
                    )

            # Detect resolved alerts
            current_types = {a.alert_type for a in current_alerts}
            for alert in previous_alerts:
                if alert.alert_type not in current_types:
                    self._trigger_event(
                        EVENT_TYPE_ALERT_RESOLVED,
                        {
                            "station_id": self._station_id,
                            "alert_type": alert.alert_type,
                            "resolution_timestamp": datetime.now().isoformat(),
                        },
                    )

            self._previous_alerts[device_sn] = list(current_alerts)
