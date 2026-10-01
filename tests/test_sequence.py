"""Sequences: keys of several appliances of one board, pressed in order."""

from __future__ import annotations

import asyncio
import json

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_mqtt_message

from custom_components.tasmota_ir import sequence as sequence_module

from .conftest import NEC_POWER, TOPIC, board_entry, receive, setup_board
from .test_transfer import _two_boards
from .typed_util import code, sent, typed

HDMI = code("0x20DF0005")
SOUND_POWER = code("0x20DF00FF")
AC_CODE = {"Protocol": "LG2", "Bits": 28, "Data": "0x880084C"}

TV = {
    "data": {"channel": 1},
    "subentry_type": "appliance",
    "title": "TV Quarto",
    "unique_id": "tvkey",
}
JBL = typed(
    "media",
    "JBL Soundbar",
    "jblkey",
    {"power": SOUND_POWER, "sources": {"HDMI 1": HDMI}},
)
AC = {
    "data": {"channel": 2, "vendor": "LG2", "model": ""},
    "subentry_type": "climate",
    "title": "Ar Escritorio",
    "unique_id": "ackey",
}


def step(appliance: str, command: str, item: str | None = None, wait: float = 0):
    found = {"appliance": appliance, "command": command, "wait": wait}
    if item is not None:
        found["item"] = item
    return found


def seq(*steps, title: str = "Cinema", key: str = "seqkey"):
    return {
        "data": {"steps": list(steps)},
        "subentry_type": "sequence",
        "title": title,
        "unique_id": key,
    }


CINEMA = seq(
    step("tvkey", "power", wait=0.4),
    step("jblkey", "power", wait=8),
    step("jblkey", "sources", "HDMI 1"),
)
B = "button.cinema"


def choice(appliance: str, command: str, item: str | None = None) -> str:
    """The value the step selector gives a key."""
    return json.dumps([appliance, command, item])


def channels(mqtt_mock) -> list[int | None]:
    """The emitter of every IRSend published so far, in order."""
    return [
        json.loads(call.args[1]).get("Channel")
        for call in mqtt_mock.async_publish.call_args_list
        if call.args[0].endswith("/IRSend")
    ]


async def _board(hass: HomeAssistant, *subentries):
    entry = await setup_board(hass, board_entry(subentries_data=(TV, JBL, *subentries)))
    await entry.runtime_data.async_store_codes("tvkey", {"power": NEC_POWER})
    await hass.async_block_till_done()
    return entry


