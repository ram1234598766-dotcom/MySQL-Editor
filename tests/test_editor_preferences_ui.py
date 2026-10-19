"""Main-window integration coverage for persisted SQL editor display preferences."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
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

def test_main_workspace_controls_expose_accessible_names(tmp_path, monkeypatch):
    settings = SettingsStub()
    monkeypatch.setattr("mysql_editor.ui.main_window.QSettings", lambda: settings)
    repository = LocalRepository(tmp_path / "workspace-accessibility.sqlite3")
    worker = StubWorker()
    profile = {
        "id": "profile-a", "name": "Development", "host": "localhost",
        "port": 3306, "username": "reader",
    }
    config = {
        "host": "localhost", "port": 3306, "username": "reader",
        "default_schema": "app_db", "tls_mode": "Automatic TLS",
    }
    window = MainWindow(
        worker, repository, object(), profile, config, {"database": "app_db"}
    )
    controls = (
        *window.workspace_nav_buttons.values(),
        window.connection_badge,
        window.tour_button,
        window.connect_button,
        window.disconnect_button,
        window.format_button,
        window.explain_button,
        window.run_selection_button,
        window.run_button,
        window.editors,
        window.result_picker,
        window.result_filter,
        window.query_meta,
        window.stop_button,
        window.commit_button,
        window.rollback_button,
        window.fetch_more_button,
        window.export_button,
        window.result_grid,
        window.result_message,
        window.export_feedback,
        window.inspector_tabs,
        window.schema_state_label,
        window.schema_refresh_button,
        window.schema_tree,
        window.history_list,
        window.saved_list,
        window.status,
        window.editor_position,
    )
    try:
        missing = [
            type(control).__name__
            for control in controls
            if not control.accessibleName().strip()
        ]
        assert not missing, (
            "Interactive workspace controls and status regions need accessible names: "
            f"{missing}"
        )
    finally:
        window.close()
        worker.shutdown()
        repository.close()
        _APP.processEvents()



def test_workspace_navigation_and_sql_actions_support_keyboard_focus(
    tmp_path, monkeypatch,
):
    settings = SettingsStub()
    monkeypatch.setattr("mysql_editor.ui.main_window.QSettings", lambda: settings)
    repository = LocalRepository(tmp_path / "workspace-keyboard-focus.sqlite3")
    worker = StubWorker()
    profile = {
        "id": "profile-keyboard", "name": "Development", "host": "localhost",
        "port": 3306, "username": "reader",
    }
    config = {
        "host": "localhost", "port": 3306, "username": "reader",
        "default_schema": "app_db", "tls_mode": "Automatic TLS",
    }
    window = MainWindow(
        worker, repository, object(), profile, config, {"database": "app_db"}
    )
    try:
        window.resize(1280, 820)
        window.show()
        _APP.processEvents()

        # Every workspace destination must participate in keyboard focus navigation.
        nav_buttons = tuple(window.workspace_nav_buttons.values())
        assert nav_buttons
        for button in nav_buttons:
            assert button.accessibleName().strip()
            assert button.focusPolicy() & Qt.FocusPolicy.TabFocus, (
                f"{button.accessibleName()!r} must be reachable with Tab"
            )
            button.setFocus(Qt.FocusReason.OtherFocusReason)
            _APP.processEvents()
            assert _APP.focusWidget() is button, (
                f"{button.accessibleName()!r} must accept keyboard focus"
            )

        # Also verify that Tab moves between destinations, not just into one of them.
        first_nav = nav_buttons[0]
        first_nav.setFocus(Qt.FocusReason.OtherFocusReason)
        _APP.processEvents()
        for current, expected in zip(nav_buttons, nav_buttons[1:], strict=False):
            QTest.keyClick(current, Qt.Key.Key_Tab)
            _APP.processEvents()
            assert _APP.focusWidget() is expected, (
                f"Tab from {current.accessibleName()!r} should focus "
                f"{expected.accessibleName()!r}"
            )

        # Verify actual Tab traversal within the adjacent SQL action toolbar.
        editor = window._current_editor()
        editor.setPlainText("SELECT 1;")
        _APP.processEvents()
        actions = (
            window.format_button,
            window.explain_button,
            window.run_selection_button,
            window.run_button,
        )
        visible_enabled = [
            control for control in actions
            if control.isVisible() and control.isEnabled()
        ]
        assert len(visible_enabled) >= 2, "At least two SQL actions should be keyboard reachable"
        first = visible_enabled[0]
        first.setFocus(Qt.FocusReason.OtherFocusReason)
        _APP.processEvents()
        assert _APP.focusWidget() is first
        for current, expected in zip(visible_enabled, visible_enabled[1:], strict=False):
            QTest.keyClick(current, Qt.Key.Key_Tab)
            _APP.processEvents()
            assert _APP.focusWidget() is expected, (
                f"Tab from {current.accessibleName()!r} should focus "
                f"{expected.accessibleName()!r}"
            )
    finally:
        window.close()
        worker.shutdown()
        repository.close()
        _APP.processEvents()

def test_update_checks_are_opt_in_and_disabled_state_never_starts_network_access(
    tmp_path, monkeypatch,
):
    settings = SettingsStub()
    monkeypatch.setattr("mysql_editor.ui.main_window.QSettings", lambda: settings)

    class ForbiddenUpdateThread:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("update-check thread must not start unless explicitly enabled")

    monkeypatch.setattr("mysql_editor.ui.main_window.UpdateCheckThread", ForbiddenUpdateThread)
    repository = LocalRepository(tmp_path / "updates-opt-in.sqlite3")
    worker = StubWorker()
    profile = {
        "id": "profile-updates",
        "name": "Development",
        "host": "localhost",
        "port": 3306,
        "username": "reader",
    }
    config = {
        "host": "localhost",
        "port": 3306,
        "username": "reader",
        "default_schema": "app_db",
        "tls_mode": "Automatic TLS",
    }
    window = MainWindow(worker, repository, object(), profile, config, {"database": "app_db"})
    try:
        assert window.update_checks_action.isCheckable()
        assert not window.update_checks_action.isChecked()
        assert settings.values.get("updates/automaticCheck", False) is False

        window._maybe_check_for_updates_on_startup()
        window._run_update_check(manual=False)
        assert window._update_check_thread is None

        window.update_checks_action.setChecked(True)
        assert settings.values["updates/automaticCheck"] is True
        # Enabling only opts in for future startup checks; it does not fire an
        # immediate request without an explicit Help > Check for updates action.
        assert window._update_check_thread is None

        window.update_checks_action.setChecked(False)
        assert settings.values["updates/automaticCheck"] is False
        assert "Update checks disabled" in window.status.text()
        window._maybe_check_for_updates_on_startup()
        assert window._update_check_thread is None
    finally:
        window.close()
        repository.close()
        _APP.processEvents()

def test_manual_update_check_is_explicit_opt_in_without_enabling_startup_checks(
    tmp_path, monkeypatch,
):
    settings = SettingsStub()
    monkeypatch.setattr("mysql_editor.ui.main_window.QSettings", lambda: settings)

    class SignalStub:
        def connect(self, *_args, **_kwargs):
            pass

    class FakeUpdateThread:
        def __init__(self, *_args, **_kwargs):
            self.result_ready = SignalStub()
            self.finished = SignalStub()
            self.started = False

        def start(self):
            self.started = True

        def isRunning(self):
            return False

    monkeypatch.setattr("mysql_editor.ui.main_window.UpdateCheckThread", FakeUpdateThread)
    repository = LocalRepository(tmp_path / "updates-manual.sqlite3")
    worker = StubWorker()
    profile = {
        "id": "profile-manual-updates",
        "name": "Development",
        "host": "localhost",
        "port": 3306,
        "username": "reader",
    }
    config = {
        "host": "localhost",
        "port": 3306,
        "username": "reader",
        "default_schema": "app_db",
        "tls_mode": "Automatic TLS",
    }
    window = MainWindow(worker, repository, object(), profile, config, {"database": "app_db"})
    try:
        assert not window.update_checks_action.isChecked()
        assert settings.values.get("updates/automaticCheck", False) is False

        window.check_for_updates()

        assert isinstance(window._update_check_thread, FakeUpdateThread)
        assert window._update_check_thread.started is True
        assert settings.values.get("updates/automaticCheck", False) is False
    finally:
        window.close()
        repository.close()
        _APP.processEvents()

