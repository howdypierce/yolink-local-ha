"""Device triggers for YoLink Local SmartRemoter (FlexFob) buttons.

Trigger types and the event payload match the cloud YoLink integration, so an
automation written against ``button_1_short_press`` there reads the same here.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    BUTTON_PRESS_TYPES,
    DOMAIN,
    EVENT_BUTTON,
    SMART_REMOTER_BUTTONS_BY_MODEL,
    SMART_REMOTER_DEFAULT_BUTTONS,
)


def trigger_types_for(button_count: int) -> list[str]:
    """Return the trigger types offered for a remote with this many buttons."""
    return [
        f"button_{button}_{press}"
        for button in range(1, button_count + 1)
        for press in BUTTON_PRESS_TYPES
    ]


TRIGGER_TYPES = trigger_types_for(SMART_REMOTER_DEFAULT_BUTTONS)

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES)}
)


def _button_count(hass: HomeAssistant, device_id: str) -> int | None:
    """Return the button count of a SmartRemoter, or None for other devices."""
    registry_device = dr.async_get(hass).async_get(device_id)
    if registry_device is None:
        return None
    yolink_ids = [
        identifier
        for domain, identifier in registry_device.identifiers
        if domain == DOMAIN
    ]
    for coordinator in hass.data.get(DOMAIN, {}).values():
        devices = getattr(coordinator, "devices", {})
        for yolink_id in yolink_ids:
            device = devices.get(yolink_id)
            if device is not None and device.device_type == "SmartRemoter":
                return SMART_REMOTER_BUTTONS_BY_MODEL.get(
                    device.model or "", SMART_REMOTER_DEFAULT_BUTTONS
                )
    return None


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """List the button triggers of a SmartRemoter device."""
    button_count = _button_count(hass, device_id)
    if button_count is None:
        return []
    return [
        {
            CONF_DEVICE_ID: device_id,
            CONF_DOMAIN: DOMAIN,
            CONF_PLATFORM: "device",
            CONF_TYPE: trigger_type,
        }
        for trigger_type in trigger_types_for(button_count)
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Listen for the button event that matches this trigger."""
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: EVENT_BUTTON,
            event_trigger.CONF_EVENT_DATA: {
                CONF_DEVICE_ID: config[CONF_DEVICE_ID],
                CONF_TYPE: config[CONF_TYPE],
            },
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
