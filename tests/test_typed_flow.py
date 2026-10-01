"""Adding and managing typed appliances: learn, reuse, clear, finish."""

from __future__ import annotations

import json

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import board_entry, receive, setup_board
from .typed_util import code, typed

P, VU, NEW = code("0x20DF10EF"), code("0x20DF40BF"), code("0x20DFC03F")
JBL_OLD = {
    "data": {"channel": 1},
    "subentry_type": "appliance",
    "title": "JBL Soundbar",
    "unique_id": "oldkey",
}


async def _start(hass: HomeAssistant, entry, kind: str, name: str = "JBL"):
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, kind), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    return await manager.async_configure(
        result["flow_id"], {"name": name, "channel": "1"}
    )


async def _pick(hass: HomeAssistant, result, function: str):
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"function": function}
    )


async def _menu(hass: HomeAssistant, result, option: str):
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": option}
    )


async def test_a_tv_from_keys_another_appliance_learned(
    hass: HomeAssistant, mqtt_mock
) -> None:
    entry = await setup_board(hass, board_entry(subentries_data=(JBL_OLD,)))
    await entry.runtime_data.async_store_codes("oldkey", {"Power": P, "Vol UP": VU})
    manager = hass.config_entries.subentries

    result = await _start(hass, entry, "media")
    assert result["step_id"] == "functions"
    result = await _pick(hass, result, "power")
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "action"
    result = await _menu(hass, result, "reuse")
    result = await manager.async_configure(result["flow_id"], {"code": "oldkey|Power"})
    result = await _pick(hass, result, "volume_up")
    result = await _menu(hass, result, "reuse")
    result = await manager.async_configure(result["flow_id"], {"code": "oldkey|Vol UP"})
    result = await _pick(hass, result, "finish")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    created = next(s for s in entry.subentries.values() if s.subentry_type == "media")
    assert created.data["roles"] == {"power": P, "volume_up": VU}
    assert hass.states.get("media_player.jbl") is not None


async def test_learning_a_function_now(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await setup_board(hass, board_entry())
    manager = hass.config_entries.subentries
    result = await _start(hass, entry, "switch", "Tomada")
    result = await _pick(hass, result, "power")
    result = await _menu(hass, result, "learn_now")
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    receive(hass, NEW)
    await hass.async_block_till_done()
    result = await manager.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "functions"
    result = await _pick(hass, result, "finish")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["roles"] == {"power": NEW}


async def test_a_list_item_is_named_first(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await setup_board(hass, board_entry(subentries_data=(JBL_OLD,)))
    await entry.runtime_data.async_store_codes("oldkey", {"Power": P, "HDMI": VU})
    manager = hass.config_entries.subentries
    result = await _start(hass, entry, "media")
    result = await _pick(hass, result, "sources")
    assert result["step_id"] == "list_item"
    result = await manager.async_configure(result["flow_id"], {"item": "HDMI 1"})
    result = await _menu(hass, result, "reuse")
    result = await manager.async_configure(result["flow_id"], {"code": "oldkey|HDMI"})
    result = await _pick(hass, result, "power")
    result = await _menu(hass, result, "reuse")
    result = await manager.async_configure(result["flow_id"], {"code": "oldkey|Power"})
    result = await _pick(hass, result, "finish")
    assert result["data"]["roles"]["sources"] == {"HDMI 1": VU}


async def test_finishing_without_power_is_refused(
    hass: HomeAssistant, mqtt_mock
) -> None:
    entry = await setup_board(hass, board_entry())
    result = await _start(hass, entry, "fan", "Ventilador")
    result = await _pick(hass, result, "finish")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "missing_power"}


async def test_a_number_is_asked(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await setup_board(hass, board_entry(subentries_data=(JBL_OLD,)))
    await entry.runtime_data.async_store_codes("oldkey", {"Power": P})
    manager = hass.config_entries.subentries
    result = await _start(hass, entry, "fan", "Ventilador")
    result = await _pick(hass, result, "speed_count")
    assert result["step_id"] == "number"
    result = await manager.async_configure(result["flow_id"], {"value": 4})
    result = await _pick(hass, result, "power")
    result = await _menu(hass, result, "reuse")
    result = await manager.async_configure(result["flow_id"], {"code": "oldkey|Power"})
    result = await _pick(hass, result, "finish")
    assert result["data"]["speed_count"] == 4


async def test_the_sensor_is_kept(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await setup_board(hass, board_entry(subentries_data=(JBL_OLD,)))
    await entry.runtime_data.async_store_codes("oldkey", {"Power": P})
    manager = hass.config_entries.subentries
    result = await _start(hass, entry, "switch", "Tomada")
    result = await _pick(hass, result, "sensor")
    result = await manager.async_configure(
        result["flow_id"],
        {"power_sensor": "sensor.tomada_potencia", "power_threshold": 8},
    )
    result = await _pick(hass, result, "power")
    result = await _menu(hass, result, "reuse")
    result = await manager.async_configure(result["flow_id"], {"code": "oldkey|Power"})
    result = await _pick(hass, result, "finish")
    assert result["data"]["power_sensor"] == "sensor.tomada_potencia"
    assert result["data"]["power_threshold"] == 8


async def test_clear_forgets_a_function(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await setup_board(
        hass,
        board_entry(
            subentries_data=(
                typed("switch", "Tomada", "swkey", {"power": P, "power_on": VU}),
            )
        ),
    )
    (subentry,) = entry.subentries.values()
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "switch"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["type"] is FlowResultType.MENU
    result = await _menu(hass, result, "functions")
    result = await _pick(hass, result, "power_on")
    result = await _menu(hass, result, "clear")
    result = await _pick(hass, result, "finish")
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    assert entry.subentries[subentry.subentry_id].data["roles"] == {"power": P}


async def test_changing_the_emitter_presses_power(
    hass: HomeAssistant, mqtt_mock
) -> None:
    entry = await setup_board(
        hass,
        board_entry(
            subentries_data=(typed("switch", "Tomada", "swkey", {"power": P}),)
        ),
    )
    (subentry,) = entry.subentries.values()
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "switch"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    result = await _menu(hass, result, "channel")
    mqtt_mock.async_publish.reset_mock()
    result = await manager.async_configure(result["flow_id"], {"channel": "5"})
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "channel_test"
    body = json.loads(mqtt_mock.async_publish.call_args.args[1])
    assert body["Data"] == P["Data"] and body["Channel"] == 5
