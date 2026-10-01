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

from .const import (
    CONF_HAS_RECEIVER,
    KEY_IRHVAC,
    SIGNAL_CODES_UPDATED,
    SIGNAL_IR_RECEIVED,
    SUBENTRY_APPLIANCE,
)
from .coordinator import Appliance, TasmotaIrCoordinator
from .device_types import TYPED_KINDS, is_list, roles_of
from .entity import TasmotaIrEntity
from .typed import is_comparable, is_same_code

EVENT_IR_RECEIVED = "ir_received"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the receiver entity, and each appliance's remote, with a receiver."""
    coordinator: TasmotaIrCoordinator = entry.runtime_data
    if not entry.data.get(CONF_HAS_RECEIVER, False):
        return
    async_add_entities([TasmotaIrEvent(coordinator)])
    for appliance in coordinator.appliances.values():
        if appliance.kind == SUBENTRY_APPLIANCE or appliance.kind in TYPED_KINDS:
            async_add_entities(
                [TasmotaIrApplianceEvent(coordinator, appliance)],
                config_subentry_id=appliance.subentry_id,
            )


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


class TasmotaIrApplianceEvent(TasmotaIrEntity, EventEntity):
    """One appliance's own remote: an event type per key it learned.

    The board's receiver fires on everything it hears. This one only fires on
    this appliance's keys, named, so an automation says "when power is pressed
    on the TV Quarto remote" from the interface, with no template. Raw codes
    are never compared: two captures of the same raw key are never identical.
    """

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_translation_key = "remote"

    def __init__(self, coordinator: TasmotaIrCoordinator, appliance: Appliance) -> None:
        """Bind the event to one appliance and its learned keys."""
        super().__init__(coordinator, appliance)
        self._key = appliance.key
        self._typed = appliance.kind in TYPED_KINDS
        self._attr_unique_id = f"{appliance.key}_remote"
        self._codes: dict[str, dict[str, Any]] = {}
        self._refresh()

    def _refresh(self) -> None:
        """Read the keys again: learned from the store, or a type's functions.

        The functions come before the items of a list, and the first name
        wins: a source called "power" must not take the power key's place. A
        raw code is left out, since it can never be recognised.
        """
        codes: dict[str, dict[str, Any]] = {}
        if self._typed and self.appliance is not None:
            kind = self.appliance.kind
            roles = roles_of(self.appliance.data)
            for name, value in roles.items():
                if isinstance(value, dict) and not is_list(kind, name):
                    codes.setdefault(name, value)
            for name, value in roles.items():
                if isinstance(value, dict) and is_list(kind, name):
                    for item, code in value.items():
                        if isinstance(code, dict):
                            codes.setdefault(item, code)
        else:
            codes = dict(self.coordinator.codes.get(self._key, {}))
        self._codes = {
            name: code for name, code in codes.items() if is_comparable(code)
        }
        self._attr_event_types = list(self._codes)

    async def async_added_to_hass(self) -> None:
        """Follow the receiver, and the keys as they are learned or deleted."""
        await super().async_added_to_hass()
        entry_id = self.coordinator.entry.entry_id
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_IR_RECEIVED.format(entry_id=entry_id),
                self._handle_received,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CODES_UPDATED.format(entry_id=entry_id),
                self._codes_updated,
            )
        )

    @callback
    def _codes_updated(self) -> None:
        self._refresh()
        self.async_write_ha_state()

    @callback
    def _handle_received(self, received: dict[str, Any]) -> None:
        """Fire every key this frame is: one key learned under two names is both."""
        for name, code in self._codes.items():
            if is_same_code(code, received):
                self._trigger_event(name)
                self.async_write_ha_state()
