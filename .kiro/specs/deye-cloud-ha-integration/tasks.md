# Implementation Plan: Deye Cloud HA Integration

## Overview

This plan implements a Home Assistant custom component (`custom_components/deye_cloud/`) that integrates with the Deye Cloud developer API for solar inverter monitoring and control. The implementation follows the HA custom component architecture with `DataUpdateCoordinator`, async patterns, config flow UI setup, and HACS compatibility. Tasks are ordered to build foundational infrastructure first, then layer on platforms and features incrementally.

## Tasks

- [x] 1. Set up project structure, constants, and data models
  - [x] 1.1 Create directory structure and manifest files
    - Create `custom_components/deye_cloud/` directory
    - Create `manifest.json` with domain `deye_cloud`, version `0.1.0`, dependencies, iot_class, codeowners
    - Create `hacs.json` with name and content_in_root fields
    - Create `const.py` with DOMAIN, default polling interval (60s), min/max intervals (30/3600), platform list, retry config constants
    - Create `strings.json` with config flow step labels, error messages, and entity descriptions
    - Create `translations/en.json` matching strings.json structure
    - _Requirements: 17.1, 17.2, 17.3_

  - [x] 1.2 Implement data models and type definitions
    - Create `models.py` with all dataclasses: `Station`, `Device`, `DeviceData`, `MPPTChannelData`, `PhaseData`, `AlertData`, `TOUSlotData`, `TariffPeriod`, `TariffConfig`, `ForecastData`, `HourlyForecast`, `TOUSchedule`
    - Implement enums: `WorkMode`, `EnergyPattern`, `TariffCategory`, `TOUSlotMode`
    - Create `helpers.py` with shared utility functions (entity naming helper, validation helpers)
    - _Requirements: 4.9, 8.1, 11.3, 12.1_

  - [x] 1.3 Create custom exception classes
    - Create exception hierarchy in `api.py` or a dedicated `exceptions.py`: `DeyeAuthError`, `DeyeApiError`, `DeyeTimeoutError`, `DeyeRateLimitError`, `DeyeConnectionError`, `OpenMeteoError`
    - _Requirements: 20.2, 20.3_

- [x] 2. Implement Deye Cloud API client
  - [x] 2.1 Implement DeyeCloudAPI core with token management
    - Create `api.py` with `DeyeCloudAPI` class
    - Implement `__init__` accepting `aiohttp.ClientSession`, `app_id`, `app_secret`
    - Implement `authenticate()` → POST `/v1.0/account/token` with 10s timeout
    - Implement `_ensure_token()` that checks expiry within 60s and refreshes proactively
    - Implement exponential backoff for token refresh (2s, 4s, 8s) up to 3 retries
    - Include access token in all subsequent request headers
    - On 401 response, perform single retry with fresh token
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 2.2 Implement station and device discovery endpoints
    - Implement `get_station_list()` → POST `/v1.0/station/list`
    - Implement `get_device_list(station_id)` → POST `/v1.0/device/list`
    - Parse response into `Station` and `Device` model objects
    - _Requirements: 2.2, 19.1, 19.3_

  - [x] 2.3 Implement device data and control endpoints
    - Implement `get_device_latest(device_sn, measure_points)` → POST `/v1.0/device/latest`
    - Implement `set_device_config(device_sn, params)` → battery, grid settings
    - Implement `set_work_mode(device_sn, mode)` → work mode control
    - Implement `set_energy_pattern(device_sn, pattern)` → energy pattern control
    - Implement `set_tou_schedule(device_sn, schedule)` → TOU schedule update
    - Implement `set_smart_load(device_sn, channel, on)` → smart load control
    - Implement `send_modbus_command(device_sn, register, value)` → custom modbus
    - Implement `get_control_strategy(device_sn)` / `set_control_strategy(device_sn, strategy)`
    - All methods raise typed exceptions on failure
    - _Requirements: 3.5, 6.2, 7.2, 7.3, 8.2, 9.3, 10.2, 18.1, 18.2, 18.3_

  - [ ]* 2.4 Write property tests for token management
    - **Property 1: Token inclusion in API requests**
    - **Property 2: Proactive token refresh on expiry proximity**
    - **Validates: Requirements 1.3, 1.4**

  - [ ]* 2.5 Write property test for exponential backoff calculation
    - **Property 5: Exponential backoff calculation**
    - **Validates: Requirements 3.3**

