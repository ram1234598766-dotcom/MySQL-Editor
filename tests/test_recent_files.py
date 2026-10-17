"""Tests for local, path-only recent SQL file tracking."""
from pathlib import Path

from mysql_editor.recent_files import (
    MAX_RECENT_SQL_FILES,
    normalize_recent_sql_paths,
    record_recent_sql_path,
    remove_recent_sql_path,
)


def test_recent_paths_are_absolute_deduplicated_and_most_recent_first(tmp_path: Path):
    first = tmp_path / "first.sql"
    second = tmp_path / "second.sql"

    paths = normalize_recent_sql_paths([str(first), str(second), str(first)])

    assert paths == [str(first.resolve()), str(second.resolve())]


def test_recording_an_open_file_moves_it_to_front_without_duplicates(tmp_path: Path):
    first = tmp_path / "first.sql"
    second = tmp_path / "second.sql"

    paths = record_recent_sql_path([str(first), str(second)], str(first))

    assert paths == [str(first.resolve()), str(second.resolve())]


def test_recent_path_list_is_bounded(tmp_path: Path):
    paths = [tmp_path / f"query-{index}.sql" for index in range(MAX_RECENT_SQL_FILES + 5)]

    result = normalize_recent_sql_paths([str(path) for path in paths])

    assert len(result) == MAX_RECENT_SQL_FILES
    assert result[0] == str(paths[0].resolve())
    assert result[-1] == str(paths[MAX_RECENT_SQL_FILES - 1].resolve())


def test_remove_recent_path_does_not_delete_file(tmp_path: Path):
    first = tmp_path / "first.sql"
    second = tmp_path / "second.sql"
    first.write_text("SELECT 1;", encoding="utf-8")
    second.write_text("SELECT 2;", encoding="utf-8")

    remaining = remove_recent_sql_path([str(first), str(second)], str(first))

    assert remaining == [str(second.resolve())]
    assert first.read_text(encoding="utf-8") == "SELECT 1;"
    assert second.read_text(encoding="utf-8") == "SELECT 2;"


def test_empty_values_and_single_string_settings_are_supported(tmp_path: Path):
    path = tmp_path / "single.sql"

    assert normalize_recent_sql_paths(["", None]) == []
    assert normalize_recent_sql_paths(str(path)) == [str(path.resolve())]
    assert normalize_recent_sql_paths([str(path)], limit=0) == []
