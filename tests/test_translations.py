"""Tests for translation catalog consistency."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TRANSLATION_ROOT = Path(__file__).parents[1] / "custom_components" / "homely"


def _shape(value: Any) -> Any:
    """Return the nested key and value-type structure of a translation catalog."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    return type(value)


def _load_json(path: Path) -> dict[str, Any]:
    """Load a translation catalog."""
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def test_translation_catalogs_match_strings_structure():
    """English and Norwegian catalogs should cover every strings.json key."""
    source = _load_json(TRANSLATION_ROOT / "strings.json")
    source_shape = _shape(source)

    for language in ("en", "nb"):
        translated = _load_json(TRANSLATION_ROOT / "translations" / f"{language}.json")
        assert _shape(translated) == source_shape
