"""Constants for the YoLink Local integration."""

from datetime import timedelta

DOMAIN = "yolocal"
EVENT_DATA_RECORD = f"{DOMAIN}_data_record"
# Fired for SmartRemoter (FlexFob) button presses. The payload mirrors the
# cloud YoLink integration's ``yolink_event`` so device triggers and event
# automations carry over: ``device_id`` is the Home Assistant device registry id
# and ``type`` is e.g. ``button_1_short_press``.
EVENT_BUTTON = f"{DOMAIN}_event"

# SmartRemoter press types, as named by the cloud integration's triggers.
BUTTON_PRESS_TYPES = ("short_press", "long_press")
# The Mini FlexFob has two buttons and the FlexFob four. A SmartRemoter whose
# model is not listed is treated as having the FlexFob's four.
SMART_REMOTER_DEFAULT_BUTTONS = 4
SMART_REMOTER_BUTTONS_BY_MODEL = {
    "YS3604-UC": 4,
    "YS3604-EC": 4,
    "YS3614-UC": 2,
    "YS3614-EC": 2,
}

# Configuration keys
CONF_HUB_IP = "hub_ip"
CONF_SECONDARY_HUB_IP = "secondary_hub_ip"
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_NET_ID = "net_id"

# Default ports
DEFAULT_HTTP_PORT = 1080
DEFAULT_MQTT_PORT = 18080
UPDATE_INTERVAL = timedelta(minutes=5)
DEVICE_DISCOVERY_INTERVAL = timedelta(minutes=1)

# API endpoints
TOKEN_ENDPOINT = "/open/yolink/token"
API_ENDPOINT = "/open/yolink/v2/api"

# Platforms we support
PLATFORMS: list[str] = [
    "sensor",
    "binary_sensor",
    "lock",
    "switch",
    "siren",
    "valve",
    "button",
    "event",
]

# Garage door controllers only pulse their relay. They get a toggle button;
# open/closed comes from whichever sensor the user pairs with it in Home
# Assistant (for example a template cover). Finger (YS4908) is not enabled:
# no captures confirm its behavior yet.
GARAGE_DOOR_DEVICE_TYPES = frozenset({"GarageDoor"})
