[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?logo=home-assistant&logoColor=white)](https://hacs.xyz/) [![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.11%2B-41BDF5?logo=home-assistant&logoColor=white)](https://www.home-assistant.io/) [![License: MIT](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

# 📡 Tasmota IR

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

## Install

### HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=self-labs&repository=tasmota-ir&category=integration)

The button opens this repository straight in your HACS. Click **Download**, then
restart Home Assistant.

It works through [my.home-assistant.io](https://my.home-assistant.io/), which
only knows how to reach your instance after you set your own URL there once,
under **Settings → System → Network → Home Assistant URL**.

<details>
<summary>Doing it by hand</summary>

1. HACS → three-dot menu → **Custom repositories**.
2. URL: `https://github.com/self-labs/tasmota-ir`, type **Integration** → **ADD**.
3. Open the entry and click **Download**.
4. Restart Home Assistant.

</details>

### Then add the board

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=tasmota_ir)

Or **Settings → Devices & Services → Add Integration → Tasmota IR**.

The board is picked from a list: Home Assistant reads the discovery topic
Tasmota already publishes. How many emitters it has is not a question, it is
probed with a `Gpio` command and counted. A board with eight emitters and a
board with one are handled by the same code, which knows neither model.

## Where to run the commands below

Every YAML block in this README is an **action**. Run it in **Developer Tools →
Actions**, switching the form to YAML mode, or paste it unchanged into an
automation or a script. That is the point of using the standard `remote`
services: they work anywhere Home Assistant accepts an action.

## Learning

```yaml
action: remote.learn_command
target:
  entity_id: remote.living_room_blaster
data:
  device: Living room TV
  command: power
  timeout: 30
```

Point the remote at the receiver and press the key once. The call waits until a
code arrives or the timeout runs out, and a
`button.living_room_blaster_living_room_tv_power` appears the moment it is
stored. No restart, on either side.

Three kinds of capture are refused on purpose, because storing them would create
a button that looks right and does nothing:

- **Partial frames.** Two presses in a row decode as one broken frame, with
  empty `Data` and zero `Bits`.
- **Repeat frames.** While a key is held, a NEC remote sends the real frame once
  and then a burst every 108 ms meaning "keep repeating the last one". The burst
  carries no command. Holding the key is fine: the real frame is kept and the
  repeats are ignored.
- **Air conditioner frames.** One capture from one of those remotes is one
  temperature in one mode. Learning says so and points at the air conditioner
  flow instead.

## Sending

```yaml
action: remote.send_command
target:
  entity_id: remote.living_room_blaster
data:
  device: Living room TV
  command: power
  num_repeats: 1
  delay_secs: 0.4
```

Or just press the button. If the name is wrong, the error lists the commands
that appliance does know.

## Appliances and their emitters

A board with several emitters needs to know which one points at which
appliance. Set it once, in **Settings → Devices & Services → Tasmota IR → your
board → Configure**:

| Menu entry                   | What it does                                          |
| ---------------------------- | ----------------------------------------------------- |
| **Add an appliance**         | a name plus the emitter pointed at it                 |
| **Add an air conditioner**   | the same, then reads vendor and model from its remote |
| **Change an emitter**        | move an appliance to another emitter                  |
| **Remove an appliance**      | forget the appliance; its learned codes stay          |
| **Delete a learned command** | forget one command, and its button with it            |

**Changing an emitter does not require learning anything again.** The code is
stored per appliance and the emitter is looked up when it is sent, so moving
"Living room TV" from emitter 1 to emitter 3 makes every one of its buttons
leave through emitter 3 from then on. The same goes for adding an appliance
after learning its commands: learn first under a name, then add that exact name
as an appliance with its emitter, and the existing buttons follow.

An appliance that was never added uses emitter 1.

## Deleting a command learned wrong

From the interface: **Configure → Delete a learned command**, then pick it from
the list.

Or as an action:

```yaml
action: remote.delete_command
target:
  entity_id: remote.living_room_blaster
data:
  device: Living room TV
  command: power
```

The button goes with it, and the command can be learned again from scratch.

## Air conditioners

**Configure → Add an air conditioner**, give it a name and an emitter, then
point its remote at the board and press any key. The firmware decodes the whole
frame, so the vendor, the model and the supported modes come from the unit
itself. There is nothing to look up in a manual.

The result is a `climate` entity driven by Tasmota's `IRHVAC`, which assembles
every command from vendor, mode, temperature and fan speed. It also reads back
every frame the receiver hears, so the card follows the physical remote as
well as Home Assistant. Setting a temperature on a unit that is off does not
turn it on.

## Automating on a key press

The `event` entity fires on every decoded frame, from any remote, whether or
not its code was learned. The payload says which protocol it was, whether it
matches something already learned (`known_as`), and whether it came from an air
conditioner (`is_hvac`).

## Known limits

- **Raw codes always leave through the first emitter.** A remote whose protocol
  the firmware does not know is stored as raw, and Tasmota's raw send form takes
  no channel at all. This is a firmware limit; the integration logs a warning
  when such an appliance is set to another emitter.
- **A code larger than about 1 KB cannot be sent.** The board's MQTT buffer
  defaults to 1200 bytes and has to carry the topic too. Such a capture is
  refused when learning, with a message, rather than failing later.
- **The icon in the HACS catalogue** keeps a placeholder. The device and
  integration pages show the right one; the catalogue listing is
  [hacs/integration#5171](https://github.com/hacs/integration/issues/5171).

## Tested with

- KinCony KC868-AG8, ESP32-S3, 8 emitters and a receiver. Learned an LG
  television's power key (NEC, 32 bits) from its own remote and switched the
  set on and off with the button that was created.
- Athom IR Remote, ESP32, one emitter.

Any Tasmota board with an `IRsend` GPIO should work. If yours does not, open an
issue with the reply your board gives to `Gpio 255`.

## Licence

MIT. See [LICENSE](./LICENSE).
