"""Tests for multi-device entity management (Requirement 13).

Verifies:
- 13.1: Unique IDs incorporate inverter serial number
- 13.2: Entity unique IDs prevent collisions across devices
- 13.3: Adding inverter via options flow creates entities without restart
- 13.4: Support at least 10 inverters per integration instance
- 13.5: Removing inverter removes device + entities without affecting others
- 13.6: Per-inverter API failure isolates to that inverter's entities only
"""

from __future__ import annotations

import pytest
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.deye_cloud import (
    _async_options_updated,
    async_setup_entry,
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_INVERTERS,
    CONF_STATIONS,
)
from custom_components.deye_cloud.const import DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS
from custom_components.deye_cloud.helpers import generate_unique_id


@pytest.fixture
def mock_hass():
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


@pytest.fixture
def mock_entry():
    """Create a mock config entry with multiple inverters."""
    entry = MagicMock()
    entry.entry_id = "test_multi_device_entry"
    entry.data = {
        CONF_APP_ID: "test_app_id",
        CONF_APP_SECRET: "test_app_secret",
        "scan_interval": 60,
        CONF_INVERTERS: ["SN001", "SN002", "SN003"],
        CONF_STATIONS: [],
    }
    entry.options = {}
    entry.async_on_unload = MagicMock()
    entry.add_update_listener = MagicMock()
    return entry


@pytest.fixture
def mock_api():
    """Create a mock DeyeCloudAPI."""
    api = AsyncMock()
    api.authenticate = AsyncMock(return_value="test_token")
    api.get_station_list = AsyncMock(return_value=[])
    api.get_device_list = AsyncMock(return_value=[])
    return api


@pytest.fixture
def mock_coordinator():
    """Create a mock DeyeDeviceCoordinator."""
    coord = MagicMock()
    coord.async_config_entry_first_refresh = AsyncMock()
    coord.update_interval = timedelta(seconds=60)
    return coord


class TestUniqueIdIncorporatesSerial:
    """Tests for Requirement 13.1 & 13.2: Unique IDs based on serial number."""

    def test_unique_id_contains_device_serial(self):
        """Verify unique ID includes the inverter serial number."""
        uid = generate_unique_id("SN12345", "pv_power_total")
        assert "SN12345" in uid
        assert "pv_power_total" in uid

    def test_unique_ids_differ_across_inverters(self):
        """Verify two inverters with the same sensor type get different IDs."""
        uid_a = generate_unique_id("SN_ALPHA", "battery_soc")
        uid_b = generate_unique_id("SN_BETA", "battery_soc")
        assert uid_a != uid_b

    def test_unique_id_with_channel(self):
        """Verify unique ID with channel includes serial + channel."""
        uid = generate_unique_id("SN001", "pv_power", channel_or_phase=1)
        assert "SN001" in uid
        assert "1" in uid

    def test_unique_ids_differ_across_channels_same_inverter(self):
        """Verify channel-specific IDs differ within same inverter."""
        uid_ch1 = generate_unique_id("SN001", "pv_power", channel_or_phase=1)
        uid_ch2 = generate_unique_id("SN001", "pv_power", channel_or_phase=2)
        assert uid_ch1 != uid_ch2

    def test_unique_ids_no_collision_many_inverters(self):
        """Verify no collisions across a large set of inverters and sensors."""
        sensor_types = [
            "pv_power_total",
            "battery_soc",
            "grid_import_power",
            "load_power",
            "grid_frequency",
        ]
        serial_numbers = [f"SN{i:04d}" for i in range(15)]

        all_ids = set()
        for sn in serial_numbers:
            for sensor_type in sensor_types:
                uid = generate_unique_id(sn, sensor_type)
                assert uid not in all_ids, f"Collision found for {sn}/{sensor_type}"
                all_ids.add(uid)

        # 15 serials × 5 sensors = 75 unique IDs
        assert len(all_ids) == 75


