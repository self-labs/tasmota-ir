"""Shared entity base, and the two kinds of device this integration uses.

A board is one device, matched to the one the Tasmota integration created by
its MAC in ``connections``. Every appliance is a device of its own, linked to
the board with ``via_device`` and owned by its subentry, so Home Assistant lists
it under the board with its commands underneath.

The devices are registered in ``__init__.py`` before any platform runs. That is
what lets an appliance with no command learned yet still show up, and it keeps
the ``via_device`` link independent of which platform happens to start first.
The entities only point at them by identifier.
"""

from __future__ import annotations

import inspect
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import CONF_MAC, CONF_MODEL, CONF_VENDOR, DOMAIN, SIGNAL_AVAILABILITY
from .coordinator import Appliance, TasmotaIrCoordinator

# Home Assistant 2026.9 takes the parent as a device id and deprecates the
# identifier form; older releases only know the identifier form.
_TAKES_VIA_DEVICE_ID = (
    "via_device_id"
    in inspect.signature(dr.DeviceRegistry.async_get_or_create).parameters
)


@callback
def async_register_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create or refresh the board device and one device per appliance."""
    registry = dr.async_get(hass)
    coordinator: TasmotaIrCoordinator = entry.runtime_data

    board: dict[str, Any] = {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": entry.title,
        "manufacturer": "Tasmota",
    }
    if mac := entry.data.get(CONF_MAC):
        board["connections"] = {(CONNECTION_NETWORK_MAC, format_mac(mac))}
    board_device = registry.async_get_or_create(config_entry_id=entry.entry_id, **board)

    for appliance in coordinator.appliances.values():
        extra: dict[str, Any] = {}
        if vendor := appliance.data.get(CONF_VENDOR):
            extra["manufacturer"] = vendor
        if model := appliance.data.get(CONF_MODEL):
            extra["model"] = model
        if _TAKES_VIA_DEVICE_ID:
            extra["via_device_id"] = board_device.id
        else:
            extra["via_device"] = (DOMAIN, entry.entry_id)
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            config_subentry_id=appliance.subentry_id,
            identifiers={(DOMAIN, appliance.key)},
            name=appliance.name,
            **extra,
        )


class TasmotaIrEntity(Entity):
    """Base for every entity this integration creates."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, coordinator: TasmotaIrCoordinator, appliance: Appliance | None = None
    ) -> None:
        """Bind the entity to its board, or to one of the board's appliances."""
        self.coordinator = coordinator
        self.appliance = appliance
        key = appliance.key if appliance else coordinator.entry.entry_id
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, key)})

    async def async_added_to_hass(self) -> None:
        """Refresh the state whenever the board goes online or offline."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_AVAILABILITY.format(entry_id=self.coordinator.entry.entry_id),
                self.async_write_ha_state,
            )
        )

    @property
    def available(self) -> bool:
        """Follow the board's last will, not our own optimism."""
        return self.coordinator.available
