"""Privacy-conscious recent SQL file path tracking."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

MAX_RECENT_SQL_FILES = 10


def _normalize_path(path: str | os.PathLike[str]) -> str:
    """Return a normalized absolute path without reading any file contents."""
    raw = os.fspath(path).strip()
    if not raw:
        return ""
    expanded = os.path.expandvars(os.path.expanduser(raw))
    return os.path.normpath(os.path.abspath(expanded))


def normalize_recent_sql_paths(
    paths: Iterable[str | os.PathLike[str]] | str | os.PathLike[str],
    *,
    limit: int = MAX_RECENT_SQL_FILES,
) -> list[str]:
    """Normalize and de-duplicate path metadata in most-recent-first order."""
    if isinstance(paths, (str, os.PathLike)):
        values = [paths]
    else:
        values = paths or []
    max_items = max(0, min(int(limit), 100))
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        path = _normalize_path(value)
        if not path:
            continue
        key = os.path.normcase(path).casefold()
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
    """Move the opened path to the front of the local recent-file list."""
    return normalize_recent_sql_paths([path, *_as_values(paths)], limit=limit)


def remove_recent_sql_path(
    paths: Iterable[str | os.PathLike[str]] | str | os.PathLike[str],
    path: str | os.PathLike[str],
) -> list[str]:
    """Remove every equivalent occurrence of a path from the local list."""
    target = _normalize_path(path)
    if not target:
        return normalize_recent_sql_paths(paths)
    key = os.path.normcase(target).casefold()
    return [
        item for item in normalize_recent_sql_paths(paths)
        if os.path.normcase(item).casefold() != key
    ]


def _as_values(paths):
    if isinstance(paths, (str, os.PathLike)):
        return [paths]
    return list(paths or [])
