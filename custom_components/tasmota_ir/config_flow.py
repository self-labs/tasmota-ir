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
import json
import logging
from collections.abc import Callable
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
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CHANNEL,
    CONF_CHANNELS,
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
    DOMAIN,
    KEY_IRHVAC,
    KNOWN_MODELS,
    LEARN_TIMEOUT_UI,
    MAX_CHANNELS,
    SUBENTRY_APPLIANCE,
    SUBENTRY_CLIMATE,
    swing_vertical_default,
)
from .coordinator import (
    CodeTooLargeError,
    TasmotaIrCoordinator,
    check_code_size,
    extract_code,
    is_hvac_frame,
)

_LOGGER = logging.getLogger(__name__)

DISCOVERY_TOPIC = "tasmota/discovery/+/config"
DISCOVERY_WINDOW = 4.0

MANUAL = "__manual__"

CONF_NAME = "name"
CONF_COMMAND = "command"

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

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """An ordinary appliance, and an air conditioner."""
        return {
            SUBENTRY_APPLIANCE: ApplianceSubentryFlow,
            SUBENTRY_CLIMATE: ClimateSubentryFlow,
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
        self._key: str = ""
        self._learn_task: asyncio.Task[dict[str, Any] | None] | None = None
        self._received: dict[str, Any] | None = None

    # ---- helpers -------------------------------------------------------

    def _coordinator(self) -> TasmotaIrCoordinator | None:
        """The board's coordinator, when the board is up."""
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return None
        return entry.runtime_data

    def _channel_selector(self) -> selector.NumberSelector:
        """Offer only the emitters the board reported."""
        channels = int(self._get_entry().data.get(CONF_CHANNELS, 1))
        return selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=min(channels, MAX_CHANNELS),
                step=1,
                mode=selector.NumberSelectorMode.BOX,
            )
        )

    def _name_taken(self, name: str, ignore: str | None = None) -> bool:
        """Whether another appliance of this board already has this name."""
        wanted = name.strip().casefold()
        return any(
            sub.title.strip().casefold() == wanted
            for sub_id, sub in self._get_entry().subentries.items()
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
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data_updates={CONF_CHANNEL: int(user_input[CONF_CHANNEL])},
            )
        return self.async_show_form(
            step_id="channel",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CHANNEL, default=int(subentry.data.get(CONF_CHANNEL, 1))
                    ): self._channel_selector()
                }
            ),
            description_placeholders={"name": subentry.title},
        )

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
                    vol.Required(CONF_CHANNEL, default=1): self._channel_selector(),
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
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["learn", "delete_command", "channel", "rename"],
            description_placeholders={"name": self._name},
        )

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
                    vol.Required(CONF_CHANNEL, default=1): self._channel_selector(),
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
        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["settings", "read_remote", "channel", "rename"],
            description_placeholders={
                "name": self._name,
                "vendor": subentry.data.get(CONF_VENDOR, ""),
                "model": subentry.data.get(CONF_MODEL, "") or "-",
            },
        )

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
        return self.async_show_form(
            step_id="settings",
            data_schema=schema,
            errors=errors,
            description_placeholders={"name": subentry.title, "vendor": vendor},
        )
