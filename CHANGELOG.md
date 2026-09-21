# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and the versions follow **CalVer `YYYY.M.R`** (year, month with no leading zero,
revision within the month), **not** Semantic Versioning: `2026.9.1` says nothing
about compatibility, only when it was published.

## [Unreleased]

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

[Unreleased]: https://github.com/self-labs/tasmota-ir/compare/v2026.9.2...HEAD
[2026.9.2]: https://github.com/self-labs/tasmota-ir/compare/v2026.9.1...v2026.9.2
[2026.9.1]: https://github.com/self-labs/tasmota-ir/releases/tag/v2026.9.1
