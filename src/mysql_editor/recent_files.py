"""Privacy-conscious, path-only recent SQL file tracking."""
from __future__ import annotations

import os
from collections.abc import Iterable

MAX_RECENT_SQL_FILES = 10


def _normalize_path(path: str | os.PathLike[str]) -> str:
    """Return a normalized absolute path without opening or reading the file."""
    raw = os.fspath(path).strip()
    if not raw:
        return ""
    expanded = os.path.expandvars(os.path.expanduser(raw))
    return os.path.normpath(os.path.abspath(expanded))


def _path_values(paths: Iterable[str | os.PathLike[str]] | str | os.PathLike[str]):
    if isinstance(paths, (str, os.PathLike)):
        return [paths]
    return list(paths or [])


def normalize_recent_sql_paths(
    paths: Iterable[str | os.PathLike[str]] | str | os.PathLike[str],
    *,
    limit: int = MAX_RECENT_SQL_FILES,
) -> list[str]:
    """Normalize, de-duplicate and bound paths in most-recent-first order."""
    try:
        requested_limit = int(limit)
    except (TypeError, ValueError, OverflowError):
        requested_limit = MAX_RECENT_SQL_FILES
    max_items = min(MAX_RECENT_SQL_FILES, max(0, requested_limit))
    if max_items == 0:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in _path_values(paths):
        if value is None:
            continue
        try:
            path = _normalize_path(value)
        except (TypeError, ValueError, OSError):
            continue
        if not path:
            continue
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(path)
        if len(normalized) >= max_items:
            break
    return normalized


def record_recent_sql_path(
    paths: Iterable[str | os.PathLike[str]] | str | os.PathLike[str],
    path: str | os.PathLike[str],
    *,
    limit: int = MAX_RECENT_SQL_FILES,
) -> list[str]:
    """Move one path to the front without reading its SQL text."""
    return normalize_recent_sql_paths([path, *_path_values(paths)], limit=limit)
