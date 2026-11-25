"""SmartRemoter (FlexFob) button events, replayed from YS3614-UC captures.

``captures/devices/SmartRemoter-1`` holds one press of each kind from a Mini
FlexFob: top button (keyMask 1) and bottom button (keyMask 2), each as a short
``Press`` and a ``LongPress``. Every press arrives as a single
``SmartRemoter.StatusChange``; a long press is not preceded by a short one.
``getState`` keeps returning the last press, so only MQTT may fire events.

``mqtt_0005.json`` is the fob's four-hourly check-in, captured with nobody
touching it: a ``SmartRemoter.Report`` that repeats the last press (keyMask 2,
Press). It must never be taken for a press.
"""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.helpers import device_registry as dr

from custom_components.yolocal import device_trigger
from custom_components.yolocal import event as event_platform
from custom_components.yolocal.api import Device, DeviceEvent
from custom_components.yolocal.const import DOMAIN, EVENT_BUTTON
from custom_components.yolocal.coordinator import (
    YoLocalCoordinator,
    smart_remoter_trigger_types,
)
from custom_components.yolocal.entity import YoLocalEntity

REPO = Path(__file__).resolve().parents[1]
CAPTURES = REPO / "captures/devices/SmartRemoter-1"
DEVICE = Device(
    "SmartRemoter-1", "Shop Fob", "token", "SmartRemoter", "SmartRemoter", "YS3614-UC"
)
HA_DEVICE_ID = "ha-device-shop-fob"
PRESS_CAPTURES = {
    "mqtt_0001.json": "button_1_short_press",
    "mqtt_0002.json": "button_2_short_press",
    "mqtt_0003.json": "button_1_long_press",
    "mqtt_0004.json": "button_2_long_press",
}


def load(name: str) -> dict:
    return json.loads((CAPTURES / name).read_text())


@pytest.fixture(autouse=True)
def registered_fob():
    """Register the fob the way its entities' DeviceInfo would."""
    registry = dr.async_get(None)
    identifiers = frozenset({(DOMAIN, DEVICE.device_id)})
    registry.devices[identifiers] = SimpleNamespace(
        id=HA_DEVICE_ID, identifiers=set(identifiers), config_entry_id="entry"
    )
    yield registry
    registry.devices.pop(identifiers, None)


def make_coordinator(stored: dict | None = None) -> YoLocalCoordinator:
    coordinator = YoLocalCoordinator(
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=Mock()), data={}),
        client=SimpleNamespace(host="127.0.0.1"),
        token_manager=SimpleNamespace(client_id="test"),
        session=SimpleNamespace(),
        config_entry_id="entry",
        net_id="test",
    )
    coordinator._contact_store.data = stored
    asyncio.run(coordinator._async_load_contact_state())
    coordinator._devices[DEVICE.device_id] = DEVICE
    return coordinator


def set_now(monkeypatch, now: datetime) -> None:
    monkeypatch.setattr(
        "custom_components.yolocal.coordinator.dt_util.utcnow", lambda: now
    )
    monkeypatch.setattr(
        "custom_components.yolocal.coordinator.monotonic", lambda: now.timestamp()
    )


def hub_time(payload: dict) -> datetime:
    return datetime.fromtimestamp(payload["time"] / 1000, UTC)


def deliver(coordinator, monkeypatch, payload: dict, delay: timedelta) -> None:
    """Receive an MQTT payload ``delay`` after the hub stamped it."""
    set_now(monkeypatch, hub_time(payload) + delay)
    coordinator._on_device_event(DeviceEvent.from_payload(payload))


def replay(coordinator, monkeypatch, name: str) -> None:
    capture = load(name)
    set_now(monkeypatch, datetime.fromisoformat(capture["captured_at"]))
    coordinator._on_device_event(DeviceEvent.from_payload(capture["mqtt_payload"]))


def fired(coordinator) -> list[tuple[str, dict]]:
    return [call.args for call in coordinator.hass.bus.async_fire.call_args_list]


def fired_types(coordinator) -> list[str]:
    return [data["type"] for event_type, data in fired(coordinator) if event_type == EVENT_BUTTON]