- [x] 3. Implement Config Flow and Options Flow
  - [x] 3.1 Implement multi-step config flow
    - Create `config_flow.py` with `DeyeCloudConfigFlow` class
    - Step 1: Collect AppId, AppSecret, polling interval (30–600s default 60)
    - Validate credentials against API; show error on auth failure or connection failure
    - Step 2: Discover stations and devices; show error if zero found
    - Step 3: Allow user to select which inverters/stations to monitor
    - Check for duplicate AppId config entries and abort if found
    - Store credentials using HA credential storage
    - Create device entries for each selected inverter and station
    - _Requirements: 1.6, 2.1, 2.2, 2.3, 2.5, 2.6, 2.7, 2.8_

  - [x] 3.2 Implement options flow
    - Add options flow for: modifying polling interval, add/remove inverters, update credentials
    - Add solar forecast config: panel tilt (0–90°, default 30), azimuth (0–360°, default 180), efficiency (0.5–0.95, default 0.75)
    - Add tariff period configuration (up to 10 periods with overlap validation)
    - _Requirements: 2.4, 11.6, 12.1_

  - [ ]* 3.3 Write unit tests for config flow
    - Test happy path setup flow
    - Test auth error, connection failure, duplicate entry, empty devices scenarios
    - Test options flow modifications
    - _Requirements: 2.1, 2.4, 2.5, 2.6, 2.7, 2.8_

- [x] 4. Implement DataUpdateCoordinator
  - [x] 4.1 Implement DeyeDeviceCoordinator
    - Create `coordinator.py` with `DeyeDeviceCoordinator` subclassing `DataUpdateCoordinator[DeviceData]`
    - Implement `_async_update_data()` calling `api.get_device_latest()`
    - Parse API response into `DeviceData` model
    - Implement retry logic: 3 retries, exponential backoff (5s → 10s → 20s, max 60s)
    - Handle rate limiting: pause for Retry-After header value (max 300s) or 60s default
    - Track consecutive failures; create Repair Flow after 5 failures
    - Mark entities unavailable on retry exhaustion; restore on next success
    - Use async HTTP calls exclusively
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 20.1, 20.2, 20.3, 20.5_

  - [ ]* 4.2 Write property tests for coordinator retry and failure tracking
    - **Property 4: Polling interval enforcement**
    - **Property 5: Exponential backoff calculation** (coordinator context)
    - **Property 6: Consecutive failure threshold for repair flow**
    - **Property 21: Rate limit pause duration**
    - **Validates: Requirements 3.1, 3.3, 3.4, 20.1**

- [x] 5. Implement integration entry setup and teardown
  - [x] 5.1 Implement __init__.py entry point
    - Create `__init__.py` with `async_setup_entry()` and `async_unload_entry()`
    - Instantiate `DeyeCloudAPI` client with stored credentials
    - Create one `DeyeDeviceCoordinator` per configured inverter
    - Create one `ForecastCoordinator` per station
    - Initialize `TariffManager` per inverter (if tariff config exists)
    - Forward setup to all platforms (sensor, binary_sensor, number, select, switch, time, event)
    - Register services
    - Register Lovelace dashboard
    - On unload: stop coordinators, stop tariff managers, unregister services
    - _Requirements: 2.3, 13.1, 13.3, 13.4, 13.5_

