"""The appliance types learned key by key, and the functions each one has.

A TV, a fan or a light is not a list of buttons: it is a media player, a fan, a
light. Each type below is a list of functions, and the flow that adds one only
asks for those, the entity only offers the ones that were learned. Keeping the
types as data means one flow and one entity base serve all five.

The learned codes live in the appliance's own subentry, under ``roles``, and
not in the store with the buttons. Moving or copying an appliance copies its
subentry, so its functions travel with it and nothing has to be relearned.

Three kinds of function:
- ``key``: one code, such as power or volume up;
- ``list``: several codes, each with a name, such as the sources "HDMI 1" and
  "Optical", in the order they were learned;
- ``number``: a setting, such as how many speeds a single cycling key goes
  through. Numbers live next to ``roles``, under their own name.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

SUBENTRY_MEDIA: Final = "media"
SUBENTRY_FAN: Final = "fan"
SUBENTRY_LIGHT: Final = "light"
SUBENTRY_COVER: Final = "cover"
SUBENTRY_SWITCH: Final = "switch"
TYPED_KINDS: Final = (
    SUBENTRY_MEDIA,
    SUBENTRY_FAN,
    SUBENTRY_LIGHT,
    SUBENTRY_COVER,
    SUBENTRY_SWITCH,
)

CONF_ROLES: Final = "roles"
CONF_POWER_SENSOR: Final = "power_sensor"
CONF_POWER_THRESHOLD: Final = "power_threshold"
DEFAULT_POWER_THRESHOLD: Final = 5.0


@dataclass(frozen=True, slots=True)
class Role:
    """One function of a type: its name and whether it is a key, a list or a number."""

    name: str
    kind: str


def _keys(*names: str) -> tuple[Role, ...]:
    return tuple(Role(name, "key") for name in names)


# Power is one key that toggles, or a pair of keys; either satisfies a type.
_POWER = _keys("power", "power_on", "power_off")

CATALOG: Final[dict[str, tuple[Role, ...]]] = {
    SUBENTRY_MEDIA: (
        *_POWER,
        *_keys("volume_up", "volume_down", "mute"),
        Role("sources", "list"),
        *_keys("channel_up", "channel_down", "play_pause"),
    ),
    SUBENTRY_FAN: (
        *_POWER,
        Role("speeds", "list"),
        Role("speed_cycle", "key"),
        Role("speed_count", "number"),
        Role("oscillate", "key"),
        Role("presets", "list"),
    ),
    SUBENTRY_LIGHT: (
        *_POWER,
        *_keys("brightness_up", "brightness_down"),
        Role("brightness_steps", "number"),
        *_keys("warmer", "cooler"),
        Role("color_temp_steps", "number"),
        Role("effects", "list"),
    ),
    SUBENTRY_COVER: (
        *_keys("open", "close", "stop"),
        Role("travel_time", "number"),
    ),
    SUBENTRY_SWITCH: _POWER,
}

# What a number is until the person sets it. A cover has no travel time until
# one is given, and without it no position is offered.
NUMBER_DEFAULTS: Final[dict[str, int | float | None]] = {
    "speed_count": 3,
    "brightness_steps": 10,
    "color_temp_steps": 5,
    "travel_time": None,
}


def role(kind: str, name: str) -> Role:
    """The function ``name`` of type ``kind``; KeyError when it has none."""
    for item in CATALOG[kind]:
        if item.name == name:
            return item
    raise KeyError(name)


def is_list(kind: str, name: str) -> bool:
    """Whether a function of this type is a list of named keys.

    Asked of the catalogue, never of the stored value: a list whose item is
    called "Protocol" looks exactly like a code.
    """
    try:
        return role(kind, name).kind == "list"
    except KeyError:
        return False


def missing_required(kind: str, roles: Mapping[str, Any]) -> list[str]:
    """What still has to be learned before the appliance can be created."""
    if kind == SUBENTRY_COVER:
        return [name for name in ("open", "close") if name not in roles]
    if "power" in roles or ("power_on" in roles and "power_off" in roles):
        return []
    return ["power"]


def roles_of(data: Mapping[str, Any]) -> dict[str, Any]:
    """The learned functions of an appliance's subentry data."""
    return dict(data.get(CONF_ROLES) or {})


def number_of(data: Mapping[str, Any], name: str) -> int | float | None:
    """A number the person set, or its default."""
    value = data.get(name)
    return NUMBER_DEFAULTS[name] if value is None else value
