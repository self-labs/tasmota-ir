"""The single MQTT conversation with one Tasmota board.

Every platform in this integration talks to the board through this object. It
owns the subscriptions, the learned codes and the appliance to emitter mapping,
so no entity ever builds a topic or guesses a channel by itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import (
    CMND_GPIO,
    CMND_IRSEND,
    CONF_CHANNEL,
    CONF_FULL_TOPIC,
    CONF_TOPIC,
    DEFAULT_CHANNEL,
    GPIO_IRRECV,
    GPIO_IRSEND_PREFIX,
    KEY_CHANNEL,
    KEY_FREQUENCY,
    KEY_IR_RECEIVED,
    KEY_IRHVAC,
    KEY_RAW_DATA,
    MAX_CHANNELS,
    MAX_CODE_BYTES,
    PROBE_TIMEOUT,
    PROTOCOL_RAW,
    RAW_FREQUENCY,
    RAW_REPLY_TIMEOUT,
    SIGNAL_AVAILABILITY,
    SIGNAL_CODES_UPDATED,
    SIGNAL_IR_RECEIVED,
    STORAGE_KEY_FORMAT,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
    SUBENTRY_APPLIANCE,
    SUBENTRY_CLIMATE,
)

_LOGGER = logging.getLogger(__name__)


class CodeTooLargeError(Exception):
    """A captured code does not fit in the board's MQTT buffer."""


