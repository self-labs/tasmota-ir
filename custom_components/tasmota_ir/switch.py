"""The on and off extras of an air conditioner: display, beep, self clean, filter.

They are not separate commands. Every IRHVAC frame carries the whole state of
the unit, so a switch only changes what the climate entity sends next, and the
climate entity keeps the state. A switch flipped while the unit is off is
remembered and goes out with the next turn on, like a temperature does.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import DOMAIN, SIGNAL_CLIMATE_EXTRAS, SUBENTRY_CLIMATE
from .coordinator import Appliance, TasmotaIrCoordinator
from .device_types import SUBENTRY_SWITCH
from .entity import TasmotaIrEntity
from .hvac_extras import SWITCH_EXTRAS, SWITCH_TRANSLATION, appliance_extras
from .typed import TasmotaIrTypedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """A switch per on and off extra each air conditioner really sends."""
    coordinator: TasmotaIrCoordinator = entry.runtime_data
    registry = async_get_entity_registry(hass)
    for appliance in coordinator.appliances.values():
        if appliance.kind == SUBENTRY_SWITCH:
            async_add_entities(
                [TasmotaIrTypedSwitch(coordinator, appliance)],
                config_subentry_id=appliance.subentry_id,
            )
            continue
        if appliance.kind != SUBENTRY_CLIMATE:
            continue
        extras = appliance_extras(appliance.data)
        # An extra unticked in Settings takes its switch with it, rather than
        # leaving one behind that no longer does anything.
        for extra in SWITCH_EXTRAS:
            if extra in extras:
                continue
            if entity_id := registry.async_get_entity_id(
                "switch", DOMAIN, f"{appliance.key}_{extra}"
            ):
                registry.async_remove(entity_id)
        switches = [
            TasmotaIrExtraSwitch(coordinator, appliance, extra)
            for extra in SWITCH_EXTRAS
            if extra in extras
        ]
        if switches:
            async_add_entities(switches, config_subentry_id=appliance.subentry_id)


class TasmotaIrExtraSwitch(TasmotaIrEntity, SwitchEntity):
    """One extra of an air conditioner, kept by its climate entity."""

    def __init__(
        self, coordinator: TasmotaIrCoordinator, appliance: Appliance, extra: str
    ) -> None:
        """Bind the switch to one extra of one unit."""
        super().__init__(coordinator, appliance)
        self._key = appliance.key
        self._extra = extra
        self._attr_unique_id = f"{appliance.key}_{extra}"
        self._attr_translation_key = SWITCH_TRANSLATION[extra]
        if extra == "beep":
            self._attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        """Follow the climate entity whenever the extras change."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CLIMATE_EXTRAS.format(key=self._key),
                self.async_write_ha_state,
            )
        )

    @property
    def is_on(self) -> bool | None:
        """What the unit was last told, or unknown before its climate is up."""
        climate = self.coordinator.climates.get(self._key)
        return None if climate is None else climate.extra_is_on(self._extra)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the extra on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the extra off."""
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        climate = self.coordinator.climates.get(self._key)
        if climate is None:
            raise HomeAssistantError(
                "The air conditioner is not loaded yet, so nothing was sent."
            )
        await climate.async_set_extra(self._extra, on)


class TasmotaIrTypedSwitch(TasmotaIrTypedEntity, SwitchEntity):
    """Something that only turns on and off, by its learned keys."""

    @property
    def is_on(self) -> bool:
        """The power sensor, or what was last sent or heard."""
        return self.power_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn it on."""
        await self._async_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn it off."""
        await self._async_power(False)
