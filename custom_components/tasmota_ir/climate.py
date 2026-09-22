"""An air conditioner, built by the firmware rather than by learned codes.

Every other appliance needs a code per button. An air conditioner does not:
Tasmota's full IR driver knows the protocol of dozens of vendors and assembles
the whole frame from vendor, mode, temperature, fan speed and vane position.
That is one command instead of one stored code per temperature.

It also reads the state back. The entity follows what the **physical remote**
does, not only what Home Assistant asked for, because the board reports every
frame its receiver hears, including the ones it did not send. That only works
for frames that arrive whole: one pressed from across the room can decode as
something else, and then there is nothing to follow.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CMND_IRHVAC,
    CONF_HVAC_MODES,
    CONF_INITIAL_SWING_VERTICAL,
    CONF_LIGHT,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_MODEL,
    CONF_SWING_HORIZONTAL,
    CONF_SWING_VERTICAL,
    CONF_VENDOR,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    KEY_IRHVAC,
    LG_DISPLAY_TOGGLE,
    LG_VANE_PREFIX,
    LG_VANE_TOGGLE,
    LG_VENDORS,
    LIGHT_TOGGLE_VENDORS,
    SIGNAL_IR_RECEIVED,
    SUBENTRY_CLIMATE,
    swing_vertical_default,
)
from .coordinator import Appliance, CodeTooLargeError, TasmotaIrCoordinator
from .entity import TasmotaIrEntity

_LOGGER = logging.getLogger(__name__)

# Tasmota speaks its own vocabulary for modes, fan speeds and vanes. These
# tables are the whole translation layer. The names on the Home Assistant side
# are translated in strings.json, under the air_conditioner translation key.
HVAC_TO_TASMOTA: dict[HVACMode, str] = {
    HVACMode.OFF: "Off",
    HVACMode.COOL: "Cool",
    HVACMode.HEAT: "Heat",
    HVACMode.DRY: "Dry",
    HVACMode.FAN_ONLY: "Fan",
    HVACMode.AUTO: "Auto",
}
TASMOTA_TO_HVAC = {value.lower(): key for key, value in HVAC_TO_TASMOTA.items()}
ALL_HVAC_MODES: list[str] = [str(mode) for mode in HVAC_TO_TASMOTA]

FAN_TO_TASMOTA: dict[str, str] = {
    "auto": "Auto",
    "min": "Min",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "max": "Max",
}
TASMOTA_TO_FAN = {value.lower(): key for key, value in FAN_TO_TASMOTA.items()}

# stdAc::swingv_t, the vertical vane. "auto" is the vane moving on its own.
SWING_TO_TASMOTA: dict[str, str] = {
    "off": "Off",
    "auto": "Auto",
    "highest": "Highest",
    "high": "High",
    "middle": "Middle",
    "low": "Low",
    "lowest": "Lowest",
}
TASMOTA_TO_SWING = {value.lower(): key for key, value in SWING_TO_TASMOTA.items()}

# stdAc::swingh_t, the horizontal vane.
SWING_H_TO_TASMOTA: dict[str, str] = {
    "off": "Off",
    "auto": "Auto",
    "left_max": "LeftMax",
    "left": "Left",
    "middle": "Middle",
    "right": "Right",
    "right_max": "RightMax",
    "wide": "Wide",
}
TASMOTA_TO_SWING_H = {value.lower(): key for key, value in SWING_H_TO_TASMOTA.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one entity per air conditioner, each on its own subentry."""
    coordinator: TasmotaIrCoordinator = entry.runtime_data
    for appliance in coordinator.appliances.values():
        if appliance.kind != SUBENTRY_CLIMATE:
            continue
        async_add_entities(
            [TasmotaIrClimate(coordinator, appliance)],
            config_subentry_id=appliance.subentry_id,
        )


