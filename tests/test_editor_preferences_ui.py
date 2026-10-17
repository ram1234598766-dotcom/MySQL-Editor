"""Main-window integration coverage for persisted SQL editor display preferences."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from mysql_editor.storage import LocalRepository
from mysql_editor.ui.main_window import MainWindow
from mysql_editor.ui.editor import SqlEditor


_APP = QApplication.instance() or QApplication([])


class SettingsStub:
    def __init__(self):
        self.values = {}

    def value(self, key, defaultValue=None, type=None):
        result = self.values.get(key, defaultValue)
        if type is not None:
            try:
                return type(result)
            except (TypeError, ValueError):
                return defaultValue
        return result

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        """Match QSettings' close-time synchronization API for this in-memory test double."""
        pass


class StubWorker(QObject):
    completed = Signal(str, str, object)
    activity = Signal(str)

    def __init__(self):
        super().__init__()
        self.submissions = []

    def submit(self, action, payload=None, task_id=None):
        self.submissions.append((action, payload or {}, task_id))
        return task_id or f"editor-preferences-{len(self.submissions)}"

    def cancel_current_query(self):
        pass

    def shutdown(self):
        pass

    def wait(self, _milliseconds=5000):
        return True


def _editor_menu(window):
    settings_action = next(
        action for action in window.menuBar().actions()
        if action.menu() and action.menu().title().replace("&", "") == "Settings"
    )
    return next(
        action.menu() for action in settings_action.menu().actions()
        if action.menu() and action.menu().title() == "Editor"
    )


def test_editor_view_preferences_persist_and_apply_to_current_and_new_tabs(tmp_path, monkeypatch):
    settings = SettingsStub()
    monkeypatch.setattr("mysql_editor.ui.main_window.QSettings", lambda: settings)
    repository = LocalRepository(tmp_path / "editor-preferences.sqlite3")
    worker = StubWorker()
    profile = {
        "id": "profile-a", "name": "Development", "host": "localhost",
        "port": 3306, "username": "reader",
    }
    config = {
        "host": "localhost", "port": 3306, "username": "reader",
        "default_schema": "app_db", "tls_mode": "Automatic TLS",
    }
    window = MainWindow(worker, repository, object(), profile, config, {"database": "app_db"})
    try:
        editor_menu = _editor_menu(window)
        line_action = next(
            action for action in editor_menu.actions()
            if action.text() == "Show line numbers"
        )
        highlight_action = next(
            action for action in editor_menu.actions()
            if action.text() == "Highlight current line"
        )

        for control in (
            window.tour_button,
            window.format_button,
            window.explain_button,
            window.run_selection_button,
            window.run_button,
        ):
            assert control.accessibleName().strip(), (
                f"{control.text()!r} must expose a screen-reader name"
            )

        current = window._current_editor()
        assert isinstance(current, SqlEditor)
        assert line_action.isChecked()
        assert highlight_action.isChecked()

        line_action.trigger()
        highlight_action.trigger()

        assert settings.values["ui/showLineNumbers"] is False
        assert settings.values["ui/currentLineHighlight"] is False
        assert current.line_number_area_width() == 0
        assert current.line_number_area.isHidden()

        sql = "SELECT (1)"
        current.setPlainText(sql)
        cursor = current.textCursor()
        cursor.setPosition(sql.index("(") + 1)
        current.setTextCursor(cursor)
        assert len(current.extraSelections()) == 2  # Bracket feedback remains active.

        window.new_query_tab()
        new_editor = window._current_editor()
        assert isinstance(new_editor, SqlEditor)
        assert new_editor.line_number_area_width() == 0
        assert new_editor.line_number_area.isHidden()
        assert len(new_editor.extraSelections()) == 0
    finally:
        window.close()
        repository.close()
        _APP.processEvents()



def test_theme_switch_preserves_tabs_editor_selection_results_filter_and_splitter(
    tmp_path, monkeypatch,
):
    settings = SettingsStub()
    monkeypatch.setattr("mysql_editor.ui.main_window.QSettings", lambda: settings)
    repository = LocalRepository(tmp_path / "theme-preservation.sqlite3")
    worker = StubWorker()
    profile = {
        "id": "profile-theme", "name": "Development", "host": "localhost",
        "port": 3306, "username": "reader",
    }
    config = {
        "host": "localhost", "port": 3306, "username": "reader",
        "default_schema": "app_db", "tls_mode": "Automatic TLS",
    }
    window = MainWindow(
        worker, repository, object(), profile, config, {"database": "app_db"}
    )
    original_stylesheet = _APP.styleSheet()
    try:
        window.resize(1280, 820)
        window.show()
        _APP.processEvents()

        source = "SELECT city FROM cities;"
        first_editor = window._current_editor()
        assert isinstance(first_editor, SqlEditor)
        first_editor.setPlainText(source)
        start = source.index("city")
        cursor = first_editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(start + len("city"), cursor.MoveMode.KeepAnchor)
        first_editor.setTextCursor(cursor)
        window.new_query_tab("SELECT 1;")
        window.editors.setCurrentIndex(0)
        _APP.processEvents()

        window.result_model.update(
            ["City"], [["London"], ["Paris"], ["Lonely"]]
        )
        window.result_filter.setText("lon")
        _APP.processEvents()

        assert window.editors.count() == 2
        assert window.editors.currentIndex() == 0
        assert first_editor.textCursor().selectedText() == "city"
        assert window.result_filter.text() == "lon"
        assert window.result_proxy.rowCount() == 2

        before_buffer = first_editor.toPlainText()
        before_cursor = first_editor.textCursor().position()
        before_selection = (
            first_editor.textCursor().selectionStart(),
            first_editor.textCursor().selectionEnd(),
            first_editor.textCursor().selectedText(),
        )
        before_tab = window.editors.currentIndex()
        before_splitter = window.main_split.saveState()
        before_connection = (
            window.connection_badge.text(),
            window.connection_details.text(),
        )
        before_rows = list(window.result_model.rows)

        window._set_theme("light")
        _APP.processEvents()

        assert settings.values["ui/theme"] == "light"
        assert window.editors.count() == 2
        assert window.editors.currentIndex() == before_tab
        assert first_editor.toPlainText() == before_buffer
        assert first_editor.textCursor().position() == before_cursor
        assert (
            first_editor.textCursor().selectionStart(),
            first_editor.textCursor().selectionEnd(),
            first_editor.textCursor().selectedText(),
        ) == before_selection
        assert window.result_filter.text() == "lon"
        assert window.result_proxy.rowCount() == 2
        assert window.result_model.rows == before_rows
        assert window.main_split.saveState() == before_splitter
        assert (
            window.connection_badge.text(),
            window.connection_details.text(),
        ) == before_connection
    finally:
        window.close()
        repository.close()
        _APP.setStyleSheet(original_stylesheet)
        _APP.processEvents()
