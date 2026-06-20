# Deye Cloud Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration for monitoring and controlling Deye solar/hybrid inverters via the official Deye Cloud developer API.

## Features

- **Real-time monitoring**: PV power, battery status, grid flow, load consumption
- **Multi-MPPT & multi-phase**: Dynamic sensors per MPPT channel and AC phase
- **Battery controls**: Min/max SOC, charge/discharge current limits
- **Work mode selection**: Self-consumption, Time-of-Use, Selling First, Zero Export
- **TOU schedule**: Configure up to 6 time-of-use charging/discharging slots
- **Grid controls**: Export limit, solar sell, peak shaving
- **Smart load switches**: Per-channel control (when supported by inverter)
- **Solar forecast**: Open-Meteo irradiance-based production estimates
- **Tariff automation**: Automatic mode switching based on electricity tariff periods
- **Energy Dashboard**: Compatible total_increasing sensors for HA Energy Dashboard
- **Multi-inverter**: Supports 10+ inverters across multiple stations
- **Lovelace dashboard**: Pre-built dashboard with power flow, charts, settings, diagnostics
- **Diagnostics & repairs**: Downloadable diagnostics, guided repair flows

## Requirements

- Home Assistant 2024.1+
- Deye Cloud developer account (AppId and AppSecret from [Deye Cloud Developer Portal](https://eu1-developer.deyecloud.com))

## Installation via HACS

1. Open HACS in your Home Assistant
2. Go to **Integrations** → click the three dots menu → **Custom repositories**
3. Add `https://github.com/aldwinbalila/deye` with category **Integration**
4. Click **Install**
5. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "Deye Cloud"
3. Enter your AppId and AppSecret
4. Select which inverters and stations to monitor
5. Configure polling interval (default 60s, range 30-600s)

## Supported Entities

| Platform | Entities |
|----------|----------|
| Sensor | PV power/yield, battery SOC/power/voltage/current/temp, grid import/export, load, frequency, per-phase, station aggregates |
| Binary Sensor | Inverter online status |
| Number | Battery SOC min/max, charge/discharge current, grid export limit, peak shaving threshold, TOU power limits |
| Select | Work mode, energy pattern, TOU slot modes |
| Switch | Solar sell, peak shaving, TOU enable, tariff automation, smart loads |
| Time | TOU slot start/end times |
| Event | Inverter alerts, station alerts |

## Services

- `deye_cloud.send_modbus_command` — Custom Modbus register write
- `deye_cloud.read_control_strategy` — Read dynamic control strategy
- `deye_cloud.write_control_strategy` — Write dynamic control strategy
- `deye_cloud.force_refresh` — Immediate data refresh (10s cooldown)

## License

MIT
