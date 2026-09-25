"""Constants for the Tasmota IR integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "tasmota_ir"

# Config entry data, written once by the config flow.
CONF_TOPIC: Final = "topic"
CONF_FULL_TOPIC: Final = "full_topic"
CONF_MAC: Final = "mac"
CONF_CHANNELS: Final = "channels"
CONF_HAS_RECEIVER: Final = "has_receiver"

# Every appliance is a config subentry of its board, so Home Assistant lists it
# under the board with its own device, its own commands and its own menu.
SUBENTRY_APPLIANCE: Final = "appliance"
SUBENTRY_CLIMATE: Final = "climate"

# Subentry data.
CONF_CHANNEL: Final = "channel"
CONF_VENDOR: Final = "vendor"
CONF_MODEL: Final = "model"
CONF_LIGHT: Final = "light"
CONF_MIN_TEMP: Final = "min_temp"
CONF_MAX_TEMP: Final = "max_temp"
CONF_HVAC_MODES: Final = "hvac_modes"
CONF_SWING_VERTICAL: Final = "swing_vertical"
CONF_SWING_HORIZONTAL: Final = "swing_horizontal"
CONF_INITIAL_SWING_VERTICAL: Final = "initial_swing_vertical"

# Version 1 kept the appliances in the entry options. Only the migration reads
# these any more.
CONF_APPLIANCES: Final = "appliances"
CONF_KIND: Final = "kind"
KIND_CLIMATE: Final = "climate"

DEFAULT_MIN_TEMP: Final = 18
DEFAULT_MAX_TEMP: Final = 30

# Vendors whose remotes come in several models that the decoder cannot tell
# apart from an ordinary frame. The model decides which features the library
# sends at all: an LG set to AKB75215403 never sends the vane, while the same
# unit set to AKB74955603 does. The flow offers these, and accepts any other.
KNOWN_MODELS: Final[dict[str, tuple[str, ...]]] = {
    "LG": ("GE6711AR2853M", "LG6711A20083V"),
    "LG2": ("AKB75215403", "AKB74955603", "AKB73757604"),
    "FUJITSU_AC": ("ARRAH2E", "ARDB1", "ARREB1E", "ARJW2", "ARRY4", "ARREW4E"),
    "GREE": ("YAW1F", "YBOFB", "YX1FSF"),
    "PANASONIC_AC": ("LKE", "NKE", "DKE", "JKE", "CKP", "RKR", "PKR"),
    "SHARP_AC": ("A907", "A705", "A903"),
    "TCL112AC": ("TAC09CHSD", "GZ055BE1"),
    "WHIRLPOOL_AC": ("DG11J13A", "DG11J191"),
}

# Protocols where the vane is a toggle, not a position (IRac::handleToggles).
# The firmware keeps one previous state per board, updated only by what the
# receiver hears, so asking for "swing" there flips it on every command. The
# vane stays off by default for these.
SWING_TOGGLE_VENDORS: Final = frozenset(
    {
        "COOLIX",
        "TRANSCOLD",
        "MIDEA",
        "CORONA_AC",
        "HITACHI_AC344",
        "HITACHI_AC424",
        "SHARP_AC",
        "KELON",
    }
)


def swing_vertical_default(vendor: str) -> bool:
    """Whether the vertical vane is offered unless the user says otherwise."""
    return vendor.upper() not in SWING_TOGGLE_VENDORS


# LG sends some keys as frames of their own that carry no state at all: the
# vane, the horizontal vane and the display toggle. The firmware still decodes
# them into a full IRHVAC, filling mode, temperature and fan with defaults (seen
# live: Mode Auto, Temp 15 on every vane key). Reading those back would throw the
# card to 15 degrees whenever somebody moved the vane with the remote.
LG_VENDORS: Final = frozenset({"LG", "LG2"})
LG_VANE_PREFIX: Final = "0X8813"
LG_VANE_TOGGLE: Final = "0X8810001"
LG_DISPLAY_TOGGLE: Final = "0X88C00A6"


# The same, for the display light. Sending "Light" to these would flip the
# display instead of setting it, so the key is left out for them.
LIGHT_TOGGLE_VENDORS: Final = frozenset(
    {
        "COOLIX",
        "TRANSCOLD",
        "DAIKIN128",
        "ELECTRA_AC",
        "MIDEA",
        "SHARP_AC",
        "AIRWELL",
        "DAIKIN64",
        "PANASONIC_AC32",
        "WHIRLPOOL_AC",
        "MIRAGE",
    }
)

# Tasmota commands and payload keys.
CMND_IRSEND: Final = "IRSend"
CMND_IRHVAC: Final = "IRHVAC"
CMND_GPIO: Final = "Gpio"
KEY_IR_RECEIVED: Final = "IrReceived"
KEY_IRHVAC: Final = "IRHVAC"
KEY_CHANNEL: Final = "Channel"
KEY_RAW_DATA: Final = "RawData"
KEY_FREQUENCY: Final = "Frequency"
PROTOCOL_RAW: Final = "RAW"
# Raw codes have two forms. The plain "IRSend <freq>,<data>" works on every
# firmware and always leaves through the first emitter. The JSON form,
# {"RawData":..., "Frequency":..., "Channel":...}, picks the emitter, and only
# a firmware carrying arendst/Tasmota#25062 understands it; an older one answers
# "Wrong Protocol" and sends nothing. 38 kHz is what consumer infrared uses and
# what the receiver assumes.
RAW_FREQUENCY: Final = 38000
# How long to wait for the board to say whether it took a raw code as JSON. It
# answers in well under a second; this only runs out when the reply is lost.
RAW_REPLY_TIMEOUT: Final = 5

# The firmware counts IR emitters from 1 and reports them as IRsend1..IRsendN
# in the reply to the Gpio command. Sixteen is the ceiling MAX_IRSEND imposes.
GPIO_IRSEND_PREFIX: Final = "IRsend"
GPIO_IRRECV: Final = "IRrecv"
MAX_CHANNELS: Final = 16
DEFAULT_CHANNEL: Final = 1

# Storage. The payload is {appliance key: {command: code}}, where the key is
# the subentry unique_id, so renaming an appliance moves nothing.
STORAGE_VERSION: Final = 1
STORAGE_KEY_FORMAT: Final = f"{DOMAIN}_{{entry_id}}_codes"
STORAGE_SAVE_DELAY: Final = 5

# Timeouts, in seconds. Learning from the interface waits longer than the
# action: there the person still has to find the remote after clicking.
LEARN_TIMEOUT: Final = 20
LEARN_TIMEOUT_UI: Final = 30
PROBE_TIMEOUT: Final = 10
DEFAULT_SEND_DELAY: Final = 0.4

# A code above this size cannot be published: the board rejects anything larger
# than its MQTT packet buffer, which defaults to 1200 bytes and has to carry the
# topic and the rest of the payload as well.
MAX_CODE_BYTES: Final = 1000

# Signals, used to hand newly learned commands to the button platform without
# either platform importing the other.
SIGNAL_CODES_UPDATED: Final = f"{DOMAIN}_codes_updated_{{entry_id}}"
SIGNAL_IR_RECEIVED: Final = f"{DOMAIN}_ir_received_{{entry_id}}"
SIGNAL_AVAILABILITY: Final = f"{DOMAIN}_availability_{{entry_id}}"
