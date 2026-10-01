"""Home Assistant's own infrared integrations, through this board.

LG, Samsung, Edifier, Marantz, Dyson and the generic LED strips have
integrations of their own in Home Assistant that know every code of those
devices. They send through an ``infrared`` entity, and each appliance here gets
one, so the emitter and the board stay a property of the appliance: change
either under Manage appliance, and the integration using it never notices.

The receiver is per appliance too, for the same reason. It relays everything
the appliance's board hears, and the integration's own decoder decides what is
its device's. Air conditioners get neither: their climate entity already
drives them, and a second one through another integration would fight it.
"""

from __future__ import annotations

from homeassistant.components.infrared import (
    InfraredCommand,
    InfraredEmitterEntity,
    InfraredReceivedSignal,
    InfraredReceiverEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_HAS_RECEIVER, RAW_FREQUENCY, SUBENTRY_APPLIANCE
from .coordinator import Appliance, CodeTooLargeError, TasmotaIrCoordinator
from .entity import TasmotaIrEntity
from .raw_timings import encode_compact, normalize


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """An emitter per appliance, and a receiver too when the board has one."""
    coordinator: TasmotaIrCoordinator = entry.runtime_data
    has_receiver = bool(entry.data.get(CONF_HAS_RECEIVER, False))
    for appliance in coordinator.appliances.values():
        if appliance.kind != SUBENTRY_APPLIANCE:
            continue
        entities: list[TasmotaIrEmitter | TasmotaIrReceiver] = [
            TasmotaIrEmitter(coordinator, appliance)
        ]
        if has_receiver:
            entities.append(TasmotaIrReceiver(coordinator, appliance))
        async_add_entities(entities, config_subentry_id=appliance.subentry_id)


class TasmotaIrEmitter(TasmotaIrEntity, InfraredEmitterEntity):
    """What other integrations send through, on the appliance's own emitter."""

    # The device already carries the appliance name, and this is what a person
    # picks as the transmitter: "TV Quarto" reads right.
    _attr_name = None

    def __init__(self, coordinator: TasmotaIrCoordinator, appliance: Appliance) -> None:
        """Bind the emitter to one appliance, whatever emitter it is on today."""
        super().__init__(coordinator, appliance)
        self._key = appliance.key
        self._attr_unique_id = f"{appliance.key}_infrared"

    async def async_send_command(self, command: InfraredCommand) -> None:
        """Send another integration's command through this appliance's emitter."""
        if not self.coordinator.available:
            raise HomeAssistantError(
                f"{self.coordinator.entry.title} is offline, so nothing was sent."
            )
        timings = normalize(command.get_raw_timings())
        if not timings:
            raise HomeAssistantError("The command has no infrared pulses to send.")
        raw = encode_compact(timings)
        frequency = command.modulation or RAW_FREQUENCY
        try:
            await self.coordinator.async_send_compact(
                raw,
                frequency,
                self.coordinator.channel_for(self._key),
                fallback=False,
            )
        except CodeTooLargeError as err:
            raise HomeAssistantError(str(err)) from err
        self.coordinator.last_infrared[self._key] = (raw, frequency)


class TasmotaIrReceiver(TasmotaIrEntity, InfraredReceiverEntity):
    """Everything the appliance's board hears, for other integrations to decode."""

    # A name of its own: Home Assistant only names a receiver after its class
    # from 2026.8 on, and before that it would take the appliance's name and
    # the entity id infrared.<appliance>_2, next to the emitter.
    _attr_translation_key = "infrared_receiver"

    def __init__(self, coordinator: TasmotaIrCoordinator, appliance: Appliance) -> None:
        """Bind the receiver to one appliance, whatever board it is on today."""
        super().__init__(coordinator, appliance)
        self._attr_unique_id = f"{appliance.key}_infrared_receiver"

    async def async_added_to_hass(self) -> None:
        """Start relaying the board's frames."""
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_timings_listener(self._relay))

    @callback
    def _relay(self, timings: list[int]) -> None:
        """Hand one decoded frame to whoever subscribed to this receiver."""
        self._handle_received_signal(InfraredReceivedSignal(timings=list(timings)))
