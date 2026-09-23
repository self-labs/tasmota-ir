"""Adding an appliance, learning from the interface, and sending."""

from __future__ import annotations

import asyncio
import json

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .conftest import NEC_POWER, TOPIC, board_entry, receive, setup_board


async def _learn(hass: HomeAssistant, flow_id: str, command: str) -> dict:
    """Name a key, press it, and return the step that follows."""
    manager = hass.config_entries.subentries
    result = await manager.async_configure(flow_id, {"next_step_id": "learn"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "learn"
    result = await manager.async_configure(flow_id, {"command": command})
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    receive(hass, NEC_POWER)
    await hass.async_block_till_done()
    return await manager.async_configure(flow_id)


async def test_add_an_appliance_and_learn_its_first_key(
    hass: HomeAssistant,
    mqtt_mock,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """The whole path a person takes, with no action typed anywhere."""
    entry = await setup_board(hass, board_entry())
    manager = hass.config_entries.subentries

    result = await manager.async_init(
        (entry.entry_id, "appliance"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await manager.async_configure(
        result["flow_id"], {"name": "TV Quarto", "channel": "3"}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "added"

    result = await _learn(hass, result["flow_id"], "power")
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "learned"

    result = await manager.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    (subentry,) = entry.subentries.values()
    assert subentry.title == "TV Quarto"
    assert subentry.data["channel"] == 3

    entity_id = entity_registry.async_get_entity_id(
        "button", "tasmota_ir", f"{subentry.unique_id}_power"
    )
    assert entity_id == "button.tv_quarto_power"
    device = device_registry.async_get(entity_registry.async_get(entity_id).device_id)
    assert device.name == "TV Quarto"
    board = device_registry.async_get(device.via_device_id)
    assert board.name == "Hubb IR1"

    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    topic, payload = mqtt_mock.async_publish.call_args.args[:2]
    assert topic == f"cmnd/{TOPIC}/IRSend"
    assert json.loads(payload) == {**NEC_POWER, "Channel": 3}


async def test_an_appliance_with_nothing_learned_still_shows_up(
    hass: HomeAssistant, mqtt_mock, device_registry: dr.DeviceRegistry
) -> None:
    """Finishing without learning creates the appliance and its device."""
    entry = await setup_board(hass, board_entry())
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "appliance"), context={"source": SOURCE_USER}
    )
    result = await manager.async_configure(
        result["flow_id"], {"name": "JBL Soundbar", "channel": "2"}
    )
    result = await manager.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    (subentry,) = entry.subentries.values()
    (device,) = device_registry.async_get_devices(
        identifiers={("tasmota_ir", subentry.unique_id)}
    )
    assert device.name == "JBL Soundbar"


async def test_learn_from_the_appliance_menu_and_move_it(
    hass: HomeAssistant, mqtt_mock, entity_registry: er.EntityRegistry
) -> None:
    """Learning later, then changing the emitter, keeps the button working."""
    entry = await setup_board(
        hass,
        board_entry(
            subentries_data=(
                {
                    "data": {"channel": "1"},
                    "subentry_type": "appliance",
                    "title": "TV Quarto",
                    "unique_id": "tvkey",
                },
            )
        ),
    )
    (subentry,) = entry.subentries.values()
    manager = hass.config_entries.subentries

    result = await manager.async_init(
        (entry.entry_id, "appliance"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["type"] is FlowResultType.MENU
    result = await _learn(hass, result["flow_id"], "power")
    assert result["step_id"] == "learned"
    result = await manager.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    assert hass.states.get("button.tv_quarto_power") is not None

    result = await manager.async_init(
        (entry.entry_id, "appliance"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    result = await manager.async_configure(
        result["flow_id"], {"next_step_id": "channel"}
    )
    mqtt_mock.async_publish.reset_mock()
    result = await manager.async_configure(result["flow_id"], {"channel": "5"})

    # Choosing an emitter tries it before saving: whether it points at the
    # appliance cannot be read from the board, only seen on the appliance.
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "channel_test"
    assert json.loads(mqtt_mock.async_publish.call_args.args[1])["Channel"] == 5

    result = await manager.async_configure(
        result["flow_id"], {"next_step_id": "channel_save"}
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()

    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.tv_quarto_power"}, blocking=True
    )
    assert json.loads(mqtt_mock.async_publish.call_args.args[1])["Channel"] == 5


async def test_a_timeout_offers_to_try_again(hass: HomeAssistant, mqtt_mock) -> None:
    """Nothing pressed: the menu says so, and keeps the flow alive."""
    entry = await setup_board(hass, board_entry())
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "appliance"), context={"source": SOURCE_USER}
    )
    result = await manager.async_configure(
        result["flow_id"], {"name": "TV", "channel": "1"}
    )
    result = await manager.async_configure(result["flow_id"], {"next_step_id": "learn"})
    flow = manager._progress[result["flow_id"]]
    flow._async_wait_for_key = _nothing
    result = await manager.async_configure(result["flow_id"], {"command": "power"})
    await hass.async_block_till_done()
    result = await manager.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "learn_timeout"
    assert set(result["menu_options"]) == {"learn_wait", "learn", "finish"}


async def _nothing() -> None:
    return None


async def test_a_duplicate_name_is_refused(hass: HomeAssistant, mqtt_mock) -> None:
    """Two appliances called the same would be one name for two emitters."""
    entry = await setup_board(
        hass,
        board_entry(
            subentries_data=(
                {
                    "data": {"channel": "1"},
                    "subentry_type": "appliance",
                    "title": "TV Quarto",
                    "unique_id": "tvkey",
                },
            )
        ),
    )
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "appliance"), context={"source": SOURCE_USER}
    )
    result = await manager.async_configure(
        result["flow_id"], {"name": "tv quarto", "channel": "2"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"name": "name_taken"}


async def test_learning_by_action_under_a_new_name_creates_the_appliance(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """remote.learn_command with an unknown name must not hide the command."""
    entry = await setup_board(hass, board_entry())

    task = hass.async_create_task(
        hass.services.async_call(
            "remote",
            "learn_command",
            {
                "entity_id": "remote.hubb_ir1",
                "device": "Ventilador",
                "command": "power",
                "timeout": 5,
            },
            blocking=True,
        )
    )
    # Let the action start waiting before the key is "pressed".
    for _ in range(10):
        await asyncio.sleep(0)
    receive(hass, NEC_POWER)
    await task
    await hass.async_block_till_done()

    (subentry,) = entry.subentries.values()
    assert subentry.title == "Ventilador"
    assert hass.states.get("button.ventilador_power") is not None
