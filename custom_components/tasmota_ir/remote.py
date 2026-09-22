"""The remote entity: learn, send and forget IR commands.

One entity per board. The emitter is never a parameter here, it is a property
of the appliance, so a command sent to the television cannot leave through the
emitter pointed at the air conditioner.

``device`` in these actions is the appliance name, the title of its subentry.
Learning under a name that does not exist yet creates the appliance, so nothing
learned through an action is ever hidden from the interface.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from homeassistant.components.remote import (
    ATTR_COMMAND,
    ATTR_DELAY_SECS,
    ATTR_DEVICE,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
    RemoteEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    LEARN_TIMEOUT,
    SIGNAL_CODES_UPDATED,
)
from .coordinator import (
    Appliance,
    CodeTooLargeError,
    TasmotaIrCoordinator,
    check_code_size,
    extract_code,
    is_hvac_frame,
)
from .entity import TasmotaIrEntity

_LOGGER = logging.getLogger(__name__)

ATTR_TIMEOUT = "timeout"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the single remote entity for this board."""
    coordinator: TasmotaIrCoordinator = entry.runtime_data
    async_add_entities([TasmotaIrRemote(coordinator)])


class TasmotaIrRemote(TasmotaIrEntity, RemoteEntity, RestoreEntity):
    """An IR blaster exposed through the standard remote services."""

    _attr_name = None
    _attr_supported_features = (
        RemoteEntityFeature.LEARN_COMMAND | RemoteEntityFeature.DELETE_COMMAND
    )

    def __init__(self, coordinator: TasmotaIrCoordinator) -> None:
        """Set up the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.entry.entry_id
        self._attr_is_on = True

    async def async_added_to_hass(self) -> None:
        """Restore whether sending was left enabled, and follow the store."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            self._attr_is_on = state.state != "off"
        # Without this the attributes keep the picture they had at creation, so
        # the interface shows no commands on a remote that has just learned one.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CODES_UPDATED.format(entry_id=self.coordinator.entry.entry_id),
                self.async_write_ha_state,
            )
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Allow sending again."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop sending without removing anything."""
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send one or more learned commands."""
        if not self._attr_is_on:
            _LOGGER.debug("%s is off, ignoring send", self.entity_id)
            return

        appliance: str | None = kwargs.get(ATTR_DEVICE)
        repeats: int = kwargs.get(ATTR_NUM_REPEATS) or 1
        delay: float = kwargs.get(ATTR_DELAY_SECS) or DEFAULT_DELAY_SECS
        commands = list(command)

        target = self._appliance(appliance)
        codes = [(name, self._resolve(target, name)) for name in commands]

        channel = self.coordinator.channel_for(target.key)
        for repeat in range(repeats):
            for index, (name, code) in enumerate(codes):
                if repeat or index:
                    await asyncio.sleep(delay)
                try:
                    await self.coordinator.async_send_code(code, channel=channel)
                except CodeTooLargeError as err:
                    raise HomeAssistantError(
                        f"The code stored for '{name}' is too large for the board "
                        f"to accept in one MQTT message: {err}"
                    ) from err

    def _appliance(self, name: str | None) -> Appliance:
        """Find the appliance by name, or say which names exist."""
        if not name:
            raise ServiceValidationError(
                "This remote stores commands per appliance, so 'device' is "
                "required. Use the appliance name shown under the board, for "
                "example device: 'Living room TV'."
            )
        appliance = self.coordinator.find_appliance(name)
        if appliance is None:
            names = ", ".join(
                sorted(a.name for a in self.coordinator.appliances.values())
            )
            raise ServiceValidationError(
                f"There is no appliance called '{name}' on this board."
                + (f" It has: {names}." if names else " It has none yet.")
            )
        return appliance

    def _resolve(self, appliance: Appliance, command: str) -> dict[str, Any]:
        """Find a stored code, or explain precisely what is missing."""
        code = self.coordinator.get_code(appliance.key, command)
        if code is None:
            known = ", ".join(self.coordinator.commands_of(appliance.key))
            raise ServiceValidationError(
                f"'{appliance.name}' has no command called '{command}'."
                + (f" It knows: {known}." if known else " It has no commands yet.")
            )
        return code

    async def async_learn_command(self, **kwargs: Any) -> None:
        """Capture a code from the receiver and store it under a name."""
        appliance: str | None = kwargs.get(ATTR_DEVICE)
        commands: list[str] = kwargs.get(ATTR_COMMAND) or []
        timeout: int = kwargs.get(ATTR_TIMEOUT) or LEARN_TIMEOUT

        if not appliance or not commands:
            raise ServiceValidationError(
                "Learning needs both 'device' and 'command', so the code has "
                "somewhere to live, for example device: 'Living room TV', "
                "command: 'power'."
            )
        if not self.coordinator.entry.data.get("has_receiver", True):
            raise ServiceValidationError(
                "This board has no IRrecv GPIO assigned, so it cannot learn. "
                "Assign one in the Tasmota template and reload the integration."
            )

        existing = self.coordinator.find_appliance(appliance)
        key = existing.key if existing else uuid4().hex
        learned: dict[str, dict[str, Any]] = {}
        try:
            for name in commands:
                received = await self.coordinator.async_wait_for_code(timeout)
                if received is None:
                    raise HomeAssistantError(
                        f"Nothing was received while learning '{name}'. Point the "
                        "remote at the receiver and press the key once, on its "
                        "own: two presses in a row decode as one broken frame."
                    )
                if is_hvac_frame(received):
                    raise HomeAssistantError(
                        f"That is an air conditioner remote, and storing it as "
                        f"'{name}' would capture one temperature in one mode and "
                        "nothing else. Add it under the board with 'Add an air "
                        "conditioner', which reads the vendor and the model from "
                        "this same frame and then builds every command."
                    )
                code = extract_code(received)
                try:
                    check_code_size(code)
                except CodeTooLargeError as err:
                    raise HomeAssistantError(
                        f"'{name}' was received but cannot be stored: {err}"
                    ) from err
                learned[name] = code
                _LOGGER.info("Learned %s/%s on %s", appliance, name, self.entity_id)
        finally:
            # Whatever was learned before a timeout is kept. For a new name the
            # codes are written first and the appliance created after, because
            # creating it reloads the entry.
            if learned:
                await self.coordinator.async_store_codes(key, learned)
                if existing is None:
                    self.coordinator.add_appliance(appliance, key=key)

    async def async_delete_command(self, **kwargs: Any) -> None:
        """Forget one or more commands."""
        appliance: str | None = kwargs.get(ATTR_DEVICE)
        commands: list[str] = kwargs.get(ATTR_COMMAND) or []
        if not appliance:
            raise ServiceValidationError(
                "Deleting needs 'device', the appliance the command belongs to."
            )
        target = self._appliance(appliance)
        for name in commands:
            if not await self.coordinator.async_delete_code(target.key, name):
                raise ServiceValidationError(
                    f"'{target.name}' has no command called '{name}'."
                )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose what the remote knows, so it can be inspected without the logs."""
        appliances = self.coordinator.appliances.values()
        return {
            "appliances": sorted(a.name for a in appliances),
            "commands": {
                a.name: self.coordinator.commands_of(a.key) for a in appliances
            },
            "emitters": self.coordinator.entry.data.get("channels", 1),
        }
