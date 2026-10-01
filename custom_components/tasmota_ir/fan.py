"""A fan, by its learned keys.

Speeds come one of two ways. Some remotes have a key per speed, and pressing it
is enough. Others have one key that goes to the next speed and back to the
first, and then the integration presses it as many times as it takes from the
speed it assumes the fan is on. The remote in someone's hand moves that
assumption too, since the receiver hears it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .coordinator import Appliance, TasmotaIrCoordinator
from .device_types import SUBENTRY_FAN, number_of
from .typed import TasmotaIrTypedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One fan entity per fan."""
    coordinator: TasmotaIrCoordinator = entry.runtime_data
    for appliance in coordinator.appliances.values():
        if appliance.kind == SUBENTRY_FAN:
            async_add_entities(
                [TasmotaIrFan(coordinator, appliance)],
                config_subentry_id=appliance.subentry_id,
            )


class TasmotaIrFan(TasmotaIrTypedEntity, FanEntity):
    """A fan."""

    _attr_assumed_state = True

    def __init__(self, coordinator: TasmotaIrCoordinator, appliance: Appliance) -> None:
        """Offer the speeds, the oscillation and the modes that were learned."""
        super().__init__(coordinator, appliance)
        self._speed_names: list[str] = list(self._roles.get("speeds") or {})
        if self._speed_names:
            count = len(self._speed_names)
        elif self.has("speed_cycle"):
            count = int(number_of(appliance.data, "speed_count") or 0)
        else:
            count = 0
        self._count = count
        features = FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
        if count:
            features |= FanEntityFeature.SET_SPEED
        if self.has("oscillate"):
            features |= FanEntityFeature.OSCILLATE
        presets = list(self._roles.get("presets") or {})
        if presets:
            features |= FanEntityFeature.PRESET_MODE
            self._attr_preset_modes = presets
        self._attr_supported_features = features
        self._attr_preset_mode: str | None = None
        self._attr_oscillating = False
        # 1 to count, or 0 while nothing is known about it.
        self._speed = 0

    @property
    def is_on(self) -> bool:
        """The power sensor, or what was last sent or heard."""
        return self.power_is_on

    @property
    def speed_count(self) -> int:
        """How many speeds there are."""
        return self._count or 1

    @property
    def percentage(self) -> int | None:
        """The speed, as Home Assistant counts it; 0 when off."""
        if not self.power_is_on:
            return 0
        if not self._count or not self._speed:
            return None
        return ranged_value_to_percentage((1, self._count), self._speed)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on, then set the speed or the mode if asked."""
        if not self.power_is_on:
            await self._async_power(True)
            if not self._speed and self.has("speed_cycle"):
                # A cycling key starts from the first speed when the fan starts.
                self._speed = 1
        if percentage:
            # Straight to the speed: a power sensor has not seen the fan start
            # yet, and asking it again would press power a second time.
            await self._async_go_to(percentage)
        if preset_mode:
            await self.async_set_preset_mode(preset_mode)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn it off."""
        await self._async_power(False)

    async def async_set_percentage(self, percentage: int) -> None:
        """Go to the speed nearest this percentage; 0 turns the fan off."""
        if percentage == 0:
            await self.async_turn_off()
            return
        if not self._count:
            return
        if not self.power_is_on:
            await self.async_turn_on()
        await self._async_go_to(percentage)

    async def _async_go_to(self, percentage: int) -> None:
        """Press what it takes to reach the speed for this percentage."""
        if not self._count:
            return
        target = math.ceil(percentage_to_ranged_value((1, self._count), percentage))
        if self._speed_names:
            if target != self._speed:
                await self._press("speeds", self._speed_names[target - 1])
        else:
            current = self._speed or 1
            presses = (target - current) % self._count
            if presses:
                await self._press("speed_cycle", times=presses)
        self._speed = target
        self.async_write_ha_state()

    async def async_oscillate(self, oscillating: bool) -> None:
        """The oscillation key toggles; press it only when it changes something."""
        if oscillating != self._attr_oscillating:
            await self._press("oscillate")
            self._attr_oscillating = oscillating
            self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Press that mode's key."""
        await self._press("presets", preset_mode)
        self._attr_preset_mode = preset_mode
        self.async_write_ha_state()

    def _heard(self, name: str, item: str | None) -> bool:
        """The remote changed speed, oscillation or mode: follow it."""
        if name == "speeds" and item in self._speed_names:
            self._speed = self._speed_names.index(item) + 1
            return True
        if name == "speed_cycle" and self._count:
            self._speed = (self._speed or 1) % self._count + 1
            return True
        if name == "oscillate":
            self._attr_oscillating = not self._attr_oscillating
            return True
        if name == "presets" and item is not None:
            self._attr_preset_mode = item
            return True
        return super()._heard(name, item)

    def _extra_state(self) -> dict[str, Any]:
        return {
            "speed": self._speed,
            "oscillating": self._attr_oscillating,
            "preset": self._attr_preset_mode,
        }

    def _restore_extra(self, data: Mapping[str, Any]) -> None:
        speed = data.get("speed")
        if isinstance(speed, int) and 0 <= speed <= self._count:
            self._speed = speed
        if isinstance(data.get("oscillating"), bool):
            self._attr_oscillating = data["oscillating"]
        if data.get("preset") in (self._attr_preset_modes or ()):
            self._attr_preset_mode = data["preset"]

    def _restore(self, state: State) -> None:
        """Power, speed, oscillation and mode come back after a restart."""
        super()._restore(state)
        percentage = state.attributes.get("percentage")
        if self._count and isinstance(percentage, int) and percentage > 0:
            self._speed = math.ceil(
                percentage_to_ranged_value((1, self._count), percentage)
            )
        self._attr_oscillating = bool(state.attributes.get("oscillating", False))
        preset = state.attributes.get("preset_mode")
        if preset in (self._attr_preset_modes or ()):
            self._attr_preset_mode = preset
