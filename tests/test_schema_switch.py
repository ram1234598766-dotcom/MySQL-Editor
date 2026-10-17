"""Regression tests for live schema switching and context preservation."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from mysql_editor.storage import ConnectionProfile, LocalRepository
from mysql_editor.ui.main_window import MainWindow


_APP = QApplication.instance() or QApplication([])


class StubWorker(QObject):
    completed = Signal(str, str, object)
    activity = Signal(str)

    def __init__(self):
        super().__init__()
        self.submissions = []

    def submit(self, action, payload=None, task_id=None):
        task_id = task_id or f"schema-switch-{len(self.submissions) + 1}"
        self.submissions.append((action, payload or {}, task_id))
        return task_id

    def cancel_current_query(self):
        pass

    def shutdown(self):
        pass

    def wait(self, _milliseconds=5000):
        return True


def _make_window(tmp_path):
    repository = LocalRepository(tmp_path / "schema-switch.sqlite3")
    stored = ConnectionProfile(
        id="schema-profile",
        name="Schema profile",
        host="localhost",
        port=3306,
        username="tester",
        default_schema="old_schema",
    )
    repository.save_profile(stored)
    worker = StubWorker()
    profile = {
        "id": stored.id,
        "name": stored.name,
        "host": stored.host,
        "port": stored.port,
        "username": stored.username,
        "default_schema": stored.default_schema,
        "tls_mode": stored.tls_mode,
        "ca_file": stored.ca_file,
        "read_timeout": stored.read_timeout,
        "write_timeout": stored.write_timeout,
    }
    config = {
        **profile,
        "profile_name": stored.name,
        "password": "session-only-test-value",
        "save_profile": True,
    }
    connect_result = {"server_version": "MySQL test", "database": "old_schema"}
    window = MainWindow(worker, repository, object(), profile, config, connect_result)
    return window, repository, worker


def _last_task_id(worker, action):
    return next(task_id for submitted, _payload, task_id in reversed(worker.submissions) if submitted == action)


def test_schema_switch_runs_on_worker_and_updates_context_only_after_success(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    try:
        same_profile_editor = window._current_editor()
        window.new_query_tab("SELECT 2;")
        different_profile_editor = window._current_editor()
        window._bind_editor_connection_context(
            different_profile_editor,
            dict(
                window._current_connection_context(),
                profile_id="other-profile",
                profile_name="Other profile",
                schema="warehouse",
            ),
        )

        window._use_schema("analytics")

        action, payload, request_id = worker.submissions[-1]
        assert action == "use_schema"
        assert payload == {"schema": "analytics"}
        assert window.config["default_schema"] == "old_schema"
        assert window.connect_result["database"] == "old_schema"
        assert repository.profiles()[0].default_schema == "old_schema"

        window._on_worker_completed(
            request_id,
            "use_schema",
            {"ok": True, "schema": "analytics", "transaction_open": False},
        )

        assert window.config["default_schema"] == "analytics"
        assert window.connect_result["database"] == "analytics"
        assert window.profile["default_schema"] == "analytics"
        assert repository.profiles()[0].default_schema == "analytics"
        assert "analytics" in window.connection_details.text()
        assert window._current_connection_context()["schema"] == "analytics"
        assert same_profile_editor._mysql_editor_connection_context["schema"] == "analytics"
        assert different_profile_editor._mysql_editor_connection_context["schema"] == "warehouse"
        assert different_profile_editor._mysql_editor_connection_context["profile_id"] == "other-profile"
        assert "warehouse" in different_profile_editor.toolTip()
        assert worker.submissions[-1][0] == "schema"
        assert window._schema_request_id == _last_task_id(worker, "schema")
    finally:
        window.close()
        repository.close()


def test_failed_schema_switch_preserves_prior_context_and_saved_profile(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    try:
        window._use_schema("restricted_schema")
        request_id = _last_task_id(worker, "use_schema")

        window._on_worker_completed(
            request_id,
            "use_schema",
            {"ok": False, "error": "Access denied for database restricted_schema"},
        )

        assert window.config["default_schema"] == "old_schema"
        assert window.connect_result["database"] == "old_schema"
        assert window.profile["default_schema"] == "old_schema"
        assert repository.profiles()[0].default_schema == "old_schema"
        assert "restricted_schema" in window.status.text()
        assert "old_schema" in window.status.text()
        assert "Access denied" in window.status.text()
        assert all(action != "schema" for action, _payload, _task_id in worker.submissions)
    finally:
        window.close()
        repository.close()


def test_schema_switch_is_blocked_while_query_is_running(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    try:
        window._query_running = True
        window._use_schema("analytics")

        assert all(action != "use_schema" for action, _payload, _task_id in worker.submissions)
        assert window.config["default_schema"] == "old_schema"
        assert window.connect_result["database"] == "old_schema"
    finally:
        # MainWindow asks for cancellation when closing with a query marked active.
        # This test simulates only the guard; teardown must remain non-interactive.
        window._query_running = False
        window.close()
        repository.close()

def test_schema_switch_respects_disabled_profile_saving(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    try:
        window.config["save_profile"] = False
        window._use_schema("analytics")
        request_id = _last_task_id(worker, "use_schema")

        window._on_worker_completed(
            request_id,
            "use_schema",
            {"ok": True, "schema": "analytics", "transaction_open": False},
        )

        # The current live session changes; the saved default does not.
        assert window.connect_result["database"] == "analytics"
        assert window.config["default_schema"] == "analytics"
        assert repository.profiles()[0].default_schema == "old_schema"
    finally:
        window.close()
        repository.close()

