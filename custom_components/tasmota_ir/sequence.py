"""A sequence: keys of several appliances of one board, pressed in order.

"Cinema" is the TV's power, the sound bar's power, eight seconds for the TV to
wake up, and the sound bar's HDMI 1, behind one button. Each step names an
appliance of the board and one of its keys, never a code: the code is looked
up when the button is pressed, so a key learned again is the one that goes, on
whichever emitter the appliance is on by then.

A step on a typed appliance moves its assumed state exactly as the physical
remote would, since that is what the press is. An air conditioner is not a
step: its frames carry the whole state, and its climate entity sends them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import SIGNAL_SEQUENCE_SENT, SUBENTRY_APPLIANCE
from .coordinator import (
    Appliance,
    CodeTooLargeError,
    TasmotaIrCoordinator,
    check_code_size,
)
from .device_types import TYPED_KINDS, is_list, roles_of
from .entity import TasmotaIrEntity

_LOGGER = logging.getLogger(__name__)

CONF_STEPS = "steps"
STEP_APPLIANCE = "appliance"
STEP_COMMAND = "command"
STEP_ITEM = "item"
STEP_WAIT = "wait"

# Waits are taken through this, so the tests can count them without sleeping.
_sleep = asyncio.sleep


def steps_of(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The steps a sequence subentry keeps, in order."""
    return [dict(step) for step in data.get(CONF_STEPS) or []]


def make_step(
    appliance: str, command: str, item: str | None, wait: float
) -> dict[str, Any]:
    """A step as the subentry keeps it. ``item`` only for a list's item."""
    step: dict[str, Any] = {
        STEP_APPLIANCE: appliance,
        STEP_COMMAND: command,
        STEP_WAIT: wait,
    }
    if item is not None:
        step[STEP_ITEM] = item
    return step


def _label(labels: Mapping[str, str], name: str) -> str:
    """A function's name without the hint in brackets the form shows."""
    return labels.get(name, name).split(" (")[0]


def can_step(appliance: Appliance) -> bool:
    """Whether an appliance can be a step: anything but an air conditioner."""
    return appliance.kind == SUBENTRY_APPLIANCE or appliance.kind in TYPED_KINDS


def step_code(
    coordinator: TasmotaIrCoordinator, step: Mapping[str, Any]
) -> tuple[Appliance, dict[str, Any]] | None:
    """The appliance and code a step stands for now, or None if gone."""
    appliance = coordinator.appliances.get(step.get(STEP_APPLIANCE, ""))
    if appliance is None or not can_step(appliance):
        return None
    command = step.get(STEP_COMMAND, "")
    item = step.get(STEP_ITEM)
    if appliance.kind in TYPED_KINDS:
        value: Any = roles_of(appliance.data).get(command)
        listed = is_list(appliance.kind, command)
        if listed != (item is not None):
            value = None
        elif listed:
            value = value.get(item) if isinstance(value, dict) else None
    else:
        value = coordinator.get_code(appliance.key, command) if item is None else None
    if not isinstance(value, dict) or not value:
        return None
    return appliance, value


def step_choices(
    coordinator: TasmotaIrCoordinator, labels: Mapping[str, str]
) -> list[tuple[dict[str, Any], str]]:
    """Every key of the board a step can press, with how to show it.

    The step comes without its wait, which the person sets beside it.
    """
    choices: list[tuple[dict[str, Any], str]] = []
    appliances = sorted(coordinator.appliances.values(), key=lambda a: a.name)
    for appliance in appliances:
        if not can_step(appliance):
            continue
        if appliance.kind not in TYPED_KINDS:
            for command in coordinator.commands_of(appliance.key):
                choices.append(
                    (
                        make_step(appliance.key, command, None, 0),
                        f"{appliance.name}: {command}",
                    )
                )
            continue
        for name, value in roles_of(appliance.data).items():
            if not isinstance(value, dict):
                continue
            if not is_list(appliance.kind, name):
                choices.append(
                    (
                        make_step(appliance.key, name, None, 0),
                        f"{appliance.name}: {_label(labels, name)}",
                    )
                )
                continue
            for item, code in value.items():
                if isinstance(code, dict):
                    choices.append(
                        (
                            make_step(appliance.key, name, item, 0),
                            f"{appliance.name}: {_label(labels, name)}: {item}",
                        )
                    )
    return choices