- [x] 6. Checkpoint - Ensure core infrastructure compiles and loads
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement sensor platform entities
  - [x] 7.1 Implement PV, battery, grid, and load sensors
    - Create `sensor.py` with entity descriptions for all sensor types
    - PV sensors: power (W), daily yield (kWh), total yield (kWh) per MPPT and aggregated
    - Battery sensors: SOC (%), power (W), voltage (V), current (A), temperature (°C)
    - Grid sensors: import/export power (W), daily/total import/export (kWh), frequency (Hz), voltage per phase
    - Load sensors: consumption power (W), daily consumption (kWh)
    - Dynamically create MPPT channel sensors based on `device.mppt_count`
    - Dynamically create phase sensors based on `device.phase_count`
    - Assign correct device_class, state_class, and native_unit for Energy Dashboard compatibility
    - Handle null values → state "unknown" while retaining attributes
    - Apply entity naming convention: `sensor.{device_name}_{sensor_type}_{channel_or_phase}`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9_

  - [x] 7.2 Implement station aggregate sensors
    - Create station device entries with aggregate sensors: total power (W), daily production (kWh), daily consumption (kWh)
    - Assign state_class measurement for power, total_increasing for energy
    - Mark unavailable when all child inverters are offline
    - Expose station metadata as device attributes (name, location, rated capacity)
    - _Requirements: 19.1, 19.3, 19.4_

  - [x] 7.3 Implement inverter status and metadata sensors
    - Create last-update timestamp sensor with device_class "timestamp"
    - Expose inverter metadata (model, serial, firmware, rated power) as device attributes
    - _Requirements: 5.2, 5.5_

  - [x] 7.4 Implement energy accumulation sensors for Energy Dashboard
    - Create total_increasing sensors: total solar production, total grid import, total grid export, total battery charge, total battery discharge, total load consumption
    - Assign device_class "energy", unit "kWh", no last_reset attribute
    - Use stable unique_ids based on inverter serial + sensor type
    - Handle counter resets: report new lower value without adjustment
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

  - [ ]* 7.5 Write property tests for sensor entities
    - **Property 7: Dynamic entity creation matches device capabilities**
    - **Property 8: Sensor classification correctness**
    - **Property 9: Null field handling preserves partial data**
    - **Property 10: Entity naming convention**
    - **Property 22: Counter reset detection**
    - **Validates: Requirements 4.5, 4.6, 4.7, 4.8, 4.9, 15.1, 15.2, 15.4**

- [x] 8. Implement binary sensor and event platforms
  - [x] 8.1 Implement binary sensor for inverter online status
    - Create `binary_sensor.py` with online/offline binary sensor
    - State derived from `DeviceData.is_online` field
    - _Requirements: 5.1_

  - [x] 8.2 Implement event entities for alerts
    - Create `event.py` with alert event entities
    - Fire event on new alert: type, severity, timestamp, message
    - Fire resolution event: original alert type, resolution timestamp
    - Fire station-level alert events with station identifier
    - _Requirements: 5.3, 5.4, 19.2_

  - [ ]* 8.3 Write property test for event field completeness
    - **Property 11: Event field completeness**
    - **Validates: Requirements 5.3, 5.4, 19.2**

- [x] 9. Implement number platform (battery and grid controls)
  - [x] 9.1 Implement battery configuration number entities
    - Create `number.py` with number entities for: min SOC (%), max SOC (%), max charge current (A), max discharge current (A)
    - Step size 1 for SOC, 0.1 for current
    - Min/max bounds from inverter-reported range
    - Mark unavailable if range data is not available
    - Optimistic update on user change; send to API within 10s
    - Revert and notify on API rejection or out-of-range value
    - Sync values from coordinator poll data
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 9.2 Implement grid control number entities
    - Grid export limit (W): min 0, max = inverter rated power, step 1
    - Peak shaving threshold (W): min 0, max = inverter rated power, step 1
    - Validate values against inverter-reported range before API send
    - Send to API within 5s; revert and notify on rejection
    - _Requirements: 9.1, 9.4, 9.5, 9.6_

  - [ ]* 9.3 Write property test for control entity bounds
    - **Property 12: Control entity bounds from inverter-reported range**
    - **Validates: Requirements 6.1, 6.3, 9.6**

- [x] 10. Implement select platform (work mode, energy pattern)
  - [x] 10.1 Implement work mode and energy pattern select entities
    - Create `select.py` with select entities for work mode and energy pattern
    - Populate options from inverter's supported mode/pattern list reported by API
    - Send mode/pattern update to API on user selection
    - Revert and notify on API rejection
    - Sync state from coordinator poll
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [ ]* 10.2 Write property tests for select entities
    - **Property 13: State synchronization from API polling**
    - **Property 14: Select entity options from API-reported capabilities**
    - **Validates: Requirements 7.1, 7.4, 7.6**

