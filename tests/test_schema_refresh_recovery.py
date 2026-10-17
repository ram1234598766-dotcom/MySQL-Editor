"""Regression tests for stale-schema invalidation and out-of-order refresh results."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
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
        assert window._schema_completion_words == set()
        assert window._active_schema_name == ""
        editor = window._current_editor()
        assert editor is not None
        assert editor._completion_columns_by_table == {}
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
