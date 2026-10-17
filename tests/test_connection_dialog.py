"""Tests for saved connection profile actions and secret handling."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from mysql_editor.storage import ConnectionProfile, LocalRepository, MasterPasswordStore
from mysql_editor.ui.connection_dialog import ConnectionDialog
from mysql_editor.ui.unlock_dialog import MasterUnlockDialog


class StubWorker(QObject):
    completed = Signal(str, str, object)

    def submit(self, action, payload=None, task_id=None):
        return task_id or "stub-task"


class FakeCredentials:
    def __init__(self):
        self.passwords: dict[str, str] = {}
        self.deleted: list[str] = []

    def save(self, profile_id: str, password: str):
        self.passwords[profile_id] = password

    def read(self, profile_id: str):
        return self.passwords.get(profile_id)

    def delete(self, profile_id: str):
        self.deleted.append(profile_id)
        self.passwords.pop(profile_id, None)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog_context(tmp_path: Path, app):
    repository = LocalRepository(tmp_path / "profiles.sqlite3")
    credentials = FakeCredentials()
    profile = ConnectionProfile(
        id="analytics-profile",
        name="Analytics",
        host="db.example.test",
        port=3307,
        username="reporter",
        default_schema="analytics",
    )
    repository.save_profile(profile)
    MasterPasswordStore(repository).create("valid master password", "valid master password")
    credentials.save(profile.id, "sample-secret")
    worker = StubWorker()
    dialog = ConnectionDialog(
        worker, repository, credentials, master_unlocked=True,
        preferred_profile_id=profile.id,
    )
    yield dialog, repository, credentials
    dialog.close()
    repository.close()


def test_duplicate_profile_creates_a_new_unsaved_draft(dialog_context):
    dialog, repository, _credentials = dialog_context
    assert dialog._profile_id == "analytics-profile"
    dialog._duplicate_profile()

    assert dialog._profile_id is None
    assert dialog.profile.currentData() == ""
    assert dialog.profile_name.text() == "Analytics copy"
    assert dialog.host.text() == "db.example.test"
    assert dialog.port.value() == 3307
    assert dialog.username.text() == "reporter"
    assert dialog.schema.text() == "analytics"
    assert dialog.password.text() == "sample-secret"
    assert len(repository.profiles()) == 1


def test_save_profile_updates_metadata_and_uses_credential_store(dialog_context, monkeypatch):
    dialog, repository, credentials = dialog_context
    dialog.profile_name.setText("Analytics reporting")
    dialog.host.setText("db-new.example.test")
    dialog._save_profile()

    profiles = repository.profiles()
    saved = next(profile for profile in profiles if profile.id == "analytics-profile")
    assert saved.name == "Analytics reporting"
    assert saved.host == "db-new.example.test"
    assert credentials.passwords["analytics-profile"] == "sample-secret"
    assert dialog.profile.currentData() == "analytics-profile"
    assert dialog._profile_id == "analytics-profile"


def test_delete_profile_requires_confirmation_and_removes_credential(dialog_context, monkeypatch):
    dialog, repository, credentials = dialog_context
    repository.set_setting("last_profile_id", "analytics-profile")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    dialog._delete_profile()

    assert repository.profiles() == []
    assert "analytics-profile" in credentials.deleted
    assert repository.get_setting("last_profile_id") == ""
    assert dialog._profile_id is None
    assert dialog.profile.currentData() == ""


def test_cancel_delete_leaves_saved_profile_and_credential(dialog_context, monkeypatch):
    dialog, repository, credentials = dialog_context
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
    )

    dialog._delete_profile()

    assert len(repository.profiles()) == 1
    assert credentials.passwords["analytics-profile"] == "sample-secret"
    assert credentials.deleted == []



def test_connection_dialog_controls_have_accessible_names_and_visual_keyboard_order(
    dialog_context, app,
):
    dialog, _repository, _credentials = dialog_context
    controls = (
        dialog.profile,
        dialog.duplicate_profile_button,
        dialog.delete_profile_button,
        dialog.profile_name,
        dialog.host,
        dialog.port,
        dialog.username,
        dialog.password,
        dialog.schema,
        dialog.tls,
        dialog.ca_file,
        dialog.browse_ca_button,
        dialog.read_timeout,
        dialog.write_timeout,
        dialog.master_password,
        dialog.master_confirm,
        dialog.save_profile_check,
        dialog.tour_button,
        dialog.test_button,
        dialog.save_profile_button,
        dialog.exit_button,
        dialog.connect_button,
    )
    missing = [
        type(control).__name__
        for control in controls
        if not control.accessibleName().strip()
    ]
    assert not missing, f"Interactive connection controls need accessible names: {missing}"

    dialog.show()
    app.processEvents()
    visible_controls = [
        control for control in controls
        if control.isVisible() and control.isEnabled()
    ]
    assert visible_controls
    first = visible_controls[0]
    first.setFocus(Qt.FocusReason.OtherFocusReason)
    app.processEvents()
    assert app.focusWidget() is first
    for current, expected in zip(visible_controls, visible_controls[1:], strict=False):
        QTest.keyClick(current, Qt.Key.Key_Tab)
        app.processEvents()
        assert app.focusWidget() is expected, (
            f"Tab from {current.accessibleName()!r} should focus "
            f"{expected.accessibleName()!r}"
        )


def test_unlock_dialog_controls_have_accessible_names_and_keyboard_order(tmp_path, app):
    repository = LocalRepository(tmp_path / "unlock-accessibility.sqlite3")
    dialog = MasterUnlockDialog(repository)
    try:
        assert dialog.accessibleName() == "Unlock MySQL Editor"
        assert dialog.password.accessibleName() == "Local master password"
        assert dialog.status.accessibleName() == "Master password verification status"
        assert dialog.exit_button.accessibleName() == "Exit MySQL Editor"
        assert dialog.unlock_button.accessibleName() == "Unlock MySQL Editor"

        dialog.show()
        app.processEvents()
        dialog.password.setFocus(Qt.FocusReason.OtherFocusReason)
        app.processEvents()
        assert app.focusWidget() is dialog.password
        QTest.keyClick(dialog.password, Qt.Key.Key_Tab)
        app.processEvents()
        assert app.focusWidget() is dialog.exit_button
        QTest.keyClick(dialog.exit_button, Qt.Key.Key_Tab)
        app.processEvents()
        assert app.focusWidget() is dialog.unlock_button
    finally:
        dialog.close()
        repository.close()
