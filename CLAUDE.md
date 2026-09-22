# Tasmota IR: repository conventions (for AI agents)

A Home Assistant custom integration, distributed through HACS, that turns any
Tasmota board with infrared into native entities. This is Python application
code, not documentation, so the usual engineering rules apply: it has to import
cleanly, pass lint, and not break an existing install on upgrade.

## What this integration is, in one paragraph

One MQTT conversation per board, owned by `coordinator.py`. Every platform talks
through it, so no entity builds a topic or picks an emitter by itself. Each
appliance is a **config subentry** of its board, of type `appliance` or
`climate`, with its own device linked to the board by `via_device`. Learned
codes live in Home Assistant's `.storage`, keyed `{appliance key: {command:
code}}`, where the key is the subentry `unique_id`. The emitter is a property of
the appliance, set in its subentry and injected on publish, never passed as a
service parameter.

## Layout

```text
custom_components/tasmota_ir/
├── __init__.py       setup and teardown of a config entry
├── const.py          every string and number that is not local to one file
├── coordinator.py    the MQTT link, the stored codes, the appliance mapping
├── entity.py         the base class, and the board and appliance devices
├── config_flow.py    add a board; the appliance and climate subentry flows
├── remote.py         learn, send, delete
├── button.py         one entity per learned command
├── climate.py        one entity per air conditioner
└── event.py          the receiver as an event source
hacs.json             HACS metadata
tests/                pytest against Home Assistant, via the custom component harness
.github/workflows/    tests, hassfest and the HACS validation on every push
```

## Rules that are not obvious

- **Devices are registered in `__init__.py`, before the platforms.** The board
  device carries `identifiers={(DOMAIN, entry_id)}` and the MAC in
  `connections`, which matches it to the Tasmota device (merged on older Home
  Assistant, linked on 2026.9 and newer). Each appliance device carries
  `identifiers={(DOMAIN, key)}`, its `config_subentry_id` and the board as
  `via_device`. Entities only point at them by identifier. Registering them up
  front is what lets an appliance with nothing learned still show up.
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
- **Everything hangs off the appliance key, never off its name.** The button id
  is `{key}_{command}`, the climate id `{key}_climate`, the device identifier
  `(DOMAIN, key)`, and the store is keyed by it. A rename is only a new subentry
  title. Version 1 keyed everything by name; `async_migrate_entry` moves an old
  install over and keeps the entity ids.
- **No placeholder in a translation is ever wrapped in apostrophes.** The
  frontend formats strings as ICU messages, where `'{name}'` escapes the
  placeholder and shows `{name}` literally.
- **A step that waits for the remote is a progress step.** It starts waiting the
  moment it opens. A form that only waits after Submit tells the user to press
  a key that nobody is listening for yet.

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

## Tests

`pip install -r requirements_test.txt`, then `pytest`. The harness pins the Home
Assistant release it tests against. It does not run on Windows as is: Home
Assistant imports `fcntl` and `resource`, and the harness blocks the loopback
socket the Windows event loop needs. Run it in CI, WSL or a Linux box, or stub
those two modules in a throwaway venv.

## Commits

- Conventional Commits, in English, scope is the module: `feat(remote): ...`,
  `fix(coordinator): ...`, `docs(readme): ...`.
- **Never commit or push without the maintainer explicitly asking.** Leave the
  changes in the working tree and report that they are ready.
- The default branch is `master`.

## Changelog

`CHANGELOG.md` follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
with **CalVer `YYYY.M.R`** versions: year, month with no leading zero, and the
revision within that month, restarting at 1 whenever the month changes. The
version says when it was published, not what it promises about compatibility.

A notable change lands in `[Unreleased]` before the task is reported as done. `manifest.json` carries the same version as the release tag.

## Related repositories

- [self-labs/homeassistant](https://github.com/self-labs/homeassistant) documents
  the boards this integration was built against, above all
  `docs/kincony-ag8.md`, which has the Tasmota template, the pin map and the
  gotchas the firmware side hides.
- [cateim/Tasmota](https://github.com/cateim/Tasmota), branch `tasmota-kincony`,
  carries the firmware builds for those boards.
