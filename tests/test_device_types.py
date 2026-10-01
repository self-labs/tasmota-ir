"""The functions each device type has, as data."""

from __future__ import annotations

import pytest

from custom_components.tasmota_ir.device_types import (
    CATALOG,
    NUMBER_DEFAULTS,
    TYPED_KINDS,
    missing_required,
    number_of,
    role,
    roles_of,
)

C = {"Protocol": "NEC", "Bits": 32, "Data": "0x10EF0001"}


def test_the_five_kinds() -> None:
    assert TYPED_KINDS == ("media", "fan", "light", "cover", "switch")
    assert set(CATALOG) == set(TYPED_KINDS)


def test_power_is_one_key_or_the_pair() -> None:
    assert missing_required("switch", {}) == ["power"]
    assert missing_required("switch", {"power": C}) == []
    assert missing_required("switch", {"power_on": C}) == ["power"]
    assert missing_required("switch", {"power_on": C, "power_off": C}) == []
    assert missing_required("media", {"volume_up": C}) == ["power"]


def test_a_cover_needs_open_and_close() -> None:
    assert missing_required("cover", {}) == ["open", "close"]
    assert missing_required("cover", {"open": C}) == ["close"]
    assert missing_required("cover", {"open": C, "close": C}) == []


def test_each_function_has_its_kind() -> None:
    assert role("media", "sources").kind == "list"
    assert role("fan", "speed_count").kind == "number"
    assert role("light", "warmer").kind == "key"
    with pytest.raises(KeyError):
        role("cover", "volume_up")


def test_numbers_have_defaults() -> None:
    assert NUMBER_DEFAULTS == {
        "speed_count": 3,
        "brightness_steps": 10,
        "color_temp_steps": 5,
        "travel_time": None,
    }
    assert number_of({"speed_count": 4}, "speed_count") == 4
    assert number_of({}, "brightness_steps") == 10


def test_roles_come_from_the_subentry_data() -> None:
    assert roles_of({"roles": {"power": C}}) == {"power": C}
    assert roles_of({}) == {}
