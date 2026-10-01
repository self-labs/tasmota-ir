"""Config flow for the board, subentry flows for its appliances.

Adding a board is three questions at most, and two of them are answered by the
board itself: the discovery topic Tasmota already publishes names it, and a
``Gpio`` probe counts its emitters. Nobody is asked how many IR LEDs their
hardware has.

Each appliance is a config subentry of its board. Home Assistant lists them
under the board, each with its own device and its own menu, which is where
people look for "the TV" and its buttons. Learning happens there too: the
appliance is chosen by opening it, so the emitter is never in question.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from collections.abc import Callable, Iterable
from types import MappingProxyType
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.components import mqtt
from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.translation import async_get_translations

from .const import (
    CMND_IRHVAC,
    CONF_CHANNEL,
    CONF_CHANNELS,
    CONF_EXTRAS,
    CONF_FULL_TOPIC,
    CONF_HAS_RECEIVER,
    CONF_HVAC_MODES,
    CONF_INITIAL_SWING_VERTICAL,
    CONF_LIGHT,
    CONF_MAC,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_MODEL,
    CONF_SWING_HORIZONTAL,
    CONF_SWING_VERTICAL,
    CONF_TOPIC,
    CONF_VENDOR,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_SEND_DELAY,
    DOMAIN,
    KEY_IRHVAC,
    KNOWN_MODELS,
    LEARN_TIMEOUT_UI,
    MAX_CHANNELS,
    SUBENTRY_APPLIANCE,
    SUBENTRY_CLIMATE,
    SUBENTRY_SEQUENCE,
    swing_vertical_default,
)
from .coordinator import (
    CodeTooLargeError,
    RawChannelError,
    RawUnconfirmedError,
    TasmotaIrCoordinator,
    check_code_size,
    codes_arriving,
    extract_code,
    is_hvac_frame,
)
from .device_types import (
    CATALOG,
    CONF_POWER_SENSOR,
    CONF_POWER_THRESHOLD,
    CONF_ROLES,
    DEFAULT_POWER_THRESHOLD,
    NUMBER_DEFAULTS,
    SUBENTRY_COVER,
    SUBENTRY_FAN,
    SUBENTRY_LIGHT,
    SUBENTRY_MEDIA,
    SUBENTRY_SWITCH,
    is_list,
    missing_required,
    role,
    roles_of,
)
from .hvac_extras import appliance_extras, extras_default, extras_offered
from .sequence import (
    CONF_STEPS,
    STEP_APPLIANCE,
    STEP_COMMAND,
    STEP_ITEM,
    STEP_WAIT,
    describe_step,
    describe_steps,
    step_choices,
    steps_of,
)

_LOGGER = logging.getLogger(__name__)

CONF_FUNCTION = "function"
CONF_ITEM = "item"
CONF_CODE = "code"
CONF_VALUE = "value"
CONF_ACTION = "action"
CONF_STEP = "step"
CONF_WAIT = "wait"


class _BoardOfflineError(Exception):
    """The board is offline, so trying an emitter would prove nothing."""


DISCOVERY_TOPIC = "tasmota/discovery/+/config"
DISCOVERY_WINDOW = 4.0

MANUAL = "__manual__"

CONF_NAME = "name"
CONF_COMMAND = "command"
CONF_BOARD = "board"

HVAC_MODE_OPTIONS = ["off", "cool", "heat", "dry", "fan_only", "auto"]


async def _async_discover_boards(hass) -> dict[str, dict[str, Any]]:
    """Collect the boards Tasmota is already announcing.

    The discovery messages are retained, so this returns whatever the broker
    holds rather than waiting for the boards to speak up.
    """
    found: dict[str, dict[str, Any]] = {}

    @callback
    def _handle(message: mqtt.ReceiveMessage) -> None:
        try:
            payload = json.loads(message.payload)
        except ValueError:
            return
        mac = payload.get("mac")
        topic = payload.get("t")
        if not mac or not topic:
            return
        found[mac] = {
            CONF_MAC: mac,
            CONF_TOPIC: topic,
            CONF_FULL_TOPIC: payload.get("ft", "%prefix%/%topic%/"),
            "name": payload.get("dn") or topic,
            "model": payload.get("md", ""),
        }

    unsubscribe = await mqtt.async_subscribe(hass, DISCOVERY_TOPIC, _handle)
    try:
        await asyncio.sleep(DISCOVERY_WINDOW)
    finally:
        unsubscribe()
    return found


class TasmotaIrConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a Tasmota board that can send infrared."""

    VERSION = 2

    def __init__(self) -> None:
        """Start with nothing discovered."""
        self._boards: dict[str, dict[str, Any]] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """The board's Configure: moving everything to another board."""
        return BoardOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """An ordinary appliance, and an air conditioner."""
        return {
            SUBENTRY_APPLIANCE: ApplianceSubentryFlow,
            SUBENTRY_CLIMATE: ClimateSubentryFlow,
            SUBENTRY_MEDIA: MediaSubentryFlow,
            SUBENTRY_FAN: FanSubentryFlow,
            SUBENTRY_LIGHT: LightSubentryFlow,
            SUBENTRY_COVER: CoverSubentryFlow,
            SUBENTRY_SWITCH: SwitchSubentryFlow,
            SUBENTRY_SEQUENCE: SequenceSubentryFlow,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a discovered board, or ask for a topic."""
        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            return self.async_abort(reason="mqtt_unavailable")

        if user_input is None:
            self._boards = await _async_discover_boards(self.hass)
            options = [
                selector.SelectOptionDict(
                    value=mac,
                    label=f"{board['name']} ({board['model'] or board[CONF_TOPIC]})",
                )
                for mac, board in sorted(
                    self._boards.items(), key=lambda item: item[1]["name"]
                )
            ]
            options.append(
                selector.SelectOptionDict(value=MANUAL, label="Enter a topic manually")
            )
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("board"): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=options,
                                mode=selector.SelectSelectorMode.DROPDOWN,
                            )
                        )
                    }
                ),
            )

        if user_input["board"] == MANUAL:
            return await self.async_step_manual()

        board = self._boards[user_input["board"]]
        return await self._async_probe_and_create(board)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the board's topic when discovery found nothing."""
        if user_input is None:
            return self.async_show_form(
                step_id="manual",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_TOPIC): str,
                        vol.Optional(CONF_FULL_TOPIC, default="%prefix%/%topic%/"): str,
                    }
                ),
            )
        return await self._async_probe_and_create(
            {
                CONF_TOPIC: user_input[CONF_TOPIC],
                CONF_FULL_TOPIC: user_input[CONF_FULL_TOPIC],
                CONF_MAC: None,
                "name": user_input[CONF_TOPIC],
                "model": "",
            }
        )

    async def _async_probe_and_create(self, board: dict[str, Any]) -> ConfigFlowResult:
        """Ask the board what it has, then create the entry."""
        unique_id = board.get(CONF_MAC) or board[CONF_TOPIC]
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        data = {
            CONF_TOPIC: board[CONF_TOPIC],
            CONF_FULL_TOPIC: board.get(CONF_FULL_TOPIC, "%prefix%/%topic%/"),
            CONF_MAC: board.get(CONF_MAC),
        }

        # A throwaway coordinator, only to reuse the topic building and the probe.
        probe = TasmotaIrCoordinator(self.hass, _FakeEntry(data))
        channels, has_receiver = await probe.async_probe_channels()

        return self.async_create_entry(
            title=board["name"],
            data={
                **data,
                CONF_CHANNELS: channels,
                CONF_HAS_RECEIVER: has_receiver,
            },
        )


