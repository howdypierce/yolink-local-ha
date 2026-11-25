"""Event platform for YoLink Local SmartRemoter (FlexFob) buttons."""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Device
from .const import (
    BUTTON_PRESS_TYPES,
    EVENT_BUTTON,
    SMART_REMOTER_BUTTONS_BY_MODEL,
    SMART_REMOTER_DEFAULT_BUTTONS,
)
from .coordinator import YoLocalCoordinator
from .entity import YoLocalEntity, async_setup_device_entities


def build_entities(
    coordinator: YoLocalCoordinator,
    device: Device,
) -> list[YoLocalButtonEvent]:
    """Create one event entity per button of a SmartRemoter."""
    if device.device_type != "SmartRemoter":
        return []
    button_count = SMART_REMOTER_BUTTONS_BY_MODEL.get(
        device.model or "", SMART_REMOTER_DEFAULT_BUTTONS
    )
    return [
        YoLocalButtonEvent(coordinator, device, button)
        for button in range(1, button_count + 1)
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up YoLink button event entities from a config entry."""
    await async_setup_device_entities(hass, entry, async_add_entities, build_entities)


class YoLocalButtonEvent(YoLocalEntity, EventEntity):
    """One button of a SmartRemoter, firing short_press and long_press.

    Presses arrive through the same ``yolocal_event`` that drives the device
    triggers, so both paths see exactly the same filtered presses.
    """

    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(
        self,
        coordinator: YoLocalCoordinator,
        device: Device,
        button: int,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator, device)
        self._button = button
        self._trigger_prefix = f"button_{button}_"
        self._attr_event_types = list(BUTTON_PRESS_TYPES)
        self._attr_unique_id = f"{device.device_id}_button_{button}"
        self._attr_name = f"Button {button}"

    async def async_added_to_hass(self) -> None:
        """Listen for this button's presses."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_BUTTON, self._handle_press)
        )

    @callback
    def _handle_press(self, event: Event) -> None:
        """Record a press of this button."""
        if event.data.get("yolink_device_id") != self._device.device_id:
            return
        trigger_type = event.data.get("type")
        if not isinstance(trigger_type, str) or not trigger_type.startswith(
            self._trigger_prefix
        ):
            return
        press_type = trigger_type.removeprefix(self._trigger_prefix)
        if press_type not in BUTTON_PRESS_TYPES:
            return
        self._trigger_event(press_type)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Stay available while the hub is reachable.

        A remote may stay silent for days between presses, so the twelve-hour
        contact timeout used by other entities does not apply. Were the button
        to go unavailable, triggers would ignore the press that brings it back.
        """
        return self.coordinator.last_update_success