def test_captured_presses_fire_cloud_compatible_events(monkeypatch) -> None:
    coordinator = make_coordinator()
    for name in PRESS_CAPTURES:
        replay(coordinator, monkeypatch, name)

    assert fired(coordinator) == [
        (
            EVENT_BUTTON,
            {
                "device_id": HA_DEVICE_ID,
                "type": trigger_type,
                "yolink_device_id": DEVICE.device_id,
            },
        )
        for trigger_type in PRESS_CAPTURES.values()
    ]


def test_press_still_updates_device_state(monkeypatch) -> None:
    coordinator = make_coordinator()
    replay(coordinator, monkeypatch, "mqtt_0001.json")

    state = coordinator.get_state(DEVICE.device_id)
    assert state["online"] is True
    assert state["state"]["battery"] == 4
    assert state["state"]["version"] == "1404"


def test_same_packet_from_both_hub_interfaces_fires_once(monkeypatch) -> None:
    coordinator = make_coordinator()
    payload = load("mqtt_0001.json")["mqtt_payload"]
    deliver(coordinator, monkeypatch, copy.deepcopy(payload), timedelta(seconds=0.1))
    deliver(coordinator, monkeypatch, copy.deepcopy(payload), timedelta(seconds=0.2))

    assert fired_types(coordinator) == ["button_1_short_press"]


def test_repeated_presses_of_one_button_each_fire(monkeypatch) -> None:
    coordinator = make_coordinator()
    first = load("mqtt_0001.json")["mqtt_payload"]
    second = copy.deepcopy(first)
    second["msgid"] = str(int(first["msgid"]) + 3000)
    second["time"] = first["time"] + 3000
    deliver(coordinator, monkeypatch, first, timedelta(seconds=0.1))
    deliver(coordinator, monkeypatch, second, timedelta(seconds=0.1))

    assert fired_types(coordinator) == ["button_1_short_press"] * 2


def test_press_replayed_after_restart_does_not_fire(monkeypatch) -> None:
    first = make_coordinator()
    replay(first, monkeypatch, "mqtt_0001.json")
    assert fired_types(first) == ["button_1_short_press"]

    restarted = make_coordinator(first._contact_store.data)
    payload = load("mqtt_0001.json")["mqtt_payload"]
    deliver(restarted, monkeypatch, payload, timedelta(seconds=30))

    assert fired_types(restarted) == []


@pytest.mark.parametrize(
    ("delay", "expected"),
    [
        (timedelta(seconds=59), ["button_2_long_press"]),
        (timedelta(seconds=61), []),
        (timedelta(minutes=20), []),
        # The hub clock running ahead of Home Assistant's is not lateness.
        (timedelta(seconds=-30), ["button_2_long_press"]),
    ],
)
def test_late_presses_are_dropped(monkeypatch, delay, expected) -> None:
    coordinator = make_coordinator()
    payload = load("mqtt_0004.json")["mqtt_payload"]
    deliver(coordinator, monkeypatch, payload, delay)

    assert fired_types(coordinator) == expected
    # A dropped press is still contact from the device.
    assert coordinator.get_state(DEVICE.device_id)["state"]["battery"] == 4


def test_polled_state_never_fires_a_press(monkeypatch) -> None:
    coordinator = make_coordinator()
    get_state = load("http_initial.json")["response"]["data"]
    assert get_state["state"]["event"] == {"keyMask": 1, "type": "Press"}

    async def get_state_with_retry(_device):
        return copy.deepcopy(get_state)

    coordinator._async_get_state_with_retry = get_state_with_retry
    set_now(monkeypatch, datetime(2026, 11, 22, 22, 51, 28, tzinfo=UTC))
    asyncio.run(coordinator._async_update_data())

    assert fired_types(coordinator) == []


def test_captured_check_in_is_not_a_press(monkeypatch) -> None:
    coordinator = make_coordinator()
    entities = button_entities(coordinator)
    check_in = load("mqtt_0005.json")
    assert check_in["mqtt_payload"]["event"] == "SmartRemoter.Report"
    assert check_in["mqtt_payload"]["data"]["event"] == {"keyMask": 2, "type": "Press"}

    replay(coordinator, monkeypatch, "mqtt_0005.json")
    deliver_fired_events(coordinator, entities)

    assert fired_types(coordinator) == []
    assert [e.last_event_type for e in entities] == [None, None]
    # The check-in is still contact from the device.
    state = coordinator.get_state(DEVICE.device_id)
    assert state["online"] is True
    assert state["state"]["devTemperature"] == 13


