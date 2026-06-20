# Requirements Document

## Introduction

This document defines the requirements for a custom Home Assistant integration that connects to the official Deye Cloud API to monitor and control Deye solar/hybrid inverters. The integration provides real-time energy monitoring, inverter control, solar forecasting, tariff-based automation, and a ready-made Lovelace dashboard replicating the Deye Cloud portal experience. It is designed as a native HA integration (not an add-on), written in Python with async patterns, installable via HACS, and configured entirely through the HA UI config flow.

## Glossary

- **Integration**: The custom Home Assistant component that communicates with the Deye Cloud API
- **Deye_Cloud_API**: The official Deye developer API at eu1-developer.deyecloud.com:443, authenticated via AppId/AppSecret token exchange
- **Inverter**: A Deye solar or hybrid inverter device registered in the Deye Cloud platform
- **Station**: A Deye Cloud entity representing a physical installation site containing one or more inverters
- **Config_Flow**: The Home Assistant UI-based setup wizard for configuring integrations without YAML
- **Coordinator**: The Home Assistant DataUpdateCoordinator responsible for polling the Deye_Cloud_API at a configurable interval
- **MPPT**: Maximum Power Point Tracker; a solar inverter input channel that independently tracks peak power from a string of panels
- **SOC**: State of Charge; the percentage of energy remaining in a battery
- **TOU**: Time-of-Use; a tariff schedule defining electricity pricing by time period
- **HACS**: Home Assistant Community Store; a third-party package manager for custom integrations
- **Lovelace_Dashboard**: The Home Assistant frontend UI framework for building custom dashboards
- **Power_Flow_Card**: A Lovelace card displaying real-time energy flow between PV, battery, grid, and load
- **Energy_Dashboard**: The built-in Home Assistant dashboard for tracking long-term energy production and consumption
- **Diagnostics**: A Home Assistant feature allowing users to download integration state and configuration for troubleshooting
- **Repair_Flow**: A Home Assistant mechanism for surfacing actionable issues to the user with guided resolution steps
- **Smart_Load**: An inverter-controlled output for managing auxiliary loads based on energy availability
- **Grid_Peak_Shaving**: A control strategy that limits grid import during peak demand periods by supplementing with battery power

## Requirements

### Requirement 1: Authentication and Token Management

**User Story:** As a user, I want the integration to authenticate with the Deye Cloud API using my AppId and AppSecret, so that it can securely access my inverter data and controls.

#### Acceptance Criteria

1. WHEN the user submits AppId and AppSecret during Config_Flow setup, THE Integration SHALL send a token request to the Deye_Cloud_API via POST /v1.0/account/token within a timeout of 10 seconds and store the returned access token and its expiration time
2. IF the Deye_Cloud_API returns an authentication error during Config_Flow setup, THEN THE Integration SHALL display an error message indicating invalid credentials and allow the user to re-enter AppId and AppSecret without restarting the flow
3. WHILE the access token has not exceeded its expiration time and has not been rejected by the Deye_Cloud_API, THE Integration SHALL include the token in all subsequent Deye_Cloud_API requests
4. WHEN the access token is within 60 seconds of its expiration time or the Deye_Cloud_API rejects the token, THE Integration SHALL automatically request a new token using the stored AppId and AppSecret without user intervention, retrying up to 3 times with exponential backoff starting at 2 seconds
5. IF the Deye_Cloud_API returns an authentication error after all token refresh retry attempts are exhausted, THEN THE Integration SHALL mark all entities as unavailable and create a Repair_Flow entry notifying the user of invalid credentials
6. THE Integration SHALL store AppId and AppSecret using the Home Assistant credential storage mechanism and SHALL NOT log or expose these values in diagnostics output

### Requirement 2: Config Flow UI Setup

**User Story:** As a user, I want to set up the integration entirely through the Home Assistant UI, so that I do not need to edit YAML configuration files.

#### Acceptance Criteria

