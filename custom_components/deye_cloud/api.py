"""Async client for the Deye Cloud developer API."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from .const import (
    API_AUTH_TIMEOUT,
    API_REQUEST_TIMEOUT,
    TOKEN_REFRESH_BACKOFF_MULTIPLIER,
    TOKEN_REFRESH_INITIAL_DELAY_S,
    TOKEN_REFRESH_MAX_DELAY_S,
    TOKEN_REFRESH_MAX_RETRIES,
    TOKEN_REFRESH_WINDOW_S,
)
from .exceptions import (
    DeyeApiError,
    DeyeAuthError,
    DeyeConnectionError,
    DeyeRateLimitError,
    DeyeTimeoutError,
)
from .models import TOUSchedule
from .models import Device, EnergyPattern, Station, WorkMode

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://eu1-developer.deyecloud.com:443"


class DeyeCloudAPI:
    """Async client for Deye Cloud developer API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        app_id: str,
        app_secret: str,
    ) -> None:
        """Initialize the Deye Cloud API client.

        Args:
            session: An aiohttp ClientSession for making HTTP requests.
            app_id: The Deye Cloud application ID.
            app_secret: The Deye Cloud application secret.
        """
        self._session = session
        self._app_id = app_id
        self._app_secret = app_secret
        self._access_token: str | None = None
        self._token_expiry: float = 0.0  # Unix timestamp when token expires

    @property
    def access_token(self) -> str | None:
        """Return the current access token."""
        return self._access_token

    @property
    def token_expiry(self) -> float:
        """Return the token expiry timestamp."""
        return self._token_expiry

    async def authenticate(self) -> str:
        """Authenticate with the Deye Cloud API and obtain an access token.

        POST /v1.0/account/token with app_id and app_secret.

        Returns:
            The access token string.

        Raises:
            DeyeAuthError: If authentication fails (invalid credentials).
            DeyeTimeoutError: If the request exceeds the 10s timeout.
            DeyeConnectionError: If unable to connect to the API.
        """
        url = f"{BASE_URL}/v1.0/account/token"
        payload = {
            "appId": self._app_id,
            "appSecret": self._app_secret,
        }

        try:
            async with self._session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=API_AUTH_TIMEOUT),
            ) as response:
                data = await response.json()

                if response.status == 401:
                    raise DeyeAuthError(
                        "Authentication failed: invalid credentials"
                    )

                if response.status != 200:
                    error_msg = data.get("msg", "Unknown error")
                    raise DeyeApiError(
                        f"Authentication request failed: {error_msg}",
                        error_code=str(data.get("code", "")),
                    )

                # Check API-level success code
                if data.get("code") not in (0, "0", None):
                    # Some API implementations use code != 0 to indicate failure
                    if data.get("code") in ("401", 401, "UNAUTHORIZED"):
                        raise DeyeAuthError(
                            f"Authentication failed: {data.get('msg', 'invalid credentials')}"
                        )
                    raise DeyeApiError(
                        f"Authentication failed: {data.get('msg', 'unknown error')}",
                        error_code=str(data.get("code", "")),
                    )

                # Extract token data from response
                token_data = data.get("data", data)
                access_token = token_data.get("accessToken") or token_data.get(
                    "access_token"
                )
                expires_in = token_data.get("expiresIn") or token_data.get(
                    "expires_in", 7200
                )

                if not access_token:
                    raise DeyeAuthError(
                        "Authentication failed: no access token in response"
                    )

                self._access_token = access_token
                self._token_expiry = time.time() + int(expires_in)

                _LOGGER.debug(
                    "Successfully authenticated, token expires in %s seconds",
                    expires_in,
                )
                return access_token

        except asyncio.TimeoutError as err:
            raise DeyeTimeoutError(
                f"Authentication request timed out after {API_AUTH_TIMEOUT}s"
            ) from err
        except aiohttp.ClientConnectorError as err:
            raise DeyeConnectionError(
                f"Unable to connect to Deye Cloud API: {err}"
            ) from err
        except (DeyeAuthError, DeyeApiError, DeyeTimeoutError, DeyeConnectionError):
            raise
        except aiohttp.ClientError as err:
            raise DeyeConnectionError(
                f"Connection error during authentication: {err}"
            ) from err

    async def _ensure_token(self) -> None:
        """Ensure a valid access token is available.

        Checks if the current token is within TOKEN_REFRESH_WINDOW_S (60s) of
        expiry and refreshes proactively. Uses exponential backoff (2s, 4s, 8s)
        for up to TOKEN_REFRESH_MAX_RETRIES (3) attempts.

        Raises:
            DeyeAuthError: If token refresh fails after all retry attempts.
        """
        if (
            self._access_token is not None
            and time.time() < self._token_expiry - TOKEN_REFRESH_WINDOW_S
        ):
            # Token is still valid and not near expiry
            return

        # Token is missing, expired, or within refresh window - refresh it
        delay = TOKEN_REFRESH_INITIAL_DELAY_S
        last_error: Exception | None = None

        for attempt in range(TOKEN_REFRESH_MAX_RETRIES):
            try:
                await self.authenticate()
                return
            except (DeyeAuthError, DeyeApiError) as err:
                # Auth errors are not transient - don't retry
                raise
            except (DeyeTimeoutError, DeyeConnectionError) as err:
                last_error = err
                if attempt < TOKEN_REFRESH_MAX_RETRIES - 1:
                    _LOGGER.debug(
                        "Token refresh attempt %d failed, retrying in %ds: %s",
                        attempt + 1,
                        delay,
                        err,
                    )
                    await asyncio.sleep(delay)
                    delay = min(
                        delay * TOKEN_REFRESH_BACKOFF_MULTIPLIER,
                        TOKEN_REFRESH_MAX_DELAY_S,
                    )

        # All retries exhausted
        raise DeyeAuthError(
            f"Token refresh failed after {TOKEN_REFRESH_MAX_RETRIES} attempts: {last_error}"
        )

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        payload: dict[str, Any] | None = None,
        retry_on_401: bool = True,
    ) -> dict[str, Any]:
        """Make an authenticated API request.

        Ensures a valid token before making the request. Includes the access
        token in the request headers. On 401 response, performs a single retry
        with a fresh token.

        Args:
            method: HTTP method (e.g., "POST").
            endpoint: API endpoint path (e.g., "/v1.0/device/list").
            payload: Optional JSON payload for the request body.
            retry_on_401: Whether to retry once on 401 response (prevents
                infinite recursion).

        Returns:
            The parsed JSON response data.

        Raises:
            DeyeAuthError: If authentication fails.
            DeyeApiError: If the API returns a non-success response.
            DeyeTimeoutError: If the request times out.
            DeyeRateLimitError: If the API returns HTTP 429.
            DeyeConnectionError: If unable to connect.
        """
        await self._ensure_token()

        url = f"{BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        try:
            async with self._session.request(
                method,
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=API_REQUEST_TIMEOUT),
            ) as response:
                # Handle rate limiting
                if response.status == 429:
                    retry_after = response.headers.get("Retry-After")
                    retry_after_s = (
                        int(retry_after) if retry_after else None
                    )
                    raise DeyeRateLimitError(
                        f"Rate limited on {endpoint}",
                        retry_after=retry_after_s,
                    )

                # Handle 401 - single retry with fresh token
                if response.status == 401:
                    if retry_on_401:
                        _LOGGER.debug(
                            "Received 401 on %s, refreshing token and retrying",
                            endpoint,
                        )
                        # Invalidate current token to force refresh
                        self._access_token = None
                        self._token_expiry = 0.0
                        return await self._request(
                            method,
                            endpoint,
                            payload=payload,
                            retry_on_401=False,
                        )
                    raise DeyeAuthError(
                        f"Authentication failed on {endpoint} after token refresh"
                    )

                data = await response.json()

                # Handle HTTP-level errors
                if response.status >= 400:
                    error_msg = data.get("msg", f"HTTP {response.status}")
                    error_code = str(data.get("code", response.status))
                    raise DeyeApiError(
                        f"API error on {endpoint}: {error_msg}",
                        error_code=error_code,
                    )

                # Check API-level success code
                api_code = data.get("code")
                if api_code is not None and api_code not in (0, "0"):
                    # Handle API-level auth errors
                    if api_code in ("401", 401, "UNAUTHORIZED"):
                        if retry_on_401:
                            _LOGGER.debug(
                                "API returned auth error code on %s, refreshing token",
                                endpoint,
                            )
                            self._access_token = None
                            self._token_expiry = 0.0
                            return await self._request(
                                method,
                                endpoint,
                                payload=payload,
                                retry_on_401=False,
                            )
                        raise DeyeAuthError(
                            f"Authentication failed on {endpoint}: {data.get('msg', 'unauthorized')}"
                        )

                    raise DeyeApiError(
                        f"API error on {endpoint}: {data.get('msg', 'unknown error')}",
                        error_code=str(api_code),
                    )

                return data

        except asyncio.TimeoutError as err:
            raise DeyeTimeoutError(
                f"Request to {endpoint} timed out after {API_REQUEST_TIMEOUT}s"
            ) from err
        except aiohttp.ClientConnectorError as err:
            raise DeyeConnectionError(
                f"Unable to connect to Deye Cloud API for {endpoint}: {err}"
            ) from err
        except (
            DeyeAuthError,
            DeyeApiError,
            DeyeTimeoutError,
            DeyeRateLimitError,
            DeyeConnectionError,
        ):
            raise
        except aiohttp.ClientError as err:
            raise DeyeConnectionError(
                f"Connection error on {endpoint}: {err}"
            ) from err

    # ─── Device Data Endpoints ────────────────────────────────────────────

    async def get_device_latest(
        self, device_sn: str, measure_points: list[str]
    ) -> dict:
        """Get the latest measurement data for a device.

        POST /v1.0/device/latest

        Args:
            device_sn: The device serial number.
            measure_points: List of measurement point keys to retrieve.

        Returns:
            The response data dictionary containing measurement values.

        Raises:
            DeyeApiError: If the API returns a non-success response.
            DeyeAuthError: If authentication fails.
        """
        payload = {
            "deviceSn": device_sn,
            "measurePoints": measure_points,
        }
        response = await self._request("POST", "/v1.0/device/latest", payload=payload)
        return response.get("data", {})

    # ─── Device Control Endpoints ─────────────────────────────────────────

    async def set_device_config(self, device_sn: str, params: dict) -> bool:
        """Set device configuration (battery, grid settings, etc.).

        POST /v1.0/device/config/set

        Args:
            device_sn: The device serial number.
            params: Configuration parameters to set (e.g., battery SOC limits,
                grid export limits).

        Returns:
            True if the configuration was applied successfully.

        Raises:
            DeyeApiError: If the API returns a non-success response.
            DeyeAuthError: If authentication fails.
        """
        payload = {
            "deviceSn": device_sn,
            **params,
        }
        await self._request("POST", "/v1.0/device/config/set", payload=payload)
        return True

    async def set_work_mode(self, device_sn: str, mode: int) -> bool:
        """Set the inverter work mode.

        POST /v1.0/device/control/workMode

        Args:
            device_sn: The device serial number.
            mode: Work mode integer (see WorkMode enum).

        Returns:
            True if the work mode was set successfully.

        Raises:
            DeyeApiError: If the API returns a non-success response.
            DeyeAuthError: If authentication fails.
        """
        payload = {
            "deviceSn": device_sn,
            "workMode": mode,
        }
        await self._request("POST", "/v1.0/device/control/workMode", payload=payload)
        return True

    async def set_energy_pattern(self, device_sn: str, pattern: int) -> bool:
        """Set the battery energy pattern.

        POST /v1.0/device/control/energyPattern

        Args:
            device_sn: The device serial number.
            pattern: Energy pattern integer (see EnergyPattern enum).

        Returns:
            True if the energy pattern was set successfully.

        Raises:
            DeyeApiError: If the API returns a non-success response.
            DeyeAuthError: If authentication fails.
        """
        payload = {
            "deviceSn": device_sn,
            "energyPattern": pattern,
        }
        await self._request(
            "POST", "/v1.0/device/control/energyPattern", payload=payload
        )
        return True

    async def set_tou_schedule(self, device_sn: str, schedule: TOUSchedule) -> bool:
        """Set the Time-of-Use schedule.

        POST /v1.0/device/control/tou

        Args:
            device_sn: The device serial number.
            schedule: TOUSchedule dataclass with enabled flag and slot definitions.

        Returns:
            True if the TOU schedule was set successfully.

        Raises:
            DeyeApiError: If the API returns a non-success response.
            DeyeAuthError: If authentication fails.
        """
        slots_payload = [
            {
                "slotIndex": slot.slot_index,
                "startTime": slot.start_time,
                "endTime": slot.end_time,
                "mode": slot.mode.value,
                "powerLimitW": slot.power_limit_w,
            }
            for slot in schedule.slots
        ]
        payload = {
            "deviceSn": device_sn,
            "enabled": schedule.enabled,
            "slots": slots_payload,
        }
        await self._request("POST", "/v1.0/device/control/tou", payload=payload)
        return True

    async def set_smart_load(
        self, device_sn: str, channel: int, on: bool
    ) -> bool:
        """Control a smart load channel.

        POST /v1.0/device/control/smartload

        Args:
            device_sn: The device serial number.
            channel: The smart load channel number.
            on: True to enable the load, False to disable.

        Returns:
            True if the smart load state was set successfully.

        Raises:
            DeyeApiError: If the API returns a non-success response.
            DeyeAuthError: If authentication fails.
        """
        payload = {
            "deviceSn": device_sn,
            "channel": channel,
            "on": on,
        }
        await self._request(
            "POST", "/v1.0/device/control/smartload", payload=payload
        )
        return True

    async def send_modbus_command(
        self, device_sn: str, register: int, value: int
    ) -> dict:
        """Send a custom Modbus command to the device.

        POST /v1.0/device/control/modbus

        Args:
            device_sn: The device serial number.
            register: The Modbus register address.
            value: The value to write to the register.

        Returns:
            The response data dictionary from the Modbus operation.

        Raises:
            DeyeApiError: If the API returns a non-success response.
            DeyeAuthError: If authentication fails.
        """
        payload = {
            "deviceSn": device_sn,
            "register": register,
            "value": value,
        }
        response = await self._request(
            "POST", "/v1.0/device/control/modbus", payload=payload
        )
        return response.get("data", {})

    async def get_control_strategy(self, device_sn: str) -> dict:
        """Read the current control strategy for a device.

        POST /v1.0/device/control/strategy/read

        Args:
            device_sn: The device serial number.

        Returns:
            The response data dictionary containing the current strategy.

        Raises:
            DeyeApiError: If the API returns a non-success response.
            DeyeAuthError: If authentication fails.
        """
        payload = {
            "deviceSn": device_sn,
        }
        response = await self._request(
            "POST", "/v1.0/device/control/strategy/read", payload=payload
        )
        return response.get("data", {})

    async def set_control_strategy(self, device_sn: str, strategy: dict) -> bool:
        """Write a control strategy to a device.

        POST /v1.0/device/control/strategy/write

        Args:
            device_sn: The device serial number.
            strategy: The strategy configuration dictionary.

        Returns:
            True if the strategy was applied successfully.

        Raises:
            DeyeApiError: If the API returns a non-success response.
            DeyeAuthError: If authentication fails.
        """
        payload = {
            "deviceSn": device_sn,
            **strategy,
        }
        await self._request(
            "POST", "/v1.0/device/control/strategy/write", payload=payload
        )
        return True

    async def get_station_list(self) -> list[Station]:
        """Retrieve the list of stations associated with the account.

        POST /v1.0/station/list

        Returns:
            A list of Station objects.

        Raises:
            DeyeAuthError: If authentication fails.
            DeyeApiError: If the API returns a non-success response.
            DeyeTimeoutError: If the request times out.
            DeyeRateLimitError: If the API returns HTTP 429.
            DeyeConnectionError: If unable to connect.
        """
        data = await self._request("POST", "/v1.0/station/list", payload={})
        stations: list[Station] = []

        station_list = data.get("data", {})
        # Handle both list and dict-with-list response formats
        if isinstance(station_list, dict):
            station_list = station_list.get("stationList", []) or []
        elif not isinstance(station_list, list):
            station_list = []

        for item in station_list:
            station = Station(
                station_id=str(item.get("id", item.get("stationId", ""))),
                name=item.get("name", item.get("stationName", "")),
                latitude=float(item.get("latitude", item.get("lat", 0.0))),
                longitude=float(item.get("longitude", item.get("lng", 0.0))),
                rated_capacity_kwp=float(
                    item.get("ratedCapacity", item.get("installedCapacity", 0.0))
                ),
            )
            stations.append(station)

        _LOGGER.debug("Retrieved %d stations", len(stations))
        return stations

    async def get_device_list(self, station_id: str) -> list[Device]:
        """Retrieve the list of devices for a specific station.

        POST /v1.0/device/list

        Args:
            station_id: The station ID to retrieve devices for.

        Returns:
            A list of Device objects.

        Raises:
            DeyeAuthError: If authentication fails.
            DeyeApiError: If the API returns a non-success response.
            DeyeTimeoutError: If the request times out.
            DeyeRateLimitError: If the API returns HTTP 429.
            DeyeConnectionError: If unable to connect.
        """
        data = await self._request(
            "POST", "/v1.0/device/list", payload={"stationId": station_id}
        )
        devices: list[Device] = []

        device_list = data.get("data", {})
        # Handle both list and dict-with-list response formats
        if isinstance(device_list, dict):
            device_list = device_list.get("deviceList", []) or []
        elif not isinstance(device_list, list):
            device_list = []

        for item in device_list:
            # Parse supported work modes
            raw_work_modes = item.get("supportedWorkModes", []) or []
            supported_work_modes: list[WorkMode] = []
            for mode in raw_work_modes:
                try:
                    supported_work_modes.append(WorkMode(int(mode)))
                except (ValueError, TypeError):
                    _LOGGER.debug("Skipping unknown work mode: %s", mode)

            # Parse supported energy patterns
            raw_patterns = item.get("supportedEnergyPatterns", []) or []
            supported_energy_patterns: list[EnergyPattern] = []
            for pattern in raw_patterns:
                try:
                    supported_energy_patterns.append(EnergyPattern(int(pattern)))
                except (ValueError, TypeError):
                    _LOGGER.debug("Skipping unknown energy pattern: %s", pattern)

            device = Device(
                device_sn=str(item.get("deviceSn", item.get("sn", ""))),
                station_id=station_id,
                model_name=str(item.get("modelName", item.get("model", ""))),
                firmware_version=str(
                    item.get("firmwareVersion", item.get("fwVersion", ""))
                ),
                rated_power_w=int(item.get("ratedPower", item.get("ratedPowerW", 0))),
                phase_count=int(item.get("phaseCount", item.get("phases", 1))),
                mppt_count=int(item.get("mpptCount", item.get("mpptChannels", 1))),
                has_battery=bool(item.get("hasBattery", item.get("batteryEnabled", False))),
                has_smart_load=bool(
                    item.get("hasSmartLoad", item.get("smartLoadEnabled", False))
                ),
                smart_load_channels=int(
                    item.get("smartLoadChannels", item.get("smartLoadCount", 0))
                ),
                supported_work_modes=supported_work_modes,
                supported_energy_patterns=supported_energy_patterns,
                battery_soc_min=int(item.get("batterySocMin", item.get("socMin", 10))),
                battery_soc_max=int(item.get("batterySocMax", item.get("socMax", 100))),
                battery_charge_current_max=float(
                    item.get("batteryChargeCurrentMax", item.get("chargeCurrentMax", 0.0))
                ),
                battery_discharge_current_max=float(
                    item.get(
                        "batteryDischargeCurrentMax",
                        item.get("dischargeCurrentMax", 0.0),
                    )
                ),
            )
            devices.append(device)

        _LOGGER.debug(
            "Retrieved %d devices for station %s", len(devices), station_id
        )
        return devices
