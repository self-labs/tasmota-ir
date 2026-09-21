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

# Config entry options, edited by the options flow.
CONF_APPLIANCES: Final = "appliances"
CONF_CHANNEL: Final = "channel"
CONF_KIND: Final = "kind"
CONF_VENDOR: Final = "vendor"
CONF_MODEL: Final = "model"
CONF_MIN_TEMP: Final = "min_temp"
CONF_MAX_TEMP: Final = "max_temp"

KIND_GENERIC: Final = "generic"
KIND_CLIMATE: Final = "climate"

# Tasmota commands and payload keys.
CMND_IRSEND: Final = "IRSend"
CMND_IRHVAC: Final = "IRHVAC"
CMND_GPIO: Final = "Gpio"
KEY_IR_RECEIVED: Final = "IrReceived"
KEY_IRHVAC: Final = "IRHVAC"
KEY_CHANNEL: Final = "Channel"

# The firmware counts IR emitters from 1 and reports them as IRsend1..IRsendN
# in the reply to the Gpio command. Sixteen is the ceiling MAX_IRSEND imposes.
GPIO_IRSEND_PREFIX: Final = "IRsend"
GPIO_IRRECV: Final = "IRrecv"
MAX_CHANNELS: Final = 16
DEFAULT_CHANNEL: Final = 1

# Storage. The payload is {appliance: {command: code}}.
STORAGE_VERSION: Final = 1
STORAGE_KEY_FORMAT: Final = f"{DOMAIN}_{{entry_id}}_codes"
STORAGE_SAVE_DELAY: Final = 5

# Timeouts, in seconds.
LEARN_TIMEOUT: Final = 20
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