class _FakeEntry:
    """The little a probe needs from a config entry, before one exists."""

    entry_id = "probe"

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.options: dict[str, Any] = {}
        self.subentries: dict[str, Any] = {}


def emitter_selector(
    entry: ConfigEntry, ignore: str | None = None
) -> selector.SelectSelector:
    """Offer the emitters the board reported, and say who uses each.

    A bare number is a guess: there is nothing on the board to read, and an
    appliance pointed at the wrong emitter fails silently. Naming the
    appliances already on each emitter turns the guess into a choice.
    ``entry`` is another board, for an appliance on its way there.
    """
    channels = min(int(entry.data.get(CONF_CHANNELS, 1)), MAX_CHANNELS)
    taken: dict[int, list[str]] = {}
    for sub_id, subentry in entry.subentries.items():
        if sub_id == ignore:
            continue
        channel = int(subentry.data.get(CONF_CHANNEL, 0))
        if channel:
            taken.setdefault(channel, []).append(subentry.title)
    options = [
        selector.SelectOptionDict(
            value=str(channel),
            label=(
                f"{channel}: {', '.join(sorted(taken[channel]))}"
                if channel in taken
                else str(channel)
            ),
        )
        for channel in range(1, channels + 1)
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, mode=selector.SelectSelectorMode.LIST
        )
    )


async def async_transfer_subentries(
    hass: HomeAssistant,
    source: ConfigEntry,
    target: ConfigEntry,
    moves: list[tuple[ConfigSubentry, str, int | None]],
    *,
    keep: bool,
) -> None:
    """Hand appliances to another board, as copies or as moves.

    Every code is written to the other board first. Adding a subentry reloads
    that board, and a reload drops codes nobody owns, so they must already be
    on disk under the key the subentry will carry, and marked as arriving,
    so the reload each addition starts keeps them whenever it runs.

    A move keeps the key. Every unique id hangs off it, so the entities come
    back with the same ids, and Home Assistant restores their entity ids,
    names and areas from the ones the old board just removed. That is also
    why the old subentry goes first: two entities cannot share a unique id.
    A copy gets a key of its own, and entities of its own. A channel of
    None keeps the data as it is: a sequence has no emitter.
    """
    coordinator: TasmotaIrCoordinator = source.runtime_data
    target_coordinator: TasmotaIrCoordinator = target.runtime_data
    keys: list[str] = []
    for subentry, _name, _channel in moves:
        key = subentry.unique_id or ""
        new_key = uuid4().hex if keep else key
        keys.append(new_key)
        codes = copy.deepcopy(coordinator.codes.get(key, {}))
        await target_coordinator.async_store_codes(new_key, codes)
    with codes_arriving(hass, target.entry_id, keys):
        for (subentry, name, channel), new_key in zip(moves, keys, strict=True):
            if not keep:
                hass.config_entries.async_remove_subentry(source, subentry.subentry_id)
            hass.config_entries.async_add_subentry(
                target,
                ConfigSubentry(
                    data=MappingProxyType(
                        {**subentry.data, CONF_CHANNEL: channel}
                        if channel is not None
                        else dict(subentry.data)
                    ),
                    subentry_type=subentry.subentry_type,
                    title=name,
                    unique_id=new_key,
                ),
            )


def already_there(
    target: ConfigEntry, subentries: Iterable[ConfigSubentry]
) -> list[str]:
    """The appliances the other board already has, whatever it calls them.

    A move keeps the key, and a key the other board already has is the same
    appliance, moved or restored there before. Moving it again would pour its
    codes into that one and then fail half way.
    """
    keys = {sub.unique_id for sub in target.subentries.values()}
    return [sub.title for sub in subentries if sub.unique_id in keys]


def other_boards(hass: HomeAssistant, source: ConfigEntry) -> dict[str, ConfigEntry]:
    """The other boards that are up, by entry id."""
    return {
        entry.entry_id: entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id != source.entry_id and entry.state is ConfigEntryState.LOADED
    }


def board_schema(boards: dict[str, ConfigEntry]) -> vol.Schema:
    """A board to choose, among the other boards that are up."""
    return vol.Schema(
        {
            vol.Required(CONF_BOARD): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=entry_id, label=entry.title)
                        for entry_id, entry in boards.items()
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }
    )


