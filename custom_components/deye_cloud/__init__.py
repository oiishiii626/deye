"""The Deye Cloud integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DeyeCloudAPI
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS
from .coordinator import DeyeDeviceCoordinator

_LOGGER = logging.getLogger(__name__)

# Config flow keys (mirrored from config_flow.py to avoid circular imports)
CONF_APP_ID = "app_id"
CONF_APP_SECRET = "app_secret"
CONF_INVERTERS = "inverters"
CONF_STATIONS = "stations"
CONF_TARIFF_PERIODS = "tariff_periods"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Deye Cloud from a config entry.

    Steps:
    1. Get credentials from config entry data
    2. Create a shared aiohttp session
    3. Create DeyeCloudAPI instance
    4. Authenticate (validate credentials still work)
    5. Create a DeyeDeviceCoordinator per configured inverter
    6. Create a ForecastCoordinator per configured station (placeholder)
    7. If tariff config exists: create TariffManager per inverter (placeholder)
    8. Store coordinators and managers in hass.data
    9. Forward setup to all platforms
    10. Register services (placeholder)
    11. Register dashboard (placeholder)
    """
    hass.data.setdefault(DOMAIN, {})

    # 1. Get credentials and config from entry data
    app_id: str = entry.data[CONF_APP_ID]
    app_secret: str = entry.data[CONF_APP_SECRET]
    email: str = entry.data.get("email", "")
    password_hash: str = entry.data.get("password_hash", "")
    scan_interval: int = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    inverters: list[str] = entry.data.get(CONF_INVERTERS, [])
    stations: list[str] = entry.data.get(CONF_STATIONS, [])

    # 2. Create shared aiohttp session
    session = async_get_clientsession(hass)

    # 3. Create DeyeCloudAPI instance
    api = DeyeCloudAPI(session, app_id, app_secret, email=email, password_hash=password_hash)

    # 4. Authenticate (validate credentials still work)
    await api.authenticate()

    # 5. Create one DeyeDeviceCoordinator per configured inverter
    device_coordinators: dict[str, DeyeDeviceCoordinator] = {}
    for device_sn in inverters:
        coordinator = DeyeDeviceCoordinator(
            hass=hass,
            api=api,
            device_sn=device_sn,
            interval=timedelta(seconds=scan_interval),
        )
        await coordinator.async_config_entry_first_refresh()
        device_coordinators[device_sn] = coordinator

    # 6. Create one ForecastCoordinator per configured station (placeholder)
    forecast_coordinators: dict[str, Any] = {}
    try:
        from .forecast import ForecastCoordinator

        for station_id in stations:
            forecast_coord = ForecastCoordinator(
                hass=hass,
                station_id=station_id,
                entry=entry,
            )
            await forecast_coord.async_config_entry_first_refresh()
            forecast_coordinators[station_id] = forecast_coord
    except ImportError:
        _LOGGER.debug(
            "ForecastCoordinator not available yet, skipping forecast setup"
        )

    # 7. Create TariffManager per inverter if tariff config exists (placeholder)
    tariff_managers: dict[str, Any] = {}
    tariff_periods = entry.options.get(CONF_TARIFF_PERIODS) or entry.data.get(
        CONF_TARIFF_PERIODS
    )
    if tariff_periods:
        try:
            from .tariff import TariffManager

            for device_sn in inverters:
                coordinator = device_coordinators[device_sn]
                tariff_manager = TariffManager(
                    hass=hass,
                    api=api,
                    device_sn=device_sn,
                    coordinator=coordinator,
                    tariff_periods=tariff_periods,
                )
                await tariff_manager.async_start()
                tariff_managers[device_sn] = tariff_manager
        except ImportError:
            _LOGGER.debug(
                "TariffManager not available yet, skipping tariff setup"
            )

    # 8. Discover station and device metadata for entity creation
    stations_metadata: dict[str, Any] = {}
    devices_metadata: dict[str, Any] = {}
    station_devices_map: dict[str, list[str]] = {}  # station_id -> [device_sn]

    try:
        discovered_stations = await api.get_station_list()
        for station in discovered_stations:
            if station.station_id in stations:
                stations_metadata[station.station_id] = {
                    "name": station.name,
                    "latitude": station.latitude,
                    "longitude": station.longitude,
                    "rated_capacity_kwp": station.rated_capacity_kwp,
                }
                # Discover which inverters belong to this station
                discovered_devices = await api.get_device_list(station.station_id)
                station_device_sns = [
                    d.device_sn
                    for d in discovered_devices
                    if d.device_sn in inverters
                ]
                station_devices_map[station.station_id] = station_device_sns
                for device in discovered_devices:
                    if device.device_sn in inverters:
                        devices_metadata[device.device_sn] = device
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "Failed to discover station/device metadata, station sensors may be limited"
        )

    # 9. Store coordinators and managers in hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "device_coordinators": device_coordinators,
        "forecast_coordinators": forecast_coordinators,
        "tariff_managers": tariff_managers,
        "stations_metadata": stations_metadata,
        "devices_metadata": devices_metadata,
        "station_devices_map": station_devices_map,
    }

    # 10. Forward setup to all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 11. Register services (placeholder)
    try:
        from .services import async_register_services

        await async_register_services(hass)
    except ImportError:
        _LOGGER.debug("Services module not available yet, skipping service registration")

    # 12. Register dashboard (placeholder)
    try:
        from .dashboard import async_register_dashboard

        await async_register_dashboard(hass)
    except ImportError:
        _LOGGER.debug(
            "Dashboard module not available yet, skipping dashboard registration"
        )

    # 13. Register options update listener for dynamic add/remove of inverters
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Deye Cloud config entry.

    Steps:
    1. Unload all platforms
    2. Stop tariff managers
    3. Unregister services (if applicable)
    4. Clean up hass.data
    """
    # 1. Unload all platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, {})

        # 2. Stop tariff managers
        tariff_managers: dict[str, Any] = entry_data.get("tariff_managers", {})
        for device_sn, manager in tariff_managers.items():
            try:
                await manager.async_stop()
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Error stopping tariff manager for %s", device_sn
                )

        # 3. Unregister services if no more entries remain
        if not hass.data[DOMAIN]:
            try:
                from .services import async_unregister_services

                await async_unregister_services(hass)
            except ImportError:
                pass

        # Clean up domain data if empty
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok


async def _async_options_updated(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options flow update: add/remove inverters dynamically.

    When the user modifies the inverter list via the options flow, this listener
    compares the new list against the currently-running coordinators and:
    - Adds new coordinators + entities for newly-added inverters
    - Removes devices + entities for removed inverters via the device registry

    This avoids requiring a full integration reload/restart.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None:
        # Entry not fully set up yet or already unloaded
        return

    # Determine the new set of inverters from options (fallback to entry.data)
    new_inverters: list[str] = entry.options.get(
        CONF_INVERTERS, entry.data.get(CONF_INVERTERS, [])
    )
    device_coordinators: dict[str, DeyeDeviceCoordinator] = entry_data[
        "device_coordinators"
    ]
    current_inverters = set(device_coordinators.keys())
    target_inverters = set(new_inverters)

    added = target_inverters - current_inverters
    removed = current_inverters - target_inverters

    api: DeyeCloudAPI = entry_data["api"]
    scan_interval: int = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    # Handle removed inverters: remove device from registry (cascades entities)
    if removed:
        device_reg = dr.async_get(hass)
        for device_sn in removed:
            _LOGGER.info("Removing inverter %s via options flow", device_sn)
            device_entry = device_reg.async_get_device(
                identifiers={(DOMAIN, device_sn)}
            )
            if device_entry is not None:
                device_reg.async_remove_device(device_entry.id)
            # Remove coordinator reference
            device_coordinators.pop(device_sn, None)

    # Handle added inverters: create coordinator + trigger first refresh
    for device_sn in added:
        _LOGGER.info("Adding inverter %s via options flow", device_sn)
        coordinator = DeyeDeviceCoordinator(
            hass=hass,
            api=api,
            device_sn=device_sn,
            interval=timedelta(seconds=scan_interval),
        )
        await coordinator.async_config_entry_first_refresh()
        device_coordinators[device_sn] = coordinator

    # If inverters were added, reload platforms to pick up new entities
    if added:
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Update scan interval for existing coordinators if it changed
    for device_sn, coordinator in device_coordinators.items():
        coordinator.update_interval = timedelta(seconds=scan_interval)
