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

| Entity         | One per                               | Example                                | What it does                                                              |
| -------------- | ------------------------------------- | -------------------------------------- | ------------------------------------------------------------------------- |
| `remote`       | board                                 | `remote.hubb_ir1`                      | `learn_command`, `send_command` and `delete_command`, as actions          |
| `event`        | board with a receiver                 | `event.hubb_ir1_ir_receiver`           | fires on every frame the receiver decodes, from any remote                |
| `event`        | appliance, on a board with a receiver | `event.tv_quarto_remote`               | fires with the key's name when that appliance's own remote is pressed     |
| `button`       | learned key                           | `button.tv_quarto_power`               | sends that key through its appliance's emitter                            |
| `climate`      | air conditioner                       | `climate.ar_escritorio`                | modes, temperature, fan and vane, following the physical remote too       |
| `infrared`     | appliance                             | `infrared.tv_quarto`                   | the emitter Home Assistant's own IR integrations send through             |
| `infrared`     | appliance, on a board with a receiver | `infrared.tv_quarto_infrared_receiver` | everything the board hears, for those integrations to decode              |
| `switch`       | air conditioner extra                 | `switch.ar_escritorio_display`         | display, beep, self clean and filter, when the unit's protocol sends them |
| `media_player` | TV or sound bar                       | `media_player.jbl_soundbar`            | power, volume, mute, sources, channel, play and pause, from learned keys  |
| `fan`          | fan                                   | `fan.ventilador`                       | power, speeds, oscillation and modes, from learned keys                   |
| `light`        | light                                 | `light.luminaria`                      | power, brightness and colour temperature in steps, effects                |
| `cover`        | cover                                 | `cover.tela`                           | open, close, stop, and a position from the travel time                    |
| `switch`       | on and off                            | `switch.tomada`                        | power, from one key that toggles or two                                   |
| `button`       | sequence                              | `button.cinema`                        | keys of several appliances of the board, pressed in order                 |

Every entity follows the board's `LWT`: while the board is offline, they are
unavailable.

The entity ids here are those of a Home Assistant set to English. Home Assistant
builds entity ids from the names in its own language, so on one set to
Portuguese the appliance's remote is `event.tv_quarto_controle` and its
receiver `infrared.tv_quarto_receptor_infravermelho`. The board's receiver is
`event.hubb_ir1_ir_receiver` in every language. An entity keeps the id it was
created with, whatever the language is changed to later.

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
    │   ├── button.tv_quarto_power
    │   ├── event.tv_quarto_remote        its own remote, key by key
    │   ├── infrared.tv_quarto            for Home Assistant's LG Infrared
    │   └── infrared.tv_quarto_infrared_receiver
    └── Ar Escritorio                     air conditioner, emitter 2, LG2 AKB74955603
        ├── climate.ar_escritorio
        └── switch.ar_escritorio_display  the only extra an LG sends
```

Every appliance carries the two `infrared` entities and, except an air
conditioner, the `event` of its own remote; the tree only shows them under TV
Quarto.

### Every function, and where it is

Everything is on **Settings → Devices & Services → Tasmota IR**. Nothing needs
YAML.

```text
Add Integration → Tasmota IR             pick the board; its emitters are counted
└── Hubb IR1                             the board
    ├── Configure
    │   └── Move everything to another board
    │                                    every appliance, an emitter each there
    ├── Add appliance                    name and emitter, then learn its keys
    ├── Add air conditioner              name and emitter, then press any key of its remote
    ├── Add TV or sound bar, fan, light, cover, on and off
    │                                    name and emitter, then each function: learn, reuse, clear
    ├── Add sequence                     name, then steps: a key of an appliance and a wait
    ├── TV Quarto → Manage appliance
    │   ├── Learn a command              a new button per key
    │   ├── Delete a learned command     the button goes with it
    │   ├── Change the emitter           tried before it is saved
    │   ├── Rename
    │   ├── Move to another board        codes and entity ids go along
    │   └── Copy to another board        the other board gets its own copy
    ├── Ar Escritorio → Manage air conditioner
    │   ├── Settings                     model, temperature range, modes, vanes, extras
    │   ├── Read the remote again        vendor and model, from one key press
    │   ├── Change the emitter           tried before it is saved
    │   ├── Rename
    │   ├── Move to another board        settings and entity id go along
    │   └── Copy to another board        the other board gets its own copy
    └── Cinema → Manage sequence
        ├── Steps                        add, remove; ⚠ marks a step that is gone
        └── Rename
