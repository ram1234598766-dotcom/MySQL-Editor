"""Regression tests for stale-schema invalidation and out-of-order refresh results."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from mysql_editor.storage import LocalRepository
from mysql_editor.ui.main_window import MainWindow


_APP = QApplication.instance() or QApplication([])


class StubWorker(QObject):
    completed = Signal(str, str, object)
    activity = Signal(str)

    def __init__(self):
        super().__init__()
        self.submissions = []

    def submit(self, action, payload=None, task_id=None):
        self.submissions.append((action, payload or {}, task_id))
        return task_id or f"schema-refresh-{len(self.submissions)}"

    def cancel_current_query(self):
        pass

    def shutdown(self):
        pass

    def wait(self, _milliseconds=5000):
        return True


def _make_window(tmp_path):
    repository = LocalRepository(tmp_path / "schema-refresh.sqlite3")
    worker = StubWorker()
    window = MainWindow(
        worker,
        repository,
        object(),
        {"id": "schema-test", "name": "Schema test", "host": "localhost", "port": 3306, "username": "tester"},
        {"host": "localhost", "port": 3306, "username": "tester", "default_schema": "old_schema"},
        {"server_version": "MySQL test", "database": "old_schema"},
    )
    return window, repository, worker


def test_failed_schema_refresh_does_not_keep_old_completion_metadata(tmp_path):
    window, repository, _worker = _make_window(tmp_path)
    try:
        window._schema_databases = {"old_schema"}
        window._schema_tables = {"customers"}
        window._schema_columns_by_table = {"customers": ["customer_id", "customer_email"]}
        window._schema_tables_by_schema = {"old_schema": {"customers"}}
        window._schema_columns_by_schema_and_table = {
            "old_schema": {"customers": ["customer_id", "customer_email"]}
        }
        window._schema_completion_words = {"old_schema", "customers"}
        window._active_schema_name = "old_schema"
        window._update_all_editor_completions()

        window.refresh_schema()
        request_id = window._schema_request_id
        assert request_id
        assert not window.schema_refresh_button.isEnabled()
        assert window._schema_databases == set()
        assert window._schema_tables == set()
        assert window._schema_columns_by_table == {}
        assert window._schema_tables_by_schema == {}
        assert window._schema_columns_by_schema_and_table == {}
        assert window._schema_completion_words == set()
        assert window._active_schema_name == ""

        window._on_worker_completed(
            request_id,
            "schema",
            {"ok": False, "error": "schema permissions were revoked"},
        )

        assert window.schema_refresh_button.isEnabled()
        assert "could not be loaded" in window.schema_state_label.text().lower()
        assert "schema permissions were revoked" in window.schema_state_label.text()
        assert window._schema_databases == set()
        assert window._schema_tables == set()
        assert window._schema_columns_by_table == {}
        assert window._schema_tables_by_schema == {}
        assert window._schema_columns_by_schema_and_table == {}
        assert window._schema_completion_words == set()
        assert window._active_schema_name == ""
        editor = window._current_editor()
        assert editor is not None
        assert editor._completion_columns_by_table == {}
    finally:
        window.close()
        repository.close()


def test_expanding_another_schema_refreshes_schema_scoped_completion(tmp_path):
    window, repository, _worker = _make_window(tmp_path)
    try:
        window._fill_schema_tree(
            {
                "ok": True,
                "schema": "app_db",
                "databases": ["app_db", "analytics"],
                "objects": [
                    {"name": "customers", "type": "BASE TABLE"},
                    {"name": "orders", "type": "BASE TABLE"},
                ],
                "columns_by_table": {
                    "customers": ["customer_id"],
                    "orders": ["app_order_id"],
                },
            }
        )
        analytics_item = next(
            window.schema_tree.topLevelItem(index)
            for index in range(window.schema_tree.topLevelItemCount())
            if (
                window.schema_tree.topLevelItem(index).data(
                    0, Qt.ItemDataRole.UserRole
                ) or {}
            ).get("schema") == "analytics"
        )
        window._finish_schema_expansion(
            "expanded-analytics",
            "analytics",
            analytics_item,
            {
                "ok": True,
                "schema": "analytics",
                "objects": [
                    {"name": "orders", "type": "BASE TABLE"},
                    {"name": "events", "type": "VIEW"},
                ],
                "columns_by_table": {
                    "orders": ["analytics_order_id"],
                    "events": ["event_id"],
                },
            },
        )

        assert window._schema_tables_by_schema["analytics"] == {"orders", "events"}
        assert window._schema_columns_by_schema_and_table["analytics"]["orders"] == [
            "analytics_order_id"
        ]
        editor = window._current_editor()
        assert editor is not None

        source = "SELECT o.analytics_ FROM `analytics`.`orders` AS o"
        editor.setPlainText(source)
        cursor = editor.textCursor()
        cursor.setPosition(source.index("analytics_") + len("analytics_"))
        editor.setTextCursor(cursor)
        candidates = set(editor._context_completion_words())
        assert "analytics_order_id" in candidates
        assert "app_order_id" not in candidates

        source = "SELECT * FROM `analytics`.`eve"
        editor.setPlainText(source)
        cursor = editor.textCursor()
        cursor.setPosition(len(source))
        editor.setTextCursor(cursor)
        table_candidates = set(editor._context_completion_words())
        assert "events" in table_candidates
        assert "customers" not in table_candidates
    finally:
        window.close()
        repository.close()


def test_late_schema_reply_cannot_replace_newer_refresh_state(tmp_path):
    window, repository, _worker = _make_window(tmp_path)
    try:
        window._jobs["old-schema-request"] = ("schema", {})
        window._schema_request_id = "new-schema-request"
        window._schema_databases = {"new_schema"}
        window._schema_tables = {"current_table"}
        window._schema_columns_by_table = {"current_table": ["current_column"]}
        window._active_schema_name = "new_schema"
        window.schema_state_label.setText("Loading current schema metadata…")

        window._on_worker_completed(
            "old-schema-request",
            "schema",
            {
                "ok": True,
                "schema": "old_schema",
                "databases": ["old_schema"],
                "objects": [{"name": "old_table", "type": "BASE TABLE"}],
                "columns_by_table": {"old_table": ["old_column"]},
            },
        )

        assert window._schema_request_id == "new-schema-request"
        assert window._schema_databases == {"new_schema"}
        assert window._schema_tables == {"current_table"}
        assert window._schema_columns_by_table == {"current_table": ["current_column"]}
        assert window._active_schema_name == "new_schema"
        assert window.schema_state_label.text() == "Loading current schema metadata…"
    finally:
        window.close()
        repository.close()
