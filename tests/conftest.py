"""Shared fixtures: a board on a mocked broker."""

from __future__ import annotations

import json
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.tasmota_ir.const import DOMAIN

TOPIC = "tasmota_2C3124"
MAC = "80:45:6b:2c:31:24"
RESULT_TOPIC = f"tele/{TOPIC}/RESULT"

BOARD_DATA: dict[str, Any] = {
    "topic": TOPIC,
    "full_topic": "%prefix%/%topic%/",
    "mac": MAC,
    "channels": 8,
    "has_receiver": True,
}

NEC_POWER = {"Protocol": "NEC", "Bits": 32, "Data": "0x20DF10EF"}
LG_AC_FRAME = {
    "Protocol": "LG2",
    "Bits": 28,
    "Data": "0x8808F07",
    "IRHVAC": {
        "Vendor": "LG2",
        "Model": "AKB75215403",
        "Mode": "Cool",
        "Power": "On",
        "Celsius": "On",
        "Temp": 23,
        "FanSpeed": "Medium",
        "SwingV": "Off",
        "SwingH": "Off",
        "Light": "On",
    },
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client keeps a periodic housekeeping timer alive.

    It belongs to the MQTT integration, not to this one, and it is still
    scheduled when the test ends.
    """
    return True


def board_entry(**kwargs: Any) -> MockConfigEntry:
    """A board entry as the config flow would have written it."""
    params: dict[str, Any] = {
        "domain": DOMAIN,
        "title": "Hubb IR1",
        "unique_id": MAC,
        "version": 2,
        "data": BOARD_DATA,
    }
    params.update(kwargs)
    return MockConfigEntry(**params)


async def setup_board(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    """Add the entry and let it settle."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def receive(hass: HomeAssistant, frame: dict[str, Any]) -> None:
    """Pretend the board's receiver heard a frame."""
    async_fire_mqtt_message(hass, RESULT_TOPIC, json.dumps({"IrReceived": frame}))
