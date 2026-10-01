"""The extras an air conditioner protocol carries, beyond mode, temperature and fan.

IRHVAC takes eight of them: Turbo, Econo, Quiet and Sleep, which the climate
card offers as presets (one at a time, like the remotes do), and Light, Beep,
Clean and Filter, which become switches on the unit's device. Not every
protocol sends every one: the IR library quietly drops what a protocol has no
bit for, so a switch for it would look right and do nothing. What each vendor
really sends is below, read from ``IRac::sendAc`` in IRremoteESP8266 2.8.6, the
copy Tasmota builds (``IRac.cpp``). A vendor that is not listed sends none.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from homeassistant.components.climate import PRESET_BOOST, PRESET_ECO, PRESET_SLEEP

from .const import CONF_EXTRAS, CONF_VENDOR, LIGHT_TOGGLE_VENDORS

PRESET_EXTRAS: Final = ("turbo", "econo", "quiet", "sleep")
SWITCH_EXTRAS: Final = ("light", "beep", "clean", "filter")
ORDER: Final = PRESET_EXTRAS + SWITCH_EXTRAS

# The preset each extra is on the card. Quiet has no standard name.
PRESET_OF: Final[dict[str, str]] = {
    "turbo": PRESET_BOOST,
    "econo": PRESET_ECO,
    "quiet": "quiet",
    "sleep": PRESET_SLEEP,
}
# The key each extra has in an IRHVAC payload.
TASMOTA_KEY: Final[dict[str, str]] = {
    "turbo": "Turbo",
    "econo": "Econo",
    "quiet": "Quiet",
    "sleep": "Sleep",
    "light": "Light",
    "beep": "Beep",
    "clean": "Clean",
    "filter": "Filter",
}
# The switch's name, as a translation key: "light" is the unit's display.
SWITCH_TRANSLATION: Final[dict[str, str]] = {
    "light": "display",
    "beep": "beep",
    "clean": "self_clean",
    "filter": "filter",
}

VENDOR_EXTRAS: Final[dict[str, frozenset[str]]] = {
    "AIRTON": frozenset({"turbo", "econo", "sleep", "light", "filter"}),
    "ARGO": frozenset({"turbo", "econo", "quiet", "sleep", "light", "filter"}),
    "BOSCH144": frozenset({"quiet"}),
    "CARRIER_AC64": frozenset({"sleep"}),
    "COOLIX": frozenset({"turbo", "sleep", "light", "clean"}),
    "CORONA_AC": frozenset({"econo"}),
    "DAIKIN": frozenset({"turbo", "econo", "quiet", "clean"}),
    "DAIKIN128": frozenset({"turbo", "econo", "quiet", "sleep", "light"}),
    "DAIKIN152": frozenset({"turbo", "econo", "quiet"}),
    "DAIKIN2": frozenset(
        {"turbo", "econo", "quiet", "sleep", "light", "beep", "clean", "filter"}
    ),
    "DAIKIN216": frozenset({"turbo", "quiet"}),
    "DAIKIN64": frozenset({"turbo", "quiet", "sleep"}),
    "DELONGHI_AC": frozenset({"turbo", "sleep"}),
    "ELECTRA_AC": frozenset({"turbo", "quiet", "light", "clean"}),
    "EUROM": frozenset({"sleep"}),
    "FUJITSU_AC": frozenset({"turbo", "econo", "quiet", "sleep", "clean", "filter"}),
    "GOODWEATHER": frozenset({"turbo", "sleep", "light"}),
    "GREE": frozenset({"turbo", "econo", "sleep", "light", "clean"}),
    "HAIER_AC": frozenset({"sleep", "filter"}),
    "HAIER_AC160": frozenset({"turbo", "quiet", "sleep", "light", "clean", "filter"}),
    "HAIER_AC176": frozenset({"turbo", "quiet", "sleep", "filter"}),
    "HAIER_AC_YRW02": frozenset({"turbo", "quiet", "sleep", "filter"}),
    "HITACHI_AC1": frozenset({"sleep"}),
    "KELON": frozenset({"turbo", "sleep"}),
    "KELVINATOR": frozenset({"turbo", "quiet", "light", "clean", "filter"}),
    "LG": frozenset({"light"}),
    "LG2": frozenset({"light"}),
    "MIDEA": frozenset({"turbo", "econo", "quiet", "sleep", "light", "clean"}),
    "MITSUBISHI112": frozenset({"quiet"}),
    "MITSUBISHI136": frozenset({"quiet"}),
    "MITSUBISHI_AC": frozenset({"quiet"}),
    "MITSUBISHI_HEAVY_152": frozenset(
        {"turbo", "econo", "quiet", "sleep", "clean", "filter"}
    ),
    "MITSUBISHI_HEAVY_88": frozenset({"turbo", "econo", "clean"}),
    "NEOCLIMA": frozenset({"turbo", "econo", "sleep", "light", "filter"}),
    "PANASONIC_AC": frozenset({"turbo", "quiet"}),
    "SAMSUNG_AC": frozenset(
        {"turbo", "econo", "quiet", "sleep", "light", "beep", "clean", "filter"}
    ),
    "SANYO_AC": frozenset({"sleep", "beep"}),
    "SANYO_AC88": frozenset({"turbo", "sleep", "filter"}),
    "SHARP_AC": frozenset({"turbo", "light", "clean", "filter"}),
    "TCL112AC": frozenset({"turbo", "econo", "quiet", "light", "filter"}),
    "TECHNIBEL_AC": frozenset({"sleep"}),
    "TECO": frozenset({"sleep", "light"}),
    "TEKNOPOINT": frozenset({"turbo", "econo", "quiet", "light", "filter"}),
    "TOSHIBA_AC": frozenset({"turbo", "econo", "filter"}),
    "TROTEC": frozenset({"sleep"}),
    "TRUMA": frozenset({"quiet"}),
    "VESTEL_AC": frozenset({"turbo", "sleep", "filter"}),
    "VOLTAS": frozenset({"turbo", "econo", "sleep", "light"}),
    "WHIRLPOOL_AC": frozenset({"turbo", "sleep", "light"}),
}


# Extras the library treats as toggles, flipped against the previous state
# (IRac::handleToggles, and HAIER_AC160's display in IRac::sendAc). Tasmota only
# keeps what its receiver heard as that state, never what it sent, so sending
# one of these on every frame would flip it on every command. They are not
# offered, the same way the display of LIGHT_TOGGLE_VENDORS never was.
TOGGLE_EXTRAS: Final[dict[str, frozenset[str]]] = {
    "COOLIX": frozenset({"turbo", "light", "clean", "sleep"}),
    "TRANSCOLD": frozenset({"turbo", "light", "clean", "sleep"}),
    "DAIKIN128": frozenset({"light"}),
    "ELECTRA_AC": frozenset({"light"}),
    "FUJITSU_AC": frozenset({"turbo", "econo"}),
    "MIDEA": frozenset({"turbo", "econo", "light", "clean"}),
    "SHARP_AC": frozenset({"light"}),
    "MIRAGE": frozenset({"light", "clean"}),
    "SAMSUNG_AC": frozenset({"beep", "clean"}),
    "HAIER_AC160": frozenset({"light"}),
}

# Vendors whose Sleep is a timer in minutes before switching off, not a sleep
# mode (IRac::daikin2, fujitsu, samsung), or is read in a way no value means
# off (IRac::eurom): a sleep preset there would shut the unit down.
SLEEP_TIMER_VENDORS: Final = frozenset({"DAIKIN2", "FUJITSU_AC", "SAMSUNG_AC", "EUROM"})

# What Sleep "on" is sent as. 0 already counts as on for most vendors, but
# DAIKIN128 only sleeps above 0; 1 is on for both.
SLEEP_ON: Final = 1
SLEEP_OFF: Final = -1


def extras_offered(vendor: str) -> list[str]:
    """The extras worth offering for a vendor, in display order.

    Left out: a display the protocol toggles (as the climate entity always did
    with Light for those vendors), any other extra the library toggles, and a
    sleep that is really a switch-off timer.
    """
    name = vendor.upper()
    supported = VENDOR_EXTRAS.get(name, frozenset()) - TOGGLE_EXTRAS.get(
        name, frozenset()
    )
    if name in LIGHT_TOGGLE_VENDORS:
        supported = supported - {"light"}
    if name in SLEEP_TIMER_VENDORS:
        supported = supported - {"sleep"}
    return [extra for extra in ORDER if extra in supported]


def extras_default(vendor: str) -> list[str]:
    """What a new unit starts with: everything its protocol sends."""
    return extras_offered(vendor)


def appliance_extras(data: Mapping[str, Any]) -> list[str]:
    """The extras an air conditioner subentry has, never more than it can send.

    A unit added before extras existed has no list, and gets its vendor's.
    """
    vendor = str(data.get(CONF_VENDOR, ""))
    chosen = data.get(CONF_EXTRAS)
    offered = extras_offered(vendor)
    if chosen is None:
        return offered
    return [extra for extra in offered if extra in chosen]