1. THE Integration SHALL provide a Config_Flow that collects AppId, AppSecret, and polling interval from the user, where the polling interval accepts a value between 30 and 600 seconds with a default of 60 seconds
2. WHEN valid credentials are provided, THE Config_Flow SHALL discover all Stations and Inverters associated with the account and allow the user to select which to monitor
3. WHEN the user completes the Config_Flow, THE Integration SHALL create device entries for each selected Inverter and Station
4. THE Integration SHALL provide an options flow allowing the user to modify polling interval, add or remove monitored Inverters, and update credentials after initial setup
5. IF the Deye_Cloud_API is unreachable during Config_Flow, THEN THE Integration SHALL display an error message indicating a connection failure and allow the user to retry
6. IF the Deye_Cloud_API returns an authentication error during Config_Flow, THEN THE Integration SHALL display an error message indicating invalid credentials and return the user to the credentials input step
7. IF the Deye_Cloud_API returns zero Stations and zero Inverters for the account, THEN THE Config_Flow SHALL display an error message indicating no devices were found and abort the setup
8. IF a config entry already exists for the same AppId, THEN THE Config_Flow SHALL abort and display an error message indicating the account is already configured

### Requirement 3: Data Polling and Coordination

**User Story:** As a user, I want the integration to poll inverter data at a configurable interval, so that I can see near-real-time energy information in Home Assistant.

#### Acceptance Criteria

1. THE Coordinator SHALL poll the Deye_Cloud_API for latest device data at the user-configured interval (default 60 seconds, minimum 30 seconds, maximum 3600 seconds)
2. WHEN the Coordinator receives updated data from the Deye_Cloud_API, THE Integration SHALL update all associated sensor entities within 2 seconds
3. IF the Deye_Cloud_API returns a transient error (timeout after 30 seconds, 5xx status), THEN THE Coordinator SHALL retry the request up to 3 times with exponential backoff (initial delay 5 seconds, multiplier 2x, maximum delay 60 seconds) before marking entities as unavailable
4. WHILE the Deye_Cloud_API is unreachable for more than 5 consecutive polling cycles, THE Integration SHALL create a Repair_Flow entry notifying the user of persistent connectivity issues
5. THE Coordinator SHALL use async HTTP calls to avoid blocking the Home Assistant event loop
6. WHEN the Deye_Cloud_API becomes reachable again after entities were marked as unavailable, THE Coordinator SHALL restore all affected entities to available status with the latest data on the next successful poll

### Requirement 4: Real-Time Energy Monitoring Sensors

**User Story:** As a user, I want to see real-time PV generation, battery status, grid flow, and load consumption as Home Assistant sensors, so that I can monitor my energy system at a glance.

#### Acceptance Criteria

1. THE Integration SHALL create sensor entities for: PV power (W), PV daily yield (kWh), PV total yield (kWh) per MPPT channel and aggregated total
2. THE Integration SHALL create sensor entities for battery: SOC (%), power (W, positive=charging, negative=discharging), voltage (V), current (A), temperature (°C)
3. THE Integration SHALL create sensor entities for grid: import power (W), export power (W), daily import (kWh), daily export (kWh), frequency (Hz), and voltage per phase (V) where the number of phase sensors matches the Inverter phase configuration (1 for single-phase, 3 for three-phase)
4. THE Integration SHALL create sensor entities for load: consumption power (W), daily consumption (kWh)
5. THE Integration SHALL assign device_class "power" and state_class "measurement" to all instantaneous power sensors (W), device_class "energy" and state_class "total_increasing" to all cumulative energy sensors (kWh), device_class "voltage" to voltage sensors, device_class "frequency" to frequency sensors, device_class "temperature" to temperature sensors, device_class "battery" to SOC sensors, and device_class "current" to current sensors for Energy_Dashboard compatibility
6. WHEN an Inverter supports multiple MPPT channels, THE Integration SHALL create individual sensor entities for each MPPT channel (power, voltage, current) up to the number of channels reported by the Deye_Cloud_API for that Inverter
7. WHEN an Inverter supports 3-phase output, THE Integration SHALL create individual sensor entities for each phase (voltage, current, power, frequency)
8. IF the Deye_Cloud_API returns a null or missing value for a sensor data point, THEN THE Integration SHALL set that sensor's state to unknown and retain the previous state_class and device_class attributes
9. THE Integration SHALL use a consistent entity naming pattern of sensor.{device_name}_{sensor_type}_{channel_or_phase} for multi-channel/multi-phase sensors, and sensor.{device_name}_{sensor_type} for single-instance sensors