async def _press(hass: HomeAssistant, entity_id: str = B) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The pauses a sequence asked for, without sleeping through them."""
    asked: list[float] = []

    async def _sleep(seconds: float) -> None:
        asked.append(seconds)

    monkeypatch.setattr(sequence_module, "_sleep", _sleep)
    return asked


# ---- pressing ------------------------------------------------------------


async def test_the_steps_go_out_in_order_on_their_emitters(
    hass: HomeAssistant, mqtt_mock, waits
) -> None:
    await _board(hass, CINEMA)
    await _press(hass)
    assert sent(mqtt_mock) == [NEC_POWER["Data"], SOUND_POWER["Data"], HDMI["Data"]]
    assert channels(mqtt_mock)[1:] == [3, 3]
    # A wait after each step but the last.
    assert waits == [0.4, 8]


async def test_the_typed_state_follows_as_if_the_remote_was_used(
    hass: HomeAssistant, mqtt_mock, waits
) -> None:
    await _board(hass, CINEMA)
    assert hass.states.get("media_player.jbl_soundbar").state == "off"
    await _press(hass)
    state = hass.states.get("media_player.jbl_soundbar")
    assert state.state == "on"
    assert state.attributes["source"] == "HDMI 1"


async def test_a_step_that_is_gone_sends_nothing(
    hass: HomeAssistant, mqtt_mock, waits
) -> None:
    await _board(hass, seq(step("tvkey", "power"), step("gonekey", "power")))
    with pytest.raises(HomeAssistantError, match=r"Step 2 of Cinema, \?: power,"):
        await _press(hass)
    assert sent(mqtt_mock) == []


async def test_a_key_deleted_later_is_reported(
    hass: HomeAssistant, mqtt_mock, waits
) -> None:
    entry = await _board(hass, seq(step("tvkey", "power")))
    await entry.runtime_data.async_delete_code("tvkey", "power")
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError, match="Step 1"):
        await _press(hass)
    assert sent(mqtt_mock) == []


async def test_a_key_learned_again_is_the_one_sent(
    hass: HomeAssistant, mqtt_mock, waits
) -> None:
    entry = await _board(hass, seq(step("tvkey", "power")))
    await entry.runtime_data.async_store_codes("tvkey", {"power": HDMI})
    await _press(hass)
    assert sent(mqtt_mock) == [HDMI["Data"]]


async def test_an_offline_board_sends_nothing(
    hass: HomeAssistant, mqtt_mock, waits
) -> None:
    await _board(hass, CINEMA)
    async_fire_mqtt_message(hass, f"tele/{TOPIC}/LWT", "Offline")
    await hass.async_block_till_done()
    assert hass.states.get(B).state == "unavailable"
    await _press(hass)
    entity = hass.data["entity_components"]["button"].get_entity(B)
    with pytest.raises(HomeAssistantError, match="offline"):
        await entity.async_press()
    assert sent(mqtt_mock) == []


async def test_a_second_press_while_it_runs_is_ignored(
    hass: HomeAssistant, mqtt_mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = asyncio.Event()

    async def _sleep(seconds: float) -> None:
        await release.wait()

    monkeypatch.setattr(sequence_module, "_sleep", _sleep)
    await _board(hass, CINEMA)
    first = hass.async_create_task(_press(hass))
    for _ in range(50):
        if sent(mqtt_mock):
            break
        await asyncio.sleep(0)
    assert sent(mqtt_mock) == [NEC_POWER["Data"]]
    async with asyncio.timeout(1):
        await _press(hass)
    release.set()
    await first
    assert sent(mqtt_mock) == [NEC_POWER["Data"], SOUND_POWER["Data"], HDMI["Data"]]


async def test_a_sequence_is_not_an_appliance(hass: HomeAssistant, mqtt_mock) -> None:
    """No infrared, no remote event, no buttons per key: only its own button."""
    entry = await _board(hass, CINEMA)
    assert "seqkey" not in entry.runtime_data.appliances
    assert hass.states.get(B) is not None
    assert hass.states.get("infrared.cinema") is None
    assert hass.states.get("event.cinema_remote") is None


# ---- adding and managing ---------------------------------------------------


async def _start(hass: HomeAssistant, entry, name: str = "Cinema"):
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "sequence"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    return await manager.async_configure(result["flow_id"], {"name": name})


async def _do(hass: HomeAssistant, result, action: str):
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"action": action}
    )


async def test_adding_a_sequence(hass: HomeAssistant, mqtt_mock, waits) -> None:
    entry = await _board(hass, AC)
    manager = hass.config_entries.subentries
    result = await _start(hass, entry)
    assert result["step_id"] == "steps"

    result = await _do(hass, result, "add_step")
    assert result["step_id"] == "add_step"
    options = result["data_schema"].schema["step"].config["options"]
    values = [option["value"] for option in options]
    labels = [option["label"] for option in options]
    assert choice("tvkey", "power") in values
    assert choice("jblkey", "sources", "HDMI 1") in values
    assert "JBL Soundbar: Sources: HDMI 1" in labels
    # An air conditioner sends its whole state, never one key.
    assert not any("ackey" in value for value in values)

    result = await manager.async_configure(
        result["flow_id"], {"step": choice("tvkey", "power"), "wait": 8}
    )
    assert result["step_id"] == "steps"
    assert "TV Quarto: power" in result["description_placeholders"]["steps"]
    result = await _do(hass, result, "add_step")
    result = await manager.async_configure(
        result["flow_id"], {"step": choice("jblkey", "sources", "HDMI 1"), "wait": 0.4}
    )
    result = await _do(hass, result, "finish")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    created = next(
        s for s in entry.subentries.values() if s.subentry_type == "sequence"
    )
    assert created.title == "Cinema"
    assert created.data["steps"] == [
        step("tvkey", "power", wait=8),
        step("jblkey", "sources", "HDMI 1", wait=0.4),
    ]
    await _press(hass)
    assert sent(mqtt_mock) == [NEC_POWER["Data"], HDMI["Data"]]


async def test_a_sequence_needs_a_step(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await _board(hass)
    result = await _start(hass, entry)
    result = await _do(hass, result, "finish")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_steps"}


async def test_a_board_with_no_keys_has_nothing_to_add(
    hass: HomeAssistant, mqtt_mock
) -> None:
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    result = await _start(hass, entry)
    result = await _do(hass, result, "add_step")
    assert result["errors"] == {"base": "nothing_to_add"}


async def test_a_name_another_appliance_has_is_refused(
    hass: HomeAssistant, mqtt_mock
) -> None:
    entry = await _board(hass)
    result = await _start(hass, entry, name="tv quarto")
    assert result["errors"] == {"name": "name_taken"}


async def test_removing_a_step_from_a_sequence(
    hass: HomeAssistant, mqtt_mock, waits
) -> None:
    entry = await _board(hass, CINEMA)
    subentry = next(
        s for s in entry.subentries.values() if s.subentry_type == "sequence"
    )
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "sequence"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["type"] is FlowResultType.MENU
    result = await manager.async_configure(result["flow_id"], {"next_step_id": "steps"})
    assert (
        "3. JBL Soundbar: Sources: HDMI 1"
        in result["description_placeholders"]["steps"]
    )
    result = await _do(hass, result, "remove_step")
    result = await manager.async_configure(result["flow_id"], {"step": "1"})
    result = await _do(hass, result, "finish")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.subentries[subentry.subentry_id].data["steps"] == [
        step("tvkey", "power", wait=0.4),
        step("jblkey", "sources", "HDMI 1"),
    ]


async def test_a_step_that_is_gone_is_marked(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await _board(hass, seq(step("gonekey", "power")))
    subentry = next(
        s for s in entry.subentries.values() if s.subentry_type == "sequence"
    )
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "sequence"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    result = await manager.async_configure(result["flow_id"], {"next_step_id": "steps"})
    assert result["description_placeholders"]["steps"].startswith("1. ⚠")


# ---- moving --------------------------------------------------------------


async def test_moving_everything_takes_the_sequence_along(
    hass: HomeAssistant, mqtt_mock, entity_registry: er.EntityRegistry, waits
) -> None:
    athom, hubb = await _two_boards(
        hass, {**TV, "title": "TV Teste"}, seq(step("tvkey", "power"))
    )
    await athom.runtime_data.async_store_codes("tvkey", {"power": NEC_POWER})
    await hass.async_block_till_done()
    button = entity_registry.async_get(B)
    manager = hass.config_entries.options
    result = await manager.async_init(athom.entry_id)
    result = await manager.async_configure(
        result["flow_id"], {"next_step_id": "move_all"}
    )
    # Only the appliance has an emitter to choose.
    assert list(result["data_schema"].schema) == ["TV Teste"]
    result = await manager.async_configure(result["flow_id"], {"TV Teste": "2"})
    assert result["reason"] == "moved_all"
    await hass.async_block_till_done()

    moved = next(s for s in hubb.subentries.values() if s.subentry_type == "sequence")
    assert moved.unique_id == "seqkey"
    assert "channel" not in moved.data
    after = entity_registry.async_get(B)
    assert after.id == button.id and after.config_entry_id == hubb.entry_id
    await _press(hass)
    assert sent(mqtt_mock)[-1] == NEC_POWER["Data"]
    assert channels(mqtt_mock)[-1] == 2


# ---- found in review -------------------------------------------------------


async def test_the_board_going_offline_half_way_stops_it(
    hass: HomeAssistant, mqtt_mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _sleep(seconds: float) -> None:
        async_fire_mqtt_message(hass, f"tele/{TOPIC}/LWT", "Offline")
        await hass.async_block_till_done()

    monkeypatch.setattr(sequence_module, "_sleep", _sleep)
    await _board(hass, CINEMA)
    entity = hass.data["entity_components"]["button"].get_entity(B)
    with pytest.raises(HomeAssistantError, match="offline at step 2"):
        await entity.async_press()
    assert sent(mqtt_mock) == [NEC_POWER["Data"]]

    async_fire_mqtt_message(hass, f"tele/{TOPIC}/LWT", "Online")
    await hass.async_block_till_done()
    monkeypatch.setattr(sequence_module, "_sleep", lambda seconds: asyncio.sleep(0))
    await _press(hass)
    assert sent(mqtt_mock)[1:] == [NEC_POWER["Data"], SOUND_POWER["Data"], HDMI["Data"]]


async def test_a_reload_half_way_stops_the_old_run(
    hass: HomeAssistant, mqtt_mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run of a button that is gone must not go on beside the new one's."""
    release = asyncio.Event()

    async def _sleep(seconds: float) -> None:
        await release.wait()

    monkeypatch.setattr(sequence_module, "_sleep", _sleep)
    entry = await _board(hass, CINEMA)
    first = hass.async_create_task(_press(hass))
    for _ in range(50):
        if sent(mqtt_mock):
            break
        await asyncio.sleep(0)
    async with asyncio.timeout(2):
        assert await hass.config_entries.async_reload(entry.entry_id)
    release.set()
    async with asyncio.timeout(1):
        await first
    await hass.async_block_till_done()
    assert sent(mqtt_mock) == [NEC_POWER["Data"]]