```

**Manage appliance**, **Manage air conditioner** and **Manage sequence** are in
the three-dot menu of each appliance or sequence, under its board. **Delete** is
in the same menu, and takes the codes with it.

## Requirements

- Home Assistant 2025.3 or newer; 2026.6 or newer for the `infrared` entities.
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
in silence. An appliance with nothing learned gets the last command another
integration sent through it (see
[Home Assistant's own infrared integrations](#home-assistants-own-infrared-integrations));
with nothing at all to send, its emitter is saved straight away.

**Moving to another board does not require learning anything again either.** A
learned code is the infrared signal itself, and every Tasmota board sends it the
same way. Moving keeps the appliance's key, so its buttons come back with the
same entity ids, names and areas, and dashboards and automations keep working;
only the emitter and the name are asked again, because the other board has its
own. Copying gives the other board an appliance of its own, with new entities,
for the same kind of TV in two rooms. Both need the other board added to Tasmota
IR first.

**Replacing a board** is **Configure → Move everything to another board** on
the old one, checking the appliances on the new one, and then deleting the old
board. One screen asks the emitter each appliance gets there, starting on the
number it has today (on emitter 1 when the new board has fewer), and lists who
already uses each; then every appliance moves as a single move would, codes,
functions, settings and entity ids included, the `infrared` emitter too. The
receiver entities, the `infrared` one and the appliance's `event`, only exist
on a board with a receiver. A name the new board already has stops it before
anything moves: rename one of the two first. So does an appliance the new board
already has under another name, moved there before. The codes are written to
the new board before the appliances leave the old one, so deleting the old
board afterwards loses nothing. Moving the appliances one at a time works the
same way. Copying works too, but a copy gets new entity ids, and whatever
pointed at the old board's entities stops working when that board goes.

## Appliance types

A TV, a fan or a light is more than a row of buttons. The board has five more
buttons for them, each giving the right entity:

| Button                  | Entity         | Functions                                                                                                  |
| ----------------------- | -------------- | ---------------------------------------------------------------------------------------------------------- |
| **Add TV or sound bar** | `media_player` | power; volume up and down; mute; sources, each with a name; channel up and down; play and pause            |
| **Add fan**             | `fan`          | power; a key per speed, or one key that cycles and how many speeds; oscillate; modes                       |
| **Add light**           | `light`        | power; brighter and dimmer with how many steps; warmer and cooler with how many steps; effects and colours |
| **Add cover**           | `cover`        | open and close; stop; how many seconds a full run takes                                                    |
| **Add on and off**      | `switch`       | power                                                                                                      |

Power is one key that toggles, or a pair of keys, one to turn on and one to turn
off; a cover needs open and close. Everything else is optional, and the entity
only offers what was learned.

1. Pick the button, give a name and the emitter pointed at the appliance.
2. Pick a function. **Learn it now** waits for the remote, as learning a key
   does. **Use a key this board already learned** takes the code of any other
   appliance of the board, so nothing is pressed again. **Clear it** forgets it.
3. For a list (sources, speeds, modes, effects), name the item first, such as
   `HDMI 1`, then learn or reuse its key.
4. Optionally, the **Power sensor**: see below.
5. **Finish**. **Manage** changes the functions later, the emitter (the test
   presses power), the name, and moves or copies the appliance: its functions
   live in the appliance itself, so they go along.

**Turning an appliance you already have into a type:** add the type and reuse
its keys one by one, check the new entity, then delete the old appliance. A
sound bar learned as buttons becomes a media player without touching its remote.

**The state is assumed.** Infrared says nothing back, so the entity keeps what
Home Assistant sent, and follows the physical remote too: the receiver hears it,
and a key that matches a learned function moves the state. Raw codes are never
matched, since two captures of the same key are never identical.

- **Power sensor.** Anything that turns on and off with the appliance, or a
  power meter with the watts above which it counts as on. When it reads
  something, it decides on and off, and a power key that toggles is only pressed
  when the sensor says it has to be. A sensor takes a moment to see a change:
  asking again right after a press can press it again. When the sensor goes
  unavailable, its last reading stands.
- **Steps are counted from the assumed level.** Brightness, colour and a cycling
  speed key press the difference from where the integration thinks the
  appliance is. If it drifts, take it to the lowest from the card and go up
  again.
- **A cover's position** needs both a stop key and the travel time: it moves for
  the share of the run the distance takes, then presses stop.

## Sequences

A sequence is one button that presses keys of several appliances of the board in
order: **Cinema** is the TV's power, the sound bar's power, a wait for the TV to
wake up, and the sound bar's HDMI 1.

1. **Add sequence** on the board, and a name: the button gets it, such as
   `button.cinema`.
2. **Add a step**: an appliance of this board and one of its keys (a learned
   key, a function of a typed appliance, or an item of its lists), and how long
   to wait after it before the next step. 0.4 s by default; a TV that was just
   turned on can need several seconds before it takes a source.
3. Add the rest, **Remove a step** if one is wrong, and **Finish**.

**Manage sequence** edits the steps or renames it.

- **A step names the key, never the code.** The code is looked up when the
  button is pressed, so a key learned again is the one that goes, on whichever
  emitter the appliance is on by then.
- **A step on a typed appliance moves its state** exactly as the physical remote
  would: pressing a toggling power key flips the assumed state, and pressing a
  source sets it. The appliance's `event` does not fire, since its remote was
  not pressed.
- **Every step is checked before anything is sent.** A step whose appliance or
  key is no longer on the board, or whose code the board could not take, stops
  the whole sequence with an error naming the step and its key, and **Manage
  sequence** shows a missing one with ⚠. An offline board sends nothing either.
- **If the board goes offline half way**, the rest is not sent, and the error
  says at which step it stopped. Editing, renaming or deleting the sequence
  while it runs stops that run too. Pressing the button again while it runs
  does nothing.
- **A sequence's name is not an appliance's.** `remote.learn_command`,
  `send_command` and `delete_command` with it as the `device` are refused, and
  say which button runs it.
- **An air conditioner is not a step**: its frames carry the whole state, and
  its `climate` entity sends them. For anything with conditions, or across
  boards, a Home Assistant script with these buttons and entities does it.
- **A sequence moves with Move everything to another board**, and only that
  way: its steps point at appliances of its own board.

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
- **Extras:** turbo, economy, quiet and sleep as presets on the card, one at a
  time as on the remotes; display, beep, self clean and filter as switches on
  the unit's device. Only the ones the IR library really sends for the vendor
  (an LG sends the display and nothing else), and only the ones ticked in
  **Settings**. An extra the library toggles, such as a Samsung's beep, is left
  out, since Tasmota keeps no memory of what it sent and every command would
  flip it; so is a sleep that is really a timer to switch off. Changed while the unit is off, they go
  out with the next turn on, and the physical remote moves them too.
- **The state survives a restart** of Home Assistant, extras included.

**Manage air conditioner → Settings** holds what the firmware is told:

- **Model.** Some vendors make several remotes that look alike to the decoder,
  and the model decides what the firmware sends. An LG read as `AKB75215403`
  never sends the vane; the same unit set to `AKB74955603` does. The known
  models of each vendor are offered, and any other can be typed.
- **Temperature range and modes.** Only the modes your unit really has.
- **Extras.** The ones this vendor's protocol sends, all ticked for a new unit;
  untick what your unit does not have, and its preset or switch goes away.
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

## Home Assistant's own infrared integrations

Home Assistant 2026.6 and newer ship integrations that already know every code
of some devices: **LG Infrared** (TVs and air conditioners), **Samsung
Infrared** (TVs), **Edifier Infrared** and **Marantz Infrared** (speakers and
receivers), **Dyson Infrared** (fans) and **LED Infrared** (the generic strips
and bulbs with a 13, 24, 40 or 44 key remote). Nothing is learned: they send
through an `infrared` entity, and every appliance here has one.

1. Add the device here as an appliance, on the emitter pointed at it. Nothing
   has to be learned; an appliance you already have works too.
2. **Settings → Devices & Services → Add Integration → LG Infrared**, or the
   one for your device. As the transmitter, pick the appliance, such as
   `infrared.tv_quarto`. As the receiver, pick
   `infrared.tv_quarto_infrared_receiver`.
3. That integration creates a device of its own, with a `media_player`, a
   `climate`, a `fan` or a `light`, and the remote's keys as buttons.

The emitter stays a property of the appliance. Changing it under **Manage
appliance → Change the emitter**, or moving the appliance to another board,
takes that integration along without touching it, because the entity ids do
not change. With nothing learned, trying an emitter replays the last command
that integration sent through the appliance.

- **The receiver needs `SetOption58 1`.** Without raw data in the frames there
  is nothing to hand over, and the log says so once.
- **Emitters other than 1 need Tasmota after 15.6.0**, or the builds at
  [self-labs.github.io/tasmota-kincony](https://self-labs.github.io/tasmota-kincony/):
  those integrations send raw timings. An older firmware makes them fail with
  an error, rather than sending through emitter 1.
- **An offline board fails the command** with an error; nothing is queued.
- **Deleting the appliance leaves that integration without a transmitter.**
  Delete its entry too.
- **An appliance on a board without `IRrecv` has no receiver entity.**

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

### Each appliance's own remote

On a board with a receiver, every appliance also gets an `event` of its own,
`event.tv_quarto_remote`, whose event types are the keys it learned: the
buttons of an appliance, or the functions of a typed one (`power`, `mute`,
each source by its name). It fires only for those keys, with the key's name as
`event_type`, so the same automation needs no template, and the automation
editor can build it with the event entity's own trigger, `event.received`:

```yaml
alias: TV power also switches the sound bar
description: The TV remote's power key presses the sound bar's.
triggers:
  - trigger: event.received
    target:
      entity_id: event.tv_quarto_remote
    options:
      event_type: power
