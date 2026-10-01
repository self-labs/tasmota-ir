"""Fan, with a key per speed or one key that cycles."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import (
    mock_restore_cache_with_extra_data,
)

from .conftest import board_entry, receive, setup_board
from .typed_util import code, sent, typed

P, S1, S2, S3 = (
    code("0x30CF0001"),
    code("0x30CF0002"),
    code("0x30CF0003"),
    code("0x30CF0004"),
)
SC, OS, NA = code("0x30CF0005"), code("0x30CF0006"), code("0x30CF0007")
LISTED = typed(
    "fan",
    "Ventilador",
    "fankey",
    {
        "power": P,
        "speeds": {"1": S1, "2": S2, "3": S3},
        "oscillate": OS,
        "presets": {"Natural": NA},
    },
)
CYCLING = typed(
    "fan", "Ventilador", "fankey", {"power": P, "speed_cycle": SC}, speed_count=3
)
E = "fan.ventilador"


async def _call(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(
        "fan", service, {"entity_id": E, **data}, blocking=True
    )


async def test_a_key_per_speed(hass: HomeAssistant, mqtt_mock, no_delay) -> None:
    await setup_board(hass, board_entry(subentries_data=(LISTED,)))
    await _call(hass, "turn_on")
    await _call(hass, "set_percentage", percentage=66)
    assert sent(mqtt_mock) == [P["Data"], S2["Data"]]
    state = hass.states.get(E)
    assert state.attributes["percentage"] == 66
    assert state.attributes["percentage_step"] == 100 / 3


async def test_a_cycling_key_presses_the_difference(
    hass: HomeAssistant, mqtt_mock, no_delay
) -> None:
    await setup_board(hass, board_entry(subentries_data=(CYCLING,)))
    await _call(hass, "turn_on")
    await _call(hass, "set_percentage", percentage=100)
    await _call(hass, "set_percentage", percentage=33)
    assert sent(mqtt_mock) == [P["Data"], SC["Data"], SC["Data"], SC["Data"]]


async def test_the_same_speed_presses_nothing(
    hass: HomeAssistant, mqtt_mock, no_delay
) -> None:
    await setup_board(hass, board_entry(subentries_data=(CYCLING,)))
    await _call(hass, "turn_on")
    await _call(hass, "set_percentage", percentage=33)
    assert sent(mqtt_mock) == [P["Data"]]


async def test_oscillate_and_presets(hass: HomeAssistant, mqtt_mock, no_delay) -> None:
    await setup_board(hass, board_entry(subentries_data=(LISTED,)))
    await _call(hass, "turn_on")
    await _call(hass, "oscillate", oscillating=True)
    await _call(hass, "set_preset_mode", preset_mode="Natural")
    assert sent(mqtt_mock) == [P["Data"], OS["Data"], NA["Data"]]
    state = hass.states.get(E)
    assert state.attributes["oscillating"] is True
    assert state.attributes["preset_mode"] == "Natural"


async def test_zero_percent_turns_it_off(
    hass: HomeAssistant, mqtt_mock, no_delay
) -> None:
    await setup_board(hass, board_entry(subentries_data=(LISTED,)))
    await _call(hass, "turn_on")
    await _call(hass, "set_percentage", percentage=0)
    assert sent(mqtt_mock) == [P["Data"], P["Data"]]
    assert hass.states.get(E).state == "off"


async def test_the_remote_sets_the_speed(hass: HomeAssistant, mqtt_mock) -> None:
    await setup_board(hass, board_entry(subentries_data=(LISTED,)))
    receive(hass, P)
    receive(hass, S3)
    await hass.async_block_till_done()
    assert hass.states.get(E).attributes["percentage"] == 100


async def test_on_with_a_speed_presses_power_once(
    hass: HomeAssistant, mqtt_mock, no_delay
) -> None:
    """The sensor has not seen the fan start yet; power must not go twice."""
    hass.states.async_set("binary_sensor.ventilador", "off")
    sensed = typed(
        "fan",
        "Ventilador",
        "fankey",
        {"power": P, "speeds": {"1": S1, "2": S2, "3": S3}},
        power_sensor="binary_sensor.ventilador",
    )
    await setup_board(hass, board_entry(subentries_data=(sensed,)))
    await _call(hass, "turn_on", percentage=66)
    assert sent(mqtt_mock) == [P["Data"], S2["Data"]]


async def test_the_speed_survives_a_restart_while_off(
    hass: HomeAssistant, mqtt_mock, no_delay
) -> None:
    """Home Assistant drops the percentage of a fan that is off."""
    mock_restore_cache_with_extra_data(
        hass, [(State(E, "off"), {"assumed_on": False, "speed": 3})]
    )
    await setup_board(hass, board_entry(subentries_data=(CYCLING,)))
    await _call(hass, "turn_on")
    await _call(hass, "set_percentage", percentage=33)
    assert sent(mqtt_mock) == [P["Data"], SC["Data"]]