async def test_a_code_too_large_is_found_before_anything_goes(
    hass: HomeAssistant, mqtt_mock, waits
) -> None:
    huge = {"Protocol": "NEC", "Bits": 32, "Data": "0x" + "F" * 2000}
    big = typed("switch", "Tomada", "plugkey", {"power": huge})
    await _board(hass, big, seq(step("tvkey", "power"), step("plugkey", "power")))
    with pytest.raises(HomeAssistantError, match="Step 2"):
        await _press(hass)
    assert sent(mqtt_mock) == []


async def test_a_list_item_called_protocol_is_still_an_item(
    hass: HomeAssistant, mqtt_mock, waits
) -> None:
    odd = typed(
        "media", "Odd", "oddkey", {"power": SOUND_POWER, "sources": {"Protocol": HDMI}}
    )
    entry = await _board(hass, odd, seq(step("oddkey", "sources", "Protocol")))
    result = await _start(hass, entry, name="Outra")
    result = await _do(hass, result, "add_step")
    labels = [
        o["label"] for o in result["data_schema"].schema["step"].config["options"]
    ]
    assert "Odd: Sources: Protocol" in labels
    assert "Odd: Sources" not in labels
    await _press(hass)
    assert sent(mqtt_mock) == [HDMI["Data"]]