class TasmotaIrClimate(TasmotaIrEntity, ClimateEntity, RestoreEntity):
    """One air conditioner driven by IRHVAC."""

    _attr_name = None
    _attr_translation_key = "air_conditioner"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1

    def __init__(self, coordinator: TasmotaIrCoordinator, appliance: Appliance) -> None:
        """Bind the entity to one appliance."""
        super().__init__(coordinator, appliance)
        data = appliance.data
        self._key = appliance.key
        self._vendor: str = data.get(CONF_VENDOR, "")
        self._model: str = data.get(CONF_MODEL, "")
        self._light: str = data.get(CONF_LIGHT, "On")
        self._attr_unique_id = f"{appliance.key}_climate"
        self._attr_min_temp = float(data.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP))
        self._attr_max_temp = float(data.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP))

        modes = [
            m for m in data.get(CONF_HVAC_MODES, ALL_HVAC_MODES) if m in ALL_HVAC_MODES
        ]
        if HVACMode.OFF not in modes:
            modes.insert(0, HVACMode.OFF)
        self._attr_hvac_modes = [HVACMode(mode) for mode in modes]
        self._attr_fan_modes = list(FAN_TO_TASMOTA)

        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        self._swing_vertical = bool(
            data.get(CONF_SWING_VERTICAL, swing_vertical_default(self._vendor))
        )
        self._swing_horizontal = bool(data.get(CONF_SWING_HORIZONTAL, False))
        if self._swing_vertical:
            features |= ClimateEntityFeature.SWING_MODE
            self._attr_swing_modes = list(SWING_TO_TASMOTA)
        if self._swing_horizontal:
            features |= ClimateEntityFeature.SWING_HORIZONTAL_MODE
            self._attr_swing_horizontal_modes = list(SWING_H_TO_TASMOTA)
        self._attr_supported_features = features

        self._attr_hvac_mode = HVACMode.OFF
        self._attr_fan_mode = "auto"
        self._attr_target_temperature = 24.0
        self._attr_swing_mode = TASMOTA_TO_SWING.get(
            str(data.get(CONF_INITIAL_SWING_VERTICAL, "Off")).lower(), "off"
        )
        self._attr_swing_horizontal_mode = "off"
        # The mode the unit was last on, so turning it back on returns to it
        # instead of guessing cool.
        self._last_on_mode = next(
            (m for m in self._attr_hvac_modes if m != HVACMode.OFF), HVACMode.COOL
        )

    async def async_added_to_hass(self) -> None:
        """Restore the last state and start listening to the receiver."""
        await super().async_added_to_hass()

        if (state := await self.async_get_last_state()) is not None:
            if state.state in self._attr_hvac_modes:
                self._attr_hvac_mode = HVACMode(state.state)
                if self._attr_hvac_mode != HVACMode.OFF:
                    self._last_on_mode = self._attr_hvac_mode
            if (temp := state.attributes.get(ATTR_TEMPERATURE)) is not None:
                self._attr_target_temperature = float(temp)
            if (fan := state.attributes.get("fan_mode")) in FAN_TO_TASMOTA:
                self._attr_fan_mode = fan
            if (swing := state.attributes.get("swing_mode")) in SWING_TO_TASMOTA:
                self._attr_swing_mode = swing
            swing_h = state.attributes.get("swing_horizontal_mode")
            if swing_h in SWING_H_TO_TASMOTA:
                self._attr_swing_horizontal_mode = swing_h

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_IR_RECEIVED.format(entry_id=self.coordinator.entry.entry_id),
                self._handle_received,
            )
        )

    @callback
    def _handle_received(self, received: dict[str, Any]) -> None:
        """Follow the physical remote.

        The board reports every frame it hears, including the ones somebody sent
        with the remote in their hand. Reading it back is what keeps the card
        honest when the unit is not driven only from Home Assistant.
        """
        hvac = received.get(KEY_IRHVAC)
        if not isinstance(hvac, dict):
            return
        if self._vendor and hvac.get("Vendor") != self._vendor:
            return

        data = str(received.get("Data", "")).upper()
        is_lg = str(hvac.get("Vendor", "")).upper() in LG_VENDORS
        if is_lg and data == LG_DISPLAY_TOGGLE:
            return
        if is_lg and (data.startswith(LG_VANE_PREFIX) or data == LG_VANE_TOGGLE):
            # A vane key: only the vane is real, the rest are defaults.
            if self._read_swing(hvac):
                self.async_write_ha_state()
            return

        changed = False

        power = str(hvac.get("Power", "")).lower()
        mode = str(hvac.get("Mode", "")).lower()
        if power == "off":
            # An off frame says the unit is off and nothing else reliable: LG
            # sends a fixed code for it. Keep the setpoint for the next on.
            if self._attr_hvac_mode != HVACMode.OFF:
                self._attr_hvac_mode = HVACMode.OFF
                self.async_write_ha_state()
            return
        new_mode = TASMOTA_TO_HVAC.get(mode, self._last_on_mode)
        if new_mode in self._attr_hvac_modes and new_mode != self._attr_hvac_mode:
            self._attr_hvac_mode = new_mode
            self._last_on_mode = new_mode
            changed = True

        if (temp := hvac.get("Temp")) is not None:
            try:
                value = float(temp)
            except (TypeError, ValueError):
                value = None
            if value is not None and value != self._attr_target_temperature:
                self._attr_target_temperature = value
                changed = True

        fan = TASMOTA_TO_FAN.get(str(hvac.get("FanSpeed", "")).lower())
        if fan and fan != self._attr_fan_mode:
            self._attr_fan_mode = fan
            changed = True

        # An LG main frame never carries the vane, that goes in a frame of its
        # own, so its SwingV is only the firmware default.
        if not is_lg and self._read_swing(hvac):
            changed = True

        if changed:
            self.async_write_ha_state()

    def _read_swing(self, hvac: dict[str, Any]) -> bool:
        """Take the vane positions from a frame. Returns whether they changed."""
        changed = False
        if self._swing_vertical:
            swing = TASMOTA_TO_SWING.get(str(hvac.get("SwingV", "")).lower())
            if swing and swing != self._attr_swing_mode:
                self._attr_swing_mode = swing
                changed = True
        if self._swing_horizontal:
            swing_h = TASMOTA_TO_SWING_H.get(str(hvac.get("SwingH", "")).lower())
            if swing_h and swing_h != self._attr_swing_horizontal_mode:
                self._attr_swing_horizontal_mode = swing_h
                changed = True
        return changed

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Change the mode, and remember it for the next turn on."""
        self._attr_hvac_mode = hvac_mode
        if hvac_mode != HVACMode.OFF:
            self._last_on_mode = hvac_mode
        await self._async_publish()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Change the target temperature.

        Setting a temperature on a unit that is off does not turn it on. The
        frame carries the whole state, so sending one here would switch the unit
        on as a side effect of moving a slider.
        """
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        self._attr_target_temperature = float(temperature)
        await self._async_publish_if_on()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Change the fan speed."""
        self._attr_fan_mode = fan_mode
        await self._async_publish_if_on()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Move the vertical vane, or set it swinging."""
        self._attr_swing_mode = swing_mode
        await self._async_publish_if_on()

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        """Move the horizontal vane, or set it swinging."""
        self._attr_swing_horizontal_mode = swing_horizontal_mode
        await self._async_publish_if_on()

    async def async_turn_on(self) -> None:
        """Return to the mode the unit was last on."""
        await self.async_set_hvac_mode(self._last_on_mode)

    async def async_turn_off(self) -> None:
        """Turn the unit off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def _async_publish_if_on(self) -> None:
        """Send only when the unit is on; otherwise just remember the choice."""
        if self._attr_hvac_mode == HVACMode.OFF:
            self.async_write_ha_state()
            return
        await self._async_publish()

    async def _async_publish(self) -> None:
        """Send the whole state as one IRHVAC frame."""
        off = self._attr_hvac_mode == HVACMode.OFF
        payload: dict[str, Any] = {
            "Vendor": self._vendor,
            "Power": "Off" if off else "On",
            "Mode": HVAC_TO_TASMOTA[
                self._last_on_mode if off else self._attr_hvac_mode
            ],
            "Temp": int(self._attr_target_temperature or 24),
            "FanSpeed": FAN_TO_TASMOTA.get(self._attr_fan_mode or "auto", "Auto"),
            "Celsius": "On",
        }
        if self._model:
            payload["Model"] = self._model
        # Left out entirely when the vane is not offered: an absent key keeps
        # the firmware's default instead of forcing a position on the unit.
        if self._swing_vertical:
            payload["SwingV"] = SWING_TO_TASMOTA.get(
                self._attr_swing_mode or "off", "Off"
            )
        if self._swing_horizontal:
            payload["SwingH"] = SWING_H_TO_TASMOTA.get(
                self._attr_swing_horizontal_mode or "off", "Off"
            )
        # Some LG models send a separate "toggle the display" frame whenever
        # Light is off, which is the firmware default. Saying what the remote
        # said keeps the display as it was. Vendors where Light is itself a
        # toggle get nothing, or every command would flip the display.
        if self._vendor.upper() not in LIGHT_TOGGLE_VENDORS:
            payload["Light"] = self._light

        try:
            await self.coordinator.async_send_json(
                CMND_IRHVAC,
                payload,
                channel=self.coordinator.channel_for(self._key),
            )
        except CodeTooLargeError as err:  # pragma: no cover - frames are small
            raise HomeAssistantError(str(err)) from err

        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """What the firmware is told, so a wrong model is easy to spot."""
        return {
            "vendor": self._vendor,
            "model": self._model,
            "emitter": self.coordinator.channel_for(self._key),
        }
