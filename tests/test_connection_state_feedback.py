"""Regression tests for explicit, recoverable MySQL disconnect feedback."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

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
        return task_id or f"connection-state-{len(self.submissions)}"

    def cancel_current_query(self):
        pass

    def shutdown(self):
        pass

    def wait(self, _milliseconds=5000):
        return True


def _make_window(tmp_path):
    repository = LocalRepository(tmp_path / "connection-state.sqlite3")
    worker = StubWorker()
    profile = {
        "id": "profile-a", "name": "Development", "host": "db.example.test",
        "port": 3306, "username": "reporter",
    }
    config = {
        "host": "db.example.test", "port": 3306, "username": "reporter",
        "default_schema": "analytics", "tls_mode": "Automatic TLS",
    }
    result = {"server_version": "8.4", "database": "analytics"}
    window = MainWindow(worker, repository, object(), profile, config, result)
    return window, repository, worker


def test_disconnect_is_queued_and_preserves_local_query_work(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    try:
        editor = window._current_editor()
        editor.setPlainText("SELECT 1;")
        window.result_model.update(["value"], [[1]])
        window._query_results = [{"result_id": "cached-1", "headers": ["value"], "rows": [[1]]}]
        window._current_result_id = "cached-1"

        window.disconnect_from_mysql()

        action, payload, job_id = worker.submissions[-1]
        assert action == "disconnect"
        assert payload == {}
        assert window._disconnect_pending is True
        assert window.status.text() == "Disconnecting from MySQL…"
        assert not window.disconnect_button.isEnabled()
        assert not window.run_button.isEnabled()

        window._on_worker_completed(job_id, "disconnect", {"ok": True})

        assert window._connection_available is False
        assert window._disconnect_pending is False
        assert window.connection_badge.property("connectionState") == "disconnected"
        assert "Disconnected" in window.connection_badge.text()
        assert "Query tabs and fetched results were kept" in window.status.text()
        assert editor.toPlainText() == "SELECT 1;"
        assert window._query_results[0]["result_id"] == "cached-1"
        assert window.result_model.rows == [[1]]
        assert window._current_result_id == "cached-1"
        assert not window.disconnect_button.isEnabled()
        assert window.connect_button.isEnabled()
        assert not window.run_button.isEnabled()
        assert not window.schema_refresh_button.isEnabled()
        assert "connect to a server" in window.schema_state_label.text().lower()

        before = len(worker.submissions)
        assert window._dispatch("query", {"sql": "SELECT 2;"}) is None
        assert len(worker.submissions) == before
        assert "no active mysql connection" in window.status.text().lower()
    finally:
        window.close()
        repository.close()


def test_disconnect_cancel_keeps_an_open_transaction_and_connection(tmp_path, monkeypatch):
    window, repository, worker = _make_window(tmp_path)
    try:
        window._transaction_open = True
        monkeypatch.setattr(
            QMessageBox, "warning",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
        )
        window.disconnect_from_mysql()

        assert worker.submissions == []
        assert window._connection_available is True
        assert window._disconnect_pending is False
        assert "disconnect cancelled" in window.status.text().lower()
        assert window.disconnect_button.isEnabled()
    finally:
        window.close()
        repository.close()


def test_disconnect_failure_keeps_connection_actions_available_and_redacts_secrets(
    tmp_path, monkeypatch
):
    window, repository, worker = _make_window(tmp_path)
    try:
        monkeypatch.setattr(
            QMessageBox, "warning",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        window._transaction_open = True
        window.disconnect_from_mysql()
        _action, _payload, job_id = worker.submissions[-1]

        window._on_worker_completed(
            job_id,
            "disconnect",
            {"ok": False, "error": "Disconnect failed: password=supersecret"},
        )

        assert window._connection_available is True
        assert window._disconnect_pending is False
        assert window.disconnect_button.isEnabled()
        assert window.run_button.isEnabled()
        assert "could not disconnect" in window.status.text().lower()
        assert "supersecret" not in window.status.text()
        assert window.connection_badge.property("connectionState") == "connected"
    finally:
        window.close()
        repository.close()


def test_reconnection_restores_database_controls_after_disconnect(tmp_path, monkeypatch):
    window, repository, _worker = _make_window(tmp_path)
    profile = {
        "id": "profile-b", "name": "Reporting", "host": "reporting.example.test",
        "port": 3307, "username": "reporter",
    }
    config = {
        "host": "reporting.example.test", "port": 3307, "username": "reporter",
        "default_schema": "warehouse", "tls_mode": "Automatic TLS", "save_profile": False,
    }
    result = {"server_version": "8.4", "database": "warehouse"}
    try:
        window._connection_available = False
        window._set_connection_badge_state("disconnected")
        window._sync_connection_controls()
        monkeypatch.setattr(window, "refresh_schema", lambda: None)
        monkeypatch.setattr(window, "_persist_profile", lambda *_args: None)

        window._switch_connection(profile, config, result)

        assert window._connection_available is True
        assert window.connection_badge.property("connectionState") == "connected"
        assert window.connect_button.isEnabled()
        assert window.disconnect_button.isEnabled()
        assert window.run_button.isEnabled()
        assert window.schema_refresh_button.isEnabled()
    finally:
        window.close()
        repository.close()
