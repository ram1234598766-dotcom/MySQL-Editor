"""Tests for saved connection profile actions and secret handling."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from mysql_editor.storage import ConnectionProfile, LocalRepository, MasterPasswordStore
from mysql_editor.ui.connection_dialog import ConnectionDialog


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
