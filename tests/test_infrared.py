"""Home Assistant's own infrared integrations, through an appliance of a board."""

from __future__ import annotations

import json

import pytest
from homeassistant.components.infrared import (
    InfraredCommand,
    async_send_command,
    async_subscribe_receiver,
)
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from infrared_protocols.commands.nec import NECCommand
from pytest_homeassistant_custom_component.common import async_fire_mqtt_message

from custom_components.tasmota_ir import coordinator as coordinator_module
from custom_components.tasmota_ir import platforms_for
from custom_components.tasmota_ir.raw_timings import decode_compact

from .conftest import (
    BOARD_DATA,
    DONE,
    NEC_POWER,
    TOPIC,
    WRONG,
    Board,
    board_entry,
    receive,
    setup_board,
)

TV = {
    "data": {"channel": 1},
    "subentry_type": "appliance",
    "title": "TV Quarto",
    "unique_id": "tvkey",
}
SOUNDBAR = {
    "data": {"channel": 3},
    "subentry_type": "appliance",
    "title": "JBL Soundbar",
    "unique_id": "jblkey",
}
AC = {
    "data": {
        "channel": 2,
        "vendor": "LG2",
        "model": "AKB74955603",
        "light": "On",
        "min_temp": 18,
        "max_temp": 30,
        "hvac_modes": ["off", "cool"],
        "swing_vertical": True,
        "swing_horizontal": False,
        "initial_swing_vertical": "Off",
    },
    "subentry_type": "climate",
    "title": "Ar Escritorio",
    "unique_id": "ackey",
}

# What Home Assistant's LG Infrared sends for the TV's power key.
LG_POWER = NECCommand(address=0xFB04, command=0x08, modulation=38000)
LG_POWER_RAW = (
    "+9000-4500+562cCcC-1687CcCcCcCcCcCdCdCcCdCdCdCdCdCcCcCcCdCcCcCcCcCdCdCdCcCdCdCdCdC"
)


class Timings(InfraredCommand):
    """A command made of whatever timings a test needs."""

    def __init__(self, timings: list[int], modulation: int = 38000) -> None:
        super().__init__(modulation=modulation)
        self._timings = timings

    def get_raw_timings(self) -> list[int]:
        return list(self._timings)


def test_older_home_assistant_gets_no_infrared_entities() -> None:
    assert "infrared" not in platforms_for("2026.5.3")
    assert "infrared" in platforms_for("2026.6.0")
    assert "infrared" in platforms_for("2026.10.0.dev20261001")


async def test_each_appliance_gets_an_emitter_and_a_receiver(
    hass: HomeAssistant, mqtt_mock, entity_registry: er.EntityRegistry
) -> None:
    await setup_board(hass, board_entry(subentries_data=(TV, AC)))

    emitter = entity_registry.async_get_entity_id(
        "infrared", "tasmota_ir", "tvkey_infrared"
    )
    receiver = entity_registry.async_get_entity_id(
        "infrared", "tasmota_ir", "tvkey_infrared_receiver"
    )
    assert emitter == "infrared.tv_quarto"
    assert receiver == "infrared.tv_quarto_infrared_receiver"
    assert hass.states.get(emitter) is not None
    assert hass.states.get(receiver) is not None
    # The air conditioner has its climate; a second path would fight it.
    assert (
        entity_registry.async_get_entity_id("infrared", "tasmota_ir", "ackey_infrared")
        is None
    )
    assert (
        entity_registry.async_get_entity_id(
            "infrared", "tasmota_ir", "ackey_infrared_receiver"
        )
        is None
    )


async def test_no_receiver_on_a_board_without_irrecv(
    hass: HomeAssistant, mqtt_mock, entity_registry: er.EntityRegistry
) -> None:
    await setup_board(
        hass,
        board_entry(data={**BOARD_DATA, "has_receiver": False}, subentries_data=(TV,)),
    )
    assert hass.states.get("infrared.tv_quarto") is not None
    assert (
        entity_registry.async_get_entity_id(
            "infrared", "tasmota_ir", "tvkey_infrared_receiver"
        )
        is None
    )


