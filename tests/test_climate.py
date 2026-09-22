"""Adding an air conditioner from its remote, and driving the vane."""

from __future__ import annotations

import json

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import LG_AC_FRAME, TOPIC, board_entry, receive, setup_board


async def _add_ac(hass: HomeAssistant, entry) -> None:
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "climate"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await manager.async_configure(
        result["flow_id"], {"name": "Ar Escritorio", "channel": 4}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["description_placeholders"]["name"] == "Ar Escritorio"
    receive(hass, LG_AC_FRAME)
    await hass.async_block_till_done()
    result = await manager.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


async def test_the_remote_names_the_unit(hass: HomeAssistant, mqtt_mock) -> None:
    """Vendor and model come from the frame, and the vane is offered."""
    entry = await setup_board(hass, board_entry())
    await _add_ac(hass, entry)

    (subentry,) = entry.subentries.values()
    assert subentry.data["vendor"] == "LG2"
    assert subentry.data["model"] == "AKB75215403"
    state = hass.states.get("climate.ar_escritorio")
    assert state is not None
    assert "lowest" in state.attributes["swing_modes"]


async def test_the_vane_is_sent_with_the_frame(hass: HomeAssistant, mqtt_mock) -> None:
    """SwingV, Light and the emitter travel in the IRHVAC payload."""
    entry = await setup_board(hass, board_entry())
    await _add_ac(hass, entry)

    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": "climate.ar_escritorio", "hvac_mode": "cool"},
        blocking=True,
    )
    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_swing_mode",
        {"entity_id": "climate.ar_escritorio", "swing_mode": "auto"},
        blocking=True,
    )
    topic, payload = mqtt_mock.async_publish.call_args.args[:2]
    assert topic == f"cmnd/{TOPIC}/IRHVAC"
    body = json.loads(payload)
    assert body["SwingV"] == "Auto"
    assert body["Light"] == "On"
    assert body["Channel"] == 4
    assert body["Model"] == "AKB75215403"


async def test_the_physical_remote_moves_the_card(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """A frame heard from the remote updates mode and temperature."""
    entry = await setup_board(hass, board_entry())
    await _add_ac(hass, entry)

    frame = json.loads(json.dumps(LG_AC_FRAME))
    frame["IRHVAC"].update({"Temp": 19, "Mode": "Dry"})
    receive(hass, frame)
    await hass.async_block_till_done()

    state = hass.states.get("climate.ar_escritorio")
    assert state.state == "dry"
    assert state.attributes["temperature"] == 19


async def test_an_lg_vane_key_moves_only_the_vane(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """Captured live: a vane key decodes with Mode Auto and Temp 15 filled in.

    Those two are firmware defaults, not the unit's state, and taking them
    would throw the card to 15 degrees every time the vane moved.
    """
    entry = await setup_board(hass, board_entry())
    await _add_ac(hass, entry)
    receive(hass, LG_AC_FRAME)
    await hass.async_block_till_done()

    receive(
        hass,
        {
            "Protocol": "LG2",
            "Bits": 28,
            "Data": "0x881308C",
            "DataLSB": "0x10810C31",
            "Repeat": 0,
            "IRHVAC": {
                "Vendor": "LG2",
                "Model": "AKB74955603",
                "Command": "Control",
                "Mode": "Auto",
                "Power": "On",
                "Celsius": "On",
                "Temp": 15,
                "FanSpeed": "Auto",
                "SwingV": "High",
                "SwingH": "Off",
                "Light": "On",
            },
        },
    )
    await hass.async_block_till_done()

    state = hass.states.get("climate.ar_escritorio")
    assert state.state == "cool"
    assert state.attributes["temperature"] == 23
    assert state.attributes["fan_mode"] == "medium"
    assert state.attributes["swing_mode"] == "high"


async def test_an_off_frame_keeps_the_setpoint(hass: HomeAssistant, mqtt_mock) -> None:
    """LG turns off with a fixed code; its temperature means nothing."""
    entry = await setup_board(hass, board_entry())
    await _add_ac(hass, entry)
    receive(hass, LG_AC_FRAME)
    await hass.async_block_till_done()

    receive(
        hass,
        {
            "Protocol": "LG2",
            "Bits": 28,
            "Data": "0x88C0051",
            "IRHVAC": {"Vendor": "LG2", "Power": "Off", "Mode": "Auto", "Temp": 15},
        },
    )
    await hass.async_block_till_done()

    state = hass.states.get("climate.ar_escritorio")
    assert state.state == "off"
    assert state.attributes["temperature"] == 23


async def test_settings_change_the_model_and_the_modes(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """The model an LG needs for its vane is set from the menu."""
    entry = await setup_board(hass, board_entry())
    await _add_ac(hass, entry)
    (subentry,) = entry.subentries.values()
    manager = hass.config_entries.subentries

    result = await manager.async_init(
        (entry.entry_id, "climate"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["type"] is FlowResultType.MENU
    result = await manager.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await manager.async_configure(
        result["flow_id"],
        {
            "model": "AKB74955603",
            "min_temp": 18,
            "max_temp": 30,
            "hvac_modes": ["off", "cool", "dry", "fan_only"],
            "swing_vertical": True,
            "swing_horizontal": False,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()

    state = hass.states.get("climate.ar_escritorio")
    assert state.attributes["model"] == "AKB74955603"
    assert "heat" not in state.attributes["hvac_modes"]
