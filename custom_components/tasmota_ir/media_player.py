"""A TV or a sound bar, by its learned keys.

Only what was learned is offered: a sound bar with power and volume has no
source list, a TV with its HDMI keys does. Mute and play are toggles on almost
every remote, so their state is assumed, like power without a sensor.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Appliance, TasmotaIrCoordinator
from .device_types import SUBENTRY_MEDIA
from .typed import TasmotaIrTypedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One media player per TV or sound bar."""
    coordinator: TasmotaIrCoordinator = entry.runtime_data
    for appliance in coordinator.appliances.values():
        if appliance.kind == SUBENTRY_MEDIA:
            async_add_entities(
                [TasmotaIrMediaPlayer(coordinator, appliance)],
                config_subentry_id=appliance.subentry_id,
            )


class TasmotaIrMediaPlayer(TasmotaIrTypedEntity, MediaPlayerEntity):
    """A TV or a sound bar."""

    _attr_assumed_state = True

    def __init__(self, coordinator: TasmotaIrCoordinator, appliance: Appliance) -> None:
        """Offer what was learned, and nothing else."""
        super().__init__(coordinator, appliance)
        features = MediaPlayerEntityFeature(0)
        if self.has("power") or (self.has("power_on") and self.has("power_off")):
            features |= MediaPlayerEntityFeature.TURN_ON
            features |= MediaPlayerEntityFeature.TURN_OFF
        if self.has("volume_up") and self.has("volume_down"):
            features |= MediaPlayerEntityFeature.VOLUME_STEP
        if self.has("mute"):
            features |= MediaPlayerEntityFeature.VOLUME_MUTE
        sources = self._roles.get("sources") or {}
        if sources:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
            self._attr_source_list = list(sources)
        if self.has("channel_up"):
            features |= MediaPlayerEntityFeature.NEXT_TRACK
        if self.has("channel_down"):
            features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
        if self.has("play_pause"):
            features |= MediaPlayerEntityFeature.PLAY | MediaPlayerEntityFeature.PAUSE
        self._attr_supported_features = features
        self._attr_source: str | None = None
        self._attr_is_volume_muted = False
        self._playing = False

    @property
    def state(self) -> MediaPlayerState:
        """On or off; playing and paused are not known, so on stands for both."""
        return MediaPlayerState.ON if self.power_is_on else MediaPlayerState.OFF

    async def async_turn_on(self) -> None:
        """Turn it on."""
        await self._async_power(True)

    async def async_turn_off(self) -> None:
        """Turn it off."""
        await self._async_power(False)

    async def async_volume_up(self) -> None:
        """One step up."""
        await self._press("volume_up")

    async def async_volume_down(self) -> None:
        """One step down."""
        await self._press("volume_down")

    async def async_mute_volume(self, mute: bool) -> None:
        """The mute key toggles, so it is pressed only when it changes something."""
        if mute != self._attr_is_volume_muted:
            await self._press("mute")
            self._attr_is_volume_muted = mute
            self.async_write_ha_state()

    async def async_select_source(self, source: str) -> None:
        """Press that source's key."""
        await self._press("sources", source)
        self._attr_source = source
        self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        """Channel up."""
        await self._press("channel_up")

    async def async_media_previous_track(self) -> None:
        """Channel down."""
        await self._press("channel_down")

    async def async_media_play_pause(self) -> None:
        """The key that toggles between play and pause."""
        await self._press("play_pause")
        self._playing = not self._playing

    async def async_media_play(self) -> None:
        """Press play and pause only if it is assumed paused."""
        if not self._playing:
            await self.async_media_play_pause()

    async def async_media_pause(self) -> None:
        """Press play and pause only if it is assumed playing."""
        if self._playing:
            await self.async_media_play_pause()

    def _heard(self, name: str, item: str | None) -> bool:
        """The remote picked a source, or muted: follow it."""
        if name == "sources" and item is not None:
            self._attr_source = item
            return True
        if name == "mute":
            self._attr_is_volume_muted = not self._attr_is_volume_muted
            return True
        return super()._heard(name, item)

    def _extra_state(self) -> dict[str, Any]:
        return {
            "source": self._attr_source,
            "muted": self._attr_is_volume_muted,
            "playing": self._playing,
        }

    def _restore_extra(self, data: Mapping[str, Any]) -> None:
        if data.get("source") in (self._attr_source_list or ()):
            self._attr_source = data["source"]
        if isinstance(data.get("muted"), bool):
            self._attr_is_volume_muted = data["muted"]
        if isinstance(data.get("playing"), bool):
            self._playing = data["playing"]

    def _restore(self, state: State) -> None:
        """Power and source come back after a restart."""
        super()._restore(state)
        source = state.attributes.get("source")
        if source in (self._attr_source_list or ()):
            self._attr_source = source
