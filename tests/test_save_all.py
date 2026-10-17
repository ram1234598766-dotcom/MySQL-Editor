"""Regression tests for Save All SQL tab behavior."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from mysql_editor.recent_files import record_recent_sql_path
from mysql_editor.ui.main_window import MainWindow


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class FakeDocument:
    def __init__(self, modified: bool):
        self.modified = modified

    def isModified(self):
        return self.modified

    def setModified(self, value: bool):
        self.modified = value


class FakeEditor:
    def __init__(self, sql: str, modified: bool = True):
        self.sql = sql
        self.doc = FakeDocument(modified)

    def toPlainText(self):
        return self.sql

    def document(self):
        return self.doc


class FakeTabs:
    def __init__(self, entries):
        self.entries = list(entries)

    def count(self):
        return len(self.entries)

    def widget(self, index):
        return self.entries[index][0]

    def tabText(self, index):
        return self.entries[index][1]

    def indexOf(self, editor):
        return next((i for i, (item, _) in enumerate(self.entries) if item is editor), -1)

    def setTabText(self, index, label):
        editor, _old_label = self.entries[index]
        self.entries[index] = (editor, label)


class FakeStatus:
    def __init__(self):
        self.message = ""

    def setText(self, value: str):
        self.message = value


class WindowHarness:
    def __init__(self, entries, paths=None):
        self.editors = FakeTabs(entries)
        self._last_saved_paths = dict(paths or {})
        self.status = FakeStatus()
        self.refresh_count = 0
        self.recent_paths = []

    def _record_recent_sql_path(self, path):
        self.recent_paths = record_recent_sql_path(self.recent_paths, path)

    def _write_editor_to_path(self, editor, path):
        return MainWindow._write_editor_to_path(self, editor, path)

    def _refresh_saved_queries(self):
        self.refresh_count += 1


def test_save_all_skips_clean_tabs_and_saves_modified_tabs_atomically(
    tmp_path: Path, app, monkeypatch,
):
    existing = tmp_path / "existing.sql"
    existing.write_text("old SQL", encoding="utf-8")
    prompted = tmp_path / "new-query.sql"
    saved_editor = FakeEditor("SELECT 1;", modified=True)
    clean_editor = FakeEditor("SELECT 'keep clean';", modified=False)
    new_editor = FakeEditor("SELECT 3;", modified=True)
    window = WindowHarness(
        [(saved_editor, "existing.sql *"), (clean_editor, "clean.sql"), (new_editor, "new-query.sql *")],
        {id(saved_editor): str(existing)},
    )
    prompts = []

    def choose_path(*args):
        prompts.append(args[2])
        return str(prompted), "SQL files (*.sql)"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose_path)
    assert MainWindow.save_all_sql_files(window) is True

    assert existing.read_text(encoding="utf-8") == "SELECT 1;"
    assert prompted.read_text(encoding="utf-8") == "SELECT 3;"
    assert prompts == ["new-query.sql"]
    assert not saved_editor.document().isModified()
    assert not new_editor.document().isModified()
    assert not clean_editor.document().isModified()
    assert window.editors.tabText(0) == "existing.sql"
    assert window.editors.tabText(2) == "new-query.sql"
    assert window.status.message == "Saved 2 modified SQL tab(s)."
    assert window.refresh_count == 2
    assert window.recent_paths == [str(prompted.resolve()), str(existing.resolve())]


def test_save_all_cancel_stops_before_touching_remaining_tabs(
    tmp_path: Path, app, monkeypatch,
):
    first_path = tmp_path / "first.sql"
    first = FakeEditor("SELECT 1;", modified=True)
    second = FakeEditor("SELECT 2;", modified=True)
    third = FakeEditor("SELECT 3;", modified=True)
    window = WindowHarness(
        [(first, "first.sql *"), (second, "second.sql *"), (third, "third.sql *")],
        {id(first): str(first_path)},
    )
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))

    assert MainWindow.save_all_sql_files(window) is False

    assert first_path.read_text(encoding="utf-8") == "SELECT 1;"
    assert not first.document().isModified()
    assert second.document().isModified()
    assert third.document().isModified()
    assert not (tmp_path / "second.sql").exists()
    assert not (tmp_path / "third.sql").exists()
    assert window.status.message == (
        "Save All cancelled after saving 1 tab(s); remaining tabs were left unchanged."
    )


def test_atomic_save_failure_keeps_existing_file_and_unsaved_state(
    tmp_path: Path, app, monkeypatch,
):
    import mysql_editor.ui.main_window as main_window_module

    destination = tmp_path / "protected.sql"
    destination.write_text("ORIGINAL CONTENT", encoding="utf-8")
    editor = FakeEditor("SELECT 'new';", modified=True)
    window = WindowHarness([(editor, "protected.sql *")], {id(editor): str(destination)})

    def fail_replace(_source, _destination):
        raise PermissionError("simulated atomic-replace failure")

    monkeypatch.setattr(main_window_module.os, "replace", fail_replace)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok)

    assert MainWindow.save_all_sql_files(window) is False
    assert destination.read_text(encoding="utf-8") == "ORIGINAL CONTENT"
    assert editor.document().isModified()
    assert window.status.message == (
        "Save All stopped after saving 0 tab(s); remaining tabs were left unchanged."
    )
    assert window.recent_paths == []
    assert not list(tmp_path.glob(".protected.sql.*.tmp"))
