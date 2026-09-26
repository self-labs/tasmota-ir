[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?logo=home-assistant&logoColor=white)](https://hacs.xyz/) [![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.3%2B-41BDF5?logo=home-assistant&logoColor=white)](https://www.home-assistant.io/) [![License: MIT](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)

# 📡 Tasmota IR

Learn and send infrared from Home Assistant with any Tasmota board. No input
helpers, no capture automation, no send script, no popup.

Every appliance you add appears **under its board**, with its own device. Every
key you learn becomes a real **button entity** on that device, ready to drop on
a dashboard. Air conditioners become real **climate entities**, built by the
firmware from vendor, mode, temperature, fan and vane, rather than by a code per
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

| Entity    | One per               | Example                      | What it does                                                        |
| --------- | --------------------- | ---------------------------- | ------------------------------------------------------------------- |
| `remote`  | board                 | `remote.hubb_ir1`            | `learn_command`, `send_command` and `delete_command`, as actions    |
| `event`   | board with a receiver | `event.hubb_ir1_ir_receiver` | fires on every frame the receiver decodes, from any remote          |
| `button`  | learned key           | `button.tv_quarto_power`     | sends that key through its appliance's emitter                      |
| `climate` | air conditioner       | `climate.ar_escritorio`      | modes, temperature, fan and vane, following the physical remote too |

Every entity follows the board's `LWT`: while the board is offline, they are
unavailable.

### What it looks like

A KinCony AG8, eight emitters and a receiver, with two appliances and an air
conditioner:

```text
Tasmota IR
└── Hubb IR1                              the board: 8 emitters, 1 receiver
    ├── remote.hubb_ir1                   learn, send and delete by action
    ├── event.hubb_ir1_ir_receiver        every key the receiver hears
    ├── JBL Soundbar                      appliance, emitter 1
    │   ├── button.jbl_soundbar_power
    │   ├── button.jbl_soundbar_vol_up
    │   ├── button.jbl_soundbar_vol_down
    │   └── button.jbl_soundbar_optical
    ├── TV Quarto                         appliance, emitter 1
    │   └── button.tv_quarto_power
    └── Ar Escritorio                     air conditioner, emitter 2, LG2 AKB74955603
        └── climate.ar_escritorio
```

### Every function, and where it is

Everything is on **Settings → Devices & Services → Tasmota IR**. Nothing needs
YAML.

```text
Add Integration → Tasmota IR             pick the board; its emitters are counted
└── Hubb IR1                             the board
    ├── Add appliance                    name and emitter, then learn its keys
    ├── Add air conditioner              name and emitter, then press any key of its remote
    ├── TV Quarto → Manage appliance
    │   ├── Learn a command              a new button per key
    │   ├── Delete a learned command     the button goes with it
    │   ├── Change the emitter           tried before it is saved
    │   ├── Rename
    │   ├── Move to another board        codes and entity ids go along
    │   └── Copy to another board        the other board gets its own copy
    └── Ar Escritorio → Manage air conditioner
        ├── Settings                     model, temperature range, modes, vanes
        ├── Read the remote again        vendor and model, from one key press
        ├── Change the emitter           tried before it is saved
        ├── Rename
        ├── Move to another board        settings and entity id go along
        └── Copy to another board        the other board gets its own copy
```

**Manage appliance** and **Manage air conditioner** are in the three-dot menu of
each appliance, under its board. **Delete** is in the same menu, and takes the
codes with it.

## Requirements

- Home Assistant 2025.3 or newer.
- An MQTT broker, with the Home Assistant MQTT integration set up.
- A Tasmota board on that broker, with:
  - `IRsend` on at least one GPIO, and `IRrecv` to learn. `Gpio` in the
    board's console lists them.
  - The full IR driver (`USE_IR_REMOTE_FULL`) for more than one emitter and
    for air conditioners. The standard builds carry the basic one; the
    `tasmota-ir` and `tasmota32-ir` builds carry the full one, and so do the
    KinCony builds at
    [self-labs.github.io/tasmota-kincony](https://self-labs.github.io/tasmota-kincony/).
  - `SetOption58 1`, so remotes whose protocol the library does not know can
    still be learned, as raw.
  - Tasmota's own discovery on, which is its default (`SetOption19 0`), for
    the board to be offered in a list. Without it, you type the topic.

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

1. Pick the board from the list. The list comes from the discovery topic
   Tasmota already publishes. **Enter a topic manually**, at the bottom, is for
   a board that does not announce itself: use the `Topic` of its MQTT settings.
2. That is all. How many emitters the board has is not a question: the
   integration sends `Gpio 255` and counts the `IRsend` pins, and looks for an
   `IRrecv`. A board with eight emitters and a board with one are handled by the
   same code, which knows neither model.

> [!IMPORTANT]
> Add the board **online, with its final template**. The emitters are counted
> once, at this step: a board that does not answer is set up with one emitter
> and no receiver, and a template changed later is only seen by removing the
> board and adding it again.

## Quick start: a working button in a minute

1. On the board, **Add appliance**. Name: `TV Quarto`. Emitter: the one whose
   LED points at the TV; the list says which appliances each emitter already
   has.
2. **Learn a command now**. Name the key `power` and continue.
3. Point the TV's remote at the board and press power once. The screen waits up
   to 30 seconds; there is nothing to click between naming the key and pressing
   it.
4. **Done**. `button.tv_quarto_power` is on the **TV Quarto** device. Press it,
   and the TV answers.
5. It did not? **Manage appliance → Change the emitter**: it sends power
   through the emitter you pick and asks whether the TV answered, before saving
   anything.

## Learning keys

To learn more keys later, choose **Manage appliance → Learn a command** on that
appliance. The appliance is the one you opened, so there is no question of which
emitter the code is for. Holding the key is fine; pressing two different keys in
a row is not.

Three kinds of capture are refused on purpose, because storing them would create
a button that looks right and does nothing:

- **Broken frames.** Two presses in a row, or one from too far away, arrive as
  a frame the library could not finish reading: empty `Data`, zero `Bits`,
  sometimes labelled with the wrong protocol. They are ignored and the wait
  goes on.
- **Repeat frames.** While a key is held, a NEC remote sends the real frame once
  and then a burst every 108 ms meaning "keep repeating the last one". The burst
  carries no command. The real frame is kept and the repeats are ignored.
- **Air conditioner frames.** One capture from one of those remotes is one
  temperature in one mode. Learning says so and points at **Add air
  conditioner** instead.

When nothing usable arrives in 30 seconds, when the key is an air conditioner's,
or when the code is too large to send (see [Known limits](#known-limits)), the
screen says which it was and offers **Try again**, **Learn a different
command** or **Stop here**.

## Managing an appliance

**Manage appliance** on any appliance offers:

| Entry                        | What it does                                                    |
| ---------------------------- | --------------------------------------------------------------- |
| **Learn a command**          | name a key, press it, and a button appears                      |
| **Delete a learned command** | forget one command, and its button with it                      |
| **Change the emitter**       | tries the emitter first, then asks whether it answered          |
| **Rename**                   | a new name; buttons, codes and emitter stay as they are         |
| **Move to another board**    | the appliance leaves this board with its codes, entity ids kept |
| **Copy to another board**    | the other board gets its own appliance, this one stays          |

**Changing an emitter does not require learning anything again.** The code is
stored per appliance and the emitter is looked up when it is sent. The emitters
are listed with the appliances already on them, and the one you pick is tried
before it is saved, by sending the appliance's first learned command: nothing on
the board says where an emitter points, and an appliance on the wrong one fails
in silence. An appliance with nothing learned has nothing to send, so its
emitter is saved straight away.

**Moving to another board does not require learning anything again either.** A
learned code is the infrared signal itself, and every Tasmota board sends it the
same way. Moving keeps the appliance's key, so its buttons come back with the
same entity ids, names and areas, and dashboards and automations keep working;
only the emitter and the name are asked again, because the other board has its
own. Copying gives the other board an appliance of its own, with new entities,
for the same kind of TV in two rooms. Both need the other board added to Tasmota
IR first.

## Air conditioners

1. On the board, **Add air conditioner**, with a name and the emitter pointed at
   the unit.
2. Point the unit's own remote at the board and press any key. Anything that
   is not an air conditioner frame is ignored while it waits, broken frames
   included, so nothing else can end the wait.
3. The firmware decodes the whole frame, so the vendor and the model come from
   the unit itself. There is nothing to look up in a manual. `climate.<name>`
   appears on its own device, with every mode offered until **Settings** says
   which ones the unit has.

The entity is driven by Tasmota's `IRHVAC`, which assembles every command from
vendor, mode, temperature, fan speed and vane position:

- **Modes:** off, plus the ones ticked in **Settings** (cool, heat, dry, fan
  only and auto; all of them until you untick some).
- **Temperature:** whole degrees Celsius, 18 to 30 unless **Settings** says
  otherwise.
- **Fan:** auto, min, low, medium, high and max.
- **Vertical vane:** fixed, swing, highest, high, middle, low and lowest.
- **Horizontal vane,** when turned on in **Settings:** fixed, swing, far left,
  left, centre, right, far right and wide.
- **Turning it on** goes back to the mode it was last on.
- **Changing temperature, fan or vane while it is off** is remembered and sent
  with the next turn on. The frame carries the whole state, so sending it would
  switch the unit on as a side effect of moving a slider.
- **It follows the physical remote.** Every frame of that vendor the receiver
  hears updates the card, so it stays right when somebody uses the remote in
  their hand.
- **The state survives a restart** of Home Assistant.

**Manage air conditioner → Settings** holds what the firmware is told:

- **Model.** Some vendors make several remotes that look alike to the decoder,
  and the model decides what the firmware sends. An LG read as `AKB75215403`
  never sends the vane; the same unit set to `AKB74955603` does. The known
  models of each vendor are offered, and any other can be typed.
- **Temperature range and modes.** Only the modes your unit really has.
- **Vertical and horizontal vane.** The vertical vane is on by default, except
  for the vendors where the firmware treats it as a toggle (`COOLIX`,
  `TRANSCOLD`, `MIDEA`, `CORONA_AC`, `HITACHI_AC344`, `HITACHI_AC424`,
  `SHARP_AC`, `KELON`), because there every command would flip it.

**Read the remote again** re-reads vendor and model from the remote. For an LG,
run it and press the **vane key**: that key is a frame of its own, and the
decoder reads it as `AKB74955603`, which is the model that sends the vane. On
the remote tested here, every vane position arrived as `0x8813...` decoded that
way, while the power and temperature keys decode as `AKB75215403`.

**Change the emitter** tries the emitter by turning the unit on, in cool at its
highest temperature, which is what can be seen from across the room. Turn it off
again once you have answered.

**Rename**, **Move to another board** and **Copy to another board** work as they
do for an appliance, carrying the settings along.

## Using the actions

Every learned key is a button, so the simplest way to send one from a script or
an automation is to press it:

```yaml
action: button.press
target:
  entity_id: button.tv_quarto_power
```

The board's `remote` entity takes the standard remote actions, in **Developer
Tools → Actions** or anywhere else:

| Action                  | Field         | Default  | What it is                                                    |
| ----------------------- | ------------- | -------- | ------------------------------------------------------------- |
| `remote.send_command`   | `device`      | required | the appliance name, as shown under the board, ignoring case   |
|                         | `command`     | required | one key or a list, sent in order; the name must match exactly |
|                         | `num_repeats` | `1`      | how many times the whole list is sent                         |
|                         | `delay_secs`  | `0.4`    | seconds between one key and the next, and between repeats     |
| `remote.learn_command`  | `device`      | required | the appliance; a name that does not exist yet creates it      |
|                         | `command`     | required | one key name or a list, learned in order, one press each      |
|                         | `timeout`     | `20`     | seconds to wait for each key                                  |
| `remote.delete_command` | `device`      | required | the appliance                                                 |
|                         | `command`     | required | one key or a list; their buttons go with them                 |

```yaml
action: remote.send_command
target:
  entity_id: remote.hubb_ir1
data:
  device: TV Quarto
  command: volume up
  num_repeats: 5
  delay_secs: 0.3
```

```yaml
action: remote.learn_command
target:
  entity_id: remote.hubb_ir1
data:
  device: TV Quarto
  command:
    - volume up
    - volume down
  timeout: 30
```

```yaml
action: remote.delete_command
target:
  entity_id: remote.hubb_ir1
data:
  device: TV Quarto
  command: volume down
```

- **Learning under a new name creates the appliance,** on emitter 1, so a
  command learned by action never ends up somewhere the interface does not
  show. Move it to its emitter afterwards, from **Manage appliance**.
- **What was learned before a timeout is kept.** Learning three keys and
  missing the third stores the first two.
- **Errors say what exists.** A wrong `device` lists the appliances the board
  has; a wrong `command` lists the keys that appliance knows.
- **`remote.turn_off` pauses `remote.send_command`**, which ignores calls until
  `remote.turn_on`, and stays off across restarts. Nothing is deleted, and the
  buttons and air conditioners keep sending.

## Attributes

| Entity    | Attribute    | Example                                          |
| --------- | ------------ | ------------------------------------------------ |
| `remote`  | `appliances` | `["Ar Escritorio", "JBL Soundbar", "TV Quarto"]` |
|           | `commands`   | `{"TV Quarto": ["power", "volume up"]}`          |
|           | `emitters`   | `8`, how many the board has                      |
| `button`  | `appliance`  | `TV Quarto`                                      |
|           | `command`    | `power`                                          |
|           | `emitter`    | `1`                                              |
| `climate` | `vendor`     | `LG2`                                            |
|           | `model`      | `AKB74955603`                                    |
|           | `emitter`    | `2`                                              |

## Automating on a key press

The `event` entity fires `ir_received` on every frame the receiver decodes,
from any remote, whether or not its code was learned. The frame rides along:

| Attribute  | What it is                                                         |
| ---------- | ------------------------------------------------------------------ |
| `protocol` | the protocol the library decoded, such as `NEC`, `LG2` or `RAW`    |
| `bits`     | the frame size                                                     |
| `data`     | the code itself, such as `0x20DF10EF`                              |
| `repeat`   | whether it was a repeat frame                                      |
| `is_hvac`  | `true` for an air conditioner frame                                |
| `known_as` | `TV Quarto/power` when it matches a learned code, `null` otherwise |

An example: the power key of the TV's own remote also switches the sound bar.

```yaml
alias: TV power also switches the sound bar
description: The board hears the TV remote's power key and presses the sound bar's.
triggers:
  - trigger: state
    entity_id: event.hubb_ir1_ir_receiver
    not_from: unavailable
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.known_as == 'TV Quarto/power' }}"
actions:
  - action: button.press
    target:
      entity_id: button.jbl_soundbar_power
mode: single
```

`not_from: unavailable` keeps the board coming back online from firing it. For
a remote you never learned, compare `data` instead of `known_as`.

## Where the codes live

- **In Home Assistant, not on the board**, in
  `.storage/tasmota_ir_<entry_id>_codes` inside the configuration folder, so a
  Home Assistant backup carries them.
- **Keyed by the appliance, not its name.** Renaming an appliance moves nothing.
- **Deleting an appliance deletes its codes.** Removing the board removes its
  appliances, and their codes do not come back if the board is added again.

## Upgrading from 2026.9.5 or older

The first start migrates by itself. Each appliance of the old **Configure** menu
becomes an appliance under the board, with the same emitter; a name that only
had learned codes becomes an appliance on emitter 1. The codes move with them,
and **entity ids do not change**, so dashboards and automations keep working.
Friendly names lose the board prefix, because the device already carries the
appliance name: `Hubb IR1 TV Quarto power` becomes `TV Quarto power`.

## Known limits

- **Raw codes reach emitters other than 1 only on a firmware that allows it.** A
  remote whose protocol the firmware does not know is stored as raw, and
  Tasmota's plain raw form, `IRSend <freq>,<data>`, takes no channel at all.
  [arendst/Tasmota#25062](https://github.com/arendst/Tasmota/pull/25062) adds a
  JSON form with a `Channel`, and the integration uses it: the first raw code
  sent to an appliance on another emitter asks the board, a firmware that
  answers `Done` keeps getting it, and one that answers `Wrong Protocol` gets
  the plain form on emitter 1 from then on, with a warning in the log. The
  question is asked again whenever the board comes back online, since that is
  when its firmware may have changed. Until that PR is merged, the builds at
  [self-labs.github.io/tasmota-kincony](https://self-labs.github.io/tasmota-kincony/)
  carry it.
- **A code larger than about 1 KB cannot be sent.** The board's MQTT buffer
  defaults to 1200 bytes and has to carry the topic too. Such a capture is
  refused when learning, with a message, rather than failing later.
- **The emitters are counted once**, when the board is added. See
  [Then add the board](#then-add-the-board).
- **The card follows the physical remote only when the frame arrives whole.** A
  key pressed from across the room can decode as something else, and then there
  is nothing to follow.
- **LG defines six vane positions and the firmware maps them onto five.** The
  one between middle and high (`0x881307B`) arrives as middle, and cannot be sent.
- **One previous state per board.** The firmware remembers a single last frame
  for the whole board, and toggle-based vendors decide what to flip from it. Two
  air conditioners of such a vendor on the same board can confuse each other.
- **The icon in the HACS catalogue** keeps a placeholder. The device and
  integration pages show the right one; the catalogue listing is
  [hacs/integration#5171](https://github.com/hacs/integration/issues/5171).

## Tested with

- KinCony KC868-AG8, ESP32-S3, 8 emitters and a receiver. Learned an LG
  television's power key (NEC, 32 bits) from its own remote and switched the
  set on and off with the button that was created. Added an LG split from its
  remote (`LG2`, `AKB75215403`) and drove power, mode, temperature and fan from
  the climate entity, each change confirmed by the unit's own Wi-Fi reporting
  about a second later.
- Athom IR Remote, ESP32, one emitter.
- The test suite, 42 tests against Home Assistant 2026.9.3:
  `pip install -r requirements_test.txt`, then `pytest`.

Any Tasmota board with an `IRsend` GPIO should work. If yours does not, open an
issue with the reply your board gives to `Gpio 255`.

## Licence

MIT. See [LICENSE](./LICENSE).
