"""What counts as a code worth keeping."""

from __future__ import annotations

from custom_components.tasmota_ir.coordinator import extract_code, is_usable_code

from .conftest import NEC_POWER


def test_a_decoded_frame_is_usable() -> None:
    """The ordinary case: a protocol, bits and data."""
    assert is_usable_code(NEC_POWER)
    assert extract_code(NEC_POWER) == NEC_POWER


def test_a_nec_repeat_burst_is_not() -> None:
    """Holding a key sends bursts that only mean "keep going"."""
    assert not is_usable_code(
        {
            "Protocol": "NEC",
            "Bits": 0,
            "Data": "0xFFFFFFFFFFFFFFFF",
            "Repeat": 1,
            "RawData": "+8950-2200+550",
        }
    )


def test_a_named_frame_with_no_bits_is_not() -> None:
    """Seen live: an LG air conditioner key, too far away, arrived as SONY."""
    assert not is_usable_code(
        {"Protocol": "SONY", "Bits": 0, "Data": "0x", "RawData": "+2400-600+1200"}
    )


def test_an_unknown_protocol_with_raw_data_is() -> None:
    """A remote the library does not know is still learnable, as raw."""
    frame = {
        "Protocol": "UNKNOWN",
        "Bits": 0,
        "Data": "0x",
        "RawData": "+9000-4500+560",
    }
    assert is_usable_code(frame)
    assert extract_code(frame)["Protocol"] == "RAW"