def test_check_in_between_presses_fires_nothing_extra(monkeypatch) -> None:
    coordinator = make_coordinator()
    replay(coordinator, monkeypatch, "mqtt_0002.json")
    replay(coordinator, monkeypatch, "mqtt_0005.json")

    assert fired_types(coordinator) == ["button_2_short_press"]


def test_only_status_change_reports_are_presses(monkeypatch) -> None:
    coordinator = make_coordinator()
    payload = load("mqtt_0001.json")["mqtt_payload"]
    payload["event"] = "SmartRemoter.Report"
    deliver(coordinator, monkeypatch, payload, timedelta(seconds=0.1))

    assert fired_types(coordinator) == []


def test_unregistered_device_does_not_fire(monkeypatch, registered_fob) -> None:
    registered_fob.devices.clear()
    coordinator = make_coordinator()
    replay(coordinator, monkeypatch, "mqtt_0001.json")

    assert fired_types(coordinator) == []


@pytest.mark.parametrize(
    ("press", "expected"),
    [
        ({"keyMask": 1, "type": "Press"}, ["button_1_short_press"]),
        ({"keyMask": 2, "type": "LongPress"}, ["button_2_long_press"]),
        ({"keyMask": 4, "type": "Press"}, ["button_3_short_press"]),
        ({"keyMask": 8, "type": "Press"}, ["button_4_short_press"]),
        (
            {"keyMask": 3, "type": "Press"},
            ["button_1_short_press", "button_2_short_press"],
        ),
        ({"keyMask": 0, "type": "Press"}, []),
        ({"keyMask": True, "type": "Press"}, []),
        ({"keyMask": "1", "type": "Press"}, []),
        ({"type": "Press"}, []),
        ({"keyMask": 1, "type": "DoublePress"}, []),
        ({"keyMask": 1}, []),
    ],
)
def test_key_mask_decoding(press, expected) -> None:
    assert smart_remoter_trigger_types({"event": press}) == expected


def test_key_mask_decoding_ignores_missing_event() -> None:
    assert smart_remoter_trigger_types({"battery": 4}) == []
    assert smart_remoter_trigger_types({"event": "Press"}) == []


def trigger_hass(*devices: Device) -> SimpleNamespace:
    coordinator = SimpleNamespace(devices={d.device_id: d for d in devices})
    return SimpleNamespace(data={DOMAIN: {"entry": coordinator}})


def get_triggers(hass, device_id: str = HA_DEVICE_ID) -> list[dict]:
    return asyncio.run(device_trigger.async_get_triggers(hass, device_id))


def test_mini_flexfob_offers_two_buttons() -> None:
    triggers = get_triggers(trigger_hass(DEVICE))

    assert triggers == [
        {"device_id": HA_DEVICE_ID, "domain": DOMAIN, "platform": "device", "type": t}
        for t in (
            "button_1_short_press",
            "button_1_long_press",
            "button_2_short_press",
            "button_2_long_press",
        )
    ]


def test_unknown_remote_model_offers_four_buttons() -> None:
    remote = Device(DEVICE.device_id, "Fob", "token", "SmartRemoter", "SmartRemoter", None)

    types = [t["type"] for t in get_triggers(trigger_hass(remote))]

    assert types == device_trigger.TRIGGER_TYPES
    assert len(types) == 8


def test_other_devices_offer_no_triggers() -> None:
    sensor = Device(DEVICE.device_id, "Leak", "token", "LeakSensor", "LeakSensor", "YS7903-UC")

    assert get_triggers(trigger_hass(sensor)) == []
    assert get_triggers(trigger_hass(DEVICE), "not-a-device") == []
    assert get_triggers(SimpleNamespace(data={})) == []


def test_attach_trigger_listens_for_matching_button_event() -> None:
    event_trigger.attached.clear()
    config = {
        "platform": "device",
        "domain": DOMAIN,
        "device_id": HA_DEVICE_ID,
        "type": "button_2_long_press",
    }
    action = object()

    asyncio.run(device_trigger.async_attach_trigger(SimpleNamespace(), config, action, {}))

    assert event_trigger.attached == [
        {
            "config": {
                "platform": "event",
                "event_type": EVENT_BUTTON,
                "event_data": {"device_id": HA_DEVICE_ID, "type": "button_2_long_press"},
            },
            "action": action,
            "platform_type": "device",
        }
    ]


