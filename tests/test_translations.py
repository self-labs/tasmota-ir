"""The strings the frontend renders, checked the way the frontend renders them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

BASE = Path(__file__).parent.parent / "custom_components" / "tasmota_ir"
FILES = {
    "strings": BASE / "strings.json",
    "en": BASE / "translations" / "en.json",
    "pt-BR": BASE / "translations" / "pt-BR.json",
}
# Steps shown with a spinner. The frontend renders their title with no
# placeholders at all, so a {name} there breaks with MISSING_VALUE.
PROGRESS_STEPS = {"appliance": ["learn_wait"], "climate": ["read_remote"]}


def _load(name: str) -> dict[str, Any]:
    return json.loads(FILES[name].read_text(encoding="utf-8"))


def _texts(node: Any, path: str = ""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _texts(value, f"{path}.{key}" if path else key)
    elif isinstance(node, str):
        yield path, node


def _keys(node: Any) -> set[str]:
    return {path for path, _ in _texts(node)}


def test_english_is_the_source() -> None:
    """translations/en.json is what Home Assistant loads; it must match."""
    assert _load("strings") == _load("en")


def test_portuguese_has_every_key() -> None:
    assert _keys(_load("pt-BR")) == _keys(_load("en"))


@pytest.mark.parametrize("name", list(FILES))
def test_no_placeholder_is_quoted(name: str) -> None:
    """In ICU formatting, an apostrophe before a brace escapes the placeholder."""
    for path, text in _texts(_load(name)):
        assert "'{" not in text, path


@pytest.mark.parametrize("name", list(FILES))
def test_progress_titles_have_no_placeholders(name: str) -> None:
    subentries = _load(name)["config_subentries"]
    for kind, steps in PROGRESS_STEPS.items():
        for step in steps:
            assert "{" not in subentries[kind]["step"][step]["title"], (kind, step)


@pytest.mark.parametrize("name", list(FILES))
def test_no_long_dashes(name: str) -> None:
    for path, text in _texts(_load(name)):
        assert "—" not in text and "–" not in text, path