- [x] 11. Implement switch platform (solar sell, peak shaving, TOU, smart loads, tariff)
  - [x] 11.1 Implement grid and solar sell switches
    - Create `switch.py` with switch entities: solar sell enable/disable, peak shaving enable/disable
    - Send control commands to API; revert on rejection with notification
    - _Requirements: 9.2, 9.3, 9.4, 9.5_

  - [x] 11.2 Implement TOU schedule global switch
    - TOU enable/disable switch entity
    - Send TOU on/off to API
    - _Requirements: 8.3_

  - [x] 11.3 Implement smart load switches
    - Conditionally create switch entities per smart load channel only if inverter supports them
    - Number of switches equals reported channel count
    - Send control command to smartload endpoint; revert on rejection
    - Do not create entities if inverter lacks smart load capability
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 11.4 Implement tariff automation global switch
    - Switch entity to enable/disable tariff-based automation
    - _Requirements: 12.4_

  - [ ]* 11.5 Write property test for smart load conditional creation
    - **Property 16: Smart load entity conditional creation**
    - **Validates: Requirements 10.1, 10.3**

- [x] 12. Implement time platform (TOU schedule slots)
  - [x] 12.1 Implement TOU time slot entities
    - Create `time.py` with time entities for start/end of each TOU slot (minimum 6 slots)
    - Create select entity per slot for mode (Charging, Discharging, Disabled)
    - Create number entity per slot for power limit (0 to inverter rated power, step 1W)
    - Validate: no overlap between enabled slots, end > start
    - Reject invalid config, retain previous value, notify user
    - Send validated schedule to API within 10s; revert on API rejection
    - _Requirements: 8.1, 8.2, 8.4, 8.5, 8.6_

  - [ ]* 12.2 Write property test for time period validation
    - **Property 15: Time period validation (TOU and tariff)**
    - **Validates: Requirements 8.2, 8.6, 12.1**

- [x] 13. Checkpoint - Ensure all entity platforms work
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Implement solar forecast coordinator
  - [x] 14.1 Implement ForecastCoordinator with Open-Meteo integration
    - Create `forecast.py` with `DeyeForecastCoordinator`
    - Poll Open-Meteo API every 60 minutes using station GPS coordinates (no API key)
    - Estimate production: irradiance (W/m²) × panel_area_m² × efficiency
    - Panel area derived from rated_power_kw / 0.2
    - Apply tilt/azimuth correction factor
    - Create forecast sensors: today (kWh), tomorrow (kWh), current hour power (W)
    - Current hour sensor includes forecast attribute with next 24 hourly values
    - On API failure: retain last values, set stale=true, add last_successful_update attribute
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [ ]* 14.2 Write property test for solar production estimation
    - **Property 17: Solar production estimation formula**
    - **Validates: Requirements 11.3**

- [x] 15. Implement tariff manager automation
  - [x] 15.1 Implement TariffManager with time-based mode switching
    - Create `tariff.py` with `TariffManager` class
    - Register time-based listeners for period transitions
    - On cheap-rate entry: switch to grid-charging mode at max charge current within 60s
    - On peak-rate entry: switch to battery-discharge mode at max discharge current within 60s
    - On standard-rate entry: restore user-configured default work mode
    - Fire HA event on transitions: device ID, previous/new category, timestamp
    - Retry failed mode switches 3 times at 30s intervals; notify on exhaustion
    - Validate tariff periods (no overlaps, up to 10 periods)
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

  - [ ]* 15.2 Write property test for time period validation in tariff context
    - **Property 15: Time period validation (TOU and tariff)** — tariff-specific scenarios
    - **Validates: Requirements 12.1**

- [x] 16. Implement services
  - [x] 16.1 Implement service registration and handlers
    - Create `services.py` with service registration
    - Create `services.yaml` with service schema definitions
    - `deye_cloud.send_modbus_command`: device ID, register address (int), register value (int)
    - `deye_cloud.read_control_strategy`: device ID → returns strategy data
    - `deye_cloud.write_control_strategy`: device ID + strategy params
    - `deye_cloud.force_refresh`: device ID, 10s cooldown between calls per device
    - Validate parameters before API calls; reject invalid/out-of-range
    - Raise `HomeAssistantError` on API failure with error code + operation name
    - Raise `HomeAssistantError` on 30s timeout
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7_

  - [ ]* 16.2 Write property test for service error message format
    - **Property 23: Service error message format**
    - **Validates: Requirements 18.5**

- [x] 17. Implement multi-inverter support and entity isolation
  - [x] 17.1 Implement multi-device entity management
    - Ensure unique IDs incorporate inverter serial number across all entities
    - Support adding new inverter via options flow: create entities within one poll cycle, no restart
    - Support removing inverter via options flow: remove device + entities without affecting others
    - Support at least 10 inverters per integration instance across multiple stations
    - On per-inverter API failure: mark only that inverter's entities unavailable, continue others
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

  - [ ]* 17.2 Write property tests for multi-inverter isolation
    - **Property 18: Unique entity identification across multiple inverters**
    - **Property 19: Fault isolation per inverter**
    - **Property 20: Station aggregate availability**
    - **Validates: Requirements 13.1, 13.2, 13.6, 19.4**

