"""The Tasmota IR integration."""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    CONF_APPLIANCES,
    CONF_CHANNEL,
    CONF_KIND,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_MODEL,
    CONF_VENDOR,
    DEFAULT_CHANNEL,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DOMAIN,
    KIND_CLIMATE,
    STORAGE_KEY_FORMAT,
    STORAGE_VERSION,
    SUBENTRY_APPLIANCE,
    SUBENTRY_CLIMATE,
)
from .coordinator import TasmotaIrCoordinator
from .entity import async_register_devices

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

    if stale := coordinator.prune_codes():
        _LOGGER.info(
            "Dropped the codes of %d appliance(s) removed from %s",
            len(stale),
            entry.title,
        )
    async_register_devices(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TasmotaIrConfigEntry) -> bool:
    """Tear one board down."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_unload()
    return unloaded


async def _async_entry_updated(
    hass: HomeAssistant, entry: TasmotaIrConfigEntry
) -> None:
    """Reload when an appliance is added, changed or removed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring an entry from an older version up to date."""
    if entry.version > 2:
        # Written by a newer release. Refuse rather than guess.
        return False
    if entry.version == 1:
        await _async_migrate_appliances_to_subentries(hass, entry)
    return True


async def _async_migrate_appliances_to_subentries(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Turn the appliances kept in the options into subentries.

    Version 1 kept appliances as a dict in the entry options and the codes
    keyed by appliance name. That made every appliance invisible in the
    interface except through a menu, and a rename would have orphaned its codes.
    Each appliance becomes a subentry with a generated key, the codes and the
    entity registry are re-keyed to it, and the entity ids stay what they were,
    so no dashboard or automation notices.

    A name that has codes but was never added as an appliance becomes one too,
    on the first emitter, which is where its commands were already being sent.
    """
    store: Store[dict[str, dict[str, Any]]] = Store(
        hass, STORAGE_VERSION, STORAGE_KEY_FORMAT.format(entry_id=entry.entry_id)
    )
    old_codes: dict[str, dict[str, Any]] = await store.async_load() or {}
    appliances: dict[str, dict[str, Any]] = dict(
        entry.options.get(CONF_APPLIANCES, {})
    )

    keys: dict[str, tuple[str, str]] = {}
    for name in sorted(set(appliances) | set(old_codes)):
        config = appliances.get(name, {})
        is_climate = config.get(CONF_KIND) == KIND_CLIMATE
        data: dict[str, Any] = {
            CONF_CHANNEL: int(config.get(CONF_CHANNEL, DEFAULT_CHANNEL))
        }
        if is_climate:
            data.update(
                {
                    CONF_VENDOR: config.get(CONF_VENDOR, ""),
                    CONF_MODEL: config.get(CONF_MODEL, ""),
                    CONF_MIN_TEMP: config.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP),
                    CONF_MAX_TEMP: config.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP),
                }
            )
        key = uuid4().hex
        subentry = ConfigSubentry(
            data=MappingProxyType(data),
            subentry_type=SUBENTRY_CLIMATE if is_climate else SUBENTRY_APPLIANCE,
            title=name,
            unique_id=key,
        )
        hass.config_entries.async_add_subentry(entry, subentry)
        keys[name] = (key, subentry.subentry_id)

    await store.async_save(
        {keys[name][0]: commands for name, commands in old_codes.items()}
    )

    registry = er.async_get(hass)
    for name, commands in old_codes.items():
        key, subentry_id = keys[name]
        for command in commands:
            old_id = f"{entry.entry_id}_{name}_{command}"
            if entity_id := registry.async_get_entity_id("button", DOMAIN, old_id):
                registry.async_update_entity(
                    entity_id,
                    new_unique_id=f"{key}_{command}",
                    config_subentry_id=subentry_id,
                )
    for name, config in appliances.items():
        if config.get(CONF_KIND) != KIND_CLIMATE:
            continue
        key, subentry_id = keys[name]
        old_id = f"{entry.entry_id}_climate_{name}"
        if entity_id := registry.async_get_entity_id("climate", DOMAIN, old_id):
            registry.async_update_entity(
                entity_id,
                new_unique_id=f"{key}_climate",
                config_subentry_id=subentry_id,
            )

    hass.config_entries.async_update_entry(entry, options={}, version=2)
    _LOGGER.info(
        "Moved %d appliance(s) of %s to subentries", len(keys), entry.title
    )
