"""Raw codes on the emitter they belong to, and on firmware that cannot do it."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import async_fire_mqtt_message

from custom_components.tasmota_ir import coordinator as coordinator_module
from custom_components.tasmota_ir.coordinator import (
    CodeTooLargeError,
    RawChannelError,
)

from .conftest import (
    DONE,
    NEC_POWER,
    TOPIC,
    WRONG,
    Board,
    board_entry,
    receive,
    setup_board,
)

RAW = "+8570-4240+550-1580C-510+565-1565F-505Fh"
RAW_CODE = {"Protocol": "RAW", "RawData": RAW, "Frequency": 38000}


async def test_emitter_one_keeps_the_plain_form(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    """Every firmware takes it, and it already leaves through emitter 1."""
    entry = await setup_board(hass, board_entry())
    board = Board(hass, mqtt_client_mock, DONE)

    await entry.runtime_data.async_send_code(RAW_CODE, channel=1)
    await hass.async_block_till_done()

    assert board.sent == [f"38000,{RAW}"]


async def test_a_firmware_that_can_gets_the_channel(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    """The first raw code asks, the answer is kept, the next one just goes."""
    entry = await setup_board(hass, board_entry())
    board = Board(hass, mqtt_client_mock, DONE)

    await entry.runtime_data.async_send_code(RAW_CODE, channel=3)
    await hass.async_block_till_done()
    assert len(board.sent) == 1
    assert json.loads(board.sent[0]) == {
        "RawData": RAW,
        "Frequency": 38000,
        "Channel": 3,
    }

    # No answer this time: a send that still waited for one would time out.
    board.reply = None
    async with asyncio.timeout(1):
        await entry.runtime_data.async_send_code(RAW_CODE, channel=5)
    await hass.async_block_till_done()
    assert len(board.sent) == 2
    assert json.loads(board.sent[1])["Channel"] == 5


async def test_an_older_firmware_falls_back_to_emitter_one(
    hass: HomeAssistant,
    mqtt_mock,
    mqtt_client_mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """It answers Wrong Protocol and sends nothing, so the plain form follows."""
    entry = await setup_board(hass, board_entry())
    board = Board(hass, mqtt_client_mock, WRONG)

    with caplog.at_level(logging.WARNING):
        await entry.runtime_data.async_send_code(RAW_CODE, channel=3)
        await hass.async_block_till_done()
    assert board.sent[0].startswith("{")
    assert board.sent[1] == f"38000,{RAW}"
    assert "#25062" in caplog.text

    # Known now: straight to the plain form, no second question.
    await entry.runtime_data.async_send_code(RAW_CODE, channel=3)
    await hass.async_block_till_done()
    assert board.sent[2:] == [f"38000,{RAW}"]


async def test_a_restart_asks_again(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    """Coming back online is when the firmware may have been updated."""
    entry = await setup_board(hass, board_entry())
    board = Board(hass, mqtt_client_mock, WRONG)
    await entry.runtime_data.async_send_code(RAW_CODE, channel=3)
    await hass.async_block_till_done()
    assert len(board.sent) == 2

    async_fire_mqtt_message(hass, f"tele/{TOPIC}/LWT", "Offline")
    async_fire_mqtt_message(hass, f"tele/{TOPIC}/LWT", "Online")
    await hass.async_block_till_done()

    board.reply = DONE
    await entry.runtime_data.async_send_code(RAW_CODE, channel=3)
    await hass.async_block_till_done()
    assert board.sent[2].startswith("{")
    assert len(board.sent) == 3


async def test_no_answer_sends_nothing_more(
    hass: HomeAssistant,
    mqtt_mock,
    mqtt_client_mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resending blind could fire the key twice, so nothing else goes out."""
    monkeypatch.setattr(coordinator_module, "RAW_REPLY_TIMEOUT", 0.05)
    entry = await setup_board(hass, board_entry())
    board = Board(hass, mqtt_client_mock, None)

    await entry.runtime_data.async_send_code(RAW_CODE, channel=3)
    await hass.async_block_till_done()

    assert len(board.sent) == 1
    assert board.sent[0].startswith("{")


