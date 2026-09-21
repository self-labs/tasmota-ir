"""The single MQTT conversation with one Tasmota board.

Every platform in this integration talks to the board through this object. It
owns the subscriptions, the learned codes and the appliance to emitter mapping,
so no entity ever builds a topic or guesses a channel by itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import (
    CMND_GPIO,
    CMND_IRSEND,
    CONF_APPLIANCES,
    CONF_CHANNEL,
    CONF_FULL_TOPIC,
    CONF_TOPIC,
    DEFAULT_CHANNEL,
    GPIO_IRRECV,
    GPIO_IRSEND_PREFIX,
    KEY_CHANNEL,
    KEY_IR_RECEIVED,
    MAX_CHANNELS,
    KEY_IRHVAC,
    KEY_RAW_DATA,
    MAX_CODE_BYTES,
    PROBE_TIMEOUT,
    PROTOCOL_RAW,
    RAW_FREQUENCY,
    SIGNAL_AVAILABILITY,
    SIGNAL_CODES_UPDATED,
    SIGNAL_IR_RECEIVED,
    STORAGE_KEY_FORMAT,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


class CodeTooLargeError(Exception):
    """A captured code does not fit in the board's MQTT buffer."""


class TasmotaIrCoordinator:
    """Owns the MQTT link, the learned codes and the appliance mapping."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Set up the coordinator without touching the network yet."""
        self.hass = hass
        self.entry = entry
        self.topic: str = entry.data[CONF_TOPIC]
        self.full_topic: str = entry.data.get(CONF_FULL_TOPIC, "%prefix%/%topic%/")
        # Optimistic until the board says otherwise. The retained LWT arrives
        # within milliseconds of subscribing and corrects this, while starting
        # at False would leave every entity unavailable on a board that was
        # configured without a last will at all.
        self.available = True

        self._store: Store[dict[str, dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_FORMAT.format(entry_id=entry.entry_id)
        )
        self._codes: dict[str, dict[str, Any]] = {}
        self._unsubscribes: list[Callable[[], None]] = []
        self._ir_waiters: list[asyncio.Future[dict[str, Any]]] = []

    # ------------------------------------------------------------------
    # Topics
    # ------------------------------------------------------------------

    def _build_topic(self, prefix: str, command: str = "") -> str:
        """Render a Tasmota topic, honouring a custom FullTopic."""
        base = (
            self.full_topic.replace("%prefix%", prefix)
            .replace("%topic%", self.topic)
            .replace("%hostname%", self.topic)
            .replace("%id%", self.topic)
        )
        if not base.endswith("/"):
            base += "/"
        return f"{base}{command}" if command else base.rstrip("/")

    @property
    def result_topic(self) -> str:
        """Where the board publishes what its receiver heard."""
        return self._build_topic("tele", "RESULT")

    @property
    def lwt_topic(self) -> str:
        """Where the board publishes its availability."""
        return self._build_topic("tele", "LWT")

    def command_topic(self, command: str) -> str:
        """Where a command is published."""
        return self._build_topic("cmnd", command)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Load the stored codes and subscribe to the board."""
        self._codes = await self._store.async_load() or {}

        self._unsubscribes.append(
            await mqtt.async_subscribe(self.hass, self.result_topic, self._handle_result)
        )
        self._unsubscribes.append(
            await mqtt.async_subscribe(self.hass, self.lwt_topic, self._handle_lwt)
        )

    async def async_unload(self) -> None:
        """Drop the subscriptions and flush pending writes."""
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        for waiter in self._ir_waiters:
            if not waiter.done():
                waiter.cancel()
        self._ir_waiters.clear()
        await self._store.async_save(self._codes)

    # ------------------------------------------------------------------
    # Incoming MQTT
    # ------------------------------------------------------------------

    @callback
    def _handle_lwt(self, message: mqtt.ReceiveMessage) -> None:
        """Track whether the board is online, and tell the entities.

        Flipping the flag is not enough: an entity reads ``available`` when its
        state is written, so without this dispatch it keeps whatever it had at
        the moment it was created. The retained LWT almost always lands after
        the platforms are set up, which is exactly when that goes wrong.
        """
        available = message.payload == "Online"
        if available == self.available:
            return
        self.available = available
        async_dispatcher_send(
            self.hass, SIGNAL_AVAILABILITY.format(entry_id=self.entry.entry_id)
        )

    @callback
    def _handle_result(self, message: mqtt.ReceiveMessage) -> None:
        """Dispatch an IrReceived payload to whoever is waiting for it."""
        try:
            payload = json.loads(message.payload)
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        received = payload.get(KEY_IR_RECEIVED)
        if not isinstance(received, dict):
            return

        # A partial capture is worse than no capture: it looks like a valid code
        # and reproduces nothing. Long frames, air conditioners above all, decode
        # this way whenever two presses arrive back to back.
        if not is_usable_code(received):
            _LOGGER.debug("Discarding a partial IR capture: %s", received)
            return

        for waiter in list(self._ir_waiters):
            if not waiter.done():
                waiter.set_result(received)

        async_dispatcher_send(
            self.hass,
            SIGNAL_IR_RECEIVED.format(entry_id=self.entry.entry_id),
            received,
        )

    async def async_wait_for_code(self, timeout: float) -> dict[str, Any] | None:
        """Wait for the next usable code the receiver reports."""
        waiter: asyncio.Future[dict[str, Any]] = self.hass.loop.create_future()
        self._ir_waiters.append(waiter)
        try:
            async with asyncio.timeout(timeout):
                return await waiter
        except TimeoutError:
            return None
        finally:
            if waiter in self._ir_waiters:
                self._ir_waiters.remove(waiter)

    # ------------------------------------------------------------------
    # Outgoing MQTT
    # ------------------------------------------------------------------

    async def async_send_raw(self, command: str, payload: str) -> None:
        """Publish a command to the board."""
        await mqtt.async_publish(self.hass, self.command_topic(command), payload)

    async def async_send_json(
        self, command: str, payload: dict[str, Any], channel: int | None = None
    ) -> None:
        """Publish a JSON command, injecting the emitter when one is given."""
        body = dict(payload)
        if channel is not None:
            body[KEY_CHANNEL] = channel
        encoded = json.dumps(body, separators=(",", ":"))
        if len(encoded) > MAX_CODE_BYTES:
            raise CodeTooLargeError(
                f"payload of {len(encoded)} bytes exceeds the board's MQTT buffer"
            )
        await self.async_send_raw(command, encoded)

    async def async_send_code(
        self, code: dict[str, Any], channel: int | None = None
    ) -> None:
        """Send a stored code, in whichever form the firmware accepts.

        A decoded protocol goes as JSON and carries the emitter. A raw capture
        cannot: ``CmndIrSend`` routes on whether the payload contains a brace,
        so raw has to be the plain ``IRSend <freq>,<data>`` form, and that form
        has no channel parameter at all. Raw therefore always leaves through the
        first emitter, which is the firmware's limit and not a choice made here.
        """
        if code.get("Protocol") == PROTOCOL_RAW:
            raw = code.get(KEY_RAW_DATA)
            if not raw:
                raise CodeTooLargeError("the stored raw code is empty")
            frequency = code.get("Frequency", RAW_FREQUENCY)
            payload = f"{frequency},{raw}"
            if len(payload) > MAX_CODE_BYTES:
                raise CodeTooLargeError(
                    f"the raw code is {len(payload)} bytes, above the "
                    f"{MAX_CODE_BYTES} the board accepts in one message"
                )
            if channel not in (None, 1):
                _LOGGER.warning(
                    "Sending a raw code on emitter 1 instead of %s: the "
                    "firmware's raw form takes no channel",
                    channel,
                )
            await self.async_send_raw(CMND_IRSEND, payload)
            return

        await self.async_send_json(CMND_IRSEND, code, channel=channel)

    async def async_probe_channels(self) -> tuple[int, bool]:
        """Ask the board how many emitters it has and whether it can receive.

        Returns the emitter count and whether an IRrecv GPIO is assigned. Falls
        back to a single emitter, which is what the firmware itself assumes when
        no channel is given.
        """
        reply = await self._async_command_reply(CMND_GPIO, "255")
        if reply is None:
            return DEFAULT_CHANNEL, False
        return count_ir_gpios(reply)

    async def _async_command_reply(
        self, command: str, payload: str
    ) -> dict[str, Any] | None:
        """Publish a command and wait for the matching stat/ reply."""
        future: asyncio.Future[dict[str, Any]] = self.hass.loop.create_future()

        @callback
        def _handle(message: mqtt.ReceiveMessage) -> None:
            if future.done():
                return
            try:
                parsed = json.loads(message.payload)
            except ValueError:
                return
            if isinstance(parsed, dict):
                future.set_result(parsed)

        unsubscribe = await mqtt.async_subscribe(
            self.hass, self._build_topic("stat", "RESULT"), _handle
        )
        try:
            await self.async_send_raw(command, payload)
            async with asyncio.timeout(PROBE_TIMEOUT):
                return await future
        except TimeoutError:
            return None
        finally:
            unsubscribe()

    # ------------------------------------------------------------------
    # Appliances and their emitters
    # ------------------------------------------------------------------

    @property
    def appliances(self) -> dict[str, dict[str, Any]]:
        """The configured appliances, keyed by name."""
        return dict(self.entry.options.get(CONF_APPLIANCES, {}))

    def channel_for(self, appliance: str | None) -> int:
        """The emitter an appliance is wired to.

        Nobody types this. It is configured once, which is the whole point: a
        channel that is never entered is a channel that is never entered wrong.
        """
        if not appliance:
            return DEFAULT_CHANNEL
        config = self.appliances.get(appliance)
        if not config:
            return DEFAULT_CHANNEL
        return int(config.get(CONF_CHANNEL, DEFAULT_CHANNEL))

    # ------------------------------------------------------------------
    # Learned codes
    # ------------------------------------------------------------------

    @property
    def codes(self) -> dict[str, dict[str, Any]]:
        """Every learned code, as {appliance: {command: code}}."""
        return self._codes

    def get_code(self, appliance: str, command: str) -> dict[str, Any] | None:
        """One learned code, or None."""
        return self._codes.get(appliance, {}).get(command)

    async def async_store_code(
        self, appliance: str, command: str, code: dict[str, Any]
    ) -> None:
        """Remember a code and tell the button platform about it."""
        encoded = json.dumps(code, separators=(",", ":"))
        if len(encoded) > MAX_CODE_BYTES:
            raise CodeTooLargeError(
                f"the captured code is {len(encoded)} bytes, above the "
                f"{MAX_CODE_BYTES} the board can accept in one message"
            )
        self._codes.setdefault(appliance, {})[command] = code
        self._schedule_save()
        self._notify_codes_changed()

    async def async_delete_code(self, appliance: str, command: str) -> bool:
        """Forget a code. Returns whether there was one."""
        commands = self._codes.get(appliance)
        if not commands or command not in commands:
            return False
        del commands[command]
        if not commands:
            del self._codes[appliance]
        self._schedule_save()
        self._notify_codes_changed()
        return True

    async def async_rename_appliance(self, old: str, new: str) -> None:
        """Carry the codes across when an appliance is renamed."""
        if old == new or old not in self._codes:
            return
        self._codes[new] = self._codes.pop(old)
        self._schedule_save()
        self._notify_codes_changed()

    def _schedule_save(self) -> None:
        """Write to disk once, after the burst of edits settles."""
        self._store.async_delay_save(lambda: self._codes, STORAGE_SAVE_DELAY)

    def _notify_codes_changed(self) -> None:
        async_dispatcher_send(
            self.hass, SIGNAL_CODES_UPDATED.format(entry_id=self.entry.entry_id)
        )


def is_hvac_frame(received: dict[str, Any]) -> bool:
    """Whether this capture is an air conditioner.

    Those do not belong in the generic store. The frame carries the whole state
    of the unit, so one capture is one temperature in one mode, and replaying it
    is nothing like having the remote. The climate platform builds the frame
    from vendor and model instead, which is both smaller and complete.
    """
    return KEY_IRHVAC in received


def is_usable_code(received: dict[str, Any]) -> bool:
    """Whether a capture carries enough to be replayed.

    A truncated frame arrives with an empty ``Data`` and zero ``Bits``, and the
    library labels it UNKNOWN. Storing one of those produces a command that is
    accepted, saved, shown in the interface and does nothing at all.
    """
    data = received.get("Data")
    bits = received.get("Bits")
    if isinstance(data, str) and data not in ("", "0x") and bits:
        return True
    raw = received.get("RawData")
    return bool(raw)


def extract_code(received: dict[str, Any]) -> dict[str, Any]:
    """Reduce a capture to the smallest payload that reproduces it."""
    protocol = received.get("Protocol")
    data = received.get("Data")
    bits = received.get("Bits")
    if protocol and protocol != "UNKNOWN" and data not in (None, "", "0x") and bits:
        return {"Protocol": protocol, "Bits": bits, "Data": data}
    return {
        "Protocol": PROTOCOL_RAW,
        "RawData": received.get("RawData"),
        "Frequency": RAW_FREQUENCY,
    }


def count_ir_gpios(gpio_reply: dict[str, Any]) -> tuple[int, bool]:
    """Read an emitter count and a receiver flag out of a Gpio 255 reply.

    The reply maps every usable pin to its function, so ``IRsend1`` through
    ``IRsend8`` on a board with eight emitters. Counting them is more honest
    than asking the user, and it is what makes this integration work on any
    Tasmota board instead of one model.
    """
    channels = 0
    has_receiver = False
    for assignment in gpio_reply.values():
        if not isinstance(assignment, dict):
            continue
        for name in assignment:
            if name == GPIO_IRRECV:
                has_receiver = True
            elif name.startswith(GPIO_IRSEND_PREFIX):
                suffix = name[len(GPIO_IRSEND_PREFIX) :]
                if suffix.isdigit():
                    channels = max(channels, int(suffix))
                else:
                    channels = max(channels, 1)
    return min(channels, MAX_CHANNELS) or DEFAULT_CHANNEL, has_receiver