### Requirement 5: Inverter Status and Metadata

**User Story:** As a user, I want to see my inverter's online status, model information, and last update time, so that I can quickly identify connectivity or hardware issues.

#### Acceptance Criteria

1. THE Integration SHALL create a binary sensor indicating Inverter online/offline status based on the device status field reported by the Deye_Cloud_API (on = online, off = offline)
2. THE Integration SHALL expose Inverter metadata (model name, serial number, firmware version, rated power) as device attributes on the Inverter device entry
3. WHEN the Deye_Cloud_API reports an active alert for an Inverter, THE Integration SHALL fire a Home Assistant event entity containing the alert type, severity, timestamp, and descriptive message as reported by the API
4. WHEN the Deye_Cloud_API reports that a previously active alert for an Inverter has cleared, THE Integration SHALL fire a follow-up event entity indicating the alert resolution with the original alert type and resolution timestamp
5. THE Integration SHALL create a sensor with device_class "timestamp" showing the last successful data collection time as reported by the Deye_Cloud_API for the Inverter

### Requirement 6: Battery Configuration Controls

**User Story:** As a user, I want to adjust battery charge/discharge thresholds and current limits from Home Assistant, so that I can optimize battery usage without opening the Deye Cloud app.

#### Acceptance Criteria

1. THE Integration SHALL create number entities for: minimum SOC (%), maximum SOC (%), maximum charge current (A), maximum discharge current (A), with step size of 1 for SOC entities and 0.1 for current entities, and min/max bounds set to the Inverter-reported acceptable range
2. WHEN the user changes a battery number entity value, THE Integration SHALL send the updated configuration to the Deye_Cloud_API via the Configuration Operation endpoints within 10 seconds
3. IF a user-provided battery parameter value falls outside the Inverter-reported acceptable range, THEN THE Integration SHALL reject the change, retain the previous entity value, and raise a persistent notification indicating the valid range
4. IF the Deye_Cloud_API rejects a battery configuration change, THEN THE Integration SHALL revert the entity to the previous value and raise a persistent notification with the error reason
5. WHEN the Coordinator retrieves updated data from the Deye_Cloud_API, THE Integration SHALL synchronize battery number entity values with the current Inverter-reported configuration
6. IF the Inverter-reported acceptable range is unavailable, THEN THE Integration SHALL mark the battery number entities as unavailable until the range is successfully retrieved

### Requirement 7: Work Mode and Energy Pattern Controls

**User Story:** As a user, I want to change the inverter work mode and energy pattern from Home Assistant, so that I can switch between self-consumption, time-of-use, and selling modes.

#### Acceptance Criteria

1. THE Integration SHALL create a select entity exposing available system work modes from the Deye_Cloud_API (e.g., Self-Consumption, Time-of-Use, Selling First, Zero Export) with the entity options populated from the Inverter's supported mode list reported by the API
2. WHEN the user selects a work mode, THE Integration SHALL send the mode update to the Deye_Cloud_API via the Control Operation work mode update endpoint and update the entity state to reflect the confirmed mode upon successful API response
3. WHEN the user selects an energy pattern, THE Integration SHALL send the energy pattern update to the Deye_Cloud_API via the Control Operation energy pattern endpoint and update the entity state to reflect the confirmed pattern upon successful API response
4. THE Integration SHALL create a select entity for energy pattern configuration (e.g., Battery First, Load First) with the entity options populated from the Inverter's supported energy pattern list reported by the API
5. IF the Deye_Cloud_API rejects a work mode or energy pattern change, THEN THE Integration SHALL revert the entity to the previous value and raise a persistent notification indicating the failure reason returned by the API
6. WHEN the Coordinator polls updated data from the Deye_Cloud_API, THE Integration SHALL synchronize the work mode and energy pattern select entities to reflect the current Inverter state

