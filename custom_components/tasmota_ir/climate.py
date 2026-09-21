"""An air conditioner, built by the firmware rather than by learned codes.

Every other appliance needs a code per button. An air conditioner does not:
Tasmota's full IR driver knows the protocol of dozens of vendors and assembles
the whole frame from vendor, mode, temperature and fan speed. That is one
command instead of one stored code per temperature.

It also reads the state back. The entity follows what the **physical remote**
does, not only what Home Assistant asked for, because the board reports every
frame its receiver hears, including the ones it did not send.
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
    CONF_APPLIANCES,
    CONF_KIND,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_MODEL,
    CONF_VENDOR,
    KEY_IRHVAC,
    KIND_CLIMATE,
    SIGNAL_IR_RECEIVED,
)
from .coordinator import CodeTooLargeError, TasmotaIrCoordinator
from .entity import TasmotaIrEntity

_LOGGER = logging.getLogger(__name__)

# Tasmota speaks its own vocabulary for modes and fan speeds. These two tables
# are the whole translation layer, and they are deliberately small: anything the
# vendor does not support is simply never offered by the config flow.
HVAC_TO_TASMOTA: dict[HVACMode, str] = {
    HVACMode.OFF: "Off",
    HVACMode.COOL: "Cool",
    HVACMode.HEAT: "Heat",
    HVACMode.DRY: "Dry",
    HVACMode.FAN_ONLY: "Fan",
    HVACMode.AUTO: "Auto",
}
TASMOTA_TO_HVAC = {value.lower(): key for key, value in HVAC_TO_TASMOTA.items()}

FAN_TO_TASMOTA: dict[str, str] = {
    "auto": "Auto",
    "min": "Min",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "max": "Max",
}
TASMOTA_TO_FAN = {value.lower(): key for key, value in FAN_TO_TASMOTA.items()}

DEFAULT_MIN_TEMP = 18
DEFAULT_MAX_TEMP = 30


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one entity per appliance configured as an air conditioner."""
    coordinator: TasmotaIrCoordinator = entry.runtime_data
    entities = [
        TasmotaIrClimate(coordinator, name, config)
        for name, config in entry.options.get(CONF_APPLIANCES, {}).items()
        if config.get(CONF_KIND) == KIND_CLIMATE
    ]
    async_add_entities(entities)


class TasmotaIrClimate(TasmotaIrEntity, ClimateEntity, RestoreEntity):
    """One air conditioner driven by IRHVAC."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(
        self,
        coordinator: TasmotaIrCoordinator,
        appliance: str,
        config: dict[str, Any],
    ) -> None:
        """Bind the entity to one appliance."""
        super().__init__(coordinator)
        self._appliance = appliance
        self._vendor: str = config.get(CONF_VENDOR, "")
        self._model: str = config.get(CONF_MODEL, "")
        self._attr_unique_id = f"{coordinator.entry.entry_id}_climate_{appliance}"
        self._attr_name = appliance
        self._attr_min_temp = float(config.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP))
        self._attr_max_temp = float(config.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP))
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.COOL,
            HVACMode.HEAT,
            HVACMode.DRY,
            HVACMode.FAN_ONLY,
            HVACMode.AUTO,
        ]
        self._attr_fan_modes = list(FAN_TO_TASMOTA)
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_fan_mode = "auto"
        self._attr_target_temperature = 24.0
        # The mode the unit was last on, so turning it back on returns to it
        # instead of guessing cool.
        self._last_on_mode = HVACMode.COOL

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

        changed = False

        power = str(hvac.get("Power", "")).lower()
        mode = str(hvac.get("Mode", "")).lower()
        if power == "off":
            new_mode = HVACMode.OFF
        else:
            new_mode = TASMOTA_TO_HVAC.get(mode, self._last_on_mode)
        if new_mode != self._attr_hvac_mode:
            self._attr_hvac_mode = new_mode
            if new_mode != HVACMode.OFF:
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

        if changed:
            self.async_write_ha_state()

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
        if self._attr_hvac_mode == HVACMode.OFF:
            self.async_write_ha_state()
            return
        await self._async_publish()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Change the fan speed."""
        self._attr_fan_mode = fan_mode
        if self._attr_hvac_mode == HVACMode.OFF:
            self.async_write_ha_state()
            return
        await self._async_publish()

    async def async_turn_on(self) -> None:
        """Return to the mode the unit was last on."""
        await self.async_set_hvac_mode(self._last_on_mode)

    async def async_turn_off(self) -> None:
        """Turn the unit off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

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

        try:
            await self.coordinator.async_send_json(
                CMND_IRHVAC,
                payload,
                channel=self.coordinator.channel_for(self._appliance),
            )
        except CodeTooLargeError as err:  # pragma: no cover - frames are small
            raise HomeAssistantError(str(err)) from err

        self.async_write_ha_state()
