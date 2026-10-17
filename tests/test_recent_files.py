"""Regression tests for path-only recent SQL file tracking."""
from pathlib import Path

import pytest

from mysql_editor.recent_files import (
    MAX_RECENT_SQL_FILES,
    normalize_recent_sql_paths,
    record_recent_sql_path,
)


def test_paths_are_absolute_deduplicated_and_recent_path_moves_to_front(tmp_path: Path):
    first = tmp_path / "first.sql"
    second = tmp_path / "second.sql"

    paths = normalize_recent_sql_paths([str(first), str(second), str(first)])
    assert paths == [str(first.resolve()), str(second.resolve())]
    assert record_recent_sql_path(paths, second) == [str(second.resolve()), str(first.resolve())]


def test_list_is_bounded_and_zero_limit_is_empty(tmp_path: Path):
    paths = [str(tmp_path / f"query-{index}.sql") for index in range(MAX_RECENT_SQL_FILES + 5)]
    assert len(normalize_recent_sql_paths(paths)) == MAX_RECENT_SQL_FILES
    assert normalize_recent_sql_paths(paths, limit=0) == []
    assert normalize_recent_sql_paths(paths, limit=-10) == []
    assert normalize_recent_sql_paths(paths, limit=1000) == paths[:MAX_RECENT_SQL_FILES]


def test_single_string_and_empty_values_are_handled(tmp_path: Path):
    file_path = tmp_path / "single.sql"
    assert normalize_recent_sql_paths(str(file_path)) == [str(file_path.resolve())]
    assert normalize_recent_sql_paths(["", None, "  "]) == []


def test_reopening_same_path_deduplicates_using_case_insensitive_key(tmp_path: Path, monkeypatch):
    file_path = tmp_path / "select.sql"
    normalized = str(file_path.resolve())
    alternate = str(file_path.parent / "." / file_path.name)
    assert normalize_recent_sql_paths([normalized, alternate]) == [normalized]


def test_recent_path_tracking_never_reads_or_deletes_file_content(tmp_path: Path):
    file_path = tmp_path / "query.sql"
    sql = "SELECT 'sensitive text';"
    file_path.write_text(sql, encoding="utf-8")
    tracked = record_recent_sql_path([], file_path)

    assert tracked == [str(file_path.resolve())]
    assert sql not in repr(tracked)
    assert file_path.read_text(encoding="utf-8") == sql

