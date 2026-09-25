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

| Where            | Entity    | What it does                                                         |
| ---------------- | --------- | -------------------------------------------------------------------- |
| the board        | `remote`  | `learn_command`, `send_command` and `delete_command`, the standard services |
| the board        | `event`   | the receiver, for automating on "a key was pressed" on any remote    |
| each appliance   | `button`  | one per learned key, created the moment you learn it                 |
| each air conditioner | `climate` | modes, temperature, fan and vane, read back from your own remote |

On the integration page it looks like this:

```text
Tasmota IR
└── Hubb IR1                      the board: remote and receiver
    ├── TV Quarto                 appliance, emitter 1
    │   ├── TV Quarto power       button
    │   └── TV Quarto volume up   button
    ├── JBL Soundbar              appliance, emitter 2
    └── Ar Escritorio             air conditioner, emitter 3
        └── Ar Escritorio         climate
```

## Requirements

- Home Assistant 2025.3 or newer.
- An MQTT broker, with the Home Assistant MQTT integration set up.
- A Tasmota board with `IRsend` assigned to at least one GPIO, and `IRrecv` if
  you want to learn. The full IR driver (`USE_IR_REMOTE_FULL`) is required for
  more than one emitter and for air conditioners.
- `SetOption58 1` on the board, so remotes whose protocol the library does not
  know can still be learned, as raw.

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

## Adding an appliance and learning its keys

On **Settings → Devices & Services → Tasmota IR**, the board has two buttons:
**Add appliance** and **Add air conditioner**.

1. **Add appliance**, give it a name and the emitter pointed at it.
2. Choose **Learn a command now**, name the key (`power`, `volume up`), and press
   it once with the remote pointed at the board. The screen waits up to 30
   seconds; there is nothing to click between naming the key and pressing it.
3. **Learn another command**, or **Done**.

To learn more keys later, open the appliance's menu on the integration page and
choose **Manage appliance → Learn a command**. The appliance is the one you
opened, so there is no question of which emitter the code is for.

Three kinds of capture are refused on purpose, because storing them would create
a button that looks right and does nothing:

- **Broken frames.** Two presses in a row, or one from too far away, arrive as
  a frame the library could not finish reading: empty `Data`, zero `Bits`,
  sometimes labelled with the wrong protocol.
- **Repeat frames.** While a key is held, a NEC remote sends the real frame once
  and then a burst every 108 ms meaning "keep repeating the last one". The burst
  carries no command. Holding the key is fine: the real frame is kept and the
  repeats are ignored.
- **Air conditioner frames.** One capture from one of those remotes is one
  temperature in one mode. Learning says so and points at **Add air
  conditioner** instead.

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

**Moving to another board does not require learning anything again either.** A
learned code is the infrared signal itself, and every Tasmota board sends it the
same way. Moving keeps the appliance's key, so its buttons come back with the
same entity ids, names and areas, and dashboards and automations keep working;
only the emitter is asked again, because the other board has its own. Copying
gives the other board an appliance of its own, with new entities, for the same
kind of TV in two rooms. Air conditioners move and copy too, with their settings.

**Changing an emitter does not require learning anything again.** The code is
stored per appliance and the emitter is looked up when it is sent. The emitters
are listed with the appliances already on them, and the one you pick is tried
before it is saved: nothing on the board says where an emitter points, and an
appliance on the wrong one fails in silence.

**Deleting an appliance deletes its codes.** Use the three-dot menu of the
appliance on the integration page.

## Using the actions

Everything above also works as actions, in **Developer Tools → Actions** or in
any automation or script. `device` is the appliance name, as shown under the
board, ignoring case.

```yaml
action: remote.send_command
target:
  entity_id: remote.hubb_ir1
data:
  device: TV Quarto
  command: power
  num_repeats: 1
  delay_secs: 0.4
```

```yaml
action: remote.learn_command
target:
  entity_id: remote.hubb_ir1
data:
  device: TV Quarto
  command: power
  timeout: 30
```

```yaml
action: remote.delete_command
target:
  entity_id: remote.hubb_ir1
data:
  device: TV Quarto
  command: power
```

Learning under a name that is not an appliance yet creates the appliance, on
emitter 1, so a command learned by action never ends up somewhere the interface
does not show. If a name is wrong when sending, the error lists the appliances
the board does have.

## Air conditioners

**Add air conditioner**, give it a name and an emitter, then point its remote at
the board and press any key. The firmware decodes the whole frame, so the
vendor, the model and the supported modes come from the unit itself. There is
nothing to look up in a manual.

The result is a `climate` entity driven by Tasmota's `IRHVAC`, which assembles
every command from vendor, mode, temperature, fan speed and vane position. It
also reads back every frame the receiver hears, so the card follows the physical
remote as well as Home Assistant. Setting a temperature on a unit that is off
does not turn it on.

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

## Automating on a key press

The `event` entity fires on every decoded frame, from any remote, whether or
not its code was learned. The payload says which protocol it was, whether it
matches something already learned (`known_as`), and whether it came from an air
conditioner (`is_hvac`).

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
- The test suite, 29 tests against Home Assistant 2026.9.3: `pip install -r
  requirements_test.txt`, then `pytest`.

Any Tasmota board with an `IRsend` GPIO should work. If yours does not, open an
issue with the reply your board gives to `Gpio 255`.

## Licence

MIT. See [LICENSE](./LICENSE).
