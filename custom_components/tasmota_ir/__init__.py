"""The Tasmota IR integration."""

from __future__ import annotations

import logging

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import TasmotaIrCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.REMOTE,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.EVENT,
]

type TasmotaIrConfigEntry = ConfigEntry[TasmotaIrCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TasmotaIrConfigEntry) -> bool:
    """Set up one board."""
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT is not available yet")

    coordinator = TasmotaIrCoordinator(hass, entry)
    await coordinator.async_setup()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TasmotaIrConfigEntry) -> bool:
    """Tear one board down."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_unload()
    return unloaded


async def _async_options_updated(
    hass: HomeAssistant, entry: TasmotaIrConfigEntry
) -> None:
    """Reload when appliances or their emitters change."""
    await hass.config_entries.async_reload(entry.entry_id)
