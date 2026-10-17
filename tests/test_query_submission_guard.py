"""Regression tests for single-query execution and connection-context safety."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

import mysql_editor.ui.main_window as main_window_module
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
        return task_id or f"query-guard-{len(self.submissions)}"

    def cancel_current_query(self):
        pass

    def shutdown(self):
        pass

    def wait(self, _milliseconds=5000):
        return True


def _make_window(tmp_path):
    repository = LocalRepository(tmp_path / "query-guard.sqlite3")
    worker = StubWorker()
    profile = {
        "id": "profile-one",
        "name": "QA profile",
        "host": "127.0.0.1",
        "port": 3306,
        "username": "tester",
    }
    config = {
        "host": "127.0.0.1",
        "port": 3306,
        "username": "tester",
        "default_schema": "",
        "tls_mode": "Automatic TLS",
    }
    window = MainWindow(
        worker, repository, object(), profile, config,
        {"server_version": "MySQL test", "database": ""},
    )
    return window, repository, worker


def test_second_sql_submission_is_rejected_while_query_is_active(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    try:
        window._query_running = True
        before = len(worker.submissions)

        window._execute_sql("SELECT 1;")
        result = window._dispatch("query", {"sql": "SELECT 2;"})

        assert result is None
        assert len(worker.submissions) == before
        assert "already active" in window.status.text().lower()
    finally:
        window._query_running = False
        window.close()
        repository.close()


def test_connection_dialog_does_not_open_during_active_query(tmp_path, monkeypatch):
    window, repository, _worker = _make_window(tmp_path)

    def unexpected_dialog(*_args, **_kwargs):
        raise AssertionError("Connection dialog must not open during an active query")

    monkeypatch.setattr(main_window_module, "ConnectionDialog", unexpected_dialog)
    try:
        window._query_running = True
        window.open_connection_dialog()

        assert "connection change blocked" in window.status.text().lower()
    finally:
        window._query_running = False
        window.close()
        repository.close()


def test_connection_switch_callback_cannot_change_context_mid_query(tmp_path):
    window, repository, _worker = _make_window(tmp_path)
    original_profile = dict(window.profile)
    original_config = dict(window.config)
    original_result = dict(window.connect_result)
    try:
        window._query_running = True
        window._switch_connection(
            {"id": "profile-two", "name": "Unexpected", "host": "db2.example.test"},
            {"host": "db2.example.test", "port": 3307, "username": "other"},
            {"server_version": "other server", "database": "other_schema"},
        )

        assert window.profile == original_profile
        assert window.config == original_config
        assert window.connect_result == original_result
        assert "connection change blocked" in window.status.text().lower()
    finally:
        window._query_running = False
        window.close()
        repository.close()


def test_transaction_controls_disable_during_query_and_restore_after_completion(tmp_path):
    window, repository, _worker = _make_window(tmp_path)
    try:
        job_id = window._dispatch("query", {"sql": "SELECT 1;"})
        assert job_id is not None
        assert window._query_running is True
        assert not window.commit_button.isEnabled()
        assert not window.rollback_button.isEnabled()

        window._on_worker_completed(
            job_id, "query", {"ok": True, "results": [], "duration_ms": 1}
        )

        assert window._query_running is False
        assert window.commit_button.isEnabled()
        assert window.rollback_button.isEnabled()
        assert not window.stop_button.isEnabled()
    finally:
        window._query_running = False
        window.close()
        repository.close()
