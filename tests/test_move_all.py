"""Moving every appliance of a board to another board at once."""

from __future__ import annotations

import json

from homeassistant.config_entries import SOURCE_RECONFIGURE, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    async_fire_mqtt_message,
    async_mock_service,
)

from .conftest import NEC_POWER, board_entry, receive, setup_board
from .test_transfer import AC, OTHER_TOPIC, TV, _two_boards
from .typed_util import typed

PLUG = typed("switch", "Tomada", "swkey", {"power": NEC_POWER})


async def _move_all(hass: HomeAssistant, entry):
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    return await manager.async_configure(
        result["flow_id"], {"next_step_id": "move_all"}
    )


async def test_everything_moves_with_its_entity_ids(
    hass: HomeAssistant, mqtt_mock, entity_registry: er.EntityRegistry
) -> None:
    athom, hubb = await _two_boards(hass, TV, AC, PLUG)
    await athom.runtime_data.async_store_codes("tvkey", {"power": NEC_POWER})
    await hass.async_block_till_done()
    button = entity_registry.async_get("button.tv_teste_power")
    # Every entity of every appliance: buttons, climate, extras, typed,
    # infrared and the remote's event.
    before = {
        e.entity_id: e.id
        for e in er.async_entries_for_config_entry(entity_registry, athom.entry_id)
        if e.config_subentry_id
    }
    assert {"climate.ar_atom", "switch.tomada", "event.tv_teste_remote"} <= set(before)

    result = await _move_all(hass, athom)
    # Only one other board: straight to the emitters there.
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "move_all_emitters"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"TV Teste": "3", "Ar Atom": "2", "Tomada": "4"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "moved_all"
    await hass.async_block_till_done()

    assert not athom.subentries
    moved = {s.unique_id: s for s in hubb.subentries.values()}
    assert set(moved) == {"tvkey", "ackey", "swkey"}
    assert moved["tvkey"].data["channel"] == 3
    assert moved["ackey"].data["channel"] == 2
    assert moved["swkey"].data["roles"] == {"power": NEC_POWER}
    assert hubb.runtime_data.get_code("tvkey", "power") == NEC_POWER
    after = entity_registry.async_get("button.tv_teste_power")
    assert after.id == button.id and after.config_entry_id == hubb.entry_id
    for entity_id, registry_id in before.items():
        moved_entity = entity_registry.async_get(entity_id)
        assert moved_entity is not None, entity_id
        assert moved_entity.id == registry_id, entity_id
        assert moved_entity.config_entry_id == hubb.entry_id, entity_id


async def test_a_name_the_other_board_has_is_refused(
    hass: HomeAssistant, mqtt_mock
) -> None:
    athom, _hubb = await _two_boards(
        hass, TV, other_subentries=({**TV, "unique_id": "other"},)
    )
    result = await _move_all(hass, athom)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"TV Teste": "1"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "names_taken"}
    assert "TV Teste" in result["description_placeholders"]["names"]
    assert athom.subentries


async def test_no_other_board(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    result = await _move_all(hass, entry)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_other_board"


async def test_an_empty_board_has_nothing_to_move(
    hass: HomeAssistant, mqtt_mock
) -> None:
    athom, _hubb = await _two_boards(hass)
    result = await _move_all(hass, athom)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "nothing_to_move"


def _athom_hears(hass: HomeAssistant, frame) -> None:
    async_fire_mqtt_message(
        hass, f"tele/{OTHER_TOPIC}/RESULT", json.dumps({"IrReceived": frame})
    )


async def test_a_move_does_not_fire_the_documented_automation(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """The README's automation runs on a key press, never on the move itself."""
    athom, _hubb = await _two_boards(hass, TV)
    await athom.runtime_data.async_store_codes("tvkey", {"power": NEC_POWER})
    calls = async_mock_service(hass, "test", "automation")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "triggers": [
                    {
                        "trigger": "event.received",
                        "target": {"entity_id": "event.tv_teste_remote"},
                        "options": {"event_type": "power"},
                    }
                ],
                "actions": [{"action": "test.automation"}],
            }
        },
    )
    await hass.async_block_till_done()
    _athom_hears(hass, NEC_POWER)
    await hass.async_block_till_done()
    assert len(calls) == 1

    result = await _move_all(hass, athom)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"TV Teste": "1"}
    )
    assert result["reason"] == "moved_all"
    await hass.async_block_till_done()
    assert len(calls) == 1

    receive(hass, NEC_POWER)
    await hass.async_block_till_done()
    assert len(calls) == 2


async def test_a_name_in_other_case_is_refused(hass: HomeAssistant, mqtt_mock) -> None:
    athom, _hubb = await _two_boards(
        hass, TV, other_subentries=({**TV, "title": "tv teste", "unique_id": "other"},)
    )
    result = await _move_all(hass, athom)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"TV Teste": "1"}
    )
    assert result["errors"] == {"base": "names_taken"}


async def test_the_same_appliance_on_the_other_board_is_refused(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """Same key, other name: moving would merge its codes into that one."""
    athom, hubb = await _two_boards(
        hass, TV, AC, other_subentries=({**TV, "title": "Outra TV"},)
    )
    await athom.runtime_data.async_store_codes("tvkey", {"power": NEC_POWER})
    await hass.async_block_till_done()
    result = await _move_all(hass, athom)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"TV Teste": "1", "Ar Atom": "1"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "already_there"}
    assert "TV Teste" in result["description_placeholders"]["names"]
    assert len(athom.subentries) == 2
    assert hubb.runtime_data.get_code("tvkey", "power") is None


async def test_the_same_appliance_refuses_a_single_move(
    hass: HomeAssistant, mqtt_mock
) -> None:
    athom, _hubb = await _two_boards(
        hass, TV, other_subentries=({**TV, "title": "Outra TV"},)
    )
    subentry = next(iter(athom.subentries.values()))
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (athom.entry_id, "appliance"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    result = await manager.async_configure(result["flow_id"], {"next_step_id": "move"})
    assert result["step_id"] == "move_target"
    result = await manager.async_configure(
        result["flow_id"], {"channel": "1", "name": "TV Nova"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "already_there"}
    assert athom.subentries


async def test_a_board_that_is_not_loaded(hass: HomeAssistant, mqtt_mock) -> None:
    athom, _hubb = await _two_boards(hass, TV)
    await hass.config_entries.async_unload(athom.entry_id)
    result = await _move_all(hass, athom)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "board_not_loaded"


async def test_an_appliance_added_while_the_form_is_open(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """The form asks for the appliances it showed; a new one must be asked too."""
    athom, hubb = await _two_boards(hass, TV)
    result = await _move_all(hass, athom)
    hass.config_entries.async_add_subentry(
        athom,
        ConfigSubentry(
            data={"channel": 1},
            subentry_type="appliance",
            title="Som",
            unique_id="somkey",
        ),
    )
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"TV Teste": "1"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "changed"}
    assert not hubb.subentries


async def test_codes_on_their_way_survive_a_prune(
    hass: HomeAssistant, mqtt_mock
) -> None:
    from custom_components.tasmota_ir.coordinator import codes_arriving

    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    coordinator = entry.runtime_data
    await coordinator.async_store_codes("ghost", {"power": NEC_POWER})
    with codes_arriving(hass, entry.entry_id, ["ghost"]):
        assert coordinator.prune_codes() == []
    assert coordinator.prune_codes() == ["ghost"]
