"""Windows-only UI smoke test for preferences and file-operation recovery.

Run with QT_QPA_PLATFORM=offscreen on a Windows host with project dependencies installed.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, QSettings, Signal, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from mysql_editor.storage import CredentialStore, LocalRepository, MasterPasswordStore
from mysql_editor.ui.main_window import MainWindow
from mysql_editor.ui.tutorial import ProductTourDialog
from mysql_editor.ui.unlock_dialog import MasterUnlockDialog


class StubWorker(QObject):
    completed = Signal(str, str, object)
    activity = Signal(str)

    def __init__(self):
        super().__init__()
        self.submissions = []

    def submit(self, action, payload=None, task_id=None):
        self.submissions.append((action, payload or {}))
        return task_id or f"smoke-{len(self.submissions)}"

    def cancel_current_query(self):
        pass

    def shutdown(self):
        pass

    def wait(self, _milliseconds=5000):
        return True


def make_window(database_path: Path):
    worker = StubWorker()
    repository = LocalRepository(database_path)
    window = MainWindow(
        worker,
        repository,
        CredentialStore(),
        {"id": "ui-smoke", "name": "UI smoke", "host": "127.0.0.1", "port": 3306, "username": "qa"},
        {"host": "127.0.0.1", "port": 3306, "username": "qa", "default_schema": ""},
        {"server_version": "smoke-test", "database": ""},
    )
    return window, repository


def main():
    with tempfile.TemporaryDirectory(prefix="mysql-editor-ui-smoke-") as temporary:
        root = Path(temporary)
        os.environ["LOCALAPPDATA"] = str(root / "localappdata")
        settings_dir = root / "settings"
        settings_dir.mkdir()
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(settings_dir))

        app = QApplication.instance() or QApplication([])
        app.setOrganizationName("MySQL Editor QA")
        app.setApplicationName("MySQL Editor QA")
        settings = QSettings()
        settings.clear()

        first, first_repo = make_window(root / "settings-one.sqlite3")
        first.resize(1360, 900)
        first.show()
        app.processEvents()
        editor = first._current_editor()
        assert editor is not None
        assert editor.accessibleName() == "SQL query editor"
        assert first.editors.accessibleName() == "SQL query tabs"
        assert first.result_picker.accessibleName() == "Select query result set"
        assert first.result_grid.accessibleName() == "SQL query results table"
        assert first.history_list.accessibleName() == "Local query history"
        assert first.saved_list.accessibleName() == "Saved SQL snippets"
        assert first.schema_tree.accessibleName() == "MySQL databases, tables and views"
        assert first.result_filter.accessibleName() == "Filter result rows"
        assert first.stop_button.accessibleName() == "Request query cancellation"
        assert first.commit_button.accessibleName() == "Commit active transaction"
        assert first.rollback_button.accessibleName() == "Roll back active transaction"
        assert first.export_button.accessibleName() == "Export fetched result rows to CSV"
        export_semantics = "preserves MySQL fetch order and includes every fetched row"
        assert export_semantics in first.export_button.accessibleDescription()
        assert "ignores grid sorting and the visible-row filter" in first.export_button.accessibleDescription()
        assert export_semantics in first.result_filter.toolTip()
        assert "fetch order" in first.result_grid.accessibleDescription().lower()
        assert first.font().pointSize() >= 0
        assert editor.font().pointSize() == 10

        # Theme changes update SQL syntax and custom editor surfaces without losing work.
        themed_sql = "SELECT current_col FROM sample_table;"
        editor.setPlainText(themed_sql)
        themed_cursor = editor.textCursor()
        themed_start = themed_sql.index("current_col")
        themed_cursor.setPosition(themed_start)
        themed_cursor.setPosition(
            themed_start + len("current_col"), QTextCursor.MoveMode.KeepAnchor
        )
        editor.setTextCursor(themed_cursor)
        first._set_theme("light")
        assert editor.theme_name == "light"
        assert editor.highlighter.theme_name == "light"
        assert editor.toPlainText() == themed_sql
        assert editor.textCursor().selectedText() == "current_col"
        assert editor.theme_palette["current_line_background"] == "#EFF6FC"
        first._set_theme("dark")
        assert editor.theme_name == "dark"
        assert editor.toPlainText() == themed_sql
        settings.setValue("ui/theme", "dark")

        first.increase_editor_font()
        assert editor.font().pointSize() == 11
        first._set_editor_tab_width(8)
        assert first._editor_tab_width == 8
        assert editor.tabStopDistance() == editor.fontMetrics().horizontalAdvance(" ") * 8
        first._set_result_row_height(36)
        assert first.result_grid.verticalHeader().defaultSectionSize() == 36
        first.main_split.setSizes([440, 320])
        first.editor_results_split.setSizes([420, 300])
        app.processEvents()
        first.inspector_tabs.setCurrentIndex(1)

        original_count = first.editors.count()
        missing_file = root / "missing-query.sql"
        with patch("mysql_editor.ui.main_window.QMessageBox.warning"):
            assert first._open_sql_path(missing_file) is False
        assert first.editors.count() == original_count

        # Recent SQL stores file paths only and offers an explicit non-destructive clear.
        recent_source = root / "queries" / "private-query.sql"
        recent_source.parent.mkdir(parents=True)
        private_sql = "SELECT 'query body is not stored in settings';"
        recent_source.write_text(private_sql, encoding="utf-8")
        assert first._open_sql_path(recent_source) is True
        # Match the application's absolute-but-not-symlink-resolved path normalization.
        normalized_recent = os.path.abspath(recent_source)
        stored_recent_paths = first._recent_sql_paths()
        assert len(stored_recent_paths) == 1
        # Short Windows paths/aliases can differ from canonicalized paths but identify
        # the same file; compare file identity instead of spelling.
        assert Path(stored_recent_paths[0]).samefile(recent_source)
        assert private_sql not in repr(first._settings.value("ui/recentSqlFiles", []))
        first._refresh_recent_sql_menu()
        assert any(action.toolTip() == normalized_recent for action in first.recent_sql_menu.actions())

        # Exercise the animated tour's navigation and its real "insert sample SQL" action.
        tour = ProductTourDialog(first, first_repo, first._insert_tour_example)
        tour._go(2)
        assert tour.pages.currentIndex() == 2
        insert_button = next(
            button for button in tour.findChildren(QPushButton)
            if button.text() == "Insert a sample SELECT into the editor"
        )
        insert_button.click()
        assert "information_schema.tables" in first._current_editor().toPlainText()
        first._current_editor().setPlainText("SELECT alpha, alpha;")
        first._current_editor().document().setModified(False)
        editor = first._current_editor()
        cursor = editor.textCursor()
        cursor.setPosition(editor.toPlainText().index("alpha"))
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        editor.setTextCursor(cursor)
        app.processEvents()
        assert "5 selected" in first.editor_position.text()
        assert first.editor_position.text().startswith("Ln 1, Col ")
        cursor = editor.textCursor()
        cursor.setPosition(0)
        editor.setTextCursor(cursor)
        app.processEvents()
        assert first.editor_position.text() == "Ln 1, Col 1"
        cursor.setPosition(editor.toPlainText().index(",") + 2)
        editor.setTextCursor(cursor)
        app.processEvents()
        assert first.editor_position.text().startswith("Ln 1, Col ")
        # Reset the caret so the first-match replacement assertion is deterministic.
        cursor = editor.textCursor()
        cursor.setPosition(0)
        editor.setTextCursor(cursor)
        app.processEvents()
        first.show_find_replace(replace=True)
        first.find_bar.search_input.setText("alpha")
        first._refresh_find_count()
        first.find_bar.replace_input.setText("beta")
        assert first.find_bar.match_count.text() == "2 matches"
        assert first._navigate_find_match()
        assert first._current_editor().textCursor().selectedText() == "alpha"
        first._replace_one()
        assert first._current_editor().toPlainText() == "SELECT beta, alpha;"
        first._replace_all()
        assert first._current_editor().toPlainText() == "SELECT beta, beta;"
        assert first.find_bar.match_count.text() == "No matches"
        first.find_bar.close_bar()
        first.inspector_tabs.setCurrentIndex(1)
        tour._skip()
        assert first_repo.get_setting("guided_tour_completed") == "true"

        # Verify the master-password-only gate rejects a wrong password and accepts the right one.
        master = MasterPasswordStore(first_repo)
        master.create("reliable local master", "reliable local master")
        unlock = MasterUnlockDialog(first_repo)
        unlock.password.setText("incorrect phrase")
        unlock._unlock()
        assert not unlock.is_unlocked
        unlock.password.setText("reliable local master")
        unlock._unlock()
        assert unlock.is_unlocked
        
        blocker = root / "not-a-directory"
        blocker.write_text("existing file", encoding="utf-8")
        editor.setPlainText("SELECT 1;")
        editor.document().setModified(True)
        with patch("mysql_editor.ui.main_window.QMessageBox.warning"):
            assert first._write_current_editor(str(blocker / "cannot-save.sql")) is False
        assert editor.document().isModified()
        editor.document().setModified(False)

        # Switching profile must not silently reroute a query tab created on another server.
        original_context = dict(editor._mysql_editor_connection_context)
        next_profile = {
            "id": "qa-reporting", "name": "Reporting", "host": "db-other.example",
            "port": 3307, "username": "reporter",
        }
        next_config = {
            "host": "db-other.example", "port": 3307, "username": "reporter",
            "default_schema": "analytics", "tls_mode": "Automatic TLS", "save_profile": False,
        }
        next_result = {"server_version": "8.4", "database": "analytics"}
        with patch.object(first, "_persist_profile"), patch.object(first, "refresh_schema"):
            first._switch_connection(next_profile, next_config, next_result)
        assert editor._mysql_editor_connection_context == original_context
        assert first._current_connection_context()["profile_id"] == "qa-reporting"
        assert "Reporting" in first.connection_badge.text()
        assert "db-other.example" in first.connection_badge.text()
        assert first.connection_badge.property("connectionState") == "connected"
        assert "TLS: Automatic TLS" in first.connection_details.toolTip()

        # A worker disconnect must surface a distinct, accessible connection-lost state.
        lost_job = "lost-connection-smoke"
        first._schema_request_id = lost_job
        first._jobs[lost_job] = ("schema", {})
        first._on_worker_completed(lost_job, "schema", {
            "ok": False, "connection_lost": True,
            "error": "Lost connection to MySQL server during query",
        })
        assert "Connection lost" in first.connection_badge.text()
        assert first.connection_badge.property("connectionState") == "lost"
        assert "Reconnect before running more SQL" in first.connection_badge.toolTip()
        first._update_connection_status()
        assert "Connected" in first.connection_badge.text()
        assert first.connection_badge.property("connectionState") == "connected"

        # Expose the schema tree so Qt delivers the item expansion event in offscreen mode.
        first.inspector_tabs.setCurrentIndex(0)
        first.schema_tree.show()
        app.processEvents()

        # Non-active schemas use placeholders and fetch object metadata only on expansion.
        first._fill_schema_tree({
            "ok": True,
            "databases": ["qa-reporting", "qa-warehouse", "qa-archive"],
            "schema": "qa-reporting",
            "objects": [{"name": "current_table", "type": "BASE TABLE"}],
            "columns_by_table": {"current_table": ["id"]},
            "column_metadata_truncated": False,
        })
        other = next(
            first.schema_tree.topLevelItem(i)
            for i in range(first.schema_tree.topLevelItemCount())
            if (first.schema_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) or {}).get("schema")
            == "qa-warehouse"
        )
        assert other.childCount() == 1
        assert (other.child(0).data(0, Qt.ItemDataRole.UserRole) or {}).get("kind") == "schema_placeholder"
        submissions_before = len(first.worker.submissions)
        other.setExpanded(True)
        app.processEvents()
        assert len(first.worker.submissions) == submissions_before + 1
        action, payload = first.worker.submissions[-1]
        assert action == "schema_objects" and payload["schema"] == "qa-warehouse"
        lazy_job = first._schema_expansion_requests["qa-warehouse"]
        first._on_worker_completed(lazy_job, "schema_objects", {
            "ok": True,
            "schema": "qa-warehouse",
            "objects": [{"name": "revenue", "type": "BASE TABLE"}],
            "columns_by_table": {"revenue": ["id"]},
            "column_metadata_truncated": False,
        })
        assert (other.data(0, Qt.ItemDataRole.UserRole) or {}).get("metadata_loaded") is True
        assert other.childCount() == 1
        assert (other.child(0).data(0, Qt.ItemDataRole.UserRole) or {}).get("table") == "revenue"
        assert "qa-warehouse" not in first._schema_columns_by_table

        archive = next(
            first.schema_tree.topLevelItem(i)
            for i in range(first.schema_tree.topLevelItemCount())
            if (first.schema_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) or {}).get("schema")
            == "qa-archive"
        )
        archive.setExpanded(True)
        app.processEvents()
        failed_job = first._schema_expansion_requests["qa-archive"]
        first._on_worker_completed(failed_job, "schema_objects", {
            "ok": False, "error": "access denied",
        })
        assert (archive.data(0, Qt.ItemDataRole.UserRole) or {}).get("metadata_loaded") is False
        assert (archive.child(0).data(0, Qt.ItemDataRole.UserRole) or {}).get("kind") == "schema_placeholder"
        previous_submissions = len(first.worker.submissions)
        archive.setExpanded(False)
        archive.setExpanded(True)
        app.processEvents()
        assert len(first.worker.submissions) == previous_submissions + 1
        assert first.worker.submissions[-1][0] == "schema_objects"
        retry_job = first._schema_expansion_requests["qa-archive"]
        first._on_worker_completed(retry_job, "schema_objects", {
            "ok": False, "error": "still denied",
        })
        # Restore the pre-existing persisted inspector preference after this test.
        first.inspector_tabs.setCurrentIndex(1)

        submitted = []
        first._dispatch = lambda action, payload, context=None: submitted.append((action, payload, context))
        with patch(
            "mysql_editor.ui.main_window.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.Cancel,
        ):
            first._execute_sql("SELECT 42;")
        assert submitted == []
        assert "not submitted" in first.status.text()

        with patch(
            "mysql_editor.ui.main_window.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            first._execute_sql("SELECT 42;")
        assert submitted and submitted[-1][0] == "query"
        assert editor._mysql_editor_connection_context["profile_id"] == "qa-reporting"

        # A pending transaction must be confirmed before a replacement connection is queued.
        first._transaction_open = True
        with patch("mysql_editor.ui.main_window.ConnectionDialog") as dialog_type:
            first.open_connection_dialog()
            before_connect = dialog_type.call_args.kwargs["before_connect"]
            assert callable(before_connect)
            candidate_config = {
                "profile_id": "qa-production", "profile_name": "Production",
                "host": "prod.example", "port": 3306, "username": "admin",
                "tls_mode": "Automatic TLS", "default_schema": "main",
            }
            with patch(
                "mysql_editor.ui.main_window.QMessageBox.warning",
                return_value=QMessageBox.StandardButton.Cancel,
            ) as warning:
                assert before_connect(candidate_config) is False
                assert "uncommitted transaction" in warning.call_args.args[1].lower()
                assert first._transaction_open is True
            with patch(
                "mysql_editor.ui.main_window.QMessageBox.warning",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                assert before_connect(candidate_config) is True

        # A delayed progress signal from a finished task must be ignored.
        with patch.object(first, "_on_activity") as consume_activity:
            first._on_task_activity("already-finished-query", "Fetched 99,999 result row(s) so far…")
            consume_activity.assert_not_called()
            first._jobs["active-query-smoke"] = ("query", {})
            first._on_task_activity("active-query-smoke", "Running 1 SQL statement(s)…")
            consume_activity.assert_called_once_with("Running 1 SQL statement(s)…")
            first._jobs.pop("active-query-smoke", None)

        first.close()
        first_repo.close()
        settings.sync()
        assert int(settings.value("ui/editorFontSize", 0)) == 11
        assert int(settings.value("ui/tabWidth", 0)) == 8
        assert int(settings.value("ui/resultRowHeight", 0)) == 36
        assert int(settings.value("ui/inspectorTab", -1)) == 1
        saved_sizes = settings.value("ui/mainSplitterSizes", [])
        result_sizes = settings.value("ui/editorResultsSplitterSizes", [])
        assert len(saved_sizes) == 2 and all(int(size) > 0 for size in saved_sizes)
        assert len(result_sizes) == 2 and all(int(size) > 0 for size in result_sizes)

        second, second_repo = make_window(root / "settings-two.sqlite3")
        second.show()
        app.processEvents()
        restored = second._current_editor()
        assert restored is not None and restored.font().pointSize() == 11
        assert second._editor_tab_width == 8
        assert restored.tabStopDistance() == restored.fontMetrics().horizontalAdvance(" ") * 8
        assert second._result_row_height == 36
        assert second.result_grid.verticalHeader().defaultSectionSize() == 36
        assert second.inspector_tabs.currentIndex() == 1
        assert any(
            action.toolTip() == normalized_recent
            for action in second.recent_sql_menu.actions()
        )
        clear_recent = next(
            action for action in second.recent_sql_menu.actions()
            if action.text() == "Clear recent list"
        )
        clear_recent.trigger()
        assert second._settings.value("ui/recentSqlFiles", []) == []
        assert recent_source.exists() and recent_source.read_text(encoding="utf-8") == private_sql
        assert len(second.editor_results_split.sizes()) == 2
        assert all(size > 0 for size in second.editor_results_split.sizes())
        second.close()
        second_repo.close()
        app.quit()

    print("Qt UI smoke checks passed: preferences persist, missing files recover, failed saves preserve edits.")


if __name__ == "__main__":
    main()
