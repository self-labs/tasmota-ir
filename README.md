# Tasmota IR

[![hacs][hacs-badge]][hacs-url]

Learn and send infrared from Home Assistant with any Tasmota board, through the
standard `remote` services. No input helpers, no capture automation, no send
script, no popup.

Every command you learn becomes a real **button entity**, with a name, an area
and a device, ready to drop on a dashboard. Air conditioners become real
**climate entities**, built by the firmware rather than by a code per
temperature.

## Why this exists

Doing this by hand means an `input_text` capped at 255 characters, an automation
to catch the code, a script to send it and a popup to tie them together. The
emitter number is typed at every call, and getting it wrong is silent: the
firmware falls back to the first emitter and the signal leaves through the wrong
device with no error anywhere.

Here the emitter is a property of the appliance, set once. A channel that is
never typed is a channel that is never typed wrong.

## What you get

| Entity    | What it does                                                                 |
| --------- | ---------------------------------------------------------------------------- |
| `remote`  | `learn_command`, `send_command` and `delete_command`, the standard services  |
| `button`  | one per learned command, created the moment you learn it                     |
| `climate` | one per air conditioner, with the vendor and model read from your own remote |
| `event`   | the receiver as an event source, for automating on "a key was pressed"       |

The entities attach to the **same device** the Tasmota integration already
created for the board, so they sit next to its diagnostics rather than in a card
of their own.

## Requirements

- Home Assistant 2024.11 or newer.
- An MQTT broker, with the Home Assistant MQTT integration set up.
- A Tasmota board with `IRsend` assigned to at least one GPIO, and `IRrecv` if
  you want to learn. The full IR driver (`USE_IR_REMOTE_FULL`) is required for
  more than one emitter and for air conditioners.

## Installation

Through HACS, as a custom repository pointing at this one. Then
**Settings → Devices & Services → Add Integration → Tasmota IR**.

The board is picked from a list: Home Assistant reads the discovery topic
Tasmota already publishes. How many emitters it has is not a question, it is
probed with a `Gpio` command and counted.

## Learning

```yaml
action: remote.learn_command
target:
  entity_id: remote.ag8
data:
  device: Living room TV
  command: power
```

Point the remote at the receiver and press the key **once, on its own**. Two
presses in a row decode as one broken frame, and those are discarded rather than
stored: a saved half frame looks like a working command and reproduces nothing.

A `button.living_room_tv_power` appears immediately. No restart, on either side.

## Sending

```yaml
action: remote.send_command
target:
  entity_id: remote.ag8
data:
  device: Living room TV
  command: power
```

Or just press the button.

## Tested with

- KinCony KC868-AG8, ESP32-S3, 8 emitters and a receiver
- Athom IR Remote, ESP32, one emitter

Any Tasmota board with an `IRsend` GPIO should work. If yours does not, open an
issue with the reply your board gives to `Gpio 255`.

## Licence

MIT. See [LICENSE](./LICENSE).

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