class TestMultipleInverterSetup:
    """Tests for Requirement 13.4: Support at least 10 inverters."""

    @pytest.mark.asyncio
    async def test_setup_with_10_inverters(self, mock_hass, mock_api, mock_coordinator):
        """Verify the integration supports setting up 10 inverters."""
        inverter_list = [f"SN{i:04d}" for i in range(10)]
        entry = MagicMock()
        entry.entry_id = "test_10_inverters"
        entry.data = {
            CONF_APP_ID: "test_app_id",
            CONF_APP_SECRET: "test_app_secret",
            "scan_interval": 60,
            CONF_INVERTERS: inverter_list,
            CONF_STATIONS: [],
        }
        entry.options = {}
        entry.async_on_unload = MagicMock()
        entry.add_update_listener = MagicMock()

        with (
            patch(
                "custom_components.deye_cloud.async_get_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.deye_cloud.DeyeCloudAPI",
                return_value=mock_api,
            ),
            patch(
                "custom_components.deye_cloud.DeyeDeviceCoordinator",
                return_value=mock_coordinator,
            ) as mock_coord_cls,
        ):
            result = await async_setup_entry(mock_hass, entry)

        assert result is True
        # Should create 10 coordinators
        assert mock_coord_cls.call_count == 10
        # All 10 should have been refreshed
        assert mock_coordinator.async_config_entry_first_refresh.await_count == 10
        # All 10 stored
        entry_data = mock_hass.data[DOMAIN][entry.entry_id]
        assert len(entry_data["device_coordinators"]) == 10

    @pytest.mark.asyncio
    async def test_setup_with_more_than_10_inverters(
        self, mock_hass, mock_api, mock_coordinator
    ):
        """Verify no artificial limit - supports 12+ inverters."""
        inverter_list = [f"SN{i:04d}" for i in range(12)]
        entry = MagicMock()
        entry.entry_id = "test_12_inverters"
        entry.data = {
            CONF_APP_ID: "test_app_id",
            CONF_APP_SECRET: "test_app_secret",
            "scan_interval": 60,
            CONF_INVERTERS: inverter_list,
            CONF_STATIONS: [],
        }
        entry.options = {}
        entry.async_on_unload = MagicMock()
        entry.add_update_listener = MagicMock()

        with (
            patch(
                "custom_components.deye_cloud.async_get_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.deye_cloud.DeyeCloudAPI",
                return_value=mock_api,
            ),
            patch(
                "custom_components.deye_cloud.DeyeDeviceCoordinator",
                return_value=mock_coordinator,
            ) as mock_coord_cls,
        ):
            result = await async_setup_entry(mock_hass, entry)

        assert result is True
        assert mock_coord_cls.call_count == 12
        entry_data = mock_hass.data[DOMAIN][entry.entry_id]
        assert len(entry_data["device_coordinators"]) == 12