def test_fired_types_are_offered_triggers_with_labels(monkeypatch) -> None:
    coordinator = make_coordinator()
    for name in PRESS_CAPTURES:
        replay(coordinator, monkeypatch, name)
    offered = {t["type"] for t in get_triggers(trigger_hass(DEVICE))}
    assert set(fired_types(coordinator)) == offered

    integration = REPO / "custom_components/yolocal"
    for name in ("strings.json", "translations/en.json"):
        labels = json.loads((integration / name).read_text())["device_automation"][
            "trigger_type"
        ]
        assert sorted(labels) == sorted(device_trigger.TRIGGER_TYPES)


def button_entities(coordinator, device: Device = DEVICE) -> list:
    entities = event_platform.build_entities(coordinator, device)
    for entity in entities:
        entity.async_write_ha_state = Mock()
    return entities


def deliver_fired_events(coordinator, entities) -> None:
    """Hand each fired bus event to every listening button entity."""
    for event_type, data in fired(coordinator):
        if event_type == EVENT_BUTTON:
            for entity in entities:
                entity._handle_press(SimpleNamespace(data=data))


def test_mini_flexfob_gets_two_button_event_entities() -> None:
    entities = button_entities(make_coordinator())

    assert [(e.unique_id, e._attr_name) for e in entities] == [
        (f"{DEVICE.device_id}_button_1", "Button 1"),
        (f"{DEVICE.device_id}_button_2", "Button 2"),
    ]
    assert all(e._attr_event_types == ["short_press", "long_press"] for e in entities)
    assert all(e._attr_device_class == "button" for e in entities)


def test_event_entities_follow_model_and_type() -> None:
    coordinator = make_coordinator()
    unknown = Device(DEVICE.device_id, "Fob", "token", "SmartRemoter", "SmartRemoter", None)
    sensor = Device("Leak-1", "Leak", "token", "LeakSensor", "LeakSensor", "YS7903-UC")

    assert len(event_platform.build_entities(coordinator, unknown)) == 4
    assert event_platform.build_entities(coordinator, sensor) == []


def test_captured_presses_reach_the_matching_button_entity(monkeypatch) -> None:
    coordinator = make_coordinator()
    button_1, button_2 = button_entities(coordinator)

    replay(coordinator, monkeypatch, "mqtt_0004.json")
    deliver_fired_events(coordinator, [button_1, button_2])

    assert button_1.last_event_type is None
    button_1.async_write_ha_state.assert_not_called()
    assert button_2.last_event_type == "long_press"
    button_2.async_write_ha_state.assert_called_once()


def test_every_captured_press_reaches_an_entity_once(monkeypatch) -> None:
    coordinator = make_coordinator()
    entities = button_entities(coordinator)
    for name in PRESS_CAPTURES:
        replay(coordinator, monkeypatch, name)
    deliver_fired_events(coordinator, entities)

    assert [e.async_write_ha_state.call_count for e in entities] == [2, 2]
    assert [e.last_event_type for e in entities] == ["long_press", "long_press"]


@pytest.mark.parametrize(
    "data",
    [
        {"yolink_device_id": "other-fob", "type": "button_1_short_press"},
        {"yolink_device_id": DEVICE.device_id, "type": "button_2_short_press"},
        {"yolink_device_id": DEVICE.device_id, "type": "button_1_double_press"},
        {"yolink_device_id": DEVICE.device_id},
        {"type": "button_1_short_press"},
    ],
)
def test_button_entity_ignores_other_presses(data) -> None:
    button_1, _ = button_entities(make_coordinator())

    button_1._handle_press(SimpleNamespace(data=data))

    assert button_1.last_event_type is None
    button_1.async_write_ha_state.assert_not_called()


def test_button_entity_ignores_the_contact_timeout(monkeypatch) -> None:
    coordinator = make_coordinator()
    button_1, _ = button_entities(coordinator)
    coordinator._states[DEVICE.device_id] = {
        "online": True,
        "reportAt": "2026-11-22T22:51:44.581Z",
        "state": {"battery": 4},
    }
    monkeypatch.setattr(
        "custom_components.yolocal.entity.dt_util.utcnow",
        lambda: datetime(2026, 11, 24, tzinfo=UTC),
    )

    # Silent for over a day: other entities of the fob go unavailable.
    assert YoLocalEntity.available.fget(button_1) is False
    assert button_1.available is True

    coordinator.last_update_success = False
    assert button_1.available is False