class BoardOptionsFlow(OptionsFlow):
    """What can be done to a whole board: for now, moving everything off it."""

    def __init__(self) -> None:
        """No board chosen yet."""
        self._target_id = ""
        # The appliances the emitter form was shown for, by subentry id.
        self._shown: dict[str, str] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The board's own menu."""
        return self.async_show_menu(step_id="init", menu_options=["move_all"])

    async def async_step_move_all(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the board. With only one other, there is nothing to choose."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="board_not_loaded")
        boards = other_boards(self.hass, self.config_entry)
        if not boards:
            return self.async_abort(reason="no_other_board")
        if not self.config_entry.subentries:
            return self.async_abort(reason="nothing_to_move")
        if user_input is not None or len(boards) == 1:
            self._target_id = (
                user_input[CONF_BOARD] if user_input else next(iter(boards))
            )
            return await self.async_step_move_all_emitters()
        return self.async_show_form(
            step_id="move_all",
            data_schema=board_schema(boards),
        )

    async def async_step_move_all_emitters(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One emitter per appliance on the other board, then everything moves.

        Each appliance is a field of its own, named after it, starting on the
        emitter it has today when the other board has that many.
        """
        source = self.config_entry
        if source.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="board_not_loaded")
        target = other_boards(self.hass, source).get(self._target_id)
        if target is None:
            return self.async_abort(reason="no_other_board")
        subentries = sorted(source.subentries.values(), key=lambda sub: sub.title)
        current = {sub.subentry_id: sub.title for sub in subentries}
        errors: dict[str, str] = {}
        placeholders = {"board": target.title, "names": ""}
        if user_input is not None:
            taken = {sub.title.strip().casefold() for sub in target.subentries.values()}
            clash = [
                sub.title for sub in subentries if sub.title.strip().casefold() in taken
            ]
            there = already_there(target, subentries)
            if current != self._shown:
                # An appliance came, went or was renamed while the form was
                # open: the answers no longer match the questions.
                errors["base"] = "changed"
            elif there:
                errors["base"] = "already_there"
                placeholders["names"] = ", ".join(there)
            elif clash:
                errors["base"] = "names_taken"
                placeholders["names"] = ", ".join(clash)
            else:
                await async_transfer_subentries(
                    self.hass,
                    source,
                    target,
                    [
                        (
                            sub,
                            sub.title,
                            None
                            if sub.subentry_type == SUBENTRY_SEQUENCE
                            else int(user_input[sub.title]),
                        )
                        for sub in subentries
                    ],
                    keep=False,
                )
                return self.async_abort(
                    reason="moved_all",
                    description_placeholders={
                        "count": str(len(subentries)),
                        "board": target.title,
                    },
                )
        self._shown = current
        channels = min(int(target.data.get(CONF_CHANNELS, 1)), MAX_CHANNELS)
        schema = {
            vol.Required(
                sub.title,
                default=str(
                    current
                    if (current := int(sub.data.get(CONF_CHANNEL, 1))) <= channels
                    else 1
                ),
            ): emitter_selector(target)
            for sub in subentries
            if sub.subentry_type != SUBENTRY_SEQUENCE
        }
        return self.async_show_form(
            step_id="move_all_emitters",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders=placeholders,
        )


async def async_function_labels(hass: HomeAssistant) -> dict[str, str]:
    """The names of a typed appliance's functions, in the server's language."""
    translations = await async_get_translations(
        hass, hass.config.language, "selector", [DOMAIN]
    )
    prefix = f"component.{DOMAIN}.selector.function.options."
    return {
        key.removeprefix(prefix): value
        for key, value in translations.items()
        if key.startswith(prefix)
    }


class _TasmotaIrSubentryFlow(ConfigSubentryFlow):
    """What both kinds of appliance share: names, emitters and waiting for a key.

    Waiting for the remote is a progress step. The wait starts the moment the
    step opens, so the person points the remote and presses, with nothing to
    click in between. A form that only starts waiting after "Submit" is exactly
    the trap the first version of this flow set.
    """

    def __init__(self) -> None:
        """Nothing chosen yet."""
        self._name: str = ""
        self._channel: int = 1
        self._probe_name: str = ""
        # True when the emitter being tried got the last command another
        # integration sent, rather than a key learned here.
        self._probe_replay = False
        self._key: str = ""
        self._learn_task: asyncio.Task[dict[str, Any] | None] | None = None
        self._received: dict[str, Any] | None = None
        self._target_id: str = ""

    # ---- helpers -------------------------------------------------------

    def _coordinator(self) -> TasmotaIrCoordinator | None:
        """The board's coordinator, when the board is up."""
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return None
        return entry.runtime_data

    def _channel_selector(
        self, ignore: str | None = None, entry: ConfigEntry | None = None
    ) -> selector.SelectSelector:
        """The emitters of this board, or of ``entry``, and who uses each."""
        return emitter_selector(entry or self._get_entry(), ignore)

    def _name_taken(
        self, name: str, ignore: str | None = None, entry: ConfigEntry | None = None
    ) -> bool:
        """Whether another appliance of this board, or of ``entry``, has this name."""
        wanted = name.strip().casefold()
        return any(
            sub.title.strip().casefold() == wanted
            for sub_id, sub in (entry or self._get_entry()).subentries.items()
            if sub_id != ignore
        )

    def _placeholders(self) -> dict[str, str]:
        return {"name": self._name}

    # What this flow is waiting for. None takes the first usable frame.
    wanted: Callable[[dict[str, Any]], bool] | None = None

    async def _async_wait_for_key(self) -> dict[str, Any] | None:
        coordinator = self._coordinator()
        if coordinator is None:
            return None
        return await coordinator.async_wait_for_code(LEARN_TIMEOUT_UI, self.wanted)

    def _progress(self, step_id: str) -> SubentryFlowResult | None:
        """Show the waiting screen until a key arrives; None once it has."""
        if self._learn_task is None:
            self._received = None
            self._learn_task = self.hass.async_create_task(self._async_wait_for_key())
        if not self._learn_task.done():
            return self.async_show_progress(
                step_id=step_id,
                progress_action="wait_for_key",
                progress_task=self._learn_task,
                description_placeholders=self._placeholders(),
            )
        try:
            self._received = self._learn_task.result()
        except Exception:  # the flow must not die on a broker hiccup
            _LOGGER.exception("Waiting for an IR code failed")
            self._received = None
        self._learn_task = None
        return None

    # ---- the rename and emitter steps, shared by both kinds ------------

    async def async_step_channel(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Move the appliance to another emitter. Nothing has to be relearned."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            self._channel = int(user_input[CONF_CHANNEL])
            try:
                probed = await self._async_probe(self._channel)
            except _BoardOfflineError:
                errors[CONF_CHANNEL] = "board_offline"
            except RawUnconfirmedError:
                # The board did not answer: nothing is known about the firmware,
                # and the command may or may not have gone out.
                errors[CONF_CHANNEL] = "not_confirmed"
            except RawChannelError:
                # Only a replayed command gets here: the firmware cannot put
                # raw data on that emitter, so trying it would prove nothing.
                errors[CONF_CHANNEL] = "raw_channel"
            else:
                if probed:
                    return await self.async_step_channel_test()
                return await self.async_step_channel_save()
        return self.async_show_form(
            step_id="channel",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CHANNEL, default=str(subentry.data.get(CONF_CHANNEL, 1))
                    ): self._channel_selector(ignore=subentry.subentry_id)
                }
            ),
            errors=errors,
            description_placeholders={
                "name": subentry.title,
                "channel": str(subentry.data.get(CONF_CHANNEL, 1)),
            },
        )

    async def async_step_channel_test(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask whether the appliance answered what was just sent through it."""
        return self.async_show_menu(
            step_id="channel_test_replay" if self._probe_replay else "channel_test",
            menu_options=["channel_save", "channel"],
            description_placeholders={
                "name": self._name,
                "channel": str(self._channel),
                "command": self._probe_name,
            },
        )

    async def async_step_channel_test_replay(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """The same question, after a replayed command instead of a learned key.

        Home Assistant only shows a step the flow can also handle, so the menu
        that names the replay needs a step of its own behind it.
        """
        return await self.async_step_channel_test(user_input)

    async def async_step_channel_save(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Keep the emitter that was chosen."""
        return self.async_update_and_abort(
            self._get_entry(),
            self._get_reconfigure_subentry(),
            data_updates={CONF_CHANNEL: self._channel},
        )

    async def _async_probe(self, channel: int) -> bool:
        """Send something through an emitter. False when there is nothing to send.

        Whether the emitter points at the appliance cannot be read from the
        board, only seen on the appliance, so the flow sends one command and
        asks.
        """
        return False

    async def async_step_rename(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Rename the appliance. Its key does not change, so nothing is lost."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not name:
                errors[CONF_NAME] = "name_empty"
            elif self._name_taken(name, ignore=subentry.subentry_id):
                errors[CONF_NAME] = "name_taken"
            else:
                return self.async_update_and_abort(
                    self._get_entry(), subentry, title=name
                )
        return self.async_show_form(
            step_id="rename",
            data_schema=vol.Schema(
                {vol.Required(CONF_NAME, default=subentry.title): str}
            ),
            errors=errors,
        )

    # ---- moving or copying to another board, shared by both kinds -----

    def _other_boards(self) -> dict[str, ConfigEntry]:
        """The other boards that are up, by entry id."""
        return other_boards(self.hass, self._get_entry())

    async def async_step_move(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Move the appliance to another board, codes and entity ids included."""
        return await self._async_step_pick_board("move", user_input)

    async def async_step_copy(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Put a copy of the appliance on another board, keeping this one."""
        return await self._async_step_pick_board("copy", user_input)

    async def async_step_move_target(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick the emitter, and the name, the appliance will have there."""
        return await self._async_step_target("move_target", user_input, keep=False)

    async def async_step_copy_target(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick the emitter, and the name, the copy will have there."""
        return await self._async_step_target("copy_target", user_input, keep=True)

    async def _async_step_pick_board(
        self, action: str, user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        """Choose the board. With only one other, there is nothing to choose."""
        boards = self._other_boards()
        if not boards:
            return self.async_abort(reason="no_other_board")
        if user_input is not None or len(boards) == 1:
            self._target_id = (
                user_input[CONF_BOARD] if user_input else next(iter(boards))
            )
            return await getattr(self, f"async_step_{action}_target")()
        return self.async_show_form(
            step_id=action,
            data_schema=board_schema(boards),
            description_placeholders={"name": self._get_reconfigure_subentry().title},
        )

    async def _async_step_target(
        self, step_id: str, user_input: dict[str, Any] | None, keep: bool
    ) -> SubentryFlowResult:
        """The emitter and name on the other board, then the transfer itself.

        The emitter has to be chosen again: the other board may have fewer, and
        what sits on each of them is different there.
        """
        subentry = self._get_reconfigure_subentry()
        target = self._other_boards().get(self._target_id)
        if target is None:
            return self.async_abort(reason="board_not_loaded")

        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not keep and already_there(target, [subentry]):
                errors["base"] = "already_there"
            elif not name:
                errors[CONF_NAME] = "name_empty"
            elif self._name_taken(name, entry=target):
                errors[CONF_NAME] = "name_taken"
            else:
                return await self._async_transfer(
                    target, name, int(user_input[CONF_CHANNEL]), keep
                )

        channels = min(int(target.data.get(CONF_CHANNELS, 1)), MAX_CHANNELS)
        current = int(subentry.data.get(CONF_CHANNEL, 1))
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CHANNEL, default=str(current if current <= channels else 1)
                    ): self._channel_selector(entry=target),
                    vol.Required(CONF_NAME, default=subentry.title): str,
                }
            ),
            errors=errors,
            description_placeholders={"name": subentry.title, "board": target.title},
        )

    async def _async_transfer(
        self, target: ConfigEntry, name: str, channel: int, keep: bool
    ) -> SubentryFlowResult:
        """Hand the appliance to the other board, as a copy or as a move."""
        if self._coordinator() is None:
            return self.async_abort(reason="board_not_loaded")
        await async_transfer_subentries(
            self.hass,
            self._get_entry(),
            target,
            [(self._get_reconfigure_subentry(), name, channel)],
            keep=keep,
        )
        return self.async_abort(
            reason="copied" if keep else "moved",
            description_placeholders={
                "name": name,
                "board": target.title,
                "channel": str(channel),
            },
        )


class ApplianceSubentryFlow(_TasmotaIrSubentryFlow):
    """A television, a sound bar, a fan: anything learned key by key."""

    def __init__(self) -> None:
        """Nothing learned yet."""
        super().__init__()
        self._command: str = ""
        self._pending: dict[str, dict[str, Any]] = {}

    def _placeholders(self) -> dict[str, str]:
        return {"name": self._name, "command": self._command}

    # ---- adding --------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name the appliance and say which emitter points at it."""
        if self._coordinator() is None:
            return self.async_abort(reason="board_not_loaded")

        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not name:
                errors[CONF_NAME] = "name_empty"
            elif self._name_taken(name):
                errors[CONF_NAME] = "name_taken"
            else:
                self._name = name
                self._channel = int(user_input[CONF_CHANNEL])
                self._key = uuid4().hex
                return await self.async_step_added()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Required(CONF_CHANNEL, default="1"): self._channel_selector(),
                }
            ),
            errors=errors,
        )

    async def async_step_added(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Offer to learn the first key now, or to finish and learn later."""
        return self.async_show_menu(
            step_id="added",
            menu_options=["learn", "finish"],
            description_placeholders=self._placeholders(),
        )

    # ---- reconfiguring -------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Everything that can be done to an appliance that exists."""
        subentry = self._get_reconfigure_subentry()
        self._name = subentry.title
        self._key = subentry.unique_id or ""
        self._channel = int(subentry.data.get(CONF_CHANNEL, 1))
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=[
                "learn",
                "delete_command",
                "channel",
                "rename",
                "move",
                "copy",
            ],
            description_placeholders={
                "name": self._name,
                "channel": str(self._channel),
            },
        )

    async def _async_probe(self, channel: int) -> bool:
        """Send something the appliance should answer, through the emitter tried.

        The first learned command when there is one. Otherwise the last command
        another integration sent through this appliance's infrared entity, such
        as LG Infrared's power: it has no name here, so the question on screen
        says where it came from instead. With neither, there is nothing to try,
        and the emitter is saved directly, as it always was.
        """
        coordinator = self._coordinator()
        if coordinator is None:
            return False
        self._probe_replay = False
        commands = coordinator.commands_of(self._key)
        if commands:
            self._probe_name = commands[0]
            code = coordinator.get_code(self._key, commands[0])
            if code is None:
                return False
            try:
                await coordinator.async_send_code(code, channel=channel)
            except CodeTooLargeError:
                return False
            return True
        last = coordinator.last_infrared.get(self._key)
        if last is None:
            return False
        if not coordinator.available:
            raise _BoardOfflineError
        raw, frequency = last
        try:
            await coordinator.async_send_compact(
                raw, frequency, channel, fallback=False
            )
        except CodeTooLargeError:
            return False
        self._probe_replay = True
        return True

    async def async_step_delete_command(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Forget one command, and take its button with it."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="board_not_loaded")
        commands = coordinator.commands_of(self._key)
        if not commands:
            return self.async_abort(reason="no_commands")

        if user_input is not None:
            await coordinator.async_delete_code(self._key, user_input[CONF_COMMAND])
            return self.async_abort(
                reason="command_deleted",
                description_placeholders={"command": user_input[CONF_COMMAND]},
            )

        return self.async_show_form(
            step_id="delete_command",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COMMAND): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=commands,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            description_placeholders={"name": self._name},
        )

    # ---- learning, from either side ------------------------------------

    async def async_step_learn(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask what the key is called, then wait for it."""
        if self._coordinator() is None:
            return self.async_abort(reason="board_not_loaded")
        if not self._get_entry().data.get(CONF_HAS_RECEIVER, True):
            return self.async_abort(reason="no_receiver")

        errors: dict[str, str] = {}
        if user_input is not None:
            command = user_input[CONF_COMMAND].strip()
            if not command:
                errors[CONF_COMMAND] = "command_empty"
            else:
                self._command = command
                return await self.async_step_learn_wait()

        return self.async_show_form(
            step_id="learn",
            data_schema=vol.Schema({vol.Required(CONF_COMMAND): str}),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    async def async_step_learn_wait(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Wait for the key, then keep the code or say why not."""
        if (progress := self._progress("learn_wait")) is not None:
            return progress

        received = self._received
        if received is None:
            return self.async_show_progress_done(next_step_id="learn_timeout")
        if is_hvac_frame(received):
            return self.async_show_progress_done(next_step_id="learn_hvac")
        code = extract_code(received)
        try:
            check_code_size(code)
        except CodeTooLargeError:
            return self.async_show_progress_done(next_step_id="learn_too_large")
        await self._async_keep(code)
        return self.async_show_progress_done(next_step_id="learned")

    async def _async_keep(self, code: dict[str, Any]) -> None:
        """Store now when the appliance exists, or hold it until it does."""
        if self.source == SOURCE_USER:
            self._pending[self._command] = code
            return
        coordinator = self._coordinator()
        if coordinator is not None:
            await coordinator.async_store_code(self._key, self._command, code)

    async def async_step_learned(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Say it worked, and offer the next key."""
        return self.async_show_menu(
            step_id="learned",
            menu_options=["learn", "finish"],
            description_placeholders=self._placeholders(),
        )

    def _failed(self, step_id: str) -> SubentryFlowResult:
        """Say what went wrong, and offer to try again, rename or stop.

        A menu rather than a form with an error, because stopping must keep
        what was already learned: when the appliance is still being added,
        "finish" is what creates it.
        """
        return self.async_show_menu(
            step_id=step_id,
            menu_options=["learn_wait", "learn", "finish"],
            description_placeholders=self._placeholders(),
        )

    async def async_step_learn_timeout(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Nothing arrived in time."""
        return self._failed("learn_timeout")

    async def async_step_learn_hvac(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """That was an air conditioner remote."""
        return self._failed("learn_hvac")

    async def async_step_learn_too_large(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """The code does not fit in the board's MQTT buffer."""
        return self._failed("learn_too_large")

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create the appliance with what was learned, or close the menu."""
        if self.source != SOURCE_USER:
            return self.async_abort(reason="done")
        coordinator = self._coordinator()
        if coordinator is not None and self._pending:
            # Written before the subentry exists: creating it reloads the entry.
            await coordinator.async_store_codes(self._key, self._pending)
        return self.async_create_entry(
            title=self._name,
            data={CONF_CHANNEL: self._channel},
            unique_id=self._key,
        )


class ClimateSubentryFlow(_TasmotaIrSubentryFlow):
    """An air conditioner: read the vendor from its remote, build every frame."""

    wanted = staticmethod(is_hvac_frame)

    def __init__(self) -> None:
        """Nothing read yet."""
        super().__init__()
        self._hvac: dict[str, Any] = {}

    # ---- adding --------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name the unit and say which emitter points at it."""
        if self._coordinator() is None:
            return self.async_abort(reason="board_not_loaded")
        if not self._get_entry().data.get(CONF_HAS_RECEIVER, True):
            return self.async_abort(reason="no_receiver")

        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not name:
                errors[CONF_NAME] = "name_empty"
            elif self._name_taken(name):
                errors[CONF_NAME] = "name_taken"
            else:
                self._name = name
                self._channel = int(user_input[CONF_CHANNEL])
                self._key = uuid4().hex
                return await self.async_step_read_remote()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Required(CONF_CHANNEL, default="1"): self._channel_selector(),
                }
            ),
            errors=errors,
        )

    async def async_step_read_remote(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Wait for any key of the unit's remote, and read who made it."""
        if (progress := self._progress("read_remote")) is not None:
            return progress
        received = self._received
        if received is None:
            return self.async_show_progress_done(next_step_id="read_failed")
        self._hvac = received[KEY_IRHVAC]
        return self.async_show_progress_done(next_step_id="read_done")

    async def async_step_read_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """No air conditioner frame arrived. Offer another go."""
        if user_input is not None:
            return await self.async_step_read_remote()
        return self.async_show_form(
            step_id="read_failed",
            data_schema=vol.Schema({}),
            errors={"base": "no_hvac_frame"},
            description_placeholders=self._placeholders(),
        )

    async def async_step_read_done(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create the unit, or update the one being reconfigured."""
        vendor = str(self._hvac.get("Vendor", ""))
        model = str(self._hvac.get("Model", ""))
        light = "On" if str(self._hvac.get("Light", "On")).lower() == "on" else "Off"
        if self.source == SOURCE_USER:
            return self.async_create_entry(
                title=self._name,
                data={
                    CONF_CHANNEL: self._channel,
                    CONF_VENDOR: vendor,
                    CONF_MODEL: model if model != "-1" else "",
                    CONF_LIGHT: light,
                    CONF_MIN_TEMP: DEFAULT_MIN_TEMP,
                    CONF_MAX_TEMP: DEFAULT_MAX_TEMP,
                    CONF_HVAC_MODES: list(HVAC_MODE_OPTIONS),
                    CONF_SWING_VERTICAL: swing_vertical_default(vendor),
                    CONF_SWING_HORIZONTAL: False,
                    CONF_INITIAL_SWING_VERTICAL: str(self._hvac.get("SwingV", "Off")),
                    CONF_EXTRAS: extras_default(vendor),
                },
                unique_id=self._key,
            )
        return self.async_update_and_abort(
            self._get_entry(),
            self._get_reconfigure_subentry(),
            data_updates={CONF_VENDOR: vendor, CONF_MODEL: model, CONF_LIGHT: light},
        )

    # ---- reconfiguring -------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Everything that can be done to a unit that exists."""
        subentry = self._get_reconfigure_subentry()
        self._name = subentry.title
        self._key = subentry.unique_id or ""
        self._channel = int(subentry.data.get(CONF_CHANNEL, 1))
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=[
                "settings",
                "read_remote",
                "channel",
                "rename",
                "move",
                "copy",
            ],
            description_placeholders={
                "name": self._name,
                "vendor": subentry.data.get(CONF_VENDOR, ""),
                "model": subentry.data.get(CONF_MODEL, "") or "-",
                "channel": str(self._channel),
            },
        )

    async def _async_probe(self, channel: int) -> bool:
        """Turn the unit on through the emitter being tried.

        An air conditioner has no learned command to replay, and turning it on
        is the one thing that can be seen from across the room.
        """
        coordinator = self._coordinator()
        if coordinator is None:
            return False
        data = self._get_reconfigure_subentry().data
        self._probe_name = "on"
        payload: dict[str, Any] = {
            CONF_VENDOR.capitalize(): data.get(CONF_VENDOR, ""),
            "Power": "On",
            "Mode": "Cool",
            "Temp": int(data.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP)),
            "FanSpeed": "Auto",
            "Celsius": "On",
        }
        if model := data.get(CONF_MODEL):
            payload["Model"] = model
        await coordinator.async_send_json(CMND_IRHVAC, payload, channel=channel)
        return True

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Model, temperature range, modes and vanes."""
        subentry = self._get_reconfigure_subentry()
        data = subentry.data
        errors: dict[str, str] = {}

        if user_input is not None:
            low = int(user_input[CONF_MIN_TEMP])
            high = int(user_input[CONF_MAX_TEMP])
            modes = [m for m in user_input[CONF_HVAC_MODES] if m in HVAC_MODE_OPTIONS]
            if low >= high:
                errors[CONF_MAX_TEMP] = "temp_range"
            elif not [m for m in modes if m != "off"]:
                errors[CONF_HVAC_MODES] = "no_modes"
            else:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    data_updates={
                        CONF_MODEL: user_input.get(CONF_MODEL, "").strip(),
                        CONF_MIN_TEMP: low,
                        CONF_MAX_TEMP: high,
                        CONF_HVAC_MODES: modes,
                        CONF_SWING_VERTICAL: bool(user_input[CONF_SWING_VERTICAL]),
                        CONF_SWING_HORIZONTAL: bool(user_input[CONF_SWING_HORIZONTAL]),
                        CONF_EXTRAS: [
                            extra
                            for extra in extras_offered(str(data.get(CONF_VENDOR, "")))
                            if extra in user_input.get(CONF_EXTRAS, [])
                        ],
                    },
                )

        vendor = str(data.get(CONF_VENDOR, ""))
        current_model = str(data.get(CONF_MODEL, ""))
        models = list(KNOWN_MODELS.get(vendor.upper(), ()))
        if current_model and current_model not in models:
            models.insert(0, current_model)
        temp = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10, max=35, step=1, mode=selector.NumberSelectorMode.BOX
            )
        )
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MODEL, default=current_model
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=models,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_MIN_TEMP,
                    default=int(data.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP)),
                ): temp,
                vol.Required(
                    CONF_MAX_TEMP,
                    default=int(data.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP)),
                ): temp,
                vol.Required(
                    CONF_HVAC_MODES,
                    default=list(data.get(CONF_HVAC_MODES, HVAC_MODE_OPTIONS)),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=HVAC_MODE_OPTIONS,
                        multiple=True,
                        translation_key="hvac_mode",
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(
                    CONF_SWING_VERTICAL,
                    default=bool(
                        data.get(CONF_SWING_VERTICAL, swing_vertical_default(vendor))
                    ),
                ): bool,
                vol.Required(
                    CONF_SWING_HORIZONTAL,
                    default=bool(data.get(CONF_SWING_HORIZONTAL, False)),
                ): bool,
            }
        )
        # Only the extras this vendor's protocol sends; a vendor with none gets
        # no field at all.
        if offered := extras_offered(vendor):
            schema = schema.extend(
                {
                    vol.Optional(
                        CONF_EXTRAS, default=appliance_extras(data)
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=offered,
                            multiple=True,
                            translation_key="extra",
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            )
        return self.async_show_form(
            step_id="settings",
            data_schema=schema,
            errors=errors,
            description_placeholders={"name": subentry.title, "vendor": vendor},
        )


# ---- appliance types, learned function by function ------------------------


class TypedSubentryFlow(_TasmotaIrSubentryFlow):
    """A TV, a fan, a light, a cover or an on and off, function by function.

    One flow for the five types: what differs is only the list of functions,
    which comes from ``device_types.CATALOG``. Each function is learned from the
    remote now, reused from a key another appliance of the board already
    learned, or cleared. Nothing is written until the person finishes, and then
    the functions go into the subentry itself, so moving or copying the
    appliance carries them.
    """

    kind = ""

    def __init__(self) -> None:
        """Nothing learned yet."""
        super().__init__()
        self._roles: dict[str, Any] = {}
        self._numbers: dict[str, Any] = {}
        self._sensor: str | None = None
        self._threshold: float = DEFAULT_POWER_THRESHOLD
        self._function = ""
        self._label = ""
        self._item: str | None = None
        self._reuse_codes: dict[str, dict[str, Any]] = {}

    def _placeholders(self) -> dict[str, str]:
        return {"name": self._name, "command": self._item or self._label}

    def _set(self, code: dict[str, Any]) -> None:
        """Keep a code for the function (or the list item) being edited."""
        if self._item is not None:
            items = dict(self._roles.get(self._function) or {})
            items[self._item] = code
            self._roles[self._function] = items
        else:
            self._roles[self._function] = code

    async def _async_labels(self) -> dict[str, str]:
        """The function names in the server's language, for the summaries."""
        return await async_function_labels(self.hass)

    async def _async_learned(self) -> str:
        """What is already learned, as a line for the step's description."""
        labels = await self._async_labels()
        parts: list[str] = []
        for item in CATALOG[self.kind]:
            value = self._roles.get(item.name)
            label = labels.get(item.name, item.name)
            if item.kind == "list" and value:
                parts.append(f"{label} ({', '.join(value)})")
            elif item.kind == "key" and value:
                parts.append(label)
            elif item.kind == "number" and item.name in self._numbers:
                parts.append(f"{label}: {self._numbers[item.name]}")
        if self._sensor:
            parts.append(f"{labels.get('sensor', 'sensor')}: {self._sensor}")
        return ", ".join(parts) or "-"

    # ---- adding --------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name the appliance and say which emitter points at it."""
        if self._coordinator() is None:
            return self.async_abort(reason="board_not_loaded")

        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not name:
                errors[CONF_NAME] = "name_empty"
            elif self._name_taken(name):
                errors[CONF_NAME] = "name_taken"
            else:
                self._name = name
                self._channel = int(user_input[CONF_CHANNEL])
                self._key = uuid4().hex
                return await self.async_step_functions()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Required(CONF_CHANNEL, default="1"): self._channel_selector(),
                }
            ),
            errors=errors,
        )

    async def async_step_functions(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick a function to learn, reuse or clear; or the sensor; or finish."""
        errors: dict[str, str] = {}
        if user_input is not None:
            choice = user_input[CONF_FUNCTION]
            if choice == "finish":
                if missing_required(self.kind, self._roles):
                    errors["base"] = (
                        "missing_open_close"
                        if self.kind == SUBENTRY_COVER
                        else "missing_power"
                    )
                else:
                    return self._finish()
            elif choice == "sensor":
                return await self.async_step_sensor()
            else:
                function = role(self.kind, choice)
                self._function = function.name
                self._label = (await self._async_labels()).get(
                    function.name, function.name
                )
                self._item = None
                if function.kind == "number":
                    return await self.async_step_number()
                if function.kind == "list":
                    return await self.async_step_list_item()
                return await self.async_step_action()

        options = [item.name for item in CATALOG[self.kind]] + ["sensor", "finish"]
        return self.async_show_form(
            step_id="functions",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_FUNCTION): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            translation_key="function",
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                "name": self._name,
                "learned": await self._async_learned(),
            },
        )

    async def async_step_list_item(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name the item of a list: a source, a speed, a mode, an effect."""
        errors: dict[str, str] = {}
        if user_input is not None:
            item = str(user_input[CONF_ITEM]).strip()
            if not item:
                errors[CONF_ITEM] = "item_empty"
            else:
                self._item = item
                return await self.async_step_action()
        existing = list(self._roles.get(self._function) or {})
        return self.async_show_form(
            step_id="list_item",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ITEM): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=existing,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    async def async_step_action(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Learn it now, reuse a key the board already has, or clear it."""
        return self.async_show_menu(
            step_id="action",
            menu_options=["learn_now", "reuse", "clear"],
            description_placeholders=self._placeholders(),
        )

    async def async_step_learn_now(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Point the remote at the board and press the key."""
        if self._coordinator() is None:
            return self.async_abort(reason="board_not_loaded")
        if not self._get_entry().data.get(CONF_HAS_RECEIVER, True):
            return self.async_abort(reason="no_receiver")
        return await self.async_step_role_wait()

    async def async_step_role_wait(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Wait for the key, then keep it or say why not."""
        if (progress := self._progress("role_wait")) is not None:
            return progress
        received = self._received
        if received is None:
            return self.async_show_progress_done(next_step_id="role_timeout")
        if is_hvac_frame(received):
            return self.async_show_progress_done(next_step_id="role_hvac")
        code = extract_code(received)
        try:
            check_code_size(code)
        except CodeTooLargeError:
            return self.async_show_progress_done(next_step_id="role_too_large")
        self._set(code)
        return self.async_show_progress_done(next_step_id="functions")

    def _role_failed(self, step_id: str) -> SubentryFlowResult:
        return self.async_show_menu(
            step_id=step_id,
            menu_options=["role_wait", "functions"],
            description_placeholders=self._placeholders(),
        )

    async def async_step_role_timeout(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Nothing arrived in time."""
        return self._role_failed("role_timeout")

    async def async_step_role_hvac(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """That was an air conditioner remote."""
        return self._role_failed("role_hvac")

    async def async_step_role_too_large(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """The code does not fit in the board's MQTT buffer."""
        return self._role_failed("role_too_large")

    def _reusable(self) -> list[selector.SelectOptionDict]:
        """Every key the board already knows, from any other appliance."""
        coordinator = self._coordinator()
        self._reuse_codes = {}
        options: list[selector.SelectOptionDict] = []
        if coordinator is None:
            return options
        for appliance in coordinator.appliances.values():
            if appliance.key == self._key:
                continue
            for command, code in coordinator.codes.get(appliance.key, {}).items():
                value = f"{appliance.key}|{command}"
                self._reuse_codes[value] = code
                options.append(
                    selector.SelectOptionDict(
                        value=value, label=f"{appliance.name}: {command}"
                    )
                )
            for name, code in roles_of(appliance.data).items():
                if isinstance(code, dict) and not is_list(appliance.kind, name):
                    value = f"{appliance.key}|role:{name}"
                    self._reuse_codes[value] = code
                    options.append(
                        selector.SelectOptionDict(
                            value=value, label=f"{appliance.name}: {name}"
                        )
                    )
                elif isinstance(code, dict):
                    for item, item_code in code.items():
                        value = f"{appliance.key}|role:{name}:{item}"
                        self._reuse_codes[value] = item_code
                        options.append(
                            selector.SelectOptionDict(
                                value=value, label=f"{appliance.name}: {item}"
                            )
                        )
        return options

    async def async_step_reuse(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Take a key another appliance of this board already learned."""
        if user_input is not None:
            chosen = self._reuse_codes.get(user_input.get(CONF_CODE, ""))
            if chosen is not None:
                self._set(copy.deepcopy(chosen))
            return await self.async_step_functions()
        options = self._reusable()
        if not options:
            return self.async_show_form(
                step_id="reuse",
                data_schema=vol.Schema({}),
                errors={"base": "nothing_to_reuse"},
                description_placeholders=self._placeholders(),
            )
        return self.async_show_form(
            step_id="reuse",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CODE): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options, mode=selector.SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
            description_placeholders=self._placeholders(),
        )

    async def async_step_clear(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Forget the function, or the one item of a list."""
        if self._item is not None:
            items = dict(self._roles.get(self._function) or {})
            items.pop(self._item, None)
            if items:
                self._roles[self._function] = items
            else:
                self._roles.pop(self._function, None)
        else:
            self._roles.pop(self._function, None)
        return await self.async_step_functions()

    async def async_step_number(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """How many speeds or steps, or how long a full run takes."""
        seconds = self._function == "travel_time"
        if user_input is not None:
            value = user_input.get(CONF_VALUE)
            if not value:
                self._numbers.pop(self._function, None)
            else:
                self._numbers[self._function] = float(value) if seconds else int(value)
            return await self.async_step_functions()
        current = self._numbers.get(self._function, NUMBER_DEFAULTS[self._function])
        field = (
            vol.Optional(CONF_VALUE, default=current)
            if current is not None
            else vol.Optional(CONF_VALUE)
        )
        return self.async_show_form(
            step_id="number",
            data_schema=vol.Schema(
                {
                    field: selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=300 if seconds else 20,
                            step=0.5 if seconds else 1,
                            mode=selector.NumberSelectorMode.BOX,
                            **({"unit_of_measurement": "s"} if seconds else {}),
                        )
                    )
                }
            ),
            description_placeholders=self._placeholders(),
        )

    async def async_step_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """An entity that knows whether the appliance is really on."""
        if user_input is not None:
            self._sensor = user_input.get(CONF_POWER_SENSOR) or None
            self._threshold = float(
                user_input.get(CONF_POWER_THRESHOLD, DEFAULT_POWER_THRESHOLD)
            )
            return await self.async_step_functions()
        return self.async_show_form(
            step_id="sensor",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_POWER_SENSOR,
                        description={"suggested_value": self._sensor},
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=[
                                "binary_sensor",
                                "sensor",
                                "switch",
                                "input_boolean",
                            ]
                        )
                    ),
                    vol.Optional(
                        CONF_POWER_THRESHOLD, default=self._threshold
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=5000,
                            step=0.5,
                            mode=selector.NumberSelectorMode.BOX,
                            unit_of_measurement="W",
                        )
                    ),
                }
            ),
            description_placeholders=self._placeholders(),
        )

    def _finish(self) -> SubentryFlowResult:
        """Create the appliance, or save what the Manage menu changed."""
        data: dict[str, Any] = {
            CONF_CHANNEL: self._channel,
            CONF_ROLES: self._roles,
            **self._numbers,
        }
        if self._sensor:
            data[CONF_POWER_SENSOR] = self._sensor
            data[CONF_POWER_THRESHOLD] = self._threshold
        if self.source == SOURCE_USER:
            return self.async_create_entry(
                title=self._name, data=data, unique_id=self._key
            )
        return self.async_update_and_abort(
            self._get_entry(), self._get_reconfigure_subentry(), data=data
        )

    # ---- managing ------------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Everything that can be done to a typed appliance that exists."""
        subentry = self._get_reconfigure_subentry()
        data = subentry.data
        self._name = subentry.title
        self._key = subentry.unique_id or ""
        self._channel = int(data.get(CONF_CHANNEL, 1))
        self._roles = copy.deepcopy(roles_of(data))
        self._numbers = {
            name: data[name] for name in NUMBER_DEFAULTS if data.get(name) is not None
        }
        self._sensor = data.get(CONF_POWER_SENSOR) or None
        self._threshold = float(data.get(CONF_POWER_THRESHOLD, DEFAULT_POWER_THRESHOLD))
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["functions", "channel", "rename", "move", "copy"],
            description_placeholders={
                "name": self._name,
                "channel": str(self._channel),
            },
        )

    async def _async_probe(self, channel: int) -> bool:
        """Press the key that shows from across the room: power, or open."""
        coordinator = self._coordinator()
        if coordinator is None:
            return False
        for name in ("power", "power_on", "open"):
            code = self._roles.get(name)
            if isinstance(code, dict) and "Protocol" in code:
                self._probe_name = (await self._async_labels()).get(name, name)
                try:
                    await coordinator.async_send_code(code, channel=channel)
                except CodeTooLargeError:
                    return False
                return True
        return False


