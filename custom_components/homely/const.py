"""Constants for the Homely Alarm integration."""

DOMAIN = "homely"
LOGGER_NAME = "custom_components.homely"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_HOME_ID = "home_id"
CONF_LOCATION_ID = "location_id"

# Options
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_WEBSOCKET = "enable_websocket"
CONF_POLL_WHEN_WEBSOCKET = "poll_when_websocket"

# Defaults
DEFAULT_HOME_ID = 0
DEFAULT_SCAN_INTERVAL = 120
DEFAULT_ENABLE_WEBSOCKET = True
DEFAULT_POLL_WHEN_WEBSOCKET = True

OPTION_KEYS = (
    CONF_HOME_ID,
    CONF_SCAN_INTERVAL,
    CONF_ENABLE_WEBSOCKET,
    CONF_POLL_WHEN_WEBSOCKET,
)