### Requirement 8: Time-of-Use Schedule Configuration

**User Story:** As a user, I want to configure time-of-use charging and discharging schedules from Home Assistant, so that I can automate battery behavior around my electricity tariff.

#### Acceptance Criteria

1. THE Integration SHALL create entities for each TOU time slot consisting of: a time entity for start time (HH:MM resolution), a time entity for end time (HH:MM resolution), a select entity for mode (Charging, Discharging, Disabled), and a number entity for power limit bounded by 0 W to the Inverter rated power
2. WHEN the user modifies a TOU time slot entity, THE Integration SHALL validate that the time slot does not overlap with other configured slots and SHALL send the updated TOU configuration to the Deye_Cloud_API via the TOU switch/update endpoint within 10 seconds
3. THE Integration SHALL create a switch entity to enable or disable the TOU schedule globally
4. THE Integration SHALL support a minimum of 6 configurable TOU time slots per Inverter
5. IF the Deye_Cloud_API rejects a TOU schedule update, THEN THE Integration SHALL revert the modified entity to its previous value and raise a persistent notification indicating the failure reason
6. IF the user configures a TOU time slot with an end time earlier than or equal to its start time or overlapping with another enabled slot, THEN THE Integration SHALL reject the change, retain the previous value, and notify the user of the validation error

### Requirement 9: Grid and Sell Power Controls

**User Story:** As a user, I want to control grid export limits and solar sell settings from Home Assistant, so that I can comply with grid regulations or maximize revenue.

#### Acceptance Criteria

1. THE Integration SHALL create a number entity for grid export power limit (W) with minimum value of 0, maximum value equal to the Inverter rated power, and step size of 1 W
2. THE Integration SHALL create a switch entity to enable or disable solar sell mode
3. WHEN the user changes the grid export limit, solar sell switch, or any Grid_Peak_Shaving entity, THE Integration SHALL send the updated setting to the Deye_Cloud_API via the corresponding control endpoint within 5 seconds
4. THE Integration SHALL create a switch entity to enable or disable Grid_Peak_Shaving and a number entity for the Grid_Peak_Shaving power threshold (W) with minimum value of 0, maximum value equal to the Inverter rated power, and step size of 1 W
5. IF the Deye_Cloud_API rejects a grid or sell configuration change, THEN THE Integration SHALL revert the entity to the last value confirmed by the Deye_Cloud_API and raise a persistent notification indicating the failure reason
6. THE Integration SHALL validate that user-provided grid export limit and Grid_Peak_Shaving power threshold values fall within the Inverter-reported acceptable range before sending to the Deye_Cloud_API

### Requirement 10: Smart Load Control

**User Story:** As a user, I want to manage smart load outputs from Home Assistant, so that I can control auxiliary loads based on solar availability.

#### Acceptance Criteria

1. WHEN the Inverter supports Smart_Load outputs as reported by the Deye_Cloud_API device capabilities, THE Integration SHALL create switch entities for each Smart_Load channel with initial state reflecting the current on/off status from the API
2. WHEN the user toggles a Smart_Load switch, THE Integration SHALL send the control command to the Deye_Cloud_API via the smartload endpoint and update the entity state upon successful API acknowledgment
3. IF the Inverter does not support Smart_Load, THEN THE Integration SHALL not create Smart_Load entities for that device
4. IF the Deye_Cloud_API rejects a Smart_Load control command, THEN THE Integration SHALL revert the switch entity to the previous state and raise a persistent notification indicating the failure reason

### Requirement 11: Solar Forecast

**User Story:** As a user, I want solar production forecasts integrated into Home Assistant, so that I can plan energy usage and automation around expected generation.

#### Acceptance Criteria

