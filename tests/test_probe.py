"""Asking a board what it has: emitters, receiver, and asking again at setup."""

from __future__ import annotations

import json
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_mqtt_message

from custom_components.tasmota_ir import coordinator as coordinator_module

from .conftest import BOARD_DATA, TOPIC, board_entry, setup_board

GPIO = f"cmnd/{TOPIC}/Gpio"
STAT = f"stat/{TOPIC}/RESULT"
TV = {
    "data": {"channel": 1},
    "subentry_type": "appliance",
    "title": "TV Quarto",
    "unique_id": "tvkey",
}

# What an AG8 with the KinCony template answers to Gpio 255, trimmed to the
# pins that matter: eight emitters and the receiver.
AG8_GPIOS: dict[str, Any] = {
    "GPIO0": {"None": 0},
    "GPIO9": {"IRsend1": 1056},
    "GPIO10": {"IRsend2": 1057},
    "GPIO11": {"IRsend3": 1058},
    "GPIO12": {"IRsend4": 1059},
    "GPIO13": {"IRsend5": 1060},
    "GPIO14": {"IRsend6": 1061},
    "GPIO21": {"IRsend7": 1062},
    "GPIO47": {"IRsend8": 1063},
    "GPIO48": {"IRrecv": 1088},
}


@pytest.fixture
def board_probe_at_setup() -> None:
    """The real setup probe, unlike every other test module."""


@pytest.fixture(autouse=True)
def fast_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ask again every 50 ms and give up after half a second."""
    monkeypatch.setattr(coordinator_module, "PROBE_RESEND", 0.05)
    monkeypatch.setattr(coordinator_module, "PROBE_TIMEOUT", 0.5)


class GpioBoard:
    """The board's side of Gpio: counts the questions, answers as told.

    ``answers`` is consumed one per question; None means the answer is lost on
    the way, as when it reaches the broker before Home Assistant subscribed.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        mqtt_client_mock,
        answers: list[dict[str, Any] | None],
    ) -> None:
        self.asked = 0
        self.answers = list(answers)
        original = mqtt_client_mock.publish.side_effect

        def _publish(topic, payload=None, qos=0, retain=False, *args, **kwargs):
            if topic == GPIO:
                self.asked += 1
                answer = self.answers.pop(0) if self.answers else None
                if answer is not None:
                    hass.loop.call_soon(
                        async_fire_mqtt_message, hass, STAT, json.dumps(answer)
                    )
            return original(topic, payload, qos, retain, *args, **kwargs)

        mqtt_client_mock.publish.side_effect = _publish


async def test_a_lost_answer_is_asked_again(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    """The first answer never arrives; the second question gets the board right."""
    entry = await setup_board(
        hass, board_entry(data={**BOARD_DATA, "channels": 1, "has_receiver": False})
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    board = GpioBoard(hass, mqtt_client_mock, [None, AG8_GPIOS])

    assert await entry.runtime_data.async_probe_channels() == (8, True)
    assert board.asked == 2


async def test_another_command_answer_is_not_the_board(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    """A reply to some other command on the same topic is skipped, not read as no IR."""
    entry = await setup_board(hass, board_entry())
    await hass.async_block_till_done(wait_background_tasks=True)
    board = GpioBoard(hass, mqtt_client_mock, [{"IRSend": "Done"}, AG8_GPIOS])

    assert await entry.runtime_data.async_probe_channels() == (8, True)
    assert board.asked == 2


async def test_a_silent_board_is_none(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    """No answer is no answer, never one emitter and no receiver."""
    entry = await setup_board(hass, board_entry())
    await hass.async_block_till_done(wait_background_tasks=True)
    board = GpioBoard(hass, mqtt_client_mock, [])

    assert await entry.runtime_data.async_probe_channels() is None
    assert board.asked > 1


async def test_setup_corrects_a_board_stored_without_its_emitters(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock, entity_registry
) -> None:
    """The entry the lost answer left behind gets the eight emitters and the receiver."""
    GpioBoard(hass, mqtt_client_mock, [None, AG8_GPIOS, AG8_GPIOS])
    entry = await setup_board(
        hass,
        board_entry(
            data={**BOARD_DATA, "channels": 1, "has_receiver": False},
            subentries_data=(TV,),
        ),
    )
    receiver = ("infrared", "tasmota_ir", "tvkey_infrared_receiver")
    assert entity_registry.async_get_entity_id(*receiver) is None

    await hass.async_block_till_done(wait_background_tasks=True)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.data["channels"] == 8
    assert entry.data["has_receiver"] is True
    # Reloaded with the receiver: the appliance's infrared receiver is up now.
    assert entity_registry.async_get_entity_id(*receiver) is not None


async def test_setup_leaves_the_entry_when_the_board_is_silent(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    """An offline board at setup keeps what was stored."""
    GpioBoard(hass, mqtt_client_mock, [])
    entry = await setup_board(hass, board_entry())
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.data["channels"] == 8
    assert entry.data["has_receiver"] is True
