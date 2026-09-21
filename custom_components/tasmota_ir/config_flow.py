"""Config and options flow.

Adding a board is three questions at most, and two of them are answered by the
board itself: the discovery topic Tasmota already publishes names it, and a
``Gpio`` probe counts its emitters. Nobody is asked how many IR LEDs their
hardware has.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_APPLIANCES,
    CONF_CHANNEL,
    CONF_CHANNELS,
    CONF_FULL_TOPIC,
    CONF_HAS_RECEIVER,
    CONF_KIND,
    CONF_MAC,
    CONF_TOPIC,
    DOMAIN,
    KIND_GENERIC,
    MAX_CHANNELS,
)
from .coordinator import TasmotaIrCoordinator

_LOGGER = logging.getLogger(__name__)

DISCOVERY_TOPIC = "tasmota/discovery/+/config"
DISCOVERY_WINDOW = 4.0

MANUAL = "__manual__"


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

    VERSION = 1

    def __init__(self) -> None:
        """Start with nothing discovered."""
        self._boards: dict[str, dict[str, Any]] = {}

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
                        vol.Optional(
                            CONF_FULL_TOPIC, default="%prefix%/%topic%/"
                        ): str,
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

    async def _async_probe_and_create(
        self, board: dict[str, Any]
    ) -> ConfigFlowResult:
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
            options={CONF_APPLIANCES: {}},
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> TasmotaIrOptionsFlow:
        """Hand over to the options flow."""
        return TasmotaIrOptionsFlow()


class _FakeEntry:
    """The little a probe needs from a config entry, before one exists."""

    entry_id = "probe"
    options: dict[str, Any] = {}

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


class TasmotaIrOptionsFlow(OptionsFlow):
    """Manage the appliances and which emitter each one uses."""

    def __init__(self) -> None:
        """Start at the menu."""
        self._editing: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer to add, edit or remove an appliance."""
        return self.async_show_menu(
            step_id="init", menu_options=["add", "edit", "remove"]
        )

    async def async_step_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name an appliance and say which emitter points at it."""
        if user_input is not None:
            appliances = dict(self.config_entry.options.get(CONF_APPLIANCES, {}))
            appliances[user_input["name"]] = {
                CONF_CHANNEL: int(user_input[CONF_CHANNEL]),
                CONF_KIND: KIND_GENERIC,
            }
            return self.async_create_entry(
                data={**self.config_entry.options, CONF_APPLIANCES: appliances}
            )

        return self.async_show_form(
            step_id="add", data_schema=self._appliance_schema()
        )

    async def async_step_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the emitter of an appliance that already exists."""
        appliances = dict(self.config_entry.options.get(CONF_APPLIANCES, {}))
        if not appliances:
            return self.async_abort(reason="no_appliances")

        if user_input is not None:
            name = user_input["name"]
            appliances[name] = {
                **appliances.get(name, {}),
                CONF_CHANNEL: int(user_input[CONF_CHANNEL]),
            }
            return self.async_create_entry(
                data={**self.config_entry.options, CONF_APPLIANCES: appliances}
            )

        return self.async_show_form(
            step_id="edit",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): vol.In(sorted(appliances)),
                    vol.Required(CONF_CHANNEL, default=1): self._channel_selector(),
                }
            ),
        )

    async def async_step_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Drop an appliance. Its learned codes stay until deleted explicitly."""
        appliances = dict(self.config_entry.options.get(CONF_APPLIANCES, {}))
        if not appliances:
            return self.async_abort(reason="no_appliances")

        if user_input is not None:
            appliances.pop(user_input["name"], None)
            return self.async_create_entry(
                data={**self.config_entry.options, CONF_APPLIANCES: appliances}
            )

        return self.async_show_form(
            step_id="remove",
            data_schema=vol.Schema({vol.Required("name"): vol.In(sorted(appliances))}),
        )

    def _appliance_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("name"): str,
                vol.Required(CONF_CHANNEL, default=1): self._channel_selector(),
            }
        )

    def _channel_selector(self) -> selector.NumberSelector:
        """Offer only the emitters the board reported."""
        channels = int(self.config_entry.data.get(CONF_CHANNELS, 1))
        return selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=min(channels, MAX_CHANNELS),
                step=1,
                mode=selector.NumberSelectorMode.BOX,
            )
        )