1. THE Integration SHALL retrieve solar irradiance forecast data from the Open-Meteo API using the Station GPS coordinates without requiring an API key
2. THE Integration SHALL create sensor entities for: forecast today (kWh), forecast tomorrow (kWh), and a single forecast hourly sensor whose state represents the current hour estimated power (W) with a forecast attribute containing the next 24 hourly values (timestamp and watts)
3. THE Integration SHALL estimate production by multiplying the Open-Meteo irradiance forecast (W/m²) by the total panel area derived from Inverter rated power, adjusted for the user-configured panel tilt, azimuth, and a system efficiency factor (default 0.75, configurable between 0.5 and 0.95 via options flow)
4. THE Coordinator SHALL update solar forecast data every 60 minutes
5. IF the Open-Meteo API is unreachable, THEN THE Integration SHALL retain the last successful forecast values, set a boolean stale attribute to true on each forecast sensor, and add a last_successful_update attribute containing the timestamp of the last successful retrieval
6. THE Integration SHALL provide panel tilt (0 to 90 degrees, default 30) and azimuth (0 to 360 degrees, default 180 south-facing) configuration options in the options flow for solar forecast estimation

### Requirement 12: Tariff Manager for Automated Charging

**User Story:** As a user, I want to define electricity tariffs and have the integration automate cheap-rate charging and peak-rate discharging, so that I can minimize electricity costs.

#### Acceptance Criteria

1. THE Integration SHALL provide a tariff configuration interface (via options flow or service call) where the user defines up to 10 rate periods, each with start time (HH:MM), end time (HH:MM), and rate category (cheap, standard, peak), and SHALL reject configurations containing overlapping time periods
2. WHILE tariff-based automation is enabled via the global switch entity, WHEN the current time enters a cheap-rate period, THE Integration SHALL switch the Inverter to grid-charging mode at the configured maximum charge current within 60 seconds of the period start time
3. WHILE tariff-based automation is enabled via the global switch entity, WHEN the current time enters a peak-rate period, THE Integration SHALL switch the Inverter to battery-discharge mode using the configured maximum discharge current within 60 seconds of the period start time
4. THE Integration SHALL create a switch entity to enable or disable tariff-based automation globally
5. WHEN a tariff period transition occurs, THE Integration SHALL fire a Home Assistant event containing the Inverter device identifier, previous rate category, new rate category, and transition timestamp
6. WHILE tariff-based automation is enabled via the global switch entity, WHEN the current time enters a standard-rate period, THE Integration SHALL restore the Inverter to the user-configured default work mode without modifying charge or discharge current settings
7. IF the Deye_Cloud_API rejects a mode-switch command during a tariff period transition, THEN THE Integration SHALL retry the command up to 3 times with 30-second intervals and raise a persistent notification if all retries fail

### Requirement 13: Multiple Inverter Support

**User Story:** As a user with multiple inverters, I want each inverter represented as a separate HA device with independent sensors and controls, so that I can manage a multi-inverter installation.

#### Acceptance Criteria

1. THE Integration SHALL create a separate Home Assistant device entry for each configured Inverter with a unique identifier based on the device serial number
2. THE Integration SHALL associate all sensor, control, and diagnostic entities with the correct parent Inverter device, using entity unique IDs that incorporate the Inverter serial number to prevent collisions across devices
3. WHEN the user adds a new Inverter via the options flow, THE Integration SHALL create all sensor, control, and diagnostic entities for the new Inverter within one polling cycle without restarting Home Assistant
4. THE Integration SHALL create independent device entries and entities for Inverters across multiple Stations within the same account, supporting at least 10 Inverters per integration instance
5. WHEN the user removes an Inverter via the options flow, THE Integration SHALL remove the corresponding device entry and all associated entities from Home Assistant without affecting other Inverter devices
6. IF the Deye_Cloud_API returns an error for a specific Inverter during polling, THEN THE Integration SHALL mark only that Inverter's entities as unavailable and continue updating entities for all other Inverters normally

### Requirement 14: Lovelace Dashboard

**User Story:** As a user, I want a pre-built Lovelace dashboard showing power flow, charts, settings, and diagnostics, so that I can immediately visualize my energy system.

#### Acceptance Criteria