async def test_removing_from_no_steps_says_so(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await _board(hass)
    result = await _start(hass, entry)
    result = await _do(hass, result, "remove_step")
    assert result["step_id"] == "steps"
    assert result["errors"] == {"base": "no_steps"}


async def test_a_step_moves_only_its_own_appliance(
    hass: HomeAssistant, mqtt_mock, waits
) -> None:
    """The other typed appliances stay put, and no remote event fires."""
    plug = typed("switch", "Tomada", "plugkey", {"power": code("0x20DF8877")})
    await _board(hass, plug, CINEMA)
    await _press(hass)
    assert hass.states.get("media_player.jbl_soundbar").state == "on"
    assert hass.states.get("switch.tomada").state == "off"
    assert hass.states.get("event.jbl_soundbar_remote").state == "unknown"
    assert hass.states.get("event.tv_quarto_remote").state == "unknown"


async def test_learning_under_a_sequence_name_is_refused(
    hass: HomeAssistant, mqtt_mock
) -> None:
    entry = await _board(hass, CINEMA)
    with pytest.raises(ServiceValidationError, match="sequence"):
        await hass.services.async_call(
            "remote",
            "learn_command",
            {"entity_id": "remote.hubb_ir1", "device": "cinema", "command": "power"},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError, match="button.cinema"):
        await hass.services.async_call(
            "remote",
            "send_command",
            {"entity_id": "remote.hubb_ir1", "device": "Cinema", "command": "power"},
            blocking=True,
        )
    assert [s.title for s in entry.subentries.values()].count("Cinema") == 1
    receive(hass, NEC_POWER)
    await hass.async_block_till_done()