class MediaSubentryFlow(TypedSubentryFlow):
    """A TV or a sound bar."""

    kind = SUBENTRY_MEDIA


class FanSubentryFlow(TypedSubentryFlow):
    """A fan."""

    kind = SUBENTRY_FAN


class LightSubentryFlow(TypedSubentryFlow):
    """A light."""

    kind = SUBENTRY_LIGHT


class CoverSubentryFlow(TypedSubentryFlow):
    """A cover, a curtain or a screen."""

    kind = SUBENTRY_COVER


class SwitchSubentryFlow(TypedSubentryFlow):
    """Something that only turns on and off."""

    kind = SUBENTRY_SWITCH


class SequenceSubentryFlow(_TasmotaIrSubentryFlow):
    """Keys of several appliances of this board, pressed in order by one button.

    Like a typed appliance's functions, the steps stay in the flow until
    Finish and are written in one go. A step is an appliance and one of its
    keys, chosen from what the board already knows, with the wait after it.
    """

    def __init__(self) -> None:
        """No steps yet."""
        super().__init__()
        self._steps: list[dict[str, Any]] = []
        self._choices: dict[str, dict[str, Any]] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name the sequence: the name its button gets."""
        if self._coordinator() is None:
            return self.async_abort(reason="board_not_loaded")
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not name:
                errors[CONF_NAME] = "name_empty"
            elif self._name_taken(name):
                errors[CONF_NAME] = "name_taken"
            else:
                self._name = name
                self._key = uuid4().hex
                return await self.async_step_steps()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_NAME): str}),
            errors=errors,
        )

    async def async_step_steps(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """The steps so far: add one, remove one, or finish."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="board_not_loaded")
        errors: dict[str, str] = {}
        if user_input is not None:
            action = user_input[CONF_ACTION]
            if action == "add_step":
                return await self.async_step_add_step()
            if action == "remove_step" and self._steps:
                return await self.async_step_remove_step()
            if action == "finish" and self._steps:
                return self._finish()
            # Removing or finishing with nothing there.
            errors["base"] = "no_steps"
        return self.async_show_form(
            step_id="steps",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACTION): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["add_step", "remove_step", "finish"],
                            translation_key="sequence_action",
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                "name": self._name,
                "steps": describe_steps(
                    coordinator, self._steps, await async_function_labels(self.hass)
                ),
            },
        )

    async def async_step_add_step(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """A key of an appliance of this board, and the wait after it."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="board_not_loaded")
        if user_input is not None:
            chosen = self._choices.get(user_input.get(CONF_STEP, ""))
            if chosen is not None:
                wait = float(user_input.get(CONF_WAIT, DEFAULT_SEND_DELAY))
                self._steps.append({**chosen, STEP_WAIT: wait})
            return await self.async_step_steps()
        choices = step_choices(coordinator, await async_function_labels(self.hass))
        self._choices = {
            json.dumps(
                [step[STEP_APPLIANCE], step[STEP_COMMAND], step.get(STEP_ITEM)]
            ): step
            for step, _label in choices
        }
        if not choices:
            return self.async_show_form(
                step_id="add_step",
                data_schema=vol.Schema({}),
                errors={"base": "nothing_to_add"},
                description_placeholders={"name": self._name},
            )
        options = [
            selector.SelectOptionDict(value=value, label=label)
            for value, (_step, label) in zip(self._choices, choices, strict=True)
        ]
        return self.async_show_form(
            step_id="add_step",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STEP): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options, mode=selector.SelectSelectorMode.DROPDOWN
                        )
                    ),
                    vol.Required(
                        CONF_WAIT, default=DEFAULT_SEND_DELAY
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=60,
                            step=0.1,
                            mode=selector.NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                }
            ),
            description_placeholders={"name": self._name},
        )

    async def async_step_remove_step(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Take one step out."""
        coordinator = self._coordinator()
        if coordinator is None:
            return self.async_abort(reason="board_not_loaded")
        if user_input is not None:
            index = int(user_input.get(CONF_STEP, -1))
            if 0 <= index < len(self._steps):
                del self._steps[index]
            return await self.async_step_steps()
        labels = await async_function_labels(self.hass)
        options = [
            selector.SelectOptionDict(
                value=str(index),
                label=f"{index + 1}. {describe_step(coordinator, step, labels)}",
            )
            for index, step in enumerate(self._steps)
        ]
        return self.async_show_form(
            step_id="remove_step",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STEP): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options, mode=selector.SelectSelectorMode.LIST
                        )
                    )
                }
            ),
            description_placeholders={"name": self._name},
        )

    def _finish(self) -> SubentryFlowResult:
        """Create the sequence, or save the steps the Manage menu changed."""
        data = {CONF_STEPS: self._steps}
        if self.source == SOURCE_USER:
            return self.async_create_entry(
                title=self._name, data=data, unique_id=self._key
            )
        return self.async_update_and_abort(
            self._get_entry(), self._get_reconfigure_subentry(), data=data
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit the steps, or rename. A sequence is not moved on its own: its
        steps point at appliances of this board. Moving everything takes it."""
        subentry = self._get_reconfigure_subentry()
        self._name = subentry.title
        self._key = subentry.unique_id or ""
        self._steps = steps_of(subentry.data)
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["steps", "rename"],
            description_placeholders={
                "name": self._name,
                "count": str(len(self._steps)),
            },
        )