def describe_step(
    coordinator: TasmotaIrCoordinator,
    step: Mapping[str, Any],
    labels: Mapping[str, str],
    *,
    mark: bool = True,
) -> str:
    """One step as a person reads it. A step that is gone starts with ⚠."""
    appliance = coordinator.appliances.get(step.get(STEP_APPLIANCE, ""))
    command = str(step.get(STEP_COMMAND, ""))
    item = step.get(STEP_ITEM)
    key = command
    if appliance is not None and appliance.kind in TYPED_KINDS:
        key = _label(labels, command)
    if item is not None:
        key = f"{key}: {item}"
    text = f"{appliance.name if appliance else '?'}: {key}"
    if mark and step_code(coordinator, step) is None:
        text = f"⚠ {text}"
    return text


def describe_steps(
    coordinator: TasmotaIrCoordinator,
    steps: list[dict[str, Any]],
    labels: Mapping[str, str],
) -> str:
    """The whole list, numbered, each with the wait after it."""
    lines = []
    for number, step in enumerate(steps, 1):
        line = f"{number}. {describe_step(coordinator, step, labels)}"
        if number < len(steps):
            line += f" ({float(step.get(STEP_WAIT, 0)):g} s)"
        lines.append(line)
    return "\n".join(lines) or "-"


class TasmotaIrSequenceButton(TasmotaIrEntity, ButtonEntity):
    """The button that runs a sequence."""

    _attr_icon = "mdi:play-box-multiple-outline"
    # The device carries the sequence name, and the button is the sequence.
    _attr_name = None

    def __init__(self, coordinator: TasmotaIrCoordinator, sequence: Appliance) -> None:
        """Bind the button to one sequence of the board."""
        super().__init__(coordinator, sequence)
        self._steps = steps_of(sequence.data)
        self._attr_unique_id = f"{sequence.key}_sequence"
        # The run in progress, so a second press can see it and a button that
        # goes away (a reload, a delete) can stop it.
        self._run: asyncio.Task[None] | None = None

    async def async_press(self) -> None:
        """Press every step, in order, waiting after each the time it asks.

        Every step is checked before anything is sent: half a sequence is worse
        than none, since the TV comes on and the sound bar does not.
        """
        name = self.appliance.name if self.appliance else ""
        board = self.coordinator.entry.title
        if self._run is not None and not self._run.done():
            _LOGGER.debug("%s is already running, ignoring the press", name)
            return
        if not self.coordinator.available:
            raise HomeAssistantError(f"{board} is offline, so nothing was sent.")
        plan: list[tuple[Appliance, dict[str, Any], dict[str, Any]]] = []
        for number, step in enumerate(self._steps, 1):
            found = step_code(self.coordinator, step)
            problem = f"presses a key that is no longer on {board}"
            if found is not None:
                try:
                    check_code_size(found[1])
                    problem = ""
                except CodeTooLargeError as err:
                    problem = f"has a code the board cannot take ({err})"
            if found is None or problem:
                text = describe_step(self.coordinator, step, {}, mark=False)
                raise HomeAssistantError(
                    f"Step {number} of {name}, {text}, {problem}, so nothing was "
                    "sent. Edit the sequence."
                )
            plan.append((found[0], found[1], step))
        self._run = run = self.hass.async_create_task(
            self._async_run(name, plan), f"tasmota_ir sequence {name}"
        )
        try:
            await run
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if run.cancelled() and current is not None and not current.cancelling():
                # The button went away half way, through a reload or a delete:
                # the run stopped with it, and that is not an error.
                return
            run.cancel()
            raise

    async def _async_run(
        self,
        name: str,
        plan: list[tuple[Appliance, dict[str, Any], dict[str, Any]]],
    ) -> None:
        """Send the checked steps, and stop if the board goes away between them."""
        for index, (appliance, code, step) in enumerate(plan):
            if index:
                await _sleep(float(plan[index - 1][2].get(STEP_WAIT, 0)))
                if not self.coordinator.available:
                    raise HomeAssistantError(
                        f"{self.coordinator.entry.title} went offline at step "
                        f"{index + 1} of {name}; the steps before it were sent."
                    )
            try:
                await self.coordinator.async_send_code(
                    code, channel=self.coordinator.channel_for(appliance.key)
                )
            except CodeTooLargeError as err:
                raise HomeAssistantError(str(err)) from err
            async_dispatcher_send(
                self.hass,
                SIGNAL_SEQUENCE_SENT.format(entry_id=self.coordinator.entry.entry_id),
                appliance.key,
                step.get(STEP_COMMAND),
                step.get(STEP_ITEM),
            )

    async def async_will_remove_from_hass(self) -> None:
        """A run of a button that is going away must not go on."""
        if self._run is not None:
            self._run.cancel()
        await super().async_will_remove_from_hass()
