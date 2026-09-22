# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and the versions follow **CalVer `YYYY.M.R`** (year, month with no leading zero,
revision within the month), **not** Semantic Versioning: `2026.9.1` says nothing
about compatibility, only when it was published.

## [Unreleased]

## [2026.9.8] - 2026-09-22

### Added

- A test built from a capture taken on the bench: two frames the library could not finish reading, then the real LG frame.

### Changed

- **The failure screen of the air conditioner says what is ignored** while it waits: anything that is not an air conditioner frame, broken frames included.

### Fixed

- **Reading an air conditioner remote ended on whatever the receiver heard first.** Pressing the remote of an LG produced bursts of frames decoded as `UNKNOWN`, and only then the real `LG2` ones. The wait took the first usable frame, which was one of those, and the flow reported that it had heard no air conditioner. It now waits for an air conditioner frame, or for the window to close.

## [2026.9.7] - 2026-09-22

### Added

- **Tests for the strings, rendered the way the frontend renders them**: no quoted placeholder anywhere, no placeholder in the title of a waiting screen, English identical to `strings.json`, and Portuguese with every key. Both bugs fixed below would have failed them. Also tests for the LG vane and off frames, captured from a real remote. 29 tests in all.

### Changed

- **Shorter waiting screens.** The frontend centres the text of a waiting screen, so the explanation moved to the step before it, and the screen itself only says what to press and how long it waits.
- **The model hint in the air conditioner settings** says that **Read the remote again**, pressing the vane key, sets the LG model that sends the vane by itself.

### Fixed

- **Adding an air conditioner showed a translation error as the title**, `[formatjs Error: MISSING_VALUE] The intl string context variable "name" was not provided`. The frontend renders the title of a waiting screen with no placeholders at all, and the title had `{name}`. Waiting screen titles no longer carry placeholders.
- **An LG vane key on the physical remote threw the card to Auto at 15 degrees.** LG sends the vane, the horizontal vane and the display toggle as frames of their own, and the firmware still decodes them into a full `IRHVAC`, with `Mode Auto` and `Temp 15` filled in as defaults. Those frames now move only the vane, and the display toggle is ignored. The other way round too: an LG main frame never carries the vane, so its `SwingV` default no longer resets the vane on the card.
- **An off frame from the physical remote overwrote the setpoint.** LG turns off with a fixed code whose temperature means nothing. The card now goes off and keeps the setpoint for the next time it is turned on.

## [2026.9.6] - 2026-09-22

### Added

- **Every appliance is listed under its board, with its own device.** Appliances are now config subentries: the board shows **Add appliance** and **Add air conditioner**, and each appliance appears underneath with its commands as buttons on its own device, linked to the board. An appliance with nothing learned yet shows up too.
- **Learning from the interface.** Open an appliance, choose **Manage appliance → Learn a command**, name the key and press it. The appliance is the one you opened, so the emitter is never in question, and the result says whether it worked, with **Try again**, **Learn a different command** and **Stop here** when it did not. Adding an appliance offers to learn its first key right away.
- **The vane of an air conditioner.** The climate entity gains the vertical vane (fixed, swing, and five positions) and, when enabled, the horizontal one. Both are sent in the `IRHVAC` frame and read back from the physical remote. The vertical vane is off by default for the vendors where the firmware treats it as a toggle (`COOLIX`, `MIDEA`, `SHARP_AC` and a few others), because there every command would flip it.
- **Air conditioner settings**: the model, the temperature range, the modes the unit really has, and which vanes it has. The model matters more than it looks: an LG read as `AKB75215403` never sends the vane, and the same unit set to `AKB74955603` does. The known models of each vendor are offered, and any other can be typed.
- **Rename an appliance**, keeping its buttons, codes and emitter. Codes and entities hang off a key that never changes, so a rename is only a new title.
- **Tests**, run against Home Assistant itself: adding an appliance and learning, learning from the menu and moving the emitter, a timeout, a duplicate name, learning through the action under a new name, the air conditioner flow, the vane payload, following the physical remote, the settings, the migration from 2026.9.5 and the clean-up after an appliance is deleted. A workflow runs them on every push, next to hassfest and the HACS validation.

### Changed

