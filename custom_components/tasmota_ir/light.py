"""A light, by its learned keys.

Infrared lamps have no "brightness 40%" key: they have up and down, and
warmer and cooler. So brightness and colour temperature are counted in steps,
from the level the integration assumes the lamp is at, and a request presses
the key the difference in steps. The top of the range is where a lamp usually
starts, and the middle of the colour range is where most start their white.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Appliance, TasmotaIrCoordinator
from .device_types import SUBENTRY_LIGHT, number_of
from .typed import TasmotaIrTypedEntity

MIN_KELVIN = 2700
MAX_KELVIN = 6500


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One light entity per light."""
    coordinator: TasmotaIrCoordinator = entry.runtime_data
    for appliance in coordinator.appliances.values():
        if appliance.kind == SUBENTRY_LIGHT:
            async_add_entities(
                [TasmotaIrLight(coordinator, appliance)],
                config_subentry_id=appliance.subentry_id,
            )


class TasmotaIrLight(TasmotaIrTypedEntity, LightEntity):
    """A light."""

    _attr_assumed_state = True
    _attr_min_color_temp_kelvin = MIN_KELVIN
    _attr_max_color_temp_kelvin = MAX_KELVIN

    def __init__(self, coordinator: TasmotaIrCoordinator, appliance: Appliance) -> None:
        """Offer brightness, colour temperature and effects only when learned."""
        super().__init__(coordinator, appliance)
        self._dimmable = self.has("brightness_up") and self.has("brightness_down")
        self._tunable = self.has("warmer") and self.has("cooler")
        self._steps = int(number_of(appliance.data, "brightness_steps") or 10)
        self._ct_steps = int(number_of(appliance.data, "color_temp_steps") or 5)
        if self._tunable:
            mode = ColorMode.COLOR_TEMP
        elif self._dimmable:
            mode = ColorMode.BRIGHTNESS
        else:
            mode = ColorMode.ONOFF
        self._attr_supported_color_modes = {mode}
        self._attr_color_mode = mode
        effects = list(self._roles.get("effects") or {})
        if effects:
            self._attr_supported_features = LightEntityFeature.EFFECT
            self._attr_effect_list = effects
        self._attr_effect: str | None = None
        self._level = self._steps
        self._ct_level = self._ct_steps // 2

    @property
    def is_on(self) -> bool:
        """The power sensor, or what was last sent or heard."""
        return self.power_is_on

    @property
    def brightness(self) -> int | None:
        """The assumed level, on Home Assistant's 0 to 255 scale."""
        if not self._dimmable:
            return None
        return round(self._level / self._steps * 255)

    @property
    def color_temp_kelvin(self) -> int | None:
        """The assumed colour level, in kelvin."""
        if not self._tunable:
            return None
        return round(
            MIN_KELVIN + self._ct_level / self._ct_steps * (MAX_KELVIN - MIN_KELVIN)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on, then walk to the brightness, colour and effect asked for."""
        if not self.power_is_on:
            await self._async_power(True)
        if ATTR_BRIGHTNESS in kwargs and self._dimmable:
            target = max(1, round(kwargs[ATTR_BRIGHTNESS] / 255 * self._steps))
            difference = target - self._level
            if difference:
                key = "brightness_up" if difference > 0 else "brightness_down"
                await self._press(key, times=abs(difference))
            self._level = target
        if ATTR_COLOR_TEMP_KELVIN in kwargs and self._tunable:
            share = (kwargs[ATTR_COLOR_TEMP_KELVIN] - MIN_KELVIN) / (
                MAX_KELVIN - MIN_KELVIN
            )
            target = min(self._ct_steps, max(0, round(share * self._ct_steps)))
            difference = target - self._ct_level
            if difference:
                key = "cooler" if difference > 0 else "warmer"
                await self._press(key, times=abs(difference))
            self._ct_level = target
        if (effect := kwargs.get(ATTR_EFFECT)) is not None:
            await self._press("effects", effect)
            self._attr_effect = effect
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn it off."""
        await self._async_power(False)

    def _heard(self, name: str, item: str | None) -> bool:
        """The remote dimmed, warmed or picked an effect: follow it."""
        if name == "brightness_up":
            self._level = min(self._steps, self._level + 1)
        elif name == "brightness_down":
            self._level = max(1, self._level - 1)
        elif name == "cooler":
            self._ct_level = min(self._ct_steps, self._ct_level + 1)
        elif name == "warmer":
            self._ct_level = max(0, self._ct_level - 1)
        elif name == "effects" and item is not None:
            self._attr_effect = item
        else:
            return super()._heard(name, item)
        return True

    def _extra_state(self) -> dict[str, Any]:
        return {
            "level": self._level,
            "ct_level": self._ct_level,
            "effect": self._attr_effect,
        }

    def _restore_extra(self, data: Mapping[str, Any]) -> None:
        if isinstance(data.get("level"), int):
            self._level = max(1, min(self._steps, data["level"]))
        if isinstance(data.get("ct_level"), int):
            self._ct_level = max(0, min(self._ct_steps, data["ct_level"]))
        if data.get("effect") in (self._attr_effect_list or ()):
            self._attr_effect = data["effect"]

    def _restore(self, state: State) -> None:
        """Power, levels and effect come back after a restart."""
        super()._restore(state)
        brightness = state.attributes.get(ATTR_BRIGHTNESS)
        if self._dimmable and isinstance(brightness, int):
            self._level = max(
                1, min(self._steps, round(brightness / 255 * self._steps))
            )
        kelvin = state.attributes.get(ATTR_COLOR_TEMP_KELVIN)
        if self._tunable and isinstance(kelvin, int):
            share = (kelvin - MIN_KELVIN) / (MAX_KELVIN - MIN_KELVIN)
            self._ct_level = min(self._ct_steps, max(0, round(share * self._ct_steps)))
        effect = state.attributes.get(ATTR_EFFECT)
        if effect in (self._attr_effect_list or ()):
            self._attr_effect = effect
