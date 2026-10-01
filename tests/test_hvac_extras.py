"""The extras an air conditioner protocol carries: presets and switches."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.tasmota_ir.hvac_extras import extras_default, extras_offered

from .conftest import LG_AC_FRAME, TOPIC, board_entry, receive, setup_board


def _ac(vendor: str, title: str, key: str, **data: Any) -> dict[str, Any]:
    """An air conditioner subentry as the flow writes it."""
    return {
        "data": {
            "channel": 2,
            "vendor": vendor,
            "model": "",
            "light": "On",
            "min_temp": 18,
            "max_temp": 30,
            "hvac_modes": ["off", "cool", "heat"],
            "swing_vertical": True,
            "swing_horizontal": False,
            "initial_swing_vertical": "Off",
            **data,
        },
        "subentry_type": "climate",
        "title": title,
        "unique_id": key,
    }


LG = _ac("LG2", "Ar Escritorio", "lgkey")
SAMSUNG = _ac("DAIKIN2", "Ar Sala", "samkey")


async def _last_irhvac(mqtt_mock) -> dict[str, Any]:
    topic, payload = mqtt_mock.async_publish.call_args.args[:2]
    assert topic == f"cmnd/{TOPIC}/IRHVAC"
    return json.loads(payload)


async def _turn_on(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": "cool"},
        blocking=True,
    )


def test_the_library_decides_what_each_vendor_offers() -> None:
    """Read from IRac::sendAc: LG sends the display and nothing else."""
    assert extras_offered("LG2") == ["light"]
    assert extras_offered("DAIKIN2") == [
        "turbo",
        "econo",
        "quiet",
        "light",
        "beep",
        "clean",
        "filter",
    ]
    assert extras_offered("DAIKIN") == ["turbo", "econo", "quiet", "clean"]
    assert extras_offered("NOBODY") == []


def test_a_display_that_toggles_is_left_out() -> None:
    """Coolix flips its display on every Light: offering it would flicker."""
    assert "light" not in extras_offered("COOLIX")
    # Every extra Coolix has is a toggle in the library, so it gets none.
    assert extras_default("COOLIX") == []


async def test_an_lg_gets_only_the_display_switch(
    hass: HomeAssistant, mqtt_mock, entity_registry: er.EntityRegistry
) -> None:
    await setup_board(hass, board_entry(subentries_data=(LG,)))

    state = hass.states.get("climate.ar_escritorio")
    assert "preset_modes" not in state.attributes
    assert hass.states.get("switch.ar_escritorio_display").state == "on"
    assert (
        entity_registry.async_get_entity_id("switch", "tasmota_ir", "lgkey_beep")
        is None
    )


async def test_a_samsung_gets_presets_and_switches(
    hass: HomeAssistant, mqtt_mock
) -> None:
    await setup_board(hass, board_entry(subentries_data=(SAMSUNG,)))

    state = hass.states.get("climate.ar_sala")
    assert state.attributes["preset_modes"] == ["none", "boost", "eco", "quiet"]
    assert state.attributes["preset_mode"] == "none"
    for name in ("display", "beep", "self_clean", "filter"):
        assert hass.states.get(f"switch.ar_sala_{name}") is not None, name


async def test_a_preset_goes_in_the_frame(hass: HomeAssistant, mqtt_mock) -> None:
    await setup_board(hass, board_entry(subentries_data=(SAMSUNG,)))
    await _turn_on(hass, "climate.ar_sala")

    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": "climate.ar_sala", "preset_mode": "boost"},
        blocking=True,
    )

    body = await _last_irhvac(mqtt_mock)
    assert body["Turbo"] == "On"
    assert body["Econo"] == "Off"
    assert body["Quiet"] == "Off"
    assert hass.states.get("climate.ar_sala").attributes["preset_mode"] == "boost"


async def test_a_switch_goes_in_the_frame(hass: HomeAssistant, mqtt_mock) -> None:
    await setup_board(hass, board_entry(subentries_data=(LG,)))
    await _turn_on(hass, "climate.ar_escritorio")

    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.ar_escritorio_display"},
        blocking=True,
    )

    body = await _last_irhvac(mqtt_mock)
    assert body["Light"] == "Off"
    assert body["Power"] == "On"
    assert hass.states.get("switch.ar_escritorio_display").state == "off"


async def test_nothing_is_sent_while_the_unit_is_off(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """Every frame carries the whole state, so sending would switch it on."""
    await setup_board(hass, board_entry(subentries_data=(SAMSUNG,)))

    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": "climate.ar_sala", "preset_mode": "eco"},
        blocking=True,
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.ar_sala_beep"}, blocking=True
    )
    assert not mqtt_mock.async_publish.called

    await _turn_on(hass, "climate.ar_sala")
    body = await _last_irhvac(mqtt_mock)
    assert body["Econo"] == "On"
    assert body["Beep"] == "On"


async def test_the_remote_sets_the_preset_and_the_switches(
    hass: HomeAssistant, mqtt_mock
) -> None:
    await setup_board(hass, board_entry(subentries_data=(SAMSUNG,)))

    receive(
        hass,
        {
            "Protocol": "DAIKIN2",
            "Bits": 112,
            "Data": "0x0292",
            "IRHVAC": {
                "Vendor": "DAIKIN2",
                "Power": "On",
                "Mode": "Cool",
                "Temp": 22,
                "FanSpeed": "Auto",
                "Quiet": "Off",
                "Turbo": "Off",
                "Econo": "On",
                "Light": "On",
                "Filter": "Off",
                "Clean": "On",
                "Beep": "On",
                "Sleep": -1,
            },
        },
    )
    await hass.async_block_till_done()

    assert hass.states.get("climate.ar_sala").attributes["preset_mode"] == "eco"
    assert hass.states.get("switch.ar_sala_self_clean").state == "on"
    assert hass.states.get("switch.ar_sala_beep").state == "on"


async def test_the_lg_display_key_flips_the_display_switch(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """LG sends its display key as a frame of its own, a toggle."""
    await setup_board(hass, board_entry(subentries_data=(LG,)))
    frame = json.loads(json.dumps(LG_AC_FRAME))
    frame["Data"] = "0x88C00A6"

    receive(hass, frame)
    await hass.async_block_till_done()
    assert hass.states.get("switch.ar_escritorio_display").state == "off"

    receive(hass, frame)
    await hass.async_block_till_done()
    assert hass.states.get("switch.ar_escritorio_display").state == "on"


async def test_settings_choose_the_extras(
    hass: HomeAssistant, mqtt_mock, entity_registry: er.EntityRegistry
) -> None:
    """Only what the unit really has: unticking the beep takes its switch away."""
    entry = await setup_board(hass, board_entry(subentries_data=(SAMSUNG,)))
    (subentry,) = entry.subentries.values()
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "climate"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    result = await manager.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    assert result["type"] is FlowResultType.FORM

    result = await manager.async_configure(
        result["flow_id"],
        {
            "model": "",
            "min_temp": 18,
            "max_temp": 30,
            "hvac_modes": ["off", "cool"],
            "swing_vertical": True,
            "swing_horizontal": False,
            "extras": ["turbo", "light"],
        },
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()

    state = hass.states.get("climate.ar_sala")
    assert state.attributes["preset_modes"] == ["none", "boost"]
    assert hass.states.get("switch.ar_sala_display") is not None
    assert (
        entity_registry.async_get_entity_id("switch", "tasmota_ir", "samkey_beep")
        is None
    )


async def test_the_extras_survive_a_restart(hass: HomeAssistant, mqtt_mock) -> None:
    """The preset and the switches come back as they were, not as defaults."""
    mock_restore_cache(
        hass,
        [
            State(
                "climate.ar_sala",
                "cool",
                {"preset_mode": "eco", "extras": {"beep": True, "clean": True}},
            )
        ],
    )
    await setup_board(hass, board_entry(subentries_data=(SAMSUNG,)))

    assert hass.states.get("climate.ar_sala").attributes["preset_mode"] == "eco"
    assert hass.states.get("switch.ar_sala_beep").state == "on"
    assert hass.states.get("switch.ar_sala_self_clean").state == "on"


def test_toggle_extras_are_never_offered() -> None:
    """Tasmota keeps no state between sends, so a toggle would flip every frame."""
    assert "beep" not in extras_offered("SAMSUNG_AC")
    assert "clean" not in extras_offered("SAMSUNG_AC")
    for extra in ("turbo", "econo", "light", "clean"):
        assert extra not in extras_offered("MIDEA"), extra
    assert "turbo" not in extras_offered("FUJITSU_AC")
    assert "econo" not in extras_offered("FUJITSU_AC")
    assert "light" not in extras_offered("HAIER_AC160")


def test_a_sleep_timer_is_not_a_sleep_mode() -> None:
    """These vendors read Sleep as minutes before switching off."""
    for vendor in ("DAIKIN2", "FUJITSU_AC", "SAMSUNG_AC", "EUROM"):
        assert "sleep" not in extras_offered(vendor), vendor
    assert "sleep" in extras_offered("DAIKIN128")


async def test_sleep_on_is_a_positive_value(hass: HomeAssistant, mqtt_mock) -> None:
    """DAIKIN128 only sleeps above 0; every other vendor takes 1 as on too."""
    await setup_board(
        hass, board_entry(subentries_data=(_ac("DAIKIN128", "Ar Quarto", "dkey"),))
    )
    await _turn_on(hass, "climate.ar_quarto")
    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": "climate.ar_quarto", "preset_mode": "sleep"},
        blocking=True,
    )
    assert (await _last_irhvac(mqtt_mock))["Sleep"] == 1


async def test_a_unit_does_not_beep_by_default(hass: HomeAssistant, mqtt_mock) -> None:
    """Before the extras, Beep was left out, and the library took it as off."""
    await setup_board(hass, board_entry(subentries_data=(SAMSUNG,)))
    await _turn_on(hass, "climate.ar_sala")
    assert (await _last_irhvac(mqtt_mock))["Beep"] == "Off"
    assert hass.states.get("switch.ar_sala_beep").state == "off"