- **Home Assistant 2025.3 or newer is required**, for config subentries.
- **The Configure menu is gone.** Everything it did now lives on the appliance itself. An existing install is migrated on the first start: each appliance becomes a subentry with the same emitter, the learned codes move with it, and **entity ids stay the same**, so no dashboard or automation notices. Friendly names lose the board prefix, because the device already carries the appliance name: `Hubb IR1 TV Quarto power` becomes `TV Quarto power`.
- **Learning under a name that is not an appliance creates the appliance.** `remote.learn_command` still accepts any `device`, and the command no longer ends up somewhere the interface does not show.
- **Deleting an appliance deletes its codes.** Before, removing an appliance left its codes behind, unreachable.
- **Waiting for the remote is a progress screen.** It starts waiting the moment it opens, so the key is pressed with nothing to click in between, and it waits 30 seconds instead of 20.
- **Commands to an air conditioner carry `Light`**, as the remote reported it, so an LG model that sends a separate display toggle whenever `Light` is off keeps its display as it was. Vendors where `Light` is itself a toggle do not get the key.

### Fixed

- **The air conditioner screen showed `{name}` instead of the name.** The translation wrapped the placeholder in apostrophes, and the frontend formats strings as ICU messages, where an apostrophe before a brace escapes it. No placeholder is quoted any more.
- **The same screen said to press a key with the window open**, while the wait only started after **Submit**. Anyone who followed it pressed too early and got an error.
- **A key pressed from too far away could be learned as nothing.** It arrived as a recognised protocol with zero bits, seen live as `SONY` from an LG air conditioner remote, and with `SetOption58` on it still carried `RawData`, so it passed as a raw capture. Such frames are now discarded, and they no longer fire the receiver event either.

## [2026.9.5] - 2026-09-21

### Added

- **Delete a learned command from the interface**, under **Configure → Delete a learned command**. `remote.delete_command` already did this, but a service call is not where anyone looks for "delete the button I learned wrong". The command is picked from a list of everything the board knows, and its button disappears with it.

### Changed

- **The README is now the full reference** for what the integration does: where to run the actions, the three kinds of capture refused on purpose, how emitters are assigned, the known limits, and the fact that moving an appliance to another emitter needs no relearning because the emitter is looked up at send time.


## [2026.9.4] - 2026-09-21

### Fixed

- **A held key could be learned as nothing.** While a key is held, a NEC remote sends the real frame once and then a short burst every 108 ms that only means "keep repeating the last one": zero bits, a run of F's in `Data` and a three pulse `RawData`. That burst carries no command, but it passed the capture filter on the strength of its `RawData`, so a learn window that opened after the real frame would store it as raw and create a button that does nothing. Repeat frames are now discarded. Measured on an LG television: one 32 bit frame followed by eighteen of these in 2.4 seconds.


## [2026.9.3] - 2026-09-21

### Changed

- **Learning refuses an air conditioner frame** and points at the air conditioner flow instead. One capture from one of those remotes is one temperature in one mode, and replaying it is nothing like having the remote in hand. The frame it refuses is the same one the climate flow reads the vendor and the model out of.
- **Raw codes warn when the appliance is not on emitter 1.** The firmware's raw send form takes no channel at all, so it always leaves through the first emitter. That is the firmware's limit rather than a choice here, and it is now said out loud in the log instead of failing quietly.

### Fixed

- **A learned raw code could never be sent.** `CmndIrSend` in the firmware routes on whether the payload contains a brace, so anything with one goes to the JSON parser, and that parser has no protocol called `RAW`. Every capture that did not decode was therefore stored in a shape the board answers with `{"IRSend":"No Bits or Data"}`. Raw now goes as the plain `IRSend <freq>,<data>` form the firmware actually accepts, with 38 kHz recorded alongside the capture.
- **The remote's attributes went stale.** The list of appliances and commands was built when the entity was created and never rewritten, so a remote that had just learned a command still reported none. It now follows the store, the same way the buttons already did.

## [2026.9.2] - 2026-09-21

### Added

- **Brand artwork**, so the integration stops showing "icon not available" on its device and integration pages. It is the project's own icon from `home-assistant/brands` with the universal IR symbol added in the bottom right corner, and the badge is drawn in the colour read out of each source file, so the light variant stays black and the dark one stays Tasmota blue. Anyone installing it sees the icon they already know, with infrared on it.