1. THE Integration SHALL provide a Lovelace_Dashboard configuration (YAML or auto-generated) containing: Power_Flow_Card view, summary statistics view, historical charts view, settings/controls view, and diagnostics view
2. THE Power_Flow_Card view SHALL display energy flow between PV, Battery, Grid, and Load with instantaneous power values in watts, updated each time the Coordinator completes a polling cycle
3. THE summary statistics view SHALL display: daily and total production (kWh), daily and total consumption (kWh), self-consumption ratio calculated as (PV energy consumed on-site / total PV energy produced) × 100 (%), and self-sufficiency ratio calculated as (energy supplied by PV and Battery / total load consumption) × 100 (%)
4. THE historical charts view SHALL display: a power profile graph showing PV, Grid, Battery, Consumption, and SOC values over the previous 24 hours at the Coordinator polling resolution, daily generation and usage bar charts for the previous 7 days, and solar/utilization donut charts for the current day
5. THE settings view SHALL expose all writable controls (battery thresholds, work mode, TOU schedule, grid limits, solar sell, smart loads)
6. THE diagnostics view SHALL display Inverter status, last update time, firmware version, and a link to download diagnostics
7. WHEN the Integration is loaded after Config_Flow setup or Home Assistant restart, THE Integration SHALL register the Lovelace_Dashboard so it appears in the Home Assistant sidebar without manual user configuration

### Requirement 15: Energy Dashboard Compatibility

**User Story:** As a user, I want the integration's sensors to work with the built-in Home Assistant Energy Dashboard, so that I can track long-term energy production and consumption.

#### Acceptance Criteria

1. THE Integration SHALL provide total_increasing state class sensors with stable unique_ids (derived from Inverter serial number and sensor type) for: total solar production (kWh), total grid import (kWh), total grid export (kWh), total battery charge (kWh), total battery discharge (kWh), total load consumption (kWh)
2. THE Integration SHALL assign device_class "energy" and native_unit "kWh" to all energy accumulation sensors, and SHALL NOT set the last_reset attribute on total_increasing sensors
3. WHEN the user configures the Energy_Dashboard, THE Integration sensors SHALL be selectable as sources in the Energy configuration panel for solar production, grid consumption, grid return, and battery systems by meeting the Home Assistant state_class, device_class, and unit requirements
4. IF the Deye_Cloud_API returns a cumulative energy value lower than the previously recorded value for a total_increasing sensor, THEN THE Integration SHALL treat this as a counter reset and report the new value without adjustment, allowing Home Assistant to detect the reset and calculate the correct delta

### Requirement 16: Diagnostics and Troubleshooting

**User Story:** As a user, I want to download diagnostics data and see guided repair flows, so that I can troubleshoot issues without digging through logs.

#### Acceptance Criteria

1. THE Integration SHALL implement the Home Assistant diagnostics platform providing a downloadable JSON file containing: integration configuration (with AppId, AppSecret, and access tokens redacted), current entity states, last API response data, and error counts accumulated since the integration was last loaded
2. IF invalid credentials are detected, OR the Deye_Cloud_API is unreachable for 5 consecutive polling cycles, OR an Inverter is offline for more than 1 hour, OR a firmware update is reported by the Deye_Cloud_API, THEN THE Integration SHALL create a Repair_Flow entry identifying the specific condition
3. WHEN a Repair_Flow is created, THE Integration SHALL provide resolution steps within the repair dialog that include: a description of the detected problem, at least one concrete user action to resolve it, and a reference to where the user can verify the fix
4. WHEN the condition that triggered a Repair_Flow is no longer detected, THE Integration SHALL automatically dismiss the corresponding Repair_Flow entry within 2 polling cycles

### Requirement 17: HACS Compatibility and Installation

**User Story:** As a user, I want to install the integration through HACS, so that I can easily manage updates.

#### Acceptance Criteria

