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


def normalize_result_row_height(value: Any) -> int:
    """Accept supported density heights only; malformed settings fall back to 28."""
    return _normalize_choice(value, (24, 28, 36), 28)
