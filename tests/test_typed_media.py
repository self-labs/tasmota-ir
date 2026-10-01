"""TV or sound bar, as a media player."""

from __future__ import annotations

from homeassistant.components.media_player import MediaPlayerEntityFeature as F
from homeassistant.core import HomeAssistant

from .conftest import board_entry, receive, setup_board
from .typed_util import code, sent, typed

P, VU, VD, M = (
    code("0x20DF0001"),
    code("0x20DF0002"),
    code("0x20DF0003"),
    code("0x20DF0004"),
)
H1, OP = code("0x20DF0005"), code("0x20DF0006")
CU, CD, PP = code("0x20DF0007"), code("0x20DF0008"), code("0x20DF0009")
FULL = typed(
    "media",
    "JBL Soundbar",
    "jblkey",
    {
        "power": P,
        "volume_up": VU,
        "volume_down": VD,
        "mute": M,
        "sources": {"HDMI 1": H1, "Optical": OP},
        "channel_up": CU,
        "channel_down": CD,
        "play_pause": PP,
    },
)
E = "media_player.jbl_soundbar"


async def _call(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(
        "media_player", service, {"entity_id": E, **data}, blocking=True
    )


async def test_features_follow_what_was_learned(hass: HomeAssistant, mqtt_mock) -> None:
    await setup_board(
        hass,
        board_entry(
            subentries_data=(
                typed(
                    "media",
                    "JBL Soundbar",
                    "jblkey",
                    {"power": P, "volume_up": VU, "volume_down": VD},
                ),
            )
        ),
    )
    features = hass.states.get(E).attributes["supported_features"]
    assert features & F.TURN_ON and features & F.VOLUME_STEP
    assert not features & F.SELECT_SOURCE
    assert not features & F.VOLUME_MUTE


async def test_each_action_sends_its_key(hass: HomeAssistant, mqtt_mock) -> None:
    await setup_board(hass, board_entry(subentries_data=(FULL,)))
    await _call(hass, "turn_on")
    await _call(hass, "volume_up")
    await _call(hass, "volume_down")
    await _call(hass, "volume_mute", is_volume_muted=True)
    await _call(hass, "select_source", source="Optical")
    await _call(hass, "media_next_track")
    await _call(hass, "media_previous_track")
    await _call(hass, "media_play_pause")
    assert sent(mqtt_mock) == [
        P["Data"],
        VU["Data"],
        VD["Data"],
        M["Data"],
        OP["Data"],
        CU["Data"],
        CD["Data"],
        PP["Data"],
    ]
    state = hass.states.get(E)
    assert state.attributes["source"] == "Optical"
    assert state.attributes["source_list"] == ["HDMI 1", "Optical"]
    assert state.attributes["is_volume_muted"] is True


async def test_the_remote_sets_the_source_and_power(
    hass: HomeAssistant, mqtt_mock
) -> None:
    await setup_board(hass, board_entry(subentries_data=(FULL,)))
    receive(hass, P)
    receive(hass, H1)
    await hass.async_block_till_done()
    state = hass.states.get(E)
    assert state.state == "on"
    assert state.attributes["source"] == "HDMI 1"


async def test_off_is_off(hass: HomeAssistant, mqtt_mock) -> None:
    await setup_board(hass, board_entry(subentries_data=(FULL,)))
    await _call(hass, "turn_on")
    await _call(hass, "turn_off")
    assert hass.states.get(E).state == "off"