@dataclass(frozen=True, slots=True)
class Appliance:
    """One appliance of a board, as its subentry describes it.

    ``key`` is the subentry unique_id. The codes, the device and every entity
    unique_id hang off it, never off the name, so a rename is only a new title.
    """

    key: str
    subentry_id: str
    name: str
    kind: str
    channel: int
    data: Mapping[str, Any]


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
        # Each waiter is a future plus what it is waiting for, if anything.
        self._ir_waiters: list[
            tuple[
                asyncio.Future[dict[str, Any]], Callable[[dict[str, Any]], bool] | None
            ]
        ] = []
        # Whether the firmware takes a raw code as JSON with a Channel. None
        # until the first raw code for an emitter other than 1 finds out, and
        # forgotten whenever the board comes back online, since that is when
        # its firmware may have changed.
        self._raw_json: bool | None = None

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
            await mqtt.async_subscribe(
                self.hass, self.result_topic, self._handle_result
            )
        )
        self._unsubscribes.append(
            await mqtt.async_subscribe(self.hass, self.lwt_topic, self._handle_lwt)
        )

    async def async_unload(self) -> None:
        """Drop the subscriptions and flush pending writes."""
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        for waiter, _wanted in self._ir_waiters:
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
        if available:
            self._raw_json = None
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

        for waiter, wanted in list(self._ir_waiters):
            if waiter.done() or (wanted is not None and not wanted(received)):
                continue
            waiter.set_result(received)

        async_dispatcher_send(
            self.hass,
            SIGNAL_IR_RECEIVED.format(entry_id=self.entry.entry_id),
            received,
        )

    async def async_wait_for_code(
        self,
        timeout: float,
        wanted: Callable[[dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any] | None:
        """Wait for a code the receiver reports, optionally a kind of code.

        A receiver hears more than the key that was pressed: a frame read at a
        bad angle decodes into something the library does not recognise, and
        those arrive in bursts. Waiting for an air conditioner while a stray
        frame is in the air would end on the stray one, which is why the
        air conditioner flow says what it is waiting for.
        """
        waiter: asyncio.Future[dict[str, Any]] = self.hass.loop.create_future()
        entry = (waiter, wanted)
        self._ir_waiters.append(entry)
        try:
            async with asyncio.timeout(timeout):
                return await waiter
        except TimeoutError:
            return None
        finally:
            if entry in self._ir_waiters:
                self._ir_waiters.remove(entry)

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
        goes through ``_async_send_raw_code``, which picks the emitter when the
        firmware allows it.
        """
        if code.get("Protocol") == PROTOCOL_RAW:
            await self._async_send_raw_code(code, channel)
            return

        await self.async_send_json(CMND_IRSEND, code, channel=channel)

    async def _async_send_raw_code(
        self, code: dict[str, Any], channel: int | None
    ) -> None:
        """Send a raw capture, on its own emitter when the firmware can.

        Emitter 1 always gets the plain ``IRSend <freq>,<data>`` form, which
        every firmware takes and which leaves through the first emitter anyway.
        Any other emitter needs the JSON form of arendst/Tasmota#25062. A
        firmware without it answers ``Wrong Protocol`` and sends nothing, so
        the first raw code of a board waits for that answer: ``Done`` settles
        it, anything else falls back to the plain form on emitter 1, where a
        remote at least has a chance, and says so in the log.
        """
        raw = code.get(KEY_RAW_DATA)
        if not raw:
            raise CodeTooLargeError("the stored raw code is empty")
        frequency = code.get(KEY_FREQUENCY, RAW_FREQUENCY)

        if channel not in (None, 1) and self._raw_json is not False:
            encoded = json.dumps(
                {KEY_RAW_DATA: raw, KEY_FREQUENCY: frequency, KEY_CHANNEL: channel},
                separators=(",", ":"),
            )
            if len(encoded) > MAX_CODE_BYTES:
                _LOGGER.warning(
                    "Sending a raw code on emitter 1 instead of %s: with the "
                    "emitter it is %s bytes, above the %s the board accepts",
                    channel,
                    len(encoded),
                    MAX_CODE_BYTES,
                )
            elif self._raw_json:
                await self.async_send_raw(CMND_IRSEND, encoded)
                return
            else:
                reply = await self._async_command_reply(
                    CMND_IRSEND,
                    encoded,
                    wanted=is_irsend_reply,
                    timeout=RAW_REPLY_TIMEOUT,
                )
                if reply is None:
                    # Whether it left is unknown, and sending it again could
                    # fire the same key twice. The next raw code asks again.
                    _LOGGER.warning(
                        "The board did not answer a raw code sent on emitter "
                        "%s; it may or may not have gone out",
                        channel,
                    )
                    return
                if irsend_reply_text(reply) == "Done":
                    self._raw_json = True
                    return
                self._raw_json = False
                _LOGGER.warning(
                    "This firmware cannot choose the emitter of a raw code (it "
                    "answered %r), so raw codes leave through emitter 1 until "
                    "the board restarts. arendst/Tasmota#25062 adds it",
                    irsend_reply_text(reply),
                )
        elif channel not in (None, 1):
            _LOGGER.warning(
                "Sending a raw code on emitter 1 instead of %s: this firmware "
                "cannot choose the emitter of a raw code",
                channel,
            )

        payload = f"{frequency},{raw}"
        if len(payload) > MAX_CODE_BYTES:
            raise CodeTooLargeError(
                f"the raw code is {len(payload)} bytes, above the "
                f"{MAX_CODE_BYTES} the board accepts in one message"
            )
        await self.async_send_raw(CMND_IRSEND, payload)

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
        self,
        command: str,
        payload: str,
        wanted: Callable[[dict[str, Any]], bool] | None = None,
        timeout: float = PROBE_TIMEOUT,
    ) -> dict[str, Any] | None:
        """Publish a command and wait for the matching stat/ reply.

        ``wanted`` skips replies to other commands, which share the topic.
        """
        future: asyncio.Future[dict[str, Any]] = self.hass.loop.create_future()

        @callback
        def _handle(message: mqtt.ReceiveMessage) -> None:
            if future.done():
                return
            try:
                parsed = json.loads(message.payload)
            except ValueError:
                return
            if isinstance(parsed, dict) and (wanted is None or wanted(parsed)):
                future.set_result(parsed)

        unsubscribe = await mqtt.async_subscribe(
            self.hass, self._build_topic("stat", "RESULT"), _handle
        )
        try:
            await self.async_send_raw(command, payload)
            async with asyncio.timeout(timeout):
                return await future
        except TimeoutError:
            return None
        finally:
            unsubscribe()

    # ------------------------------------------------------------------
    # Appliances and their emitters
    # ------------------------------------------------------------------

    @property
    def appliances(self) -> dict[str, Appliance]:
        """The appliances of this board, keyed by their stable key."""
        result: dict[str, Appliance] = {}
        for subentry in self.entry.subentries.values():
            if subentry.subentry_type not in (SUBENTRY_APPLIANCE, SUBENTRY_CLIMATE):
                continue
            if not subentry.unique_id:
                continue
            result[subentry.unique_id] = Appliance(
                key=subentry.unique_id,
                subentry_id=subentry.subentry_id,
                name=subentry.title,
                kind=subentry.subentry_type,
                channel=int(subentry.data.get(CONF_CHANNEL, DEFAULT_CHANNEL)),
                data=subentry.data,
            )
        return result

    def find_appliance(self, name: str | None) -> Appliance | None:
        """The appliance a person means by this name, ignoring case."""
        if not name:
            return None
        wanted = name.strip().casefold()
        for appliance in self.appliances.values():
            if appliance.name.strip().casefold() == wanted:
                return appliance
        return None

    def channel_for(self, key: str | None) -> int:
        """The emitter an appliance is wired to.

        Nobody types this. It is configured once, which is the whole point: a
        channel that is never entered is a channel that is never entered wrong.
        """
        appliance = self.appliances.get(key) if key else None
        return appliance.channel if appliance else DEFAULT_CHANNEL

    def add_appliance(
        self, name: str, key: str | None = None, channel: int = DEFAULT_CHANNEL
    ) -> str:
        """Create an appliance subentry, for a name learned through the action.

        ``remote.learn_command`` accepts any name, and a command kept under a
        name nobody registered would be invisible in the interface and stuck on
        the first emitter. Registering it here makes it show up under the board
        like any other appliance, ready to be moved to its emitter.
        """
        key = key or uuid4().hex
        self.hass.config_entries.async_add_subentry(
            self.entry,
            ConfigSubentry(
                data=MappingProxyType({CONF_CHANNEL: channel}),
                subentry_type=SUBENTRY_APPLIANCE,
                title=name.strip(),
                unique_id=key,
            ),
        )
        return key

    # ------------------------------------------------------------------
    # Learned codes
    # ------------------------------------------------------------------

    @property
    def codes(self) -> dict[str, dict[str, Any]]:
        """Every learned code, as {appliance key: {command: code}}."""
        return self._codes

    def get_code(self, key: str, command: str) -> dict[str, Any] | None:
        """One learned code, or None."""
        return self._codes.get(key, {}).get(command)

    def commands_of(self, key: str) -> list[str]:
        """The commands one appliance knows, sorted for display."""
        return sorted(self._codes.get(key, {}))

    async def async_store_code(
        self, key: str, command: str, code: dict[str, Any]
    ) -> None:
        """Remember a code and tell the button platform about it."""
        check_code_size(code)
        self._codes.setdefault(key, {})[command] = code
        self._schedule_save()
        self._notify_codes_changed()

    async def async_store_codes(
        self, key: str, codes: dict[str, dict[str, Any]]
    ) -> None:
        """Remember several codes at once, learned before the appliance existed.

        Written to disk straight away: the subentry that owns them is created
        right after, and that reloads the entry.
        """
        if not codes:
            return
        self._codes.setdefault(key, {}).update(codes)
        await self._store.async_save(self._codes)
        self._notify_codes_changed()

    async def async_delete_code(self, key: str, command: str) -> bool:
        """Forget a code. Returns whether there was one."""
        commands = self._codes.get(key)
        if not commands or command not in commands:
            return False
        del commands[command]
        if not commands:
            del self._codes[key]
        self._schedule_save()
        self._notify_codes_changed()
        return True

    def prune_codes(self) -> list[str]:
        """Drop the codes of appliances that no longer exist.

        Deleting an appliance in the interface removes its subentry, and with it
        the only way to see or send those codes. Keeping them would leave data
        nobody can reach, so they go at the next setup.
        """
        known = self.appliances
        stale = [key for key in self._codes if key not in known]
        for key in stale:
            del self._codes[key]
        if stale:
            self._schedule_save()
        return stale

    async def async_flush(self) -> None:
        """Write the codes now, before something reloads the entry."""
        await self._store.async_save(self._codes)

    def _schedule_save(self) -> None:
        """Write to disk once, after the burst of edits settles."""
        self._store.async_delay_save(lambda: self._codes, STORAGE_SAVE_DELAY)

    def _notify_codes_changed(self) -> None:
        async_dispatcher_send(
            self.hass, SIGNAL_CODES_UPDATED.format(entry_id=self.entry.entry_id)
        )


def check_code_size(code: dict[str, Any]) -> None:
    """Refuse a code the board could never accept in one MQTT message."""
    encoded = json.dumps(code, separators=(",", ":"))
    if len(encoded) > MAX_CODE_BYTES:
        raise CodeTooLargeError(
            f"the captured code is {len(encoded)} bytes, above the "
            f"{MAX_CODE_BYTES} the board can accept in one message"
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

    A repeat frame is the other trap. While a key is held, a NEC remote sends
    the real frame once and then a short burst every 108 ms that only means
    "keep repeating the last one": zero bits, a run of F's in ``Data``, and a
    three pulse ``RawData``. That burst carries no command, so a learn that
    started after the real frame would otherwise store it as raw, and the
    button it creates would do nothing. Measured on a LG television: one
    32 bit frame followed by eighteen of these in 2.4 seconds.
    """
    if received.get("Repeat") and not received.get("Bits"):
        return False
    # A frame the library recognised but could not finish reading. Seen with an
    # LG air conditioner remote pressed from across the room: it arrived as SONY
    # with zero bits, and with SetOption58 on it still carried RawData, so it
    # used to pass as a raw capture that reproduces nothing.
    protocol = received.get("Protocol")
    if protocol not in (None, "", "UNKNOWN") and not received.get("Bits"):
        return False
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


def irsend_reply_text(reply: dict[str, Any]) -> str | None:
    """The board's answer to an IRSend, whatever case the key comes in.

    Tasmota names the key after the command table, not after what was typed,
    so it is matched without regard to case.
    """
    for key, value in reply.items():
        if key.lower() == CMND_IRSEND.lower():
            return value if isinstance(value, str) else str(value)
    return None


def is_irsend_reply(reply: dict[str, Any]) -> bool:
    """Whether a stat/RESULT payload answers an IRSend, not some other command."""
    return irsend_reply_text(reply) is not None


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
