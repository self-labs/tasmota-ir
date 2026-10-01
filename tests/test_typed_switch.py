"""The on and off type, and the base every typed appliance shares."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    async_fire_mqtt_message,
    mock_restore_cache,
)

from .conftest import TOPIC, board_entry, receive, setup_board
from .typed_util import code, sent, typed

ON = code("0x10EF0001")
OFF = code("0x10EF0002")
TOGGLE = code("0x10EF0003")
PAIR = typed("switch", "Tomada IR", "swkey", {"power_on": ON, "power_off": OFF})
ONE_KEY = typed("switch", "Tomada IR", "swkey", {"power": TOGGLE})


async def _call(hass: HomeAssistant, service: str) -> None:
    await hass.services.async_call(
        "switch", service, {"entity_id": "switch.tomada_ir"}, blocking=True
    )


async def test_the_board_knows_the_new_kinds(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await setup_board(hass, board_entry(subentries_data=(PAIR,)))
    assert entry.runtime_data.appliances["swkey"].kind == "switch"


async def test_a_pair_sends_on_and_off(hass: HomeAssistant, mqtt_mock) -> None:
    await setup_board(hass, board_entry(subentries_data=(PAIR,)))
    await _call(hass, "turn_on")
    await _call(hass, "turn_off")
    assert sent(mqtt_mock) == [ON["Data"], OFF["Data"]]
    assert hass.states.get("switch.tomada_ir").state == "off"


async def test_a_toggle_only_presses_when_needed(
    hass: HomeAssistant, mqtt_mock
) -> None:
    await setup_board(hass, board_entry(subentries_data=(ONE_KEY,)))
    await _call(hass, "turn_on")
    await _call(hass, "turn_on")
    await _call(hass, "turn_off")
    assert sent(mqtt_mock) == [TOGGLE["Data"], TOGGLE["Data"]]


async def test_a_binary_sensor_decides(hass: HomeAssistant, mqtt_mock) -> None:
    hass.states.async_set("binary_sensor.tomada", "on")
    await setup_board(
        hass,
        board_entry(
            subentries_data=(
                typed(
                    "switch",
                    "Tomada IR",
                    "swkey",
                    {"power": TOGGLE},
                    power_sensor="binary_sensor.tomada",
                ),
            )
        ),
    )
    assert hass.states.get("switch.tomada_ir").state == "on"
    await _call(hass, "turn_on")
    assert sent(mqtt_mock) == []
    await _call(hass, "turn_off")
    assert sent(mqtt_mock) == [TOGGLE["Data"]]

    hass.states.async_set("binary_sensor.tomada", "off")
    await hass.async_block_till_done()
    assert hass.states.get("switch.tomada_ir").state == "off"


async def test_a_power_meter_with_a_threshold(hass: HomeAssistant, mqtt_mock) -> None:
    hass.states.async_set("sensor.tomada_potencia", "12.5")
    await setup_board(
        hass,
        board_entry(
            subentries_data=(
                typed(
                    "switch",
                    "Tomada IR",
                    "swkey",
                    {"power": TOGGLE},
                    power_sensor="sensor.tomada_potencia",
                    power_threshold=5,
                ),
            )
        ),
    )
    assert hass.states.get("switch.tomada_ir").state == "on"
    hass.states.async_set("sensor.tomada_potencia", "1.0")
    await hass.async_block_till_done()
    assert hass.states.get("switch.tomada_ir").state == "off"


async def test_an_unavailable_sensor_falls_back_to_assumed(
    hass: HomeAssistant, mqtt_mock
) -> None:
    hass.states.async_set("binary_sensor.tomada", "unavailable")
    await setup_board(
        hass,
        board_entry(
            subentries_data=(
                typed(
                    "switch",
                    "Tomada IR",
                    "swkey",
                    {"power": TOGGLE},
                    power_sensor="binary_sensor.tomada",
                ),
            )
        ),
    )
    await _call(hass, "turn_on")
    assert sent(mqtt_mock) == [TOGGLE["Data"]]
    assert hass.states.get("switch.tomada_ir").state == "on"


async def test_the_remote_moves_it(hass: HomeAssistant, mqtt_mock) -> None:
    await setup_board(hass, board_entry(subentries_data=(PAIR,)))
    receive(hass, ON)
    await hass.async_block_till_done()
    assert hass.states.get("switch.tomada_ir").state == "on"
    receive(hass, OFF)
    await hass.async_block_till_done()
    assert hass.states.get("switch.tomada_ir").state == "off"


async def test_a_heard_toggle_flips_it(hass: HomeAssistant, mqtt_mock) -> None:
    await setup_board(hass, board_entry(subentries_data=(ONE_KEY,)))
    receive(hass, TOGGLE)
    await hass.async_block_till_done()
    assert hass.states.get("switch.tomada_ir").state == "on"


async def test_an_offline_board_sends_nothing(hass: HomeAssistant, mqtt_mock) -> None:
    """Home Assistant skips a service on an unavailable entity, and it is one."""
    await setup_board(hass, board_entry(subentries_data=(PAIR,)))
    async_fire_mqtt_message(hass, f"tele/{TOPIC}/LWT", "Offline")
    await hass.async_block_till_done()
    assert hass.states.get("switch.tomada_ir").state == "unavailable"
    await _call(hass, "turn_on")
    assert sent(mqtt_mock) == []


async def test_a_press_on_an_offline_board_is_an_error(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """Called directly, not through a service, the press itself refuses."""
    entry = await setup_board(hass, board_entry(subentries_data=(PAIR,)))
    async_fire_mqtt_message(hass, f"tele/{TOPIC}/LWT", "Offline")
    await hass.async_block_till_done()
    entity = hass.data["entity_components"]["switch"].get_entity("switch.tomada_ir")
    with pytest.raises(HomeAssistantError, match="offline"):
        await entity._press("power_on")
    assert sent(mqtt_mock) == []
    assert entry.runtime_data.available is False


async def test_the_state_survives_a_restart(hass: HomeAssistant, mqtt_mock) -> None:
    mock_restore_cache(hass, [State("switch.tomada_ir", "on")])
    await setup_board(hass, board_entry(subentries_data=(PAIR,)))
    assert hass.states.get("switch.tomada_ir").state == "on"


async def test_a_sensor_outage_keeps_the_last_reading(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """The sensor said on, then went quiet: on is still the best guess."""
    hass.states.async_set("binary_sensor.tomada", "on")
    await setup_board(
        hass,
        board_entry(
            subentries_data=(
                typed(
                    "switch",
                    "Tomada IR",
                    "swkey",
                    {"power": TOGGLE},
                    power_sensor="binary_sensor.tomada",
                ),
            )
        ),
    )
    hass.states.async_set("binary_sensor.tomada", "unavailable")
    await hass.async_block_till_done()

    assert hass.states.get("switch.tomada_ir").state == "on"
    await _call(hass, "turn_on")
    assert sent(mqtt_mock) == []
