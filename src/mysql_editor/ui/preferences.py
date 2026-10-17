"""Validation helpers for persisted editor and result-grid preferences."""
from __future__ import annotations

from typing import Any


def _normalize_choice(value: Any, allowed: tuple[int, ...], default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if isinstance(value, float) and value != parsed:
        return default
    return parsed if parsed in allowed else default


def normalize_tab_width(value: Any) -> int:
    """Accept supported indentation widths only; malformed settings fall back to 4."""
    return _normalize_choice(value, (2, 4, 8), 4)


def normalize_boolean_preference(value: Any, default: bool) -> bool:
    """Normalize persisted boolean settings without treating arbitrary strings as true."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(default)


def normalize_result_row_height(value: Any) -> int:
    """Accept supported density heights only; malformed settings fall back to 28."""
    return _normalize_choice(value, (24, 28, 36), 28)


DEFAULT_EDITOR_FONT_FAMILY = "Cascadia Code"

def normalize_editor_font_family(value: Any) -> str:
    """Validate a persisted editor font name and fall back to the SQL default."""
    if not isinstance(value, str) or any(ord(character) < 32 for character in value):
        return DEFAULT_EDITOR_FONT_FAMILY
    family = " ".join(value.split())
    if not family or len(family) > 128:
        return DEFAULT_EDITOR_FONT_FAMILY
    return family
