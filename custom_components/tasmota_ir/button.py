"""A button per learned command.

This is the platform that removes the last script. Learn "power" for the
"Living room TV" and a button appears on that TV's own device, with a name, an
area and a place on a dashboard. Nothing else has to be written.

The entities are created and removed as the stored codes change, so a command
learned now shows up now, without restarting anything, and a command deleted
takes its button with it.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import DOMAIN, SIGNAL_CODES_UPDATED
from .coordinator import Appliance, CodeTooLargeError, TasmotaIrCoordinator
from .entity import TasmotaIrEntity

_LOGGER = logging.getLogger(__name__)


def button_unique_id(key: str, command: str) -> str:
    """A stable id: it follows the appliance key, so a rename changes nothing."""
    return f"{key}_{command}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a button per learned command, and keep the set in step."""
    coordinator: TasmotaIrCoordinator = entry.runtime_data
    known: set[tuple[str, str]] = set()

    @callback
    def _sync() -> None:
        """Add buttons for new commands and drop the ones that went away."""
        appliances = coordinator.appliances
        current = {
            (key, command)
            for key, commands in coordinator.codes.items()
            if key in appliances
            for command in commands
        }

        added: dict[str, list[TasmotaIrButton]] = defaultdict(list)
        for key, command in sorted(current - known):
            appliance = appliances[key]
            added[appliance.subentry_id].append(
                TasmotaIrButton(coordinator, appliance, command)
            )
        for subentry_id, buttons in added.items():
            async_add_entities(buttons, config_subentry_id=subentry_id)

        if removed := known - current:
            registry = async_get_entity_registry(hass)
            for key, command in removed:
                if entity_id := registry.async_get_entity_id(
                    "button", DOMAIN, button_unique_id(key, command)
                ):
                    registry.async_remove(entity_id)

        known.clear()
        known.update(current)

    _sync()
    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_CODES_UPDATED.format(entry_id=entry.entry_id), _sync
        )
    )


class TasmotaIrButton(TasmotaIrEntity, ButtonEntity):
    """One learned command, as a real entity on its appliance's device."""

    _attr_icon = "mdi:remote"

    def __init__(
        self, coordinator: TasmotaIrCoordinator, appliance: Appliance, command: str
    ) -> None:
        """Bind the button to one stored code."""
        super().__init__(coordinator, appliance)
        self._key = appliance.key
        self._command = command
        self._attr_unique_id = button_unique_id(appliance.key, command)
        # The device already carries the appliance name, so "power" on the
        # "TV Quarto" device reads as "TV Quarto power".
        self._attr_name = command

    async def async_press(self) -> None:
        """Send the code this button stands for."""
        code = self.coordinator.get_code(self._key, self._command)
        if code is None:
            raise HomeAssistantError(
                f"This appliance no longer has a command called '{self._command}'."
            )
        try:
            await self.coordinator.async_send_code(
                code, channel=self.coordinator.channel_for(self._key)
            )
        except CodeTooLargeError as err:
            raise HomeAssistantError(str(err)) from err

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Say which appliance and emitter this button belongs to."""
        appliance = self.coordinator.appliances.get(self._key)
        return {
            "appliance": appliance.name if appliance else None,
            "command": self._command,
            "emitter": self.coordinator.channel_for(self._key),
        }
