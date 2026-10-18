"""Regression tests for transaction-safe connection switching."""
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
        return task_id or f"transaction-switch-{len(self.submissions)}"

    def cancel_current_query(self):
        pass

    def shutdown(self):
        pass

    def wait(self, _milliseconds=5000):
        return True


def _make_window(tmp_path):
    repository = LocalRepository(tmp_path / "transaction-switch.sqlite3")
    worker = StubWorker()
    window = MainWindow(
        worker,
        repository,
        object(),
        {
            "id": "profile-active",
            "name": "Production",
            "host": "prod.example.test",
            "port": 3306,
            "username": "writer",
        },
        {
            "profile_id": "profile-active",
            "profile_name": "Production",
            "host": "prod.example.test",
            "port": 3306,
            "username": "writer",
            "default_schema": "orders",
            "tls_mode": "Verify server identity",
        },
        {"server_version": "8.4", "database": "orders", "transaction_open": False},
    )
    return window, repository


def test_switch_without_open_transaction_does_not_prompt(tmp_path, monkeypatch):
    window, repository = _make_window(tmp_path)
    try:
        def unexpected_prompt(*_args, **_kwargs):
            raise AssertionError("No warning is needed when no transaction is open.")

        monkeypatch.setattr(QMessageBox, "warning", unexpected_prompt)
        assert window._confirm_connection_switch({
            "profile_id": "profile-next",
            "profile_name": "Analytics",
            "host": "analytics.example.test",
            "port": 3306,
            "username": "reader",
            "default_schema": "reporting",
        }) is True
    finally:
        window.deleteLater()
        repository.close()


def test_cancelled_switch_preserves_open_transaction_and_explains_context(
    tmp_path, monkeypatch,
):
    window, repository = _make_window(tmp_path)
    calls = []

    def cancel_switch(parent, title, message, buttons, default):
        calls.append((title, message, buttons, default))
        return QMessageBox.StandardButton.Cancel

    try:
        window._transaction_open = True
        monkeypatch.setattr(QMessageBox, "warning", cancel_switch)

        accepted = window._confirm_connection_switch({
            "profile_id": "profile-next",
            "profile_name": "Analytics",
            "host": "analytics.example.test",
            "port": 3307,
            "username": "reader",
            "default_schema": "reporting",
        })

        assert accepted is False
        assert len(calls) == 1
        title, message, _buttons, default = calls[0]
        assert title == "Uncommitted transaction"
        assert "prod.example.test:3306" in message
        assert "analytics.example.test:3307" in message
        assert default == QMessageBox.StandardButton.Cancel
        assert "open transaction remain active" in window.status.text()
        assert window._transaction_open is True
    finally:
        window.deleteLater()
        repository.close()


def test_explicit_confirmation_allows_switch_with_open_transaction(tmp_path, monkeypatch):
    window, repository = _make_window(tmp_path)
    try:
        window._transaction_open = True
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )

        assert window._confirm_connection_switch({
            "profile_id": "profile-next",
            "profile_name": "Analytics",
            "host": "analytics.example.test",
            "port": 3307,
            "username": "reader",
            "default_schema": "reporting",
        }) is True
    finally:
        window.deleteLater()
        repository.close()
