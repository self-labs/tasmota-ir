# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **The `remote` entity**, with `learn_command`, `send_command` and `delete_command`. Codes live in Home Assistant's `.storage` as `{appliance: {command: code}}`, so the 255 character ceiling of an `input_text` no longer applies and a board reboot no longer decides when an entity appears.
- **A `button` entity per learned command**, created the moment the code is stored and removed when it is deleted. Learning "Living room TV" and "power" produces a `button.living_room_tv_power` with a name, an area and a device, which is what removes the last script from the setup.
- **The emitter as a property of the appliance.** It is configured once in the options flow and injected into every payload, instead of being typed at each call. This closes a failure that gives no error at all: the firmware falls back to the first emitter when a channel has no GPIO assigned, and the signal leaves through the wrong device in silence.
- **Emitter count probed, not asked.** Adding a board publishes `Gpio 255` and counts the `IRsend` entries in the reply, so the same code serves a board with one emitter and a board with eight without knowing either model.
- **Board discovery from the topic Tasmota already publishes**, so adding a board is picking it from a list rather than typing a topic.
- **Partial captures are discarded at capture time.** A truncated frame arrives with `Data` of `"0x"` and `Bits` of `0`, and storing one produces a command that is accepted, listed and reproduces nothing.
- **Entities attach to the board's existing device.** The device info declares `connections={(CONNECTION_NETWORK_MAC, mac)}`, which is what the Tasmota integration uses, so the IR entities sit next to the board's diagnostics instead of forming a second device for the same hardware.

[Unreleased]: https://github.com/self-labs/tasmota-ir/compare/v0.1.0...HEAD
