"""Config flow for the Deye Cloud integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithConfigEntry,
)
from homeassistant.const import CONF_SCAN_INTERVAL

from .api import DeyeCloudAPI
from .const import (
    DEFAULT_PANEL_AZIMUTH,
    DEFAULT_PANEL_TILT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SYSTEM_EFFICIENCY,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MAX_SYSTEM_EFFICIENCY,
    MAX_TARIFF_PERIODS,
    MIN_SCAN_INTERVAL,
    MIN_SYSTEM_EFFICIENCY,
)
from .exceptions import DeyeApiError, DeyeAuthError, DeyeConnectionError
from .helpers import check_time_periods_overlap
from .models import Device, Station

_LOGGER = logging.getLogger(__name__)

CONF_APP_ID = "app_id"
CONF_APP_SECRET = "app_secret"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_INVERTERS = "inverters"
CONF_STATIONS = "stations"
CONF_PANEL_TILT = "panel_tilt"
CONF_PANEL_AZIMUTH = "panel_azimuth"
CONF_SYSTEM_EFFICIENCY = "system_efficiency"
CONF_TARIFF_PERIODS = "tariff_periods"

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_APP_ID): str,
        vol.Required(CONF_APP_SECRET): str,
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(
            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
        ): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
        ),
    }
)


class DeyeCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Deye Cloud."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._app_id: str = ""
        self._app_secret: str = ""
        self._email: str = ""
        self._password_hash: str = ""
        self._scan_interval: int = DEFAULT_SCAN_INTERVAL
        self._stations: list[Station] = []
        self._devices: dict[str, list[Device]] = {}  # station_id -> devices

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> DeyeCloudOptionsFlowHandler:
        """Get the options flow handler."""
        return DeyeCloudOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial credentials step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._app_id = user_input[CONF_APP_ID]
            self._app_secret = user_input[CONF_APP_SECRET]
            self._scan_interval = user_input[CONF_SCAN_INTERVAL]

            # Hash the password with SHA-256 as required by Deye API
            import hashlib
            password_hash = hashlib.sha256(
                user_input[CONF_PASSWORD].encode("utf-8")
            ).hexdigest()
            self._email = user_input[CONF_EMAIL]
            self._password_hash = password_hash

            # Check for duplicate config entries
            await self.async_set_unique_id(self._app_id)
            self._abort_if_unique_id_configured()

            # Validate credentials against the API
            try:
                async with aiohttp.ClientSession() as session:
                    api = DeyeCloudAPI(
                        session,
                        self._app_id,
                        self._app_secret,
                        email=user_input[CONF_EMAIL],
                        password_hash=password_hash,
                    )
                    await api.authenticate()

                    # Discover stations
                    self._stations = await api.get_station_list()
                    # Note: device/list endpoint may not be available for all accounts
                    # Skip device discovery for now - user will input device SNs manually
                    # or we discover them from station data later

            except DeyeAuthError:
                errors["base"] = "invalid_auth"
            except (DeyeConnectionError, aiohttp.ClientError) as err:
                _LOGGER.error("Connection error during config flow: %s", err)
                errors["base"] = "cannot_connect"
            except DeyeApiError as err:
                _LOGGER.error(
                    "API error during config flow: %s (code=%s)",
                    err,
                    getattr(err, "error_code", "unknown"),
                )
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception(
                    "Unexpected error during config flow setup: %s (%s)",
                    err,
                    type(err).__name__,
                )
                errors["base"] = "unknown"
            else:
                # Check if we found stations
                if not self._stations:
                    return self.async_abort(reason="no_devices")

                # Proceed to device selection step
                return await self.async_step_select_devices()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_select_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the device selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Parse device serial numbers from comma-separated input
            inverter_input = user_input.get(CONF_INVERTERS, "")
            selected_inverters = [
                sn.strip() for sn in inverter_input.split(",") if sn.strip()
            ] if isinstance(inverter_input, str) else list(inverter_input)

            selected_stations = user_input.get(CONF_STATIONS, [])

            if not selected_inverters and not selected_stations:
                errors["base"] = "no_devices"
            else:
                # Create the config entry
                return self.async_create_entry(
                    title=f"Deye Cloud ({self._app_id})",
                    data={
                        CONF_APP_ID: self._app_id,
                        CONF_APP_SECRET: self._app_secret,
                        "email": self._email,
                        "password_hash": self._password_hash,
                        CONF_SCAN_INTERVAL: self._scan_interval,
                        CONF_INVERTERS: selected_inverters,
                        CONF_STATIONS: selected_stations,
                    },
                )

        # Build multi-select options for stations
        station_options: dict[str, str] = {}
        for station in self._stations:
            label = f"{station.name} ({station.rated_capacity_kwp} kWp)"
            station_options[station.station_id] = label

        # Schema: stations as multi-select, inverters as comma-separated text
        select_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_STATIONS,
                    default=list(station_options.keys()),
                ): vol.All(
                    vol.Coerce(list),
                    [vol.In(station_options)],
                ) if station_options else vol.Optional(CONF_STATIONS, default=[]),
                vol.Required(CONF_INVERTERS, default=""): str,
            }
        )

        return self.async_show_form(
            step_id="select_devices",
            data_schema=select_schema,
            errors=errors,
            description_placeholders={
                "stations_found": str(len(self._stations)),
            },
        )


class DeyeCloudOptionsFlowHandler(OptionsFlowWithConfigEntry):
    """Handle options flow for Deye Cloud."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial options step (polling + forecast settings)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate system efficiency range
            efficiency = user_input.get(
                CONF_SYSTEM_EFFICIENCY, DEFAULT_SYSTEM_EFFICIENCY
            )
            if not (MIN_SYSTEM_EFFICIENCY <= efficiency <= MAX_SYSTEM_EFFICIENCY):
                errors[CONF_SYSTEM_EFFICIENCY] = "invalid_efficiency"
            else:
                # Save options and show menu for sub-steps
                options = dict(self.options)
                options[CONF_SCAN_INTERVAL] = user_input[CONF_SCAN_INTERVAL]
                options[CONF_PANEL_TILT] = user_input[CONF_PANEL_TILT]
                options[CONF_PANEL_AZIMUTH] = user_input[CONF_PANEL_AZIMUTH]
                options[CONF_SYSTEM_EFFICIENCY] = user_input[CONF_SYSTEM_EFFICIENCY]
                self.options.update(options)
                return await self.async_step_menu()

        current_options = self.options
        scan_interval = current_options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        panel_tilt = current_options.get(CONF_PANEL_TILT, DEFAULT_PANEL_TILT)
        panel_azimuth = current_options.get(CONF_PANEL_AZIMUTH, DEFAULT_PANEL_AZIMUTH)
        system_efficiency = current_options.get(
            CONF_SYSTEM_EFFICIENCY, DEFAULT_SYSTEM_EFFICIENCY
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=scan_interval
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
                vol.Required(
                    CONF_PANEL_TILT, default=panel_tilt
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=0, max=90),
                ),
                vol.Required(
                    CONF_PANEL_AZIMUTH, default=panel_azimuth
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=0, max=360),
                ),
                vol.Required(
                    CONF_SYSTEM_EFFICIENCY, default=system_efficiency
                ): vol.All(
                    vol.Coerce(float),
                    vol.Range(
                        min=MIN_SYSTEM_EFFICIENCY, max=MAX_SYSTEM_EFFICIENCY
                    ),
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a menu to navigate to sub-steps."""
        return self.async_show_menu(
            step_id="menu",
            menu_options=["devices", "credentials", "tariff", "finish"],
        )

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the devices selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_inverters = user_input.get(CONF_INVERTERS, [])
            if not selected_inverters:
                errors["base"] = "no_devices"
            else:
                options = dict(self.options)
                options[CONF_INVERTERS] = selected_inverters
                self.options.update(options)
                return await self.async_step_menu()

        # Get current inverters from config entry data
        current_inverters = self.options.get(
            CONF_INVERTERS,
            self.config_entry.data.get(CONF_INVERTERS, []),
        )

        # Discover available inverters from the API
        inverter_options: dict[str, str] = {}
        try:
            app_id = self.config_entry.data[CONF_APP_ID]
            app_secret = self.config_entry.data[CONF_APP_SECRET]
            async with aiohttp.ClientSession() as session:
                api = DeyeCloudAPI(session, app_id, app_secret)
                await api.authenticate()
                stations = await api.get_station_list()
                for station in stations:
                    devices = await api.get_device_list(station.station_id)
                    for device in devices:
                        label = (
                            f"{device.model_name} ({device.device_sn})"
                            f" - {station.name}"
                        )
                        inverter_options[device.device_sn] = label
        except (DeyeAuthError, DeyeConnectionError, aiohttp.ClientError):
            # If we can't reach the API, use the currently configured inverters
            for sn in current_inverters:
                inverter_options[sn] = sn

        # Default to current selection
        default_inverters = [
            sn for sn in current_inverters if sn in inverter_options
        ]

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_INVERTERS, default=default_inverters
                ): vol.All(
                    vol.Coerce(list),
                    [vol.In(inverter_options)],
                ),
            }
        )

        return self.async_show_form(
            step_id="devices",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the credentials update step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            new_app_id = user_input[CONF_APP_ID]
            new_app_secret = user_input[CONF_APP_SECRET]

            # Validate the new credentials
            try:
                async with aiohttp.ClientSession() as session:
                    api = DeyeCloudAPI(session, new_app_id, new_app_secret)
                    await api.authenticate()
            except DeyeAuthError:
                errors["base"] = "invalid_auth"
            except (DeyeConnectionError, aiohttp.ClientError) as err:
                _LOGGER.error("Connection error validating credentials: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception(
                    "Unexpected error validating credentials: %s (%s)",
                    err,
                    type(err).__name__,
                )
                errors["base"] = "unknown"
            else:
                # Update the config entry data with new credentials
                new_data = dict(self.config_entry.data)
                new_data[CONF_APP_ID] = new_app_id
                new_data[CONF_APP_SECRET] = new_app_secret
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                return await self.async_step_menu()

        current_app_id = self.config_entry.data.get(CONF_APP_ID, "")
        current_app_secret = self.config_entry.data.get(CONF_APP_SECRET, "")

        schema = vol.Schema(
            {
                vol.Required(CONF_APP_ID, default=current_app_id): str,
                vol.Required(CONF_APP_SECRET, default=current_app_secret): str,
            }
        )

        return self.async_show_form(
            step_id="credentials",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_tariff(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the tariff period configuration step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            tariff_periods = user_input.get(CONF_TARIFF_PERIODS, [])

            # Validate max periods
            if len(tariff_periods) > MAX_TARIFF_PERIODS:
                errors[CONF_TARIFF_PERIODS] = "too_many_periods"
            else:
                # Validate each period: end > start
                invalid_period = False
                periods_for_overlap: list[tuple[str, str]] = []
                for period in tariff_periods:
                    start = period.get("start_time", "")
                    end = period.get("end_time", "")
                    if not start or not end:
                        invalid_period = True
                        break
                    # Convert to minutes for comparison
                    try:
                        from .helpers import time_to_minutes

                        start_min = time_to_minutes(start)
                        end_min = time_to_minutes(end)
                        if end_min <= start_min:
                            invalid_period = True
                            break
                        periods_for_overlap.append((start, end))
                    except ValueError:
                        invalid_period = True
                        break

                if invalid_period:
                    errors[CONF_TARIFF_PERIODS] = "invalid_period"
                elif periods_for_overlap and check_time_periods_overlap(
                    periods_for_overlap
                ):
                    errors[CONF_TARIFF_PERIODS] = "overlapping_periods"
                else:
                    # Save tariff periods
                    options = dict(self.options)
                    options[CONF_TARIFF_PERIODS] = tariff_periods
                    self.options.update(options)
                    return await self.async_step_menu()

        current_periods = self.options.get(CONF_TARIFF_PERIODS, [])

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TARIFF_PERIODS, default=current_periods
                ): list,
            }
        )

        return self.async_show_form(
            step_id="tariff",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finalize options and create entry."""
        return self.async_create_entry(title="", data=dict(self.options))
