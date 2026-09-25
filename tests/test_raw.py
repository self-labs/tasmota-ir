"""Raw codes on the emitter they belong to, and on firmware that cannot do it."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_mqtt_message

from custom_components.tasmota_ir import coordinator as coordinator_module

from .conftest import TOPIC, board_entry, setup_board

RAW = "+8570-4240+550-1580C-510+565-1565F-505Fh"
RAW_CODE = {"Protocol": "RAW", "RawData": RAW, "Frequency": 38000}
IRSEND = f"cmnd/{TOPIC}/IRSend"
DONE = {"IRSend": "Done"}
# What a firmware without arendst/Tasmota#25062 answers to raw data as JSON.
WRONG = {"IRSend": "Wrong Protocol (NEC,SONY,RC5)"}


class Board:
    """The board's side of IRSend: records what arrives, answers JSON with ``reply``."""

    def __init__(
        self, hass: HomeAssistant, mqtt_client_mock, reply: dict[str, Any] | None
    ) -> None:
        self.sent: list[str] = []
        self.reply = reply
        original = mqtt_client_mock.publish.side_effect

        def _publish(topic, payload=None, qos=0, retain=False, *args, **kwargs):
            text = payload.decode() if isinstance(payload, bytes) else (payload or "")
            if topic == IRSEND:
                self.sent.append(text)
                if self.reply is not None and text.startswith("{"):
                    hass.loop.call_soon(
                        async_fire_mqtt_message,
                        hass,
                        f"stat/{TOPIC}/RESULT",
                        json.dumps(self.reply),
                    )
            return original(topic, payload, qos, retain, *args, **kwargs)

        mqtt_client_mock.publish.side_effect = _publish


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