actions:
  - action: button.press
    target:
      entity_id: button.jbl_soundbar_power
mode: single
```

`event.received` needs Home Assistant 2026.7 or newer (2026.4 to 2026.6 have it
only as a Labs preview). Use it rather than a state trigger with a condition on
`event_type`: moving the appliance to another board creates its event again
with the last key it heard, and a state trigger takes that for a key press. On
an older release, add `{{ trigger.from_state is not none }}` as a template
condition to the state trigger.

A key learned or deleted later joins or leaves the event types by itself. Raw
codes are not event types: two captures of the same raw key are never
identical, so there is nothing to compare. A key learned twice under two names
fires both. In a typed appliance, a function keeps its name over an item of a
list that has the same one: a source called `power` does not replace the power
key. An air conditioner has no such event, since its `climate` entity already
follows every frame of its remote.

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

- **Raw codes reach emitters other than 1 only on a recent Tasmota.** A remote
  whose protocol the firmware does not know is stored as raw, and Tasmota's
  plain raw form, `IRSend <freq>,<data>`, takes no channel at all. The JSON form
  with a `Channel` is native since
  [arendst/Tasmota#25062](https://github.com/arendst/Tasmota/pull/25062), merged
  on 27 September 2026 with the maintainer's follow-up
  [#25077](https://github.com/arendst/Tasmota/pull/25077): every release after
  15.6.0 has it, and so do the builds at
  [self-labs.github.io/tasmota-kincony](https://self-labs.github.io/tasmota-kincony/).
  The integration uses it: the first raw code sent to an appliance on another
  emitter asks the board, a firmware that answers `Done` keeps getting it, and
  an older one, which answers `Wrong Protocol`, gets the plain form on emitter 1
  from then on, with a warning in the log. The question is asked again whenever
  the board comes back online, since that is when its firmware may have
  changed.
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
