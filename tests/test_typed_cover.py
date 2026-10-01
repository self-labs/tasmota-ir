"""Cover, with a position estimated from the travel time."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.cover import CoverEntityFeature as F
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import board_entry, receive, setup_board
from .typed_util import code, sent, typed

O, C, S = code("0x50AF0001"), code("0x50AF0002"), code("0x50AF0003")
TIMED = typed(
    "cover", "Tela", "covkey", {"open": O, "close": C, "stop": S}, travel_time=10
)
E = "cover.tela"


async def _call(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(
        "cover", service, {"entity_id": E, **data}, blocking=True
    )


async def test_open_close_and_stop(hass: HomeAssistant, mqtt_mock) -> None:
    await setup_board(hass, board_entry(subentries_data=(TIMED,)))
    await _call(hass, "open_cover")
    assert hass.states.get(E).state == "open"
    await _call(hass, "close_cover")
    await _call(hass, "stop_cover")
    assert sent(mqtt_mock) == [O["Data"], C["Data"], S["Data"]]


async def test_a_position_by_travel_time(hass: HomeAssistant, mqtt_mock) -> None:
    await setup_board(hass, board_entry(subentries_data=(TIMED,)))
    await _call(hass, "set_cover_position", position=50)
    assert sent(mqtt_mock) == [O["Data"]]
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert sent(mqtt_mock) == [O["Data"], S["Data"]]
    assert hass.states.get(E).attributes["current_position"] == 50


async def test_a_new_position_cancels_the_pending_stop(
    hass: HomeAssistant, mqtt_mock
) -> None:
    await setup_board(hass, board_entry(subentries_data=(TIMED,)))
    await _call(hass, "set_cover_position", position=80)
    # No time has passed: the cover is still near 0, so 20 is further open.
    await _call(hass, "set_cover_position", position=20)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
    await hass.async_block_till_done()
    assert sent(mqtt_mock) == [O["Data"], O["Data"], S["Data"]]
    assert hass.states.get(E).attributes["current_position"] == 20


async def test_no_position_without_stop_and_time(
    hass: HomeAssistant, mqtt_mock
) -> None:
    await setup_board(
        hass,
        board_entry(
            subentries_data=(
                typed("cover", "Tela", "covkey", {"open": O, "close": C, "stop": S}),
            )
        ),
    )
    assert not hass.states.get(E).attributes["supported_features"] & F.SET_POSITION


async def test_the_remote_opens_it(hass: HomeAssistant, mqtt_mock) -> None:
    await setup_board(hass, board_entry(subentries_data=(TIMED,)))
    receive(hass, O)
    await hass.async_block_till_done()
    assert hass.states.get(E).attributes["current_position"] == 100


async def test_the_remote_cancels_a_timed_move(hass: HomeAssistant, mqtt_mock) -> None:
    """Somebody opened it all the way by hand: no stop halfway after that."""
    await setup_board(hass, board_entry(subentries_data=(TIMED,)))
    await _call(hass, "set_cover_position", position=50)
    receive(hass, O)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
    await hass.async_block_till_done()
    assert sent(mqtt_mock) == [O["Data"]]
    assert hass.states.get(E).attributes["current_position"] == 100


async def test_an_interrupted_move_counts_from_where_it_is(
    hass: HomeAssistant, mqtt_mock, freezer
) -> None:
    """Three seconds into a 10 s run towards 80, the cover is near 30."""
    await setup_board(hass, board_entry(subentries_data=(TIMED,)))
    await _call(hass, "set_cover_position", position=80)
    freezer.tick(timedelta(seconds=3))
    await _call(hass, "stop_cover")
    assert hass.states.get(E).attributes["current_position"] == 30
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
    await hass.async_block_till_done()
    assert sent(mqtt_mock) == [O["Data"], S["Data"]]


async def test_the_ends_need_no_stop(hass: HomeAssistant, mqtt_mock) -> None:
    """All the way open is just open: the cover stops by itself there."""
    await setup_board(hass, board_entry(subentries_data=(TIMED,)))
    await _call(hass, "set_cover_position", position=100)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
    await hass.async_block_till_done()
    assert sent(mqtt_mock) == [O["Data"]]
