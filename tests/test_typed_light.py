"""Light, with brightness and colour temperature counted in steps."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import (
    mock_restore_cache_with_extra_data,
)

from .conftest import board_entry, setup_board
from .typed_util import code, sent, typed

P, BU, BD = code("0x40BF0001"), code("0x40BF0002"), code("0x40BF0003")
W, CO, NI = code("0x40BF0004"), code("0x40BF0005"), code("0x40BF0006")
DIMMABLE = typed(
    "light",
    "Luminaria",
    "litkey",
    {
        "power": P,
        "brightness_up": BU,
        "brightness_down": BD,
        "warmer": W,
        "cooler": CO,
        "effects": {"Noite": NI},
    },
    brightness_steps=4,
    color_temp_steps=4,
)
E = "light.luminaria"


async def _on(hass: HomeAssistant, **data) -> None:
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": E, **data}, blocking=True
    )


async def test_color_modes_follow_what_was_learned(
    hass: HomeAssistant, mqtt_mock
) -> None:
    await setup_board(
        hass,
        board_entry(
            subentries_data=(typed("light", "Luminaria", "litkey", {"power": P}),)
        ),
    )
    assert hass.states.get(E).attributes["supported_color_modes"] == ["onoff"]


async def test_brightness_presses_the_difference(
    hass: HomeAssistant, mqtt_mock, no_delay
) -> None:
    await setup_board(hass, board_entry(subentries_data=(DIMMABLE,)))
    await _on(hass)
    await _on(hass, brightness=128)
    assert sent(mqtt_mock) == [P["Data"], BD["Data"], BD["Data"]]
    assert hass.states.get(E).attributes["brightness"] == 128


async def test_the_lowest_brightness_is_one_step(
    hass: HomeAssistant, mqtt_mock, no_delay
) -> None:
    await setup_board(hass, board_entry(subentries_data=(DIMMABLE,)))
    await _on(hass)
    await _on(hass, brightness=1)
    assert sent(mqtt_mock) == [P["Data"], BD["Data"], BD["Data"], BD["Data"]]
    assert hass.states.get(E).attributes["brightness"] == 64


async def test_colour_temperature_in_steps(
    hass: HomeAssistant, mqtt_mock, no_delay
) -> None:
    await setup_board(hass, board_entry(subentries_data=(DIMMABLE,)))
    await _on(hass)
    await _on(hass, color_temp_kelvin=2700)
    assert sent(mqtt_mock) == [P["Data"], W["Data"], W["Data"]]
    assert hass.states.get(E).attributes["color_temp_kelvin"] == 2700


async def test_an_effect_sends_its_key(
    hass: HomeAssistant, mqtt_mock, no_delay
) -> None:
    await setup_board(hass, board_entry(subentries_data=(DIMMABLE,)))
    await _on(hass, effect="Noite")
    assert sent(mqtt_mock) == [P["Data"], NI["Data"]]
    assert hass.states.get(E).attributes["effect"] == "Noite"


async def test_the_level_survives_a_restart_while_off(
    hass: HomeAssistant, mqtt_mock, no_delay
) -> None:
    """Home Assistant drops the brightness of a light that is off."""
    mock_restore_cache_with_extra_data(
        hass,
        [(State(E, "off"), {"assumed_on": False, "level": 1, "ct_level": 0})],
    )
    await setup_board(hass, board_entry(subentries_data=(DIMMABLE,)))
    await _on(hass, brightness=255)
    assert sent(mqtt_mock) == [P["Data"], BU["Data"], BU["Data"], BU["Data"]]
