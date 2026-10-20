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

def test_close_defers_without_blocking_ui_until_update_thread_finishes(tmp_path, monkeypatch):
    import mysql_editor.ui.main_window as main_window_module

    settings = SettingsStub()
    monkeypatch.setattr("mysql_editor.ui.main_window.QSettings", lambda: settings)
    callbacks = []
    monkeypatch.setattr(
        main_window_module.QTimer,
        "singleShot",
        lambda delay, callback: callbacks.append((delay, callback)),
    )

    class FakeUpdateThread:
        def __init__(self):
            self.running = True
            self.deleted = False
            self.wait_called = False

        def isRunning(self):
            return self.running

        def wait(self, *_args, **_kwargs):
            self.wait_called = True
            raise AssertionError("close must not synchronously wait for the update thread")

        def deleteLater(self):
            self.deleted = True

    class CloseEvent:
        ignored = False

        def ignore(self):
            self.ignored = True

    repository = LocalRepository(tmp_path / "update-close.sqlite3")
    worker = StubWorker()
    profile = {
        "id": "profile-update-close",
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
    update_thread = FakeUpdateThread()
    window._update_check_thread = update_thread
    event = CloseEvent()
    try:
        window.closeEvent(event)

        assert event.ignored is True
        assert update_thread.wait_called is False
        assert window._close_after_update_check is True
        assert not window.isEnabled()
        assert "before closing" in window.status.text()

        update_thread.running = False
        window._on_update_check_finished()

        assert update_thread.deleted is True
        assert window._update_check_thread is None
        assert window._close_after_update_check is False
        assert window._close_after_update_check_approved is True
        assert window.isEnabled()
        close_callbacks = [
            callback
            for delay, callback in callbacks
            if delay == 0
            and getattr(callback, "__self__", None) is window
            and getattr(callback, "__name__", "") == "close"
        ]
        assert len(close_callbacks) == 1
    finally:
        window._close_after_update_check = False
        window._close_after_update_check_approved = False
        window._update_check_thread = None
        window.close()
        repository.close()
        _APP.processEvents()


def test_table_preview_edit_metadata_stays_aligned_when_window_evicts_rows(tmp_path, monkeypatch):
    settings = SettingsStub()
    monkeypatch.setattr("mysql_editor.ui.main_window.QSettings", lambda: settings)
    repository = LocalRepository(tmp_path / "preview-page-edit-metadata.sqlite3")
    worker = StubWorker()
    window = MainWindow(
        worker,
        repository,
        object(),
        {"id": "profile-preview-window", "name": "Preview", "host": "localhost", "port": 3306, "username": "reader"},
        {"host": "localhost", "port": 3306, "username": "reader", "default_schema": "analytics", "tls_mode": "Automatic TLS"},
        {"database": "analytics"},
    )
    try:
        headers = ["id", "label", "quantity"]
        old_rows = [[index, f"row-{index}", index % 9] for index in range(1000, 6000)]
        edit = {
            "enabled": True,
            "schema": "analytics",
            "table": "items",
            "session_token": "session-a",
            "primary_key_columns": ["id"],
            "primary_key_indices": [0],
            "row_keys": [[index] for index in range(1000, 6000)],
            "editable_column_indices": [1, 2],
            "original_values": {
                "1": [f"row-{index}" for index in range(1000, 6000)],
                "2": [index % 9 for index in range(1000, 6000)],
            },
            "reason": "",
        }
        item = {
            "result_id": "preview-window",
            "table_preview": True,
            "headers": headers,
            "rows": old_rows,
            "row_count": 6000,
            "window_start_offset": 1000,
            "preview_loaded_count": 6000,
            "preview_has_more": True,
            "preview_stable_order": True,
            "table_edit": edit,
        }
        window._query_results = [item]
        window._current_result_id = "preview-window"
        window.result_model.update(headers, old_rows, base_offset=1000, total_rows=6001)
        item["rows"] = window.result_model.rows
        item["initial_rows"] = [list(row) for row in old_rows[:1000]]
        initial_edit = window._copy_table_edit_context(edit)
        initial_edit["row_keys"] = list(initial_edit["row_keys"][:1000])
        initial_edit["original_values"] = {
            key: list(values[:1000])
            for key, values in initial_edit["original_values"].items()
        }
        item["initial_table_edit"] = initial_edit

        next_rows = [[index, f"row-{index}", index % 9] for index in range(6000, 7000)]
        page_edit = {
            "enabled": True,
            "schema": "analytics",
            "table": "items",
            "session_token": "session-a",
            "primary_key_columns": ["id"],
            "primary_key_indices": [0],
            "row_keys": [[index] for index in range(6000, 7000)],
            "editable_column_indices": [1, 2],
            "original_values": {
                "1": [f"row-{index}" for index in range(6000, 7000)],
                "2": [index % 9 for index in range(6000, 7000)],
            },
            "reason": "",
        }

        evicted = window.result_model.append_rows(next_rows)
        item["rows"] = window.result_model.rows
        item["window_start_offset"] = window.result_model.base_offset
        window._merge_table_preview_edit_page(
            item, page_edit, direction="next", page_count=len(next_rows), evicted=evicted
        )

        assert evicted == 1000
        assert item["window_start_offset"] == 2000
        assert len(item["rows"]) == 5000
        assert len(item["table_edit"]["row_keys"]) == 5000
        assert item["table_edit"]["row_keys"][0] == [2000]
        assert item["table_edit"]["row_keys"][-1] == [6999]
        assert item["table_edit"]["original_values"]["1"][0] == "row-2000"
        assert item["table_edit"]["original_values"]["1"][-1] == "row-6999"

        window._restore_initial_result_window(item)
        assert item["window_start_offset"] == 0
        assert item["rows"] == old_rows[:1000]
        assert len(item["table_edit"]["row_keys"]) == 1000
        assert item["table_edit"]["row_keys"][0] == [1000]
        assert item["table_edit"]["row_keys"][-1] == [1999]
    finally:
        window.close()
        repository.close()
        _APP.processEvents()


def test_table_preview_cell_edit_uses_absolute_spool_row_and_local_window_row(tmp_path, monkeypatch):
    settings = SettingsStub()
    monkeypatch.setattr("mysql_editor.ui.main_window.QSettings", lambda: settings)
    repository = LocalRepository(tmp_path / "preview-absolute-row.sqlite3")
    worker = StubWorker()
    window = MainWindow(
        worker,
        repository,
        object(),
        {"id": "profile-preview-absolute", "name": "Preview", "host": "localhost", "port": 3306, "username": "reader"},
        {"host": "localhost", "port": 3306, "username": "reader", "default_schema": "analytics", "tls_mode": "Automatic TLS"},
        {"database": "analytics"},
    )
    try:
        rows = [[1000, "row-1000", 1], [1001, "row-1001", 2], [1002, "row-1002", 3]]
        item = {
            "result_id": "preview-absolute",
            "table_preview": True,
            "kind": "rows",
            "headers": ["id", "label", "quantity"],
            "rows": rows,
            "row_count": 2000,
            "window_start_offset": 1000,
            "table_edit": {
                "enabled": True,
                "schema": "analytics",
                "table": "items",
                "session_token": "session-a",
                "primary_key_columns": ["id"],
                "primary_key_indices": [0],
                "editable_column_indices": [1, 2],
                "row_keys": [[1000], [1001], [1002]],
                "original_values": {
                    "1": ["row-1000", "row-1001", "row-1002"],
                    "2": [1, 2, 3],
                },
            },
        }
        window._query_results = [item]
        window._current_result_id = "preview-absolute"
        window.result_model.update(item["headers"], rows, base_offset=1000, total_rows=2000)
        index = window.result_proxy.index(1, 1)

        entry = window._table_cell_edit_entry(index)

        assert entry is not None
        assert entry["local_row_index"] == 1
        assert entry["row_index"] == 1001
        assert entry["primary_key_values"] == [1001]
        assert entry["old_value"] == "row-1001"
    finally:
        window.close()
        repository.close()
        _APP.processEvents()


def test_table_preview_rollback_restores_visible_local_row_using_absolute_spool_index(tmp_path, monkeypatch):
    settings = SettingsStub()
    monkeypatch.setattr("mysql_editor.ui.main_window.QSettings", lambda: settings)
    repository = LocalRepository(tmp_path / "preview-rollback-index.sqlite3")
    worker = StubWorker()
    window = MainWindow(
        worker,
        repository,
        object(),
        {"id": "profile-preview-rollback", "name": "Preview", "host": "localhost", "port": 3306, "username": "reader"},
        {"host": "localhost", "port": 3306, "username": "reader", "default_schema": "analytics", "tls_mode": "Automatic TLS"},
        {"database": "analytics"},
    )
    try:
        headers = ["id", "label", "quantity"]
        rows = [[1000, "row-1000", 1], [1001, "edited", 2], [1002, "row-1002", 3]]
        item = {
            "result_id": "preview-rollback",
            "table_preview": True,
            "kind": "rows",
            "headers": headers,
            "rows": rows,
            "row_count": 2000,
            "window_start_offset": 1000,
            "table_edit": {
                "enabled": True,
                "schema": "analytics",
                "table": "items",
                "session_token": "session-a",
                "primary_key_columns": ["id"],
                "primary_key_indices": [0],
                "editable_column_indices": [1, 2],
                "row_keys": [[1000], [1001], [1002]],
                "original_values": {
                    "1": ["row-1000", "edited", "row-1002"],
                    "2": [1, 2, 3],
                },
            },
        }
        window._query_results = [item]
        window._current_result_id = "preview-rollback"
        window.result_model.update(headers, rows, base_offset=1000, total_rows=2000)
        window._pending_table_preview_undo[("preview-rollback", 1001)] = {
            "display_row": [1001, "row-1001", 2],
            "original_values": {"1": "row-1001", "2": 2},
        }

        window._restore_table_preview_rows([{
            "result_id": "preview-rollback",
            "row_index": 1001,
            "display_row": [1001, "row-1001", 2],
        }])

        assert item["rows"][1] == [1001, "row-1001", 2]
        assert item["table_edit"]["original_values"]["1"][1] == "row-1001"
        assert item["table_edit"]["original_values"]["2"][1] == 2
        assert window.result_model.rows[1] == [1001, "row-1001", 2]
        assert ("preview-rollback", 1001) not in window._pending_table_preview_undo
    finally:
        window.close()
        repository.close()
        _APP.processEvents()


def test_table_preview_paging_control_distinguishes_source_and_cached_pages(tmp_path, monkeypatch):
    settings = SettingsStub()
    monkeypatch.setattr("mysql_editor.ui.main_window.QSettings", lambda: settings)
    repository = LocalRepository(tmp_path / "preview-page-controls.sqlite3")
    worker = StubWorker()
    window = MainWindow(
        worker,
        repository,
        object(),
        {"id": "profile-preview-controls", "name": "Preview", "host": "localhost", "port": 3306, "username": "reader"},
        {"host": "localhost", "port": 3306, "username": "reader", "default_schema": "analytics", "tls_mode": "Automatic TLS"},
        {"database": "analytics"},
    )
    try:
        rows = [[index, f"row-{index}", index % 9] for index in range(1000)]
        item = {
            "result_id": "preview-controls",
            "table_preview": True,
            "kind": "rows",
            "headers": ["id", "label", "quantity"],
            "rows": rows,
            "row_count": 6000,
            "window_start_offset": 0,
            "preview_loaded_count": 6000,
            "preview_has_more": True,
            "preview_stable_order": True,
            "table_edit": {"enabled": True},
        }
        window._query_results = [item]
        window._current_result_id = "preview-controls"
        window.result_model.update(item["headers"], rows, base_offset=0, total_rows=6001)
        window._set_result_controls()

        assert window.fetch_more_button.text() == "Verify Cached Preview Rows"
        assert "Re-check the next cached page" in window.fetch_more_button.toolTip()

        item["preview_loaded_count"] = 1000
        item["row_count"] = 1000
        window.result_model.set_paging_state(total_rows=1001, pending=False)
        window._set_result_controls()

        assert window.fetch_more_button.text() == "Fetch Next Preview Page"
        assert "from MySQL in primary-key order" in window.fetch_more_button.toolTip()

        window._connection_available = False
        window._set_result_controls()
        assert window.fetch_more_button.isEnabled() is False
        assert "Reconnect to MySQL" in window.fetch_more_button.toolTip()
    finally:
        window.close()
        repository.close()
        _APP.processEvents()


def test_table_preview_page_error_stops_source_requests_but_reports_cached_rows(tmp_path, monkeypatch):
    settings = SettingsStub()
    monkeypatch.setattr("mysql_editor.ui.main_window.QSettings", lambda: settings)
    repository = LocalRepository(tmp_path / "preview-page-error.sqlite3")
    worker = StubWorker()
    window = MainWindow(
        worker,
        repository,
        object(),
        {"id": "profile-preview-page-error", "name": "Preview", "host": "localhost", "port": 3306, "username": "reader"},
        {"host": "localhost", "port": 3306, "username": "reader", "default_schema": "analytics", "tls_mode": "Automatic TLS"},
        {"database": "analytics"},
    )
    try:
        rows = [[index, f"row-{index}", index % 9] for index in range(1000)]
        item = {
            "result_id": "preview-page-error",
            "table_preview": True,
            "kind": "rows",
            "headers": ["id", "label", "quantity"],
            "rows": rows,
            "row_count": 1000,
            "window_start_offset": 0,
            "preview_loaded_count": 1000,
            "preview_has_more": False,
            "preview_stable_order": False,
            "preview_page_error": True,
            "preview_truncated": True,
            "table_edit": {"enabled": False, "reason": "refresh required"},
        }
        window._query_results = [item]
        window._current_result_id = "preview-page-error"
        window.result_model.update(item["headers"], rows, base_offset=0, total_rows=1000)
        window._set_result_controls()

        assert window.fetch_more_button.text() == "Preview Page Unavailable"
        assert not window.fetch_more_button.isEnabled()
        assert "Already cached rows remain available" in window.fetch_more_button.toolTip()
    finally:
        window.close()
        repository.close()
        _APP.processEvents()

