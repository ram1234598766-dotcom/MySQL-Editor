"""Windows-only UI smoke test for preferences and file-operation recovery.

Run with QT_QPA_PLATFORM=offscreen on a Windows host with project dependencies installed.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication

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
        assert editor.font().pointSize() == 10

        first.increase_editor_font()
        assert editor.font().pointSize() == 11
        first.main_split.setSizes([440, 320])
        app.processEvents()
        first.inspector_tabs.setCurrentIndex(1)

        original_count = first.editors.count()
        missing_file = root / "missing-query.sql"
        with patch("mysql_editor.ui.main_window.QMessageBox.warning"):
            assert first._open_sql_path(missing_file) is False
        assert first.editors.count() == original_count

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
        first._current_editor().document().setModified(False)
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

        first.close()
        first_repo.close()
        settings.sync()
        assert int(settings.value("ui/editorFontSize", 0)) == 11
        assert int(settings.value("ui/inspectorTab", -1)) == 1
        saved_sizes = settings.value("ui/mainSplitterSizes", [])
        assert len(saved_sizes) == 2 and all(int(size) > 0 for size in saved_sizes)

        second, second_repo = make_window(root / "settings-two.sqlite3")
        second.show()
        app.processEvents()
        restored = second._current_editor()
        assert restored is not None and restored.font().pointSize() == 11
        assert second.inspector_tabs.currentIndex() == 1
        second.close()
        second_repo.close()
        app.quit()

    print("Qt UI smoke checks passed: preferences persist, missing files recover, failed saves preserve edits.")


if __name__ == "__main__":
    main()
