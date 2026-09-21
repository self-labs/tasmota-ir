# Tasmota IR: repository conventions (for AI agents)

A Home Assistant custom integration, distributed through HACS, that turns any
Tasmota board with infrared into native entities. This is Python application
code, not documentation, so the usual engineering rules apply: it has to import
cleanly, pass lint, and not break an existing install on upgrade.

## What this integration is, in one paragraph

One MQTT conversation per board, owned by `coordinator.py`. Every platform talks
through it, so no entity builds a topic or picks an emitter by itself. Learned
codes live in Home Assistant's `.storage`, keyed `{appliance: {command: code}}`,
the same shape Broadlink uses. The emitter is a property of the appliance, set
once in the options flow and injected on publish, never passed as a service
parameter.

## Layout

```text
custom_components/tasmota_ir/
├── __init__.py       setup and teardown of a config entry
├── const.py          every string and number that is not local to one file
├── coordinator.py    the MQTT link, the stored codes, the appliance mapping
├── entity.py         the base class, and the device merge by MAC
├── config_flow.py    add a board, manage appliances
├── remote.py         learn, send, delete
├── button.py         one entity per learned command
├── climate.py        one entity per air conditioner
└── event.py          the receiver as an event source
hacs.json             HACS metadata
```

## Rules that are not obvious

- **Never create a second device for a board.** `entity.py` declares
  `connections={(CONNECTION_NETWORK_MAC, mac)}`, which is what the Tasmota
  integration uses, so Home Assistant attaches this config entry to the device
  the user already has. Adding `identifiers` would split it in two.
- **Discard partial captures.** A truncated frame arrives with `Data` of `"0x"`
  and `Bits` of `0`. Storing one produces a command that is accepted, saved,
  listed in the interface and does nothing. `is_usable_code` is the gate and it
  runs before anything is offered to a waiter.
- **Respect the board's MQTT buffer.** `MAX_PACKET_SIZE` defaults to 1200 bytes
  and has to carry the topic too. A `RawData` capture passes that easily, so it
  is rejected at capture time with a clear message rather than failing silently
  at send time.
- **The channel is never a service parameter.** If a future feature seems to
  need one, the appliance mapping is the place to change, not the signature.
- **Unique ids must survive a rename of the entity but not of the code.** The
  button id is `{entry_id}_{appliance}_{command}`. Renaming an appliance has to
  migrate both the storage keys and the entity registry, in the options flow.

## Style

- Python 3.12 or newer, `from __future__ import annotations` at the top of every
  module, full type hints, `async` everywhere that touches IO.
- Docstrings on every module, class and public function. They say **why**, not
  what the next line already says.
- User-facing strings are in English, and every one of them belongs in
  `strings.json` with a `pt-BR` translation. Error messages say what to do next,
  not just what failed.
- **Never use em dashes or en dashes**, in code, comments, docstrings, commit
  messages or documentation. A comma, a colon, parentheses or a new sentence.

## Commits

- Conventional Commits, in English, scope is the module: `feat(remote): ...`,
  `fix(coordinator): ...`, `docs(readme): ...`.
- **Never commit or push without the maintainer explicitly asking.** Leave the
  changes in the working tree and report that they are ready.
- The default branch is `master`.

## Changelog

`CHANGELOG.md` follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
with semantic versions, because HACS reads releases and users upgrade across
them. A notable change lands in `[Unreleased]` before the task is reported as
done. `manifest.json` carries the same version as the release tag.

## Related repositories

- [self-labs/homeassistant](https://github.com/self-labs/homeassistant) documents
  the boards this integration was built against, above all
  `docs/kincony-ag8.md`, which has the Tasmota template, the pin map and the
  gotchas the firmware side hides.
- [cateim/Tasmota](https://github.com/cateim/Tasmota), branch `tasmota-kincony`,
  carries the firmware builds for those boards.
