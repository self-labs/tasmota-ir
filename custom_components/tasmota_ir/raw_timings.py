"""Tasmota's compact raw format, and the signed timings Home Assistant uses.

Home Assistant hands infrared around as a list of microseconds, positive for a
pulse and negative for a pause. Tasmota publishes and accepts the same thing as
text, ``+8570-4240+550-1580C-510...``: a number for each new duration, and a
letter for one it has already seen, uppercase in a pulse and lowercase in a
pause. The letters index a table of the first 26 distinct durations, filled in
the order they appear, which is ``IRRawTable`` in ``xdrv_05_irremote_full.ino``.
Both sides build the table the same way, so no table is ever sent.
"""

from __future__ import annotations

# Tasmota keeps durations in uint16_t, and its table has one slot per letter.
MAX_DURATION = 0xFFFF
TABLE_SIZE = 26
# 65535 has five digits; one more leaves room for a board that writes more.
MAX_DIGITS = 6


def normalize(timings: list[int]) -> list[int]:
    """Make a timing list something Tasmota can replay as it is.

    Zeros go, neighbours of the same sign are added together so pulse and pause
    alternate, a pause at the start is dropped (the emitter starts idle), a
    pause at the end is dropped (nothing follows it), and every duration is
    capped at 65535, the most a uint16_t holds.
    """
    merged: list[int] = []
    for value in timings:
        if value == 0:
            continue
        if merged and (merged[-1] > 0) == (value > 0):
            merged[-1] += value
        else:
            merged.append(value)
    while merged and merged[0] < 0:
        merged.pop(0)
    while merged and merged[-1] < 0:
        merged.pop()
    return [max(-MAX_DURATION, min(MAX_DURATION, value)) for value in merged]


def encode_compact(timings: list[int]) -> str:
    """Write alternating pulses and pauses the way Tasmota reads them.

    ``timings`` must alternate and start with a pulse, which is what
    ``normalize`` returns. The sign survives in the text, as ``+``, ``-`` or the
    letter's case, so the result is also what the board itself would publish
    for the same frame.
    """
    table: list[int] = []
    parts: list[str] = []
    for value in timings:
        duration = abs(value)
        pulse = value > 0
        if duration in table:
            letter = chr(ord("A") + table.index(duration))
            parts.append(letter if pulse else letter.lower())
            continue
        if len(table) < TABLE_SIZE:
            table.append(duration)
        parts.append(f"{'+' if pulse else '-'}{duration}")
    return "".join(parts)


def decode_compact(raw: str) -> list[int]:
    """Read Tasmota's compact raw format back into signed timings.

    The signs in the text are not trusted: pulse and pause alternate, starting
    with a pulse, which is how the receiver writes them. Commas are accepted,
    so the plain comma separated form reads too. Anything unreadable gives an
    empty list, never a partial one.
    """
    table: list[int] = []
    durations: list[int] = []
    i = 0
    while i < len(raw):
        char = raw[i]
        if char in "+-,":
            i += 1
            continue
        if "0" <= char <= "9":
            j = i
            while j < len(raw) and "0" <= raw[j] <= "9":
                j += 1
            # No duration Tasmota writes has more digits than this; a longer
            # run is a mangled frame, and int() would refuse a very long one.
            if j - i > MAX_DIGITS:
                return []
            value = int(raw[i:j])
            if value and len(table) < TABLE_SIZE:
                table.append(value)
            durations.append(value)
            i = j
            continue
        # Only A to Z name a slot. Anything else, "ß" included, whose upper
        # case is two characters, means the frame arrived mangled.
        if not ("A" <= char <= "Z" or "a" <= char <= "z"):
            return []
        index = ord(char.upper()) - ord("A")
        if index >= len(table):
            return []
        durations.append(table[index])
        i += 1
    return [value if n % 2 == 0 else -value for n, value in enumerate(durations)]
