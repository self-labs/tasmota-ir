"""A cover, a curtain or a projector screen, by its learned keys.

Open, close and stop are keys. A position is not: the only way to stop halfway
is to start moving and press stop at the right moment. With the time a full
run takes and a stop key, the integration does exactly that, and assumes the
cover is where it stopped.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .coordinator import Appliance, TasmotaIrCoordinator
from .device_types import SUBENTRY_COVER, number_of
from .typed import TasmotaIrTypedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One cover entity per cover."""
    coordinator: TasmotaIrCoordinator = entry.runtime_data
    for appliance in coordinator.appliances.values():
        if appliance.kind == SUBENTRY_COVER:
            async_add_entities(
                [TasmotaIrCover(coordinator, appliance)],
                config_subentry_id=appliance.subentry_id,
            )


class TasmotaIrCover(TasmotaIrTypedEntity, CoverEntity):
    """A cover."""

    _attr_assumed_state = True

    def __init__(self, coordinator: TasmotaIrCoordinator, appliance: Appliance) -> None:
        """Open and close always; stop and position only when they can work."""
        super().__init__(coordinator, appliance)
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        if self.has("stop"):
            features |= CoverEntityFeature.STOP
        travel = number_of(appliance.data, "travel_time")
        self._travel: float | None = float(travel) if travel else None
        if self.has("stop") and self._travel:
            features |= CoverEntityFeature.SET_POSITION
        self._attr_supported_features = features
        self._position = 0
        self._pending_stop: Callable[[], None] | None = None
        # A timed move in progress: when it started, from where, to where,
        # and how long it takes. None when the cover is still.
        self._move: tuple[datetime, int, int, float] | None = None

    @property
    def current_cover_position(self) -> int:
        """Where the cover is assumed to be, 0 closed and 100 open."""
        return self._position

    @property
    def is_closed(self) -> bool:
        """Closed at position 0."""
        return self._position == 0

    def _interrupt(self) -> None:
        """End a timed move where the cover is now, and drop its pending stop.

        The position during a move is estimated from the time it has run: a
        new target, a stop or a key of the remote in the middle of a move
        starts from there, not from where the move was going.
        """
        if self._pending_stop is not None:
            self._pending_stop()
            self._pending_stop = None
        if self._move is not None:
            started, start, target, duration = self._move
            elapsed = (dt_util.utcnow() - started).total_seconds()
            share = min(1.0, elapsed / duration) if duration else 1.0
            self._position = round(start + (target - start) * share)
            self._move = None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open all the way."""
        self._interrupt()
        await self._press("open")
        self._position = 100
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close all the way."""
        self._interrupt()
        await self._press("close")
        self._position = 0
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop where it is."""
        self._interrupt()
        await self._press("stop")
        self.async_write_ha_state()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move for the share of the travel time the distance needs, then stop.

        The ends are plain open and close: the cover stops by itself there.
        """
        target = int(kwargs[ATTR_POSITION])
        if target >= 100:
            await self.async_open_cover()
            return
        if target <= 0:
            await self.async_close_cover()
            return
        if not self._travel:
            return
        self._interrupt()
        difference = target - self._position
        if not difference:
            self.async_write_ha_state()
            return
        await self._press("open" if difference > 0 else "close")
        duration = abs(difference) / 100 * self._travel
        self._move = (dt_util.utcnow(), self._position, target, duration)
        self._position = target
        self.async_write_ha_state()
        self._pending_stop = async_call_later(self.hass, duration, self._timed_stop)

    @callback
    def _timed_stop(self, _now: datetime) -> None:
        self._pending_stop = None
        self._move = None
        self.hass.async_create_task(self._press("stop"))

    async def async_will_remove_from_hass(self) -> None:
        """A stop scheduled for a cover that is going away must not fire."""
        self._interrupt()
        await super().async_will_remove_from_hass()

    def _heard(self, name: str, item: str | None) -> bool:
        """The remote opened, closed or stopped it: follow it, and drop any
        stop this integration had scheduled, which would now be wrong."""
        if name not in ("open", "close", "stop"):
            return False
        self._interrupt()
        if name == "open":
            self._position = 100
        elif name == "close":
            self._position = 0
        return True

    def _restore(self, state: State) -> None:
        """The position comes back after a restart."""
        position = state.attributes.get("current_position")
        if isinstance(position, int):
            self._position = max(0, min(100, position))