- [x] 18. Checkpoint - Ensure all features integrated
  - Ensure all tests pass, ask the user if questions arise.

- [x] 19. Implement diagnostics and repair flows
  - [x] 19.1 Implement diagnostics platform
    - Create `diagnostics.py` implementing `async_get_config_entry_diagnostics()`
    - Output: redacted config (AppId/AppSecret/tokens → `**REDACTED**`), entity states, last API response, error counts
    - _Requirements: 16.1_

  - [x] 19.2 Implement repair flows
    - Create `repairs.py` with repair flow handlers
    - Trigger conditions: invalid credentials, 5+ consecutive failures, inverter offline > 1 hour, firmware update reported
    - Each repair includes: problem description, actionable resolution step, verification reference
    - Auto-dismiss when condition clears within 2 polling cycles
    - Deduplicate: one repair per condition per device
    - _Requirements: 16.2, 16.3, 16.4_

  - [ ]* 19.3 Write property test for credential redaction
    - **Property 3: Credential redaction in diagnostics**
    - **Validates: Requirements 1.6, 16.1**

- [x] 20. Implement Lovelace dashboard
  - [x] 20.1 Implement dashboard registration and YAML config
    - Create `dashboard.py` with dashboard registration logic
    - Create `lovelace/dashboard.yaml` with views: Power Flow Card, summary statistics, historical charts, settings/controls, diagnostics
    - Power Flow Card: PV, Battery, Grid, Load with instantaneous watts
    - Summary: daily/total production/consumption, self-consumption %, self-sufficiency %
    - Charts: 24h power profile, 7-day bar charts, daily donut charts
    - Settings: expose all writable controls
    - Diagnostics view: status, last update, firmware, diagnostics download link
    - Register dashboard in sidebar on integration load (after config flow or restart)
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7_

- [x] 21. Final wiring, HACS validation, and integration tests
  - [x] 21.1 Verify HACS compatibility and file structure
    - Confirm `custom_components/deye_cloud/` contains all required files
    - Validate `manifest.json` version matches semantic versioning for HACS detection
    - Validate `hacs.json` fields
    - Ensure strings.json and translations are complete
    - _Requirements: 17.1, 17.2, 17.3, 17.4_

  - [ ]* 21.2 Write integration tests for end-to-end flows
    - Test full config flow with mocked API
    - Test coordinator lifecycle: setup → poll → error → recovery → teardown
    - Test tariff automation with mocked time progression
    - Test service calls with mocked API success and failure
    - _Requirements: 2.1, 3.1, 12.2, 18.1_

- [x] 22. Final checkpoint - Full integration verification
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (23 properties defined in design)
- Unit tests validate specific examples and edge cases
- All code uses Python with async/await patterns (`aiohttp`, `asyncio`)
- Testing uses `pytest` with `Hypothesis` for property-based tests
- The integration targets Home Assistant 2024.1+ APIs

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3"] },
    { "id": 3, "tasks": ["2.4", "2.5", "3.1"] },
    { "id": 4, "tasks": ["3.2", "3.3", "4.1"] },
    { "id": 5, "tasks": ["4.2", "5.1"] },
    { "id": 6, "tasks": ["7.1", "7.2", "7.3", "7.4", "8.1", "8.2"] },
    { "id": 7, "tasks": ["7.5", "8.3", "9.1", "9.2", "10.1"] },
    { "id": 8, "tasks": ["9.3", "10.2", "11.1", "11.2", "11.3", "11.4"] },
    { "id": 9, "tasks": ["11.5", "12.1"] },
    { "id": 10, "tasks": ["12.2", "14.1", "15.1"] },
    { "id": 11, "tasks": ["14.2", "15.2", "16.1"] },
    { "id": 12, "tasks": ["16.2", "17.1"] },
    { "id": 13, "tasks": ["17.2", "19.1", "19.2"] },
    { "id": 14, "tasks": ["19.3", "20.1"] },
    { "id": 15, "tasks": ["21.1", "21.2"] }
  ]
}
```
