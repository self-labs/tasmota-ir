"""Tasmota's compact raw format, read and written the way the board does."""

from __future__ import annotations

from custom_components.tasmota_ir.raw_timings import (
    decode_compact,
    encode_compact,
    normalize,
)

# The example in the comment above IrRemoteSendRawStandard, in Tasmota's own
# xdrv_05_irremote_full.ino: what a board publishes with SetOption58 1.
TASMOTA_EXAMPLE = (
    "+8570-4240+550-1580C-510+565-1565F-505Fh+570gFhIdChIgFeFgFgIhFgIhF-525C"
    "-1560IhIkI-520ChFhFhFgFhIkIhIgIgIkIkI-25270A-4225IkIhIgIhIhIkFhIkFjCgIhIk"
    "IkI-500IkIhIhIkFhIgIl+545hIhIoIgIhIkFhFgIkIgFgI"
)


def test_tasmotas_own_example_reads_and_writes_back() -> None:
    timings = decode_compact(TASMOTA_EXAMPLE)
    assert len(timings) == 135
    assert timings[:6] == [8570, -4240, 550, -1580, 550, -510]
    assert encode_compact(timings) == TASMOTA_EXAMPLE


def test_pulses_and_pauses_alternate() -> None:
    timings = decode_compact(TASMOTA_EXAMPLE)
    assert all((value > 0) == (n % 2 == 0) for n, value in enumerate(timings))


def test_a_repeated_pause_is_a_lowercase_letter() -> None:
    assert encode_compact([562, -562, 562, -562]) == "+562aAa"


def test_the_27th_distinct_duration_stays_a_number() -> None:
    timings = [v for k in range(27) for v in (1000 + k, -(2000 + k))]
    timings += [1000, -2000]
    text = encode_compact(timings)
    # The table is full after 26 values; later new values are written out and
    # never enter it, while values already in it still get their letter.
    assert text.endswith("+1026-2026Ab")
    assert decode_compact(text) == timings


def test_normalize_makes_it_replayable() -> None:
    raw = [-100, 0, 500, 300, -200, -50, 70000, -80000, 400, -900]
    assert normalize(raw) == [800, -250, 65535, -65535, 400]


def test_an_unknown_letter_reads_as_nothing() -> None:
    assert decode_compact("+9000-4500Z") == []
    assert decode_compact("+9000-4500?") == []


def test_garbage_never_raises() -> None:
    """A frame the receiver mangled must not take the rest of the frame down."""
    # "ß".upper() is two characters, which ord() refuses.
    assert decode_compact("+9000-4500ß") == []
    # Python refuses to read a digit run this long as one integer.
    assert decode_compact("+" + "9" * 5000) == []


def test_commas_read_too() -> None:
    assert decode_compact("9000,4500,560,560") == [9000, -4500, 560, -560]


def test_nothing_in_nothing_out() -> None:
    assert normalize([]) == []
    assert encode_compact([]) == ""
    assert decode_compact("") == []
