"""A button per learned command.

This is the platform that removes the last script. Learn "Living room TV" /
"power" and a ``button.living_room_tv_power`` appears, with a name, an area and
a device, ready to drop on a dashboard. Nothing else has to be written.

The entities are created and removed as the stored codes change, so a command
learned now shows up now, without restarting anything, and a command deleted
takes its button with it.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import CMND_IRSEND, DOMAIN, SIGNAL_CODES_UPDATED
from .coordinator import CodeTooLargeError, TasmotaIrCoordinator
from .entity import TasmotaIrEntity

_LOGGER = logging.getLogger(__name__)


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
        current = {
            (appliance, command)
            for appliance, commands in coordinator.codes.items()
            for command in commands
        }

        if added := current - known:
            async_add_entities(
                TasmotaIrButton(coordinator, appliance, command)
                for appliance, command in sorted(added)
            )

        if removed := known - current:
            registry = async_get_entity_registry(hass)
            for appliance, command in removed:
                unique_id = _unique_id(entry.entry_id, appliance, command)
                if entity_id := registry.async_get_entity_id(
                    "button", DOMAIN, unique_id
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


def _unique_id(entry_id: str, appliance: str, command: str) -> str:
    """A stable id that survives a rename of the entity, but not of the code."""
    return f"{entry_id}_{appliance}_{command}"


class TasmotaIrButton(TasmotaIrEntity, ButtonEntity):
    """One learned command, as a real entity."""

    def __init__(
        self, coordinator: TasmotaIrCoordinator, appliance: str, command: str
    ) -> None:
        """Bind the button to one stored code."""
        super().__init__(coordinator)
        self._appliance = appliance
        self._command = command
        self._attr_unique_id = _unique_id(
            coordinator.entry.entry_id, appliance, command
        )
        self._attr_name = f"{appliance} {command}"
        self._attr_icon = "mdi:remote"

    async def async_press(self) -> None:
        """Send the code this button stands for."""
        code = self.coordinator.get_code(self._appliance, self._command)
        if code is None:
            raise HomeAssistantError(
                f"'{self._appliance}' no longer has a command called "
                f"'{self._command}'."
            )
        channel = self.coordinator.channel_for(self._appliance)
        try:
            await self.coordinator.async_send_json(CMND_IRSEND, code, channel=channel)
        except CodeTooLargeError as err:
            raise HomeAssistantError(str(err)) from err

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Say which appliance and emitter this button belongs to."""
        return {
            "appliance": self._appliance,
            "command": self._command,
            "emitter": self.coordinator.channel_for(self._appliance),
        }
