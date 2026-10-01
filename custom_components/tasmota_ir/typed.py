"""What every appliance type learned key by key shares.

Infrared goes one way: the board sends, and nothing says whether the TV came
on. So the state here is assumed. It follows what Home Assistant sent, and it
follows the physical remote too, because the receiver hears that remote and a
frame whose code matches a learned function moves the state the same way.

A power sensor, when one is set, beats all of that for on and off: a smart plug
reading watts, or anything with an on and off state. With a power key that only
toggles, the sensor is also what keeps a press from switching the wrong way.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoredExtraData, RestoreEntity

from .const import DEFAULT_SEND_DELAY, SIGNAL_IR_RECEIVED, SIGNAL_SEQUENCE_SENT
from .coordinator import Appliance, CodeTooLargeError, TasmotaIrCoordinator
from .device_types import (
    CONF_POWER_SENSOR,
    CONF_POWER_THRESHOLD,
    DEFAULT_POWER_THRESHOLD,
    is_list,
    roles_of,
)
from .entity import TasmotaIrEntity

# Between presses of the same key in a row: brightness steps, fan speeds.
PRESS_DELAY = DEFAULT_SEND_DELAY

# Frames that carry no stable code to compare: a raw capture never repeats
# exactly, and an unknown one has nothing to name it by.
_UNCOMPARABLE = (None, "", "RAW", "UNKNOWN")


def sensor_reads_on(state: State | None, threshold: float) -> bool | None:
    """What a power sensor says, or None when it says nothing usable.

    A numeric sensor is a power meter: above the threshold is on. Anything else
    is read by its own on and off state.
    """
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    if state.domain == "sensor":
        try:
            return float(state.state) > threshold
        except ValueError:
            return None
    return state.state == STATE_ON


def is_comparable(code: Mapping[str, Any]) -> bool:
    """Whether a code can be recognised when heard: a known protocol, with data.

    Raw and unknown frames cannot: two captures of one key differ.
    """
    return code.get("Protocol") not in _UNCOMPARABLE and bool(code.get("Data"))


def is_same_code(code: Mapping[str, Any], received: Mapping[str, Any]) -> bool:
    """Whether a heard frame is this learned code, by protocol and data."""
    if not is_comparable(received):
        return False
    protocol = received.get("Protocol")
    return (
        code.get("Protocol") == protocol
        and str(code.get("Data", "")).upper() == str(received.get("Data", "")).upper()
    )


class TasmotaIrTypedEntity(TasmotaIrEntity, RestoreEntity):
    """An appliance type driven by learned keys, on its appliance's emitter."""

    # The device carries the appliance name, and the entity is the appliance.
    _attr_name = None

    def __init__(self, coordinator: TasmotaIrCoordinator, appliance: Appliance) -> None:
        """Bind the entity to one typed appliance."""
        super().__init__(coordinator, appliance)
        self._key = appliance.key
        self._kind = appliance.kind
        self._roles = roles_of(appliance.data)
        self._data = appliance.data
        self._sensor: str | None = appliance.data.get(CONF_POWER_SENSOR) or None
        self._threshold = float(
            appliance.data.get(CONF_POWER_THRESHOLD, DEFAULT_POWER_THRESHOLD)
        )
        self._assumed_on = False
        self._attr_unique_id = f"{appliance.key}_{appliance.kind}"

    def has(self, name: str) -> bool:
        """Whether this function was learned."""
        return bool(self._roles.get(name))

    def _code(self, name: str, item: str | None = None) -> dict[str, Any] | None:
        value = self._roles.get(name)
        if item is not None:
            value = (value or {}).get(item)
        return value if isinstance(value, dict) and value else None

    async def _press(self, name: str, item: str | None = None, times: int = 1) -> None:
        """Send a learned key, ``times`` times in a row, through this emitter."""
        if not self.coordinator.available:
            raise HomeAssistantError(
                f"{self.coordinator.entry.title} is offline, so nothing was sent."
            )
        code = self._code(name, item)
        if code is None:
            raise HomeAssistantError(
                f"Nothing was learned for {item or name} on {self.appliance.name}."
            )
        channel = self.coordinator.channel_for(self._key)
        for press in range(times):
            if press:
                await asyncio.sleep(PRESS_DELAY)
            try:
                await self.coordinator.async_send_code(code, channel=channel)
            except CodeTooLargeError as err:
                raise HomeAssistantError(str(err)) from err

    @property
    def power_is_on(self) -> bool:
        """The sensor when it reads anything, the assumed state otherwise."""
        if self._sensor and self.hass is not None:
            reading = sensor_reads_on(
                self.hass.states.get(self._sensor), self._threshold
            )
            if reading is not None:
                return reading
        return self._assumed_on

    async def _async_power(self, on: bool) -> None:
        """Turn on or off, pressing a toggle only when it would change something."""
        if self.has("power_on") and self.has("power_off"):
            await self._press("power_on" if on else "power_off")
        elif self.power_is_on != on:
            await self._press("power")
        self._assumed_on = on
        self.async_write_ha_state()

    def _heard(self, name: str, item: str | None) -> bool:
        """The physical remote sent this function. Returns whether state moved."""
        if name == "power_on":
            self._assumed_on = True
        elif name == "power_off":
            self._assumed_on = False
        elif name == "power":
            self._assumed_on = not self._assumed_on
        else:
            return False
        return True

    def _restore(self, state: State) -> None:
        """Take back what the entity was before Home Assistant restarted."""
        self._assumed_on = state.state == STATE_ON

    def _extra_state(self) -> dict[str, Any]:
        """What the state attributes lose while the appliance is off.

        Home Assistant drops a light's brightness, a fan's speed and a media
        player's source when they are off, and the steps are counted from
        exactly those. Each type adds its own levels here.
        """
        return {}

    def _restore_extra(self, data: Mapping[str, Any]) -> None:
        """Take back the levels saved by ``_extra_state``."""

    @property
    def extra_restore_state_data(self) -> RestoredExtraData:
        """Saved beside the state, and kept while the appliance is off."""
        return RestoredExtraData(
            {"assumed_on": self._assumed_on, **self._extra_state()}
        )

    def _read_sensor(self) -> None:
        """Let a readable power sensor correct the assumption.

        Kept in the assumption, so a sensor that goes unavailable falls back to
        its last reading rather than to whatever was assumed before it.
        """
        if not self._sensor:
            return
        reading = sensor_reads_on(self.hass.states.get(self._sensor), self._threshold)
        if reading is not None:
            self._assumed_on = reading

    async def async_added_to_hass(self) -> None:
        """Restore, then follow the receiver and the power sensor."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            self._restore(state)
        if (extra := await self.async_get_last_extra_data()) is not None:
            saved = extra.as_dict()
            if isinstance(saved.get("assumed_on"), bool):
                self._assumed_on = saved["assumed_on"]
            self._restore_extra(saved)
        self._read_sensor()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_IR_RECEIVED.format(entry_id=self.coordinator.entry.entry_id),
                self._handle_received,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SEQUENCE_SENT.format(entry_id=self.coordinator.entry.entry_id),
                self._sequence_sent,
            )
        )
        if self._sensor:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [self._sensor], self._sensor_changed
                )
            )

    @callback
    def _sequence_sent(self, key: str, name: str, item: str | None) -> None:
        """A sequence pressed one of this appliance's keys: follow it, as the
        physical remote is followed, since a press is what it was."""
        if key == self._key and self._heard(name, item):
            self.async_write_ha_state()

    @callback
    def _sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        self._read_sensor()
        self.async_write_ha_state()

    @callback
    def _handle_received(self, received: dict[str, Any]) -> None:
        """Find the learned function this frame is, if any, and follow it."""
        if received.get("Protocol") in _UNCOMPARABLE or not received.get("Data"):
            return
        for name, value in self._roles.items():
            if not isinstance(value, dict):
                continue
            if not is_list(self._kind, name):
                if is_same_code(value, received):
                    if self._heard(name, None):
                        self.async_write_ha_state()
                    return
                continue
            for item, code in value.items():
                if isinstance(code, dict) and is_same_code(code, received):
                    if self._heard(name, item):
                        self.async_write_ha_state()
                    return
