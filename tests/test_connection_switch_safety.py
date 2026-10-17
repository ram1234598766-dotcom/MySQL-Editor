"""Tests for guarding connection changes during query execution or pending writes."""
from types import SimpleNamespace

from PySide6.QtWidgets import QMessageBox

from mysql_editor.ui import main_window as main_window_module
from mysql_editor.ui.main_window import MainWindow


class FakeStatus:
    def __init__(self):
        self.message = ""

    def setText(self, text):
        self.message = text


class FakeSignal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback


class FakeConnectionDialog:
    instances = []

    def __init__(self, *_args, **_kwargs):
        self.connected = FakeSignal()
        self.executed = False
        self.__class__.instances.append(self)

    def exec(self):
        self.executed = True


def _window(**overrides):
    values = {
        "_query_running": False,
        "_transaction_pending": False,
        "status": FakeStatus(),
        "worker": object(),
        "repository": object(),
        "credentials": object(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_connection_dialog_is_blocked_while_query_is_running(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main_window_module.QMessageBox, "warning",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    window = _window(_query_running=True)

    MainWindow.open_connection_dialog(window)

    assert len(calls) == 1
    assert "running" in calls[0][0][1].casefold()
    assert "running" in calls[0][0][2].casefold()
    assert window.status.message == "Connection switch blocked while a query is running."


def test_connection_dialog_requires_confirmation_for_pending_writes(monkeypatch):
    calls = []
    monkeypatch.setattr(main_window_module, "ConnectionDialog", FakeConnectionDialog)
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *args, **kwargs: calls.append((args, kwargs)) or QMessageBox.StandardButton.Cancel,
    )
    FakeConnectionDialog.instances.clear()
    window = _window(_transaction_pending=True)

    MainWindow.open_connection_dialog(window)

    assert len(calls) == 1
    message = calls[0][0][2]
    assert "uncommitted writes" in message.casefold()
    assert "roll back" in message.casefold()
    assert FakeConnectionDialog.instances == []


def test_confirmed_connection_dialog_can_open_but_state_clears_only_after_switch(monkeypatch):
    calls = []
    monkeypatch.setattr(main_window_module, "ConnectionDialog", FakeConnectionDialog)
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *args, **kwargs: calls.append((args, kwargs)) or QMessageBox.StandardButton.Yes,
    )
    FakeConnectionDialog.instances.clear()
    window = _window(_transaction_pending=True)
    window._persist_profile = lambda _profile, _config: None
    window._update_connection_status = lambda: None
    window.refresh_schema = lambda: None

    MainWindow.open_connection_dialog(window)

    assert len(calls) == 1
    assert FakeConnectionDialog.instances[0].executed is True
    assert window._transaction_pending is True

    MainWindow._switch_connection(window, {"id": "next"}, {"host": "new"}, {"database": "new_db"})

    assert window._transaction_pending is False
    assert window.profile == {"id": "next"}
    assert window.config == {"host": "new"}