async def test_emitter_one_sends_the_plain_form(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    board = Board(hass, mqtt_client_mock, DONE)

    await async_send_command(hass, "infrared.tv_quarto", LG_POWER)
    await hass.async_block_till_done()

    assert board.sent == [f"38000,{LG_POWER_RAW}"]
    assert entry.runtime_data.last_infrared["tvkey"] == (LG_POWER_RAW, 38000)
    assert hass.states.get("infrared.tv_quarto").state not in (
        "unknown",
        "unavailable",
    )


async def test_another_emitter_sends_json_with_its_channel(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    await setup_board(hass, board_entry(subentries_data=(SOUNDBAR,)))
    board = Board(hass, mqtt_client_mock, DONE)

    await async_send_command(hass, "infrared.jbl_soundbar", LG_POWER)
    await hass.async_block_till_done()

    assert [json.loads(text) for text in board.sent] == [
        {"RawData": LG_POWER_RAW, "Frequency": 38000, "Channel": 3}
    ]


async def test_an_older_firmware_fails_instead_of_using_emitter_one(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    await setup_board(hass, board_entry(subentries_data=(SOUNDBAR,)))
    board = Board(hass, mqtt_client_mock, WRONG)

    with pytest.raises(HomeAssistantError, match="15.6.0"):
        await async_send_command(hass, "infrared.jbl_soundbar", LG_POWER)
    await hass.async_block_till_done()

    assert len(board.sent) == 1
    assert board.sent[0].startswith("{")


async def test_an_offline_board_refuses_to_send(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    await setup_board(hass, board_entry(subentries_data=(TV,)))
    board = Board(hass, mqtt_client_mock, DONE)
    async_fire_mqtt_message(hass, f"tele/{TOPIC}/LWT", "Offline")
    await hass.async_block_till_done()
    assert hass.states.get("infrared.tv_quarto").state == "unavailable"

    with pytest.raises(HomeAssistantError, match="offline"):
        await async_send_command(hass, "infrared.tv_quarto", LG_POWER)
    await hass.async_block_till_done()

    assert board.sent == []


async def test_no_carrier_means_38_khz(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    await setup_board(hass, board_entry(subentries_data=(TV,)))
    board = Board(hass, mqtt_client_mock, DONE)

    await async_send_command(
        hass, "infrared.tv_quarto", Timings([9000, -4500, 560], modulation=0)
    )
    await hass.async_block_till_done()

    assert board.sent == ["38000,+9000-4500+560"]


async def test_an_empty_or_huge_command_is_an_error(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    await setup_board(hass, board_entry(subentries_data=(TV,)))
    board = Board(hass, mqtt_client_mock, DONE)
    huge = [v for k in range(300) for v in (1000 + k, -(3000 + k))]

    with pytest.raises(HomeAssistantError):
        await async_send_command(hass, "infrared.tv_quarto", Timings([]))
    with pytest.raises(HomeAssistantError, match="bytes"):
        await async_send_command(hass, "infrared.tv_quarto", Timings(huge))
    await hass.async_block_till_done()

    assert board.sent == []


async def test_the_receivers_relay_what_the_board_hears(
    hass: HomeAssistant, mqtt_mock
) -> None:
    await setup_board(hass, board_entry(subentries_data=(TV, SOUNDBAR)))
    tv: list = []
    jbl: list = []
    async_subscribe_receiver(hass, "infrared.tv_quarto_infrared_receiver", tv.append)
    async_subscribe_receiver(
        hass, "infrared.jbl_soundbar_infrared_receiver", jbl.append
    )

    receive(hass, {**NEC_POWER, "RawData": LG_POWER_RAW})
    await hass.async_block_till_done()

    expected = decode_compact(LG_POWER_RAW)
    assert [signal.timings for signal in tv] == [expected]
    assert [signal.timings for signal in jbl] == [expected]
    assert NECCommand.from_raw_timings(tv[0].timings).command == 0x08


async def _change_emitter(hass: HomeAssistant, entry, channel: str):
    """Open Manage appliance, pick Change the emitter, choose ``channel``."""
    (subentry,) = entry.subentries.values()
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "appliance"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    result = await manager.async_configure(
        result["flow_id"], {"next_step_id": "channel"}
    )
    return subentry, await manager.async_configure(
        result["flow_id"], {"channel": channel}
    )


async def test_changing_the_emitter_replays_the_last_command(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    """Nothing learned, but LG Infrared sent power: that is what gets tried."""
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    board = Board(hass, mqtt_client_mock, DONE)
    await async_send_command(hass, "infrared.tv_quarto", LG_POWER)
    await hass.async_block_till_done()

    subentry, result = await _change_emitter(hass, entry, "2")

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "channel_test_replay"
    assert json.loads(board.sent[-1]) == {
        "RawData": LG_POWER_RAW,
        "Frequency": 38000,
        "Channel": 2,
    }
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "channel_save"}
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    assert entry.subentries[subentry.subentry_id].data["channel"] == 2


async def test_a_replay_the_firmware_cannot_send_is_a_form_error(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    board = Board(hass, mqtt_client_mock, WRONG)
    await async_send_command(hass, "infrared.tv_quarto", LG_POWER)
    await hass.async_block_till_done()

    _, result = await _change_emitter(hass, entry, "2")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "channel"
    assert result["errors"] == {"channel": "raw_channel"}
    assert len(board.sent) == 2  # the plain send on emitter 1, then the JSON try


async def test_nothing_to_replay_saves_directly(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    """Right after a restart there is nothing to try, as before this feature."""
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    board = Board(hass, mqtt_client_mock, DONE)

    subentry, result = await _change_emitter(hass, entry, "4")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.subentries[subentry.subentry_id].data["channel"] == 4
    assert board.sent == []


async def test_the_receiver_is_named_on_every_release(
    hass: HomeAssistant,
    mqtt_mock,
    entity_registry: er.EntityRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Home Assistant 2026.6 and 2026.7 do not name a receiver by its class.

    That override arrived in 2026.8. Without a name of its own, the receiver
    became infrared.tv_quarto_2, called "TV Quarto" like the emitter.
    """
    from homeassistant.components.infrared import InfraredReceiverEntity

    monkeypatch.setattr(
        InfraredReceiverEntity, "_default_to_device_class_name", lambda self: False
    )
    await setup_board(hass, board_entry(subentries_data=(TV,)))

    assert (
        entity_registry.async_get_entity_id(
            "infrared", "tasmota_ir", "tvkey_infrared_receiver"
        )
        == "infrared.tv_quarto_infrared_receiver"
    )


async def test_a_replay_the_board_does_not_confirm_is_its_own_error(
    hass: HomeAssistant,
    mqtt_mock,
    mqtt_client_mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No answer is not an old firmware, and must not say so."""
    monkeypatch.setattr(coordinator_module, "RAW_REPLY_TIMEOUT", 0.05)
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    board = Board(hass, mqtt_client_mock, None)
    await async_send_command(hass, "infrared.tv_quarto", LG_POWER)
    await hass.async_block_till_done()

    _, result = await _change_emitter(hass, entry, "2")

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"channel": "not_confirmed"}
    assert len(board.sent) == 2


async def test_a_replay_on_an_offline_board_is_an_error(
    hass: HomeAssistant, mqtt_mock, mqtt_client_mock
) -> None:
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    board = Board(hass, mqtt_client_mock, DONE)
    await async_send_command(hass, "infrared.tv_quarto", LG_POWER)
    await hass.async_block_till_done()
    async_fire_mqtt_message(hass, f"tele/{TOPIC}/LWT", "Offline")
    await hass.async_block_till_done()

    _, result = await _change_emitter(hass, entry, "2")

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"channel": "board_offline"}
    assert len(board.sent) == 1
