"""Constants for the Deye Cloud integration."""

from typing import Final

DOMAIN: Final = "deye_cloud"

# Polling intervals (seconds)
DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 30
MAX_SCAN_INTERVAL: Final = 3600

# Platforms
PLATFORMS: Final = [
    "sensor",
    "binary_sensor",
]

# Retry configuration - Coordinator
COORDINATOR_MAX_RETRIES: Final = 3
COORDINATOR_INITIAL_DELAY_S: Final = 5
COORDINATOR_BACKOFF_MULTIPLIER: Final = 2
COORDINATOR_MAX_DELAY_S: Final = 60

# Retry configuration - Token refresh
TOKEN_REFRESH_MAX_RETRIES: Final = 3
TOKEN_REFRESH_INITIAL_DELAY_S: Final = 2
TOKEN_REFRESH_BACKOFF_MULTIPLIER: Final = 2
TOKEN_REFRESH_MAX_DELAY_S: Final = 16

# Retry configuration - Tariff mode switch
TARIFF_MODE_SWITCH_MAX_RETRIES: Final = 3
TARIFF_MODE_SWITCH_DELAY_S: Final = 30

# Consecutive failure threshold for repair flow
CONSECUTIVE_FAILURE_THRESHOLD: Final = 5

# Rate limit
RATE_LIMIT_MAX_PAUSE_S: Final = 300
RATE_LIMIT_DEFAULT_PAUSE_S: Final = 60

# API timeouts (seconds)
API_REQUEST_TIMEOUT: Final = 30
API_AUTH_TIMEOUT: Final = 10

# Token refresh window (seconds before expiry)
TOKEN_REFRESH_WINDOW_S: Final = 60

# Service cooldowns
FORCE_REFRESH_COOLDOWN_S: Final = 10

# Forecast
FORECAST_UPDATE_INTERVAL_MINUTES: Final = 60
DEFAULT_PANEL_TILT: Final = 30
DEFAULT_PANEL_AZIMUTH: Final = 180
DEFAULT_SYSTEM_EFFICIENCY: Final = 0.75
MIN_SYSTEM_EFFICIENCY: Final = 0.5
MAX_SYSTEM_EFFICIENCY: Final = 0.95

# Tariff
MAX_TARIFF_PERIODS: Final = 10