async def test_without_fallback_emitter_one_is_the_plain_form(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    entry = await setup_board(hass, board_entry())
    board = Board(hass, mqtt_client_mock, DONE)

    await entry.runtime_data.async_send_compact(RAW, 38000, 1, fallback=False)
    await hass.async_block_till_done()

    assert board.sent == [f"38000,{RAW}"]


async def test_without_fallback_an_older_firmware_is_an_error(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    """Another integration asked for this emitter; emitter 1 would fail in silence."""
    entry = await setup_board(hass, board_entry())
    board = Board(hass, mqtt_client_mock, WRONG)

    with pytest.raises(RawChannelError, match="15.6.0"):
        await entry.runtime_data.async_send_compact(RAW, 38000, 3, fallback=False)
    await hass.async_block_till_done()
    assert len(board.sent) == 1
    assert board.sent[0].startswith("{")

    # Known now: refused straight away, and still nothing in the plain form.
    with pytest.raises(RawChannelError):
        await entry.runtime_data.async_send_compact(RAW, 38000, 3, fallback=False)
    await hass.async_block_till_done()
    assert len(board.sent) == 1


async def test_without_fallback_no_answer_is_an_error(
    hass: HomeAssistant,
    mqtt_mock,
    mqtt_client_mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(coordinator_module, "RAW_REPLY_TIMEOUT", 0.05)
    entry = await setup_board(hass, board_entry())
    board = Board(hass, mqtt_client_mock, None)

    with pytest.raises(HomeAssistantError, match="did not confirm"):
        await entry.runtime_data.async_send_compact(RAW, 38000, 3, fallback=False)
    await hass.async_block_till_done()
    assert len(board.sent) == 1


async def test_without_fallback_too_large_is_an_error(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    entry = await setup_board(hass, board_entry())
    board = Board(hass, mqtt_client_mock, DONE)
    big = "+1000" * 250

    with pytest.raises(CodeTooLargeError):
        await entry.runtime_data.async_send_compact(big, 38000, 3, fallback=False)
    with pytest.raises(CodeTooLargeError):
        await entry.runtime_data.async_send_compact(big, 38000, 1, fallback=False)
    await hass.async_block_till_done()
    assert board.sent == []


async def test_frames_reach_every_listener_decoded_once(
    hass: HomeAssistant, mqtt_mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = await setup_board(hass, board_entry())
    calls: list[str] = []
    real = coordinator_module.decode_compact

    def counting(raw: str) -> list[int]:
        calls.append(raw)
        return real(raw)

    monkeypatch.setattr(coordinator_module, "decode_compact", counting)
    got_a: list[list[int]] = []
    got_b: list[list[int]] = []
    entry.runtime_data.async_add_timings_listener(got_a.append)
    entry.runtime_data.async_add_timings_listener(got_b.append)

    receive(hass, {**NEC_POWER, "RawData": "+9000-4500+560c"})
    await hass.async_block_till_done()

    assert got_a == got_b == [[9000, -4500, 560, -560]]
    assert len(calls) == 1


async def test_frames_without_rawdata_warn_once(
    hass: HomeAssistant, mqtt_mock, caplog: pytest.LogCaptureFixture
) -> None:
    entry = await setup_board(hass, board_entry())
    got: list[list[int]] = []
    entry.runtime_data.async_add_timings_listener(got.append)

    with caplog.at_level(logging.WARNING):
        receive(hass, NEC_POWER)
        receive(hass, NEC_POWER)
        await hass.async_block_till_done()

    assert got == []
    assert caplog.text.count("SetOption58") == 1


async def test_no_listener_no_warning(
    hass: HomeAssistant, mqtt_mock, caplog: pytest.LogCaptureFixture
) -> None:
    """A board nobody listens to through infrared never nags about SetOption58."""
    await setup_board(hass, board_entry())
    with caplog.at_level(logging.WARNING):
        receive(hass, NEC_POWER)
        await hass.async_block_till_done()
    assert "SetOption58" not in caplog.text


async def test_garbage_rawdata_is_not_relayed(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await setup_board(hass, board_entry())
    got: list[list[int]] = []
    entry.runtime_data.async_add_timings_listener(got.append)

    receive(hass, {**NEC_POWER, "RawData": "+9000-4500Z"})
    await hass.async_block_till_done()

    assert got == []
    assert entry.runtime_data.available


async def test_a_removed_listener_hears_nothing(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await setup_board(hass, board_entry())
    got: list[list[int]] = []
    remove = entry.runtime_data.async_add_timings_listener(got.append)
    remove()

    receive(hass, {**NEC_POWER, "RawData": "+9000-4500+560c"})
    await hass.async_block_till_done()

    assert got == []
