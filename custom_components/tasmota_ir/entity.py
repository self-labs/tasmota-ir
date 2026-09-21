"""Shared entity base.

The only thing worth reading here is the device info. Home Assistant matches
devices on ``connections``, and the Tasmota integration registers each board
with ``{(CONNECTION_NETWORK_MAC, mac)}`` and no identifiers. Declaring the same
MAC therefore does not create a second device: it attaches this config entry to
the one the user already has, so the IR entities land on the same card as the
board's diagnostics instead of in a card of their own.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.entity import Entity

from .const import CONF_MAC, DOMAIN
from .coordinator import TasmotaIrCoordinator


class TasmotaIrEntity(Entity):
    """Base for every entity this integration creates."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: TasmotaIrCoordinator) -> None:
        """Bind the entity to its board."""
        self.coordinator = coordinator
        entry = coordinator.entry
        mac = entry.data.get(CONF_MAC)

        if mac:
            self._attr_device_info = DeviceInfo(
                connections={(CONNECTION_NETWORK_MAC, format_mac(mac))}
            )
        else:
            # No MAC means the board was added by topic alone, so there is
            # nothing to merge with and a device of our own is the best we can do.
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, entry.entry_id)},
                name=entry.title,
                manufacturer="Tasmota",
            )

    @property
    def available(self) -> bool:
        """Follow the board's last will, not our own optimism."""
        return self.coordinator.available