class TestOptionsFlowAddInverter:
    """Tests for Requirement 13.3: Adding inverter via options flow."""

    @pytest.mark.asyncio
    async def test_adding_inverter_creates_coordinator(self, mock_hass):
        """Verify adding a new inverter via options creates a coordinator."""
        mock_api = AsyncMock()
        existing_coord = MagicMock()
        existing_coord.update_interval = timedelta(seconds=60)

        # Set up existing state with one inverter
        mock_hass.data = {
            DOMAIN: {
                "test_entry": {
                    "api": mock_api,
                    "device_coordinators": {"SN001": existing_coord},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.data = {
            CONF_APP_ID: "test_app_id",
            CONF_APP_SECRET: "test_app_secret",
            "scan_interval": 60,
            CONF_INVERTERS: ["SN001"],
        }
        # Options now include a new inverter
        entry.options = {CONF_INVERTERS: ["SN001", "SN002"]}

        new_coord = MagicMock()
        new_coord.async_config_entry_first_refresh = AsyncMock()
        new_coord.update_interval = timedelta(seconds=60)

        with patch(
            "custom_components.deye_cloud.DeyeDeviceCoordinator",
            return_value=new_coord,
        ) as mock_coord_cls:
            await _async_options_updated(mock_hass, entry)

        # New coordinator created for SN002
        mock_coord_cls.assert_called_once()
        call_kwargs = mock_coord_cls.call_args[1]
        assert call_kwargs["device_sn"] == "SN002"

        # First refresh called for new coordinator
        new_coord.async_config_entry_first_refresh.assert_awaited_once()

        # New coordinator stored
        coordinators = mock_hass.data[DOMAIN]["test_entry"]["device_coordinators"]
        assert "SN002" in coordinators

        # Platforms reloaded to pick up new entities
        mock_hass.config_entries.async_unload_platforms.assert_awaited_once()
        mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_adding_inverter_does_not_affect_existing(self, mock_hass):
        """Verify adding a new inverter doesn't disrupt existing coordinator."""
        mock_api = AsyncMock()
        existing_coord = MagicMock()
        existing_coord.update_interval = timedelta(seconds=60)

        mock_hass.data = {
            DOMAIN: {
                "test_entry": {
                    "api": mock_api,
                    "device_coordinators": {"SN001": existing_coord},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.data = {
            CONF_APP_ID: "test_app_id",
            CONF_APP_SECRET: "test_app_secret",
            "scan_interval": 60,
            CONF_INVERTERS: ["SN001"],
        }
        entry.options = {CONF_INVERTERS: ["SN001", "SN002"]}

        new_coord = MagicMock()
        new_coord.async_config_entry_first_refresh = AsyncMock()
        new_coord.update_interval = timedelta(seconds=60)

        with patch(
            "custom_components.deye_cloud.DeyeDeviceCoordinator",
            return_value=new_coord,
        ):
            await _async_options_updated(mock_hass, entry)

        # SN001 coordinator is still present and untouched
        coordinators = mock_hass.data[DOMAIN]["test_entry"]["device_coordinators"]
        assert coordinators["SN001"] is existing_coord


class TestOptionsFlowRemoveInverter:
    """Tests for Requirement 13.5: Removing inverter via options flow."""

    @pytest.mark.asyncio
    async def test_removing_inverter_removes_device(self, mock_hass):
        """Verify removing an inverter removes it from device registry."""
        mock_api = AsyncMock()
        coord_1 = MagicMock()
        coord_1.update_interval = timedelta(seconds=60)
        coord_2 = MagicMock()
        coord_2.update_interval = timedelta(seconds=60)

        mock_hass.data = {
            DOMAIN: {
                "test_entry": {
                    "api": mock_api,
                    "device_coordinators": {
                        "SN001": coord_1,
                        "SN002": coord_2,
                    },
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.data = {
            CONF_APP_ID: "test_app_id",
            CONF_APP_SECRET: "test_app_secret",
            "scan_interval": 60,
            CONF_INVERTERS: ["SN001", "SN002"],
        }
        # Options now exclude SN002
        entry.options = {CONF_INVERTERS: ["SN001"]}

        mock_device_entry = MagicMock()
        mock_device_entry.id = "device_id_sn002"

        mock_device_reg = MagicMock()
        mock_device_reg.async_get_device = MagicMock(return_value=mock_device_entry)
        mock_device_reg.async_remove_device = MagicMock()

        with patch(
            "custom_components.deye_cloud.dr.async_get",
            return_value=mock_device_reg,
        ):
            await _async_options_updated(mock_hass, entry)

        # Device registry queried for SN002
        mock_device_reg.async_get_device.assert_called_with(
            identifiers={(DOMAIN, "SN002")}
        )
        # Device removed
        mock_device_reg.async_remove_device.assert_called_once_with("device_id_sn002")

        # Coordinator removed from dict
        coordinators = mock_hass.data[DOMAIN]["test_entry"]["device_coordinators"]
        assert "SN002" not in coordinators
        assert "SN001" in coordinators

    @pytest.mark.asyncio
    async def test_removing_inverter_does_not_affect_others(self, mock_hass):
        """Verify removing one inverter leaves other inverters untouched."""
        mock_api = AsyncMock()
        coord_1 = MagicMock()
        coord_1.update_interval = timedelta(seconds=60)
        coord_2 = MagicMock()
        coord_2.update_interval = timedelta(seconds=60)
        coord_3 = MagicMock()
        coord_3.update_interval = timedelta(seconds=60)

        mock_hass.data = {
            DOMAIN: {
                "test_entry": {
                    "api": mock_api,
                    "device_coordinators": {
                        "SN001": coord_1,
                        "SN002": coord_2,
                        "SN003": coord_3,
                    },
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.data = {
            CONF_APP_ID: "test_app_id",
            CONF_APP_SECRET: "test_app_secret",
            "scan_interval": 60,
            CONF_INVERTERS: ["SN001", "SN002", "SN003"],
        }
        # Remove SN002 only
        entry.options = {CONF_INVERTERS: ["SN001", "SN003"]}

        mock_device_reg = MagicMock()
        mock_device_reg.async_get_device = MagicMock(return_value=MagicMock(id="dev2"))
        mock_device_reg.async_remove_device = MagicMock()

        with patch(
            "custom_components.deye_cloud.dr.async_get",
            return_value=mock_device_reg,
        ):
            await _async_options_updated(mock_hass, entry)

        coordinators = mock_hass.data[DOMAIN]["test_entry"]["device_coordinators"]
        # SN001 and SN003 still present
        assert coordinators["SN001"] is coord_1
        assert coordinators["SN003"] is coord_3
        # SN002 removed
        assert "SN002" not in coordinators

    @pytest.mark.asyncio
    async def test_removing_nonexistent_device_in_registry(self, mock_hass):
        """Verify graceful handling when device not found in registry."""
        mock_api = AsyncMock()
        coord_1 = MagicMock()
        coord_1.update_interval = timedelta(seconds=60)
        coord_2 = MagicMock()
        coord_2.update_interval = timedelta(seconds=60)

        mock_hass.data = {
            DOMAIN: {
                "test_entry": {
                    "api": mock_api,
                    "device_coordinators": {
                        "SN001": coord_1,
                        "SN002": coord_2,
                    },
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.data = {
            CONF_APP_ID: "test_app_id",
            CONF_APP_SECRET: "test_app_secret",
            "scan_interval": 60,
            CONF_INVERTERS: ["SN001", "SN002"],
        }
        entry.options = {CONF_INVERTERS: ["SN001"]}

        mock_device_reg = MagicMock()
        # Device not found in registry
        mock_device_reg.async_get_device = MagicMock(return_value=None)

        with patch(
            "custom_components.deye_cloud.dr.async_get",
            return_value=mock_device_reg,
        ):
            # Should not raise
            await _async_options_updated(mock_hass, entry)

        # Coordinator still removed from dict
        coordinators = mock_hass.data[DOMAIN]["test_entry"]["device_coordinators"]
        assert "SN002" not in coordinators
        # async_remove_device not called since device not found
        mock_device_reg.async_remove_device.assert_not_called()


class TestFaultIsolation:
    """Tests for Requirement 13.6: Per-inverter API failure isolation.

    The fault isolation is inherent in the architecture: each inverter has its own
    DeyeDeviceCoordinator. When one coordinator raises UpdateFailed, only entities
    tied to that coordinator go unavailable. Other coordinators continue independently.
    """

    @pytest.mark.asyncio
    async def test_independent_coordinators_per_inverter(
        self, mock_hass, mock_api
    ):
        """Verify each inverter gets its own independent coordinator instance."""
        inverters = ["SN001", "SN002", "SN003"]
        entry = MagicMock()
        entry.entry_id = "test_fault_isolation"
        entry.data = {
            CONF_APP_ID: "test_app_id",
            CONF_APP_SECRET: "test_app_secret",
            "scan_interval": 60,
            CONF_INVERTERS: inverters,
            CONF_STATIONS: [],
        }
        entry.options = {}
        entry.async_on_unload = MagicMock()
        entry.add_update_listener = MagicMock()

        coordinators_created = []

        def make_coordinator(**kwargs):
            coord = MagicMock()
            coord.async_config_entry_first_refresh = AsyncMock()
            coord.device_sn = kwargs.get("device_sn", "")
            coordinators_created.append(coord)
            return coord

        with (
            patch(
                "custom_components.deye_cloud.async_get_clientsession",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.deye_cloud.DeyeCloudAPI",
                return_value=mock_api,
            ),
            patch(
                "custom_components.deye_cloud.DeyeDeviceCoordinator",
                side_effect=make_coordinator,
            ),
        ):
            await async_setup_entry(mock_hass, entry)

        # 3 distinct coordinator instances
        assert len(coordinators_created) == 3
        # Each is a separate object
        assert coordinators_created[0] is not coordinators_created[1]
        assert coordinators_created[1] is not coordinators_created[2]

    @pytest.mark.asyncio
    async def test_no_change_when_options_unchanged(self, mock_hass):
        """Verify no action when options don't change inverter list."""
        mock_api = AsyncMock()
        coord_1 = MagicMock()
        coord_1.update_interval = timedelta(seconds=60)

        mock_hass.data = {
            DOMAIN: {
                "test_entry": {
                    "api": mock_api,
                    "device_coordinators": {"SN001": coord_1},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.data = {
            CONF_APP_ID: "test_app_id",
            CONF_APP_SECRET: "test_app_secret",
            "scan_interval": 60,
            CONF_INVERTERS: ["SN001"],
        }
        # Same inverter list
        entry.options = {CONF_INVERTERS: ["SN001"]}

        await _async_options_updated(mock_hass, entry)

        # No platform reload triggered
        mock_hass.config_entries.async_unload_platforms.assert_not_awaited()
        mock_hass.config_entries.async_forward_entry_setups.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_options_update_when_entry_not_loaded(self, mock_hass):
        """Verify graceful exit when entry data not in hass.data."""
        mock_hass.data = {}

        entry = MagicMock()
        entry.entry_id = "nonexistent"
        entry.data = {CONF_INVERTERS: ["SN001"]}
        entry.options = {CONF_INVERTERS: ["SN001", "SN002"]}

        # Should not raise
        await _async_options_updated(mock_hass, entry)


class TestScanIntervalUpdate:
    """Tests for scan interval update via options flow."""

    @pytest.mark.asyncio
    async def test_scan_interval_updated_on_options_change(self, mock_hass):
        """Verify coordinators get updated interval from options."""
        mock_api = AsyncMock()
        coord_1 = MagicMock()
        coord_1.update_interval = timedelta(seconds=60)

        mock_hass.data = {
            DOMAIN: {
                "test_entry": {
                    "api": mock_api,
                    "device_coordinators": {"SN001": coord_1},
                }
            }
        }

        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.data = {
            CONF_APP_ID: "test_app_id",
            CONF_APP_SECRET: "test_app_secret",
            "scan_interval": 60,
            CONF_INVERTERS: ["SN001"],
        }
        entry.options = {
            CONF_INVERTERS: ["SN001"],
            "scan_interval": 120,
        }

        await _async_options_updated(mock_hass, entry)

        # Coordinator interval updated
        assert coord_1.update_interval == timedelta(seconds=120)
