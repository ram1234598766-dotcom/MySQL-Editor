"""Small, testable query outcome classifier used by the desktop status UI."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def classify_query_outcome(
    result: Mapping[str, Any],
    cancellation_requested: bool = False,
) -> str:
    """Distinguish completed, interrupted, cancelled, failed, and partial scripts."""
    if result.get("ok"):
        return "complete"
    if result.get("interrupted"):
        return "cancelled" if cancellation_requested else "interrupted"

    items = result.get("results") or []
    has_error = any(item.get("kind") == "error" for item in items)
    has_completed_result = any(item.get("kind") != "error" for item in items)
    if has_error and has_completed_result:
        return "partial_failure"
    return "failed"
