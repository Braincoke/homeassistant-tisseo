"""Constants for the Tisseo integration."""
from typing import Final

DOMAIN: Final = "tisseo"

# Config keys (for API access)
CONF_API_KEY: Final = "api_key"
CONF_USE_MOCK: Final = "use_mock_data"
CONF_DEBUG: Final = "debug"

# Config keys (for stop data)
CONF_STOP_ID: Final = "stop_id"
CONF_STOP_NAME: Final = "stop_name"
CONF_LINE: Final = "line"
CONF_LINE_NAME: Final = "line_name"
CONF_ROUTE: Final = "route"
CONF_ROUTE_DIRECTION: Final = "route_direction"
CONF_TRANSPORT_MODE: Final = "transport_mode"
CONF_IMMINENT_THRESHOLD: Final = "imminent_threshold"

# Config keys (for update options)
CONF_UPDATE_STRATEGY: Final = "update_strategy"
CONF_STATIC_INTERVAL: Final = "static_interval"
CONF_MESSAGES_REFRESH_INTERVAL: Final = "messages_refresh_interval"
CONF_OUTAGES_REFRESH_INTERVAL: Final = "outages_refresh_interval"

# Update strategies
UPDATE_STRATEGY_STATIC: Final = "static"
UPDATE_STRATEGY_SMART: Final = "smart"
UPDATE_STRATEGY_TIME_WINDOW: Final = "time_window"

# Default values
DEFAULT_IMMINENT_THRESHOLD: Final = 2  # minutes
DEFAULT_UPDATE_STRATEGY: Final = UPDATE_STRATEGY_SMART
DEFAULT_STATIC_INTERVAL: Final = 60  # seconds

# Smart update timing
SMART_PRE_DEPARTURE_SECONDS: Final = 60  # Call API 1 minute before departure
SMART_POST_DEPARTURE_SECONDS: Final = 20  # Call API 20 seconds after departure
COUNTDOWN_UPDATE_INTERVAL: Final = 30  # Update displayed countdown every 30 seconds

# Schedule configuration
CONF_SCHEDULE_ENABLED: Final = "schedule_enabled"
CONF_ACTIVE_WINDOWS: Final = "active_windows"
CONF_INACTIVE_INTERVAL: Final = "inactive_interval"

# Active window keys
CONF_WINDOW_NAME: Final = "name"
CONF_WINDOW_DAYS: Final = "days"
CONF_WINDOW_START: Final = "start"
CONF_WINDOW_END: Final = "end"

# Schedule defaults
DEFAULT_SCHEDULE_ENABLED: Final = False
DEFAULT_INACTIVE_INTERVAL: Final = 0  # 0 = no updates when inactive

# Day constants for selector
DAYS_OF_WEEK: Final = [
    {"value": "mon", "label": "Monday"},
    {"value": "tue", "label": "Tuesday"},
    {"value": "wed", "label": "Wednesday"},
    {"value": "thu", "label": "Thursday"},
    {"value": "fri", "label": "Friday"},
    {"value": "sat", "label": "Saturday"},
    {"value": "sun", "label": "Sunday"},
]

# Map day abbreviations to Python weekday numbers (Monday=0)
DAY_TO_WEEKDAY: Final = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}

# Alert caching
ALERT_CACHE_DURATION: Final = 300  # Cache alerts for 5 minutes (300 seconds)
DEFAULT_MESSAGES_REFRESH_INTERVAL: Final = ALERT_CACHE_DURATION
DEFAULT_OUTAGES_REFRESH_INTERVAL: Final = ALERT_CACHE_DURATION

# API usage tracking
STORAGE_VERSION_API_USAGE: Final = 1
STORAGE_KEY_API_USAGE: Final = f"{DOMAIN}_api_usage"
API_USAGE_ENTITY_ID: Final = "sensor.tisseo_api_calls_total"
API_USAGE_SAVE_DELAY_SECONDS: Final = 10
API_USAGE_DAILY_RETENTION_DAYS: Final = 90

# API Configuration
API_BASE_URL: Final = "https://api.tisseo.fr/v2"
API_TIMEOUT: Final = 10  # seconds
DEFAULT_SCAN_INTERVAL: Final = 60  # seconds

# Device info
DEVICE_MANUFACTURER: Final = "Tisseo"
DEVICE_MODEL: Final = "Bus Stop"

# Attribution
ATTRIBUTION: Final = "Data provided by Tisseo Open Data"
