"""The receiver, as an event source.

An IR receiver is literally a thing that emits events, so this is the platform
that fits it. With it you can automate on "somebody pressed a key", on any
remote, without writing an MQTT trigger and without the code having to be
learned first. The decoded frame rides along in the attributes.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_HAS_RECEIVER, KEY_IRHVAC, SIGNAL_IR_RECEIVED
from .coordinator import TasmotaIrCoordinator
from .entity import TasmotaIrEntity

EVENT_IR_RECEIVED = "ir_received"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the receiver entity, if the board has a receiver at all."""
    coordinator: TasmotaIrCoordinator = entry.runtime_data
    if not entry.data.get(CONF_HAS_RECEIVER, False):
        return
    async_add_entities([TasmotaIrEvent(coordinator)])


class TasmotaIrEvent(TasmotaIrEntity, EventEntity):
    """Fires whenever the board decodes a frame."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = [EVENT_IR_RECEIVED]
    _attr_translation_key = "receiver"
    _attr_name = "IR receiver"

    def __init__(self, coordinator: TasmotaIrCoordinator) -> None:
        """Bind the entity to its board."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_receiver"

    async def async_added_to_hass(self) -> None:
        """Start listening for decoded frames."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_IR_RECEIVED.format(entry_id=self.coordinator.entry.entry_id),
                self._handle_received,
            )
        )

    @callback
    def _handle_received(self, received: dict[str, Any]) -> None:
        """Fire the event with the decoded frame attached.

        Whether this code is already known is part of the payload, so an
        automation can act on an unknown remote without having to look the code
        up itself.
        """
        attributes: dict[str, Any] = {
            "protocol": received.get("Protocol"),
            "bits": received.get("Bits"),
            "data": received.get("Data"),
            "repeat": received.get("Repeat"),
            "is_hvac": KEY_IRHVAC in received,
            "known_as": self._lookup(received),
        }
        self._trigger_event(EVENT_IR_RECEIVED, attributes)
        self.async_write_ha_state()

    def _lookup(self, received: dict[str, Any]) -> str | None:
        """Name this frame if it matches something already learned."""
        data = received.get("Data")
        if not data:
            return None
        appliances = self.coordinator.appliances
        for key, commands in self.coordinator.codes.items():
            for command, code in commands.items():
                if code.get("Data") == data and key in appliances:
                    return f"{appliances[key].name}/{command}"
        return None