### Fixed

- **Every entity showed as unavailable.** The last will handler flipped the availability flag without telling the entities, and an entity only reads `available` when its state is written, so it kept whatever it had when it was created. The retained LWT almost always lands after the platforms are set up, which is exactly when that goes wrong. The coordinator now dispatches on change, and it starts optimistic rather than unavailable, so a board configured without a last will at all is not stuck offline forever.


## [2026.9.1] - 2026-09-21

### Added

- **A `climate` entity per air conditioner**, built by the firmware instead of by learned codes. Tasmota's full IR driver assembles the whole frame from vendor, mode, temperature and fan speed, which replaces one stored code per temperature with one command. It sends `Channel` as well, which is what the existing Tasmota IRHVAC integration cannot do: its payload is built from fixed keys with no channel among them, so a second air conditioner leaves through the wrong emitter.
- **The air conditioner configures itself.** Adding one asks for a name and an emitter, then says "point the remote at the board". The vendor and the model come out of the decoded frame, because the firmware already knows them. Nothing is looked up in a manual.
- **The climate entity follows the physical remote.** It subscribes to the board's `RESULT` and reads back every frame the receiver hears, including the ones nobody sent from Home Assistant, so the card stays honest when somebody uses the remote in their hand.
- **Setting a temperature on a unit that is off does not turn it on.** The frame carries the whole state, so publishing one there would switch the unit on as a side effect of moving a slider.
- **An `event` entity for the receiver**, so an automation can react to "a key was pressed" on any remote without an MQTT trigger and without the code having been learned first. The payload says whether the frame belongs to something already known, and whether it is an air conditioner.

- **The `remote` entity**, with `learn_command`, `send_command` and `delete_command`. Codes live in Home Assistant's `.storage` as `{appliance: {command: code}}`, so the 255 character ceiling of an `input_text` no longer applies and a board reboot no longer decides when an entity appears.
- **A `button` entity per learned command**, created the moment the code is stored and removed when it is deleted. Learning "Living room TV" and "power" produces a `button.living_room_tv_power` with a name, an area and a device, which is what removes the last script from the setup.
- **The emitter as a property of the appliance.** It is configured once in the options flow and injected into every payload, instead of being typed at each call. This closes a failure that gives no error at all: the firmware falls back to the first emitter when a channel has no GPIO assigned, and the signal leaves through the wrong device in silence.
- **Emitter count probed, not asked.** Adding a board publishes `Gpio 255` and counts the `IRsend` entries in the reply, so the same code serves a board with one emitter and a board with eight without knowing either model.
- **Board discovery from the topic Tasmota already publishes**, so adding a board is picking it from a list rather than typing a topic.
- **Partial captures are discarded at capture time.** A truncated frame arrives with `Data` of `"0x"` and `Bits` of `0`, and storing one produces a command that is accepted, listed and reproduces nothing.
- **Entities attach to the board's existing device.** The device info declares `connections={(CONNECTION_NETWORK_MAC, mac)}`, which is what the Tasmota integration uses, so the IR entities sit next to the board's diagnostics instead of forming a second device for the same hardware.

[Unreleased]: https://github.com/self-labs/tasmota-ir/compare/v2026.9.8...HEAD
[2026.9.8]: https://github.com/self-labs/tasmota-ir/compare/v2026.9.7...v2026.9.8
[2026.9.7]: https://github.com/self-labs/tasmota-ir/compare/v2026.9.6...v2026.9.7
[2026.9.6]: https://github.com/self-labs/tasmota-ir/compare/v2026.9.5...v2026.9.6
[2026.9.5]: https://github.com/self-labs/tasmota-ir/compare/v2026.9.4...v2026.9.5
[2026.9.4]: https://github.com/self-labs/tasmota-ir/compare/v2026.9.3...v2026.9.4
[2026.9.3]: https://github.com/self-labs/tasmota-ir/compare/v2026.9.2...v2026.9.3
[2026.9.2]: https://github.com/self-labs/tasmota-ir/compare/v2026.9.1...v2026.9.2
[2026.9.1]: https://github.com/self-labs/tasmota-ir/releases/tag/v2026.9.1
