"""Moving an appliance to another board, and copying it there."""

from __future__ import annotations

import json

from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from .conftest import BOARD_DATA, NEC_POWER, board_entry, setup_board

OTHER_TOPIC = "tasmota_ATHOM"
OTHER_MAC = "a4:cf:12:00:11:22"

TV = {
    "data": {"channel": 1},
    "subentry_type": "appliance",
    "title": "TV Teste",
    "unique_id": "tvkey",
}
AC = {
    "data": {
        "channel": 1,
        "vendor": "LG2",
        "model": "AKB75215403",
        "light": "On",
        "min_temp": 18,
        "max_temp": 30,
        "hvac_modes": ["off", "cool", "auto"],
        "swing_vertical": True,
        "swing_horizontal": False,
        "initial_swing_vertical": "Off",
    },
    "subentry_type": "climate",
    "title": "Ar Atom",
    "unique_id": "ackey",
}


async def _two_boards(hass: HomeAssistant, *subentries, other_subentries=()):
    """The Athom with its appliances, and the eight emitter board next to it."""
    athom = await setup_board(
        hass,
        board_entry(
            title="Athom IR",
            unique_id=OTHER_MAC,
            data={
                **BOARD_DATA,
                "topic": OTHER_TOPIC,
                "mac": OTHER_MAC,
                "channels": 1,
            },
            subentries_data=subentries,
        ),
    )
    hubb = await setup_board(hass, board_entry(subentries_data=other_subentries))
    return athom, hubb


async def _open(hass: HomeAssistant, entry, kind: str, action: str):
    """Open the appliance's menu and pick move or copy."""
    subentry = next(iter(entry.subentries.values()))
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, kind),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["type"] is FlowResultType.MENU
    return await manager.async_configure(result["flow_id"], {"next_step_id": action})


async def test_moving_keeps_the_codes_and_the_entity_ids(
    hass: HomeAssistant, mqtt_mock, entity_registry: er.EntityRegistry
) -> None:
    """The TV leaves the Athom and arrives on the other board, button and all."""
    athom, hubb = await _two_boards(hass, TV)
    await athom.runtime_data.async_store_codes("tvkey", {"power": NEC_POWER})
    await hass.async_block_till_done()
    entity_registry.async_update_entity("button.tv_teste_power", name="Liga a TV")

    result = await _open(hass, athom, "appliance", "move")
    # Only one other board: nothing to choose, straight to the emitter.
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "move_target"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"channel": "3", "name": "TV Teste"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "moved"
    await hass.async_block_till_done()

    assert not athom.subentries
    (moved,) = hubb.subentries.values()
    assert moved.unique_id == "tvkey"
    assert moved.data["channel"] == 3
    assert hubb.runtime_data.get_code("tvkey", "power") == NEC_POWER
    assert "tvkey" not in athom.runtime_data.codes

    entry = entity_registry.async_get("button.tv_teste_power")
    assert entry is not None
    assert entry.config_entry_id == hubb.entry_id
    assert entry.name == "Liga a TV"

    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.tv_teste_power"}, blocking=True
    )
    topic, payload = mqtt_mock.async_publish.call_args.args[:2]
    assert topic == "cmnd/tasmota_2C3124/IRSend"
    assert json.loads(payload) == {**NEC_POWER, "Channel": 3}


async def test_copying_leaves_the_original_where_it_was(
    hass: HomeAssistant, mqtt_mock, entity_registry: er.EntityRegistry
) -> None:
    """Both boards end up with the TV, each with its own key and buttons."""
    athom, hubb = await _two_boards(hass, TV)
    await athom.runtime_data.async_store_codes("tvkey", {"power": NEC_POWER})
    await hass.async_block_till_done()

    result = await _open(hass, athom, "appliance", "copy")
    assert result["step_id"] == "copy_target"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"channel": "2", "name": "TV Teste"}
    )
    assert result["reason"] == "copied"
    await hass.async_block_till_done()

    (original,) = athom.subentries.values()
    assert original.unique_id == "tvkey"
    assert athom.runtime_data.get_code("tvkey", "power") == NEC_POWER

    (copy,) = hubb.subentries.values()
    assert copy.unique_id != "tvkey"
    assert copy.data["channel"] == 2
    assert hubb.runtime_data.get_code(copy.unique_id, "power") == NEC_POWER
    assert entity_registry.async_get_entity_id(
        "button", "tasmota_ir", f"{copy.unique_id}_power"
    ) not in (None, "button.tv_teste_power")


async def test_a_name_already_on_the_other_board_is_refused(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """Two appliances with one name on the same board could not be told apart."""
    athom, _ = await _two_boards(hass, TV, other_subentries=({**TV, "unique_id": "x"},))
    result = await _open(hass, athom, "appliance", "copy")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"channel": "1", "name": "tv teste"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"name": "name_taken"}


async def test_with_no_other_board_there_is_nowhere_to_go(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """A single board says so instead of offering an empty list."""
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    result = await _open(hass, entry, "appliance", "move")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_other_board"


async def test_an_air_conditioner_moves_with_its_settings(
    hass: HomeAssistant, mqtt_mock, entity_registry: er.EntityRegistry
) -> None:
    """Nothing is learned for a unit, so what travels is its configuration."""
    athom, hubb = await _two_boards(hass, AC)
    assert hass.states.get("climate.ar_atom") is not None

    result = await _open(hass, athom, "climate", "move")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"channel": "4", "name": "Ar Atom"}
    )
    assert result["reason"] == "moved"
    await hass.async_block_till_done()

    (moved,) = hubb.subentries.values()
    assert moved.data["vendor"] == "LG2"
    assert moved.data["model"] == "AKB75215403"
    assert moved.data["channel"] == 4
    entry = entity_registry.async_get("climate.ar_atom")
    assert entry is not None
    assert entry.config_entry_id == hubb.entry_id


async def test_with_several_boards_the_board_is_chosen_first(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """Two other boards: the flow asks which one before asking the emitter."""
    athom, hubb = await _two_boards(hass, TV)
    third = await setup_board(
        hass,
        board_entry(
            title="Sala IR",
            unique_id="a4:cf:12:00:33:44",
            data={**BOARD_DATA, "topic": "tasmota_SALA", "mac": "a4:cf:12:00:33:44"},
        ),
    )
    result = await _open(hass, athom, "appliance", "move")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "move"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"board": third.entry_id}
    )
    assert result["step_id"] == "move_target"
    assert result["description_placeholders"]["board"] == "Sala IR"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"channel": "1", "name": "TV Teste"}
    )
    assert result["reason"] == "moved"
    await hass.async_block_till_done()
    assert not hubb.subentries
    (moved,) = third.subentries.values()
    assert moved.unique_id == "tvkey"
