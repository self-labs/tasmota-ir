"""Each appliance's own remote as a trigger: one event per learned key."""

from __future__ import annotations

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import NEC_POWER, board_entry, receive, setup_board
from .typed_util import code, typed

TV = {
    "data": {"channel": 1},
    "subentry_type": "appliance",
    "title": "TV Quarto",
    "unique_id": "tvkey",
}
AC = {
    "data": {"channel": 2, "vendor": "LG2", "model": "", "light": "On"},
    "subentry_type": "climate",
    "title": "Ar Escritorio",
    "unique_id": "ackey",
}
VOL = {"Protocol": "NEC", "Bits": 32, "Data": "0x20DF40BF"}
E = "event.tv_quarto_remote"


async def test_a_key_of_the_remote_fires_its_event(
    hass: HomeAssistant, mqtt_mock
) -> None:
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    await entry.runtime_data.async_store_codes("tvkey", {"power": NEC_POWER})
    await hass.async_block_till_done()
    assert hass.states.get(E).attributes["event_types"] == ["power"]

    receive(hass, NEC_POWER)
    await hass.async_block_till_done()

    state = hass.states.get(E)
    assert state.attributes["event_type"] == "power"


async def test_a_key_learned_later_joins_the_types(
    hass: HomeAssistant, mqtt_mock
) -> None:
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    await entry.runtime_data.async_store_codes("tvkey", {"power": NEC_POWER})
    await entry.runtime_data.async_store_codes("tvkey", {"volume up": VOL})
    await hass.async_block_till_done()

    assert hass.states.get(E).attributes["event_types"] == ["power", "volume up"]
    receive(hass, VOL)
    await hass.async_block_till_done()
    assert hass.states.get(E).attributes["event_type"] == "volume up"


async def test_a_typed_appliance_fires_its_functions(
    hass: HomeAssistant, mqtt_mock
) -> None:
    hdmi = code("0x20DF0005")
    await setup_board(
        hass,
        board_entry(
            subentries_data=(
                typed(
                    "media",
                    "JBL Soundbar",
                    "jblkey",
                    {"power": NEC_POWER, "sources": {"HDMI 1": hdmi}},
                ),
            )
        ),
    )
    entity_id = "event.jbl_soundbar_remote"
    assert hass.states.get(entity_id).attributes["event_types"] == ["power", "HDMI 1"]
    receive(hass, hdmi)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["event_type"] == "HDMI 1"


async def test_a_raw_code_never_fires(hass: HomeAssistant, mqtt_mock) -> None:
    """Two captures of the same raw key are never identical to compare."""
    raw = {"Protocol": "RAW", "RawData": "+9000-4500+560", "Frequency": 38000}
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    await entry.runtime_data.async_store_codes("tvkey", {"power": raw})
    await hass.async_block_till_done()
    # Not even offered: an event type that can never fire is a trap.
    assert hass.states.get(E).attributes["event_types"] == []
    receive(
        hass,
        {"Protocol": "UNKNOWN", "Bits": 0, "Data": "0x0", "RawData": "+9000-4500+560"},
    )
    await hass.async_block_till_done()
    assert hass.states.get(E).state == "unknown"


async def test_an_air_conditioner_has_no_remote_event(
    hass: HomeAssistant, mqtt_mock, entity_registry: er.EntityRegistry
) -> None:
    """Its climate entity already follows the remote, frame by frame."""
    await setup_board(hass, board_entry(subentries_data=(AC,)))
    assert (
        entity_registry.async_get_entity_id("event", "tasmota_ir", "ackey_remote")
        is None
    )


async def test_a_deleted_key_leaves_the_types(hass: HomeAssistant, mqtt_mock) -> None:
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    await entry.runtime_data.async_store_codes(
        "tvkey", {"power": NEC_POWER, "volume up": VOL}
    )
    await hass.async_block_till_done()
    await entry.runtime_data.async_delete_code("tvkey", "power")
    await hass.async_block_till_done()
    assert hass.states.get(E).attributes["event_types"] == ["volume up"]


async def test_two_keys_on_one_code_both_fire(hass: HomeAssistant, mqtt_mock) -> None:
    """The same key learned twice, under two names: each name is a trigger."""
    entry = await setup_board(hass, board_entry(subentries_data=(TV,)))
    await entry.runtime_data.async_store_codes(
        "tvkey", {"power": NEC_POWER, "on": NEC_POWER}
    )
    await hass.async_block_till_done()
    fired: list[str] = []

    def _changed(event: Event) -> None:
        if event.data["entity_id"] == E and event.data["new_state"]:
            fired.append(event.data["new_state"].attributes.get("event_type"))

    hass.bus.async_listen(EVENT_STATE_CHANGED, _changed)
    receive(hass, NEC_POWER)
    await hass.async_block_till_done()
    assert fired == ["power", "on"]


async def test_a_source_named_like_a_function_does_not_hide_it(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """A list item called "power" must not take the power key's place."""
    await setup_board(
        hass,
        board_entry(
            subentries_data=(
                typed(
                    "media",
                    "JBL Soundbar",
                    "jblkey",
                    {"power": NEC_POWER, "sources": {"power": code("0x20DF0005")}},
                ),
            )
        ),
    )
    receive(hass, NEC_POWER)
    await hass.async_block_till_done()
    assert (
        hass.states.get("event.jbl_soundbar_remote").attributes["event_type"] == "power"
    )


async def test_the_entity_id_follows_the_language(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """Home Assistant names entity ids in its own language: the README says so."""
    hass.config.language = "pt-BR"
    await setup_board(hass, board_entry(subentries_data=(TV,)))
    assert hass.states.get("event.tv_quarto_controle") is not None
    assert hass.states.get("infrared.tv_quarto_receptor_infravermelho") is not None
    assert hass.states.get("event.hubb_ir1_ir_receiver") is not None