1. THE Integration SHALL include a hacs.json manifest file specifying at minimum the name field set to the integration display name and the content_in_root field indicating whether integration files reside at the repository root
2. THE Integration SHALL include a manifest.json file with domain set to "deye_cloud", a human-readable name, a version string following semantic versioning (MAJOR.MINOR.PATCH), a dependencies array listing required PyPI packages, an iot_class field, and a codeowners array with at least one GitHub username
3. THE Integration SHALL follow the Home Assistant custom component directory structure custom_components/deye_cloud/ containing at minimum: __init__.py, manifest.json, config_flow.py, and strings.json
4. WHEN a new version tag is published to the repository, THE Integration SHALL be detectable as upgradeable by HACS through the version field in manifest.json matching the repository release tag

### Requirement 18: HA Services and Actions

**User Story:** As a user, I want to call integration services from automations and scripts, so that I can build custom energy management logic.

#### Acceptance Criteria

1. THE Integration SHALL register a service for sending custom Modbus commands to the Inverter via the Deye_Cloud_API custom modbus control endpoint, accepting required parameters: target device identifier, register address (integer), and register value (integer)
2. THE Integration SHALL register a service for reading the current dynamic control strategy from the Deye_Cloud_API, accepting a target device identifier and returning the strategy data in the service response
3. THE Integration SHALL register a service for writing a dynamic control strategy to the Deye_Cloud_API, accepting a target device identifier and the strategy parameters to apply
4. THE Integration SHALL register a service to force an immediate data refresh outside the normal polling cycle, accepting a target device identifier, with a minimum cooldown of 10 seconds between consecutive forced refreshes per device
5. WHEN a service call fails due to a Deye_Cloud_API error response, THE Integration SHALL raise a HomeAssistantError with a message including the Deye_Cloud_API error code and the failed operation name
6. IF a service call does not receive a response from the Deye_Cloud_API within 30 seconds, THEN THE Integration SHALL raise a HomeAssistantError indicating a timeout
7. IF a service call receives invalid or out-of-range parameters, THEN THE Integration SHALL raise a HomeAssistantError indicating which parameter failed validation without sending a request to the Deye_Cloud_API

### Requirement 19: Station-Level Monitoring

**User Story:** As a user, I want to see station-level aggregate data (total production, consumption across all inverters at a site), so that I can monitor the overall installation performance.

#### Acceptance Criteria

1. THE Integration SHALL create a Home Assistant device entry for each Station, identified by the Deye_Cloud_API station identifier, with aggregate sensors: total station power (W) with state_class measurement, daily station production (kWh) with state_class total_increasing, and daily station consumption (kWh) with state_class total_increasing
2. WHEN the Deye_Cloud_API reports station-level alerts, THE Integration SHALL create event entities containing the alert type, severity, timestamp, and affected station identifier
3. THE Integration SHALL expose Station metadata as device attributes: name (string), location (latitude and longitude coordinates as reported by the Deye_Cloud_API), and rated capacity (kWp)
4. IF all Inverters within a Station are offline or unavailable, THEN THE Integration SHALL mark the Station aggregate sensors as unavailable and retain the last known device attribute values

### Requirement 20: Error Handling and Resilience

**User Story:** As a user, I want the integration to handle API errors gracefully without crashing Home Assistant, so that my smart home remains stable even when the cloud service has issues.

#### Acceptance Criteria

1. IF the Deye_Cloud_API returns a rate-limiting response (HTTP 429) with a Retry-After header, THEN THE Integration SHALL pause polling for the duration specified in the Retry-After header (up to a maximum of 300 seconds) and resume automatically. IF the Retry-After header is absent, THEN THE Integration SHALL pause polling for 60 seconds before resuming.
2. IF an unexpected exception occurs during data polling, THEN THE Integration SHALL log the error at warning level, mark affected entities as unavailable, and continue polling at the next scheduled interval
3. THE Integration SHALL catch all exceptions within its polling, event handling, and service call code paths so that no unhandled exceptions propagate to the Home Assistant core event loop
4. WHEN the Deye_Cloud_API returns a response where one or more requested measure point fields are absent or null while other fields contain valid data, THE Integration SHALL update sensors that have valid data and set sensors corresponding to missing fields to state unknown rather than unavailable
5. WHEN the Deye_Cloud_API returns a successful response after entities were previously marked as unavailable due to errors, THE Integration SHALL restore those entities to available status and update them with the received data within the same polling cycle
