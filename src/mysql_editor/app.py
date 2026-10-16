"""Desktop application startup and shared product theme."""
from __future__ import annotations
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog, QProgressDialog
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox
from mysql_editor.core import redact_secrets
from mysql_editor.database import DatabaseWorker
from mysql_editor.storage import (
    CredentialStore, ConnectionProfile, LocalRepository,
    connection_config_from_profile, profile_to_dict,
)
from mysql_editor.ui.unlock_dialog import MasterUnlockDialog
from mysql_editor.ui.connection_dialog import ConnectionDialog
from mysql_editor.ui.main_window import MainWindow

STYLESHEET = """
* { font-family: "Segoe UI"; font-size: 12px; }
QMainWindow, QDialog, QWidget { background: #0b111b; color: #e8f1ff; }
QMenuBar { background: #121a27; color: #e8f1ff; padding: 4px 10px; border-bottom: 1px solid #2c3a50; }
QMenuBar::item { padding: 6px 9px; border-radius: 5px; }
QMenuBar::item:selected, QMenu { background: #172235; }
QMenu { border: 1px solid #344761; padding: 5px; }
QMenu::item { padding: 7px 25px 7px 12px; border-radius: 4px; }
QMenu::item:selected { background: #2569cb; color: white; }
QLabel { color: #e8f1ff; }
QLabel#mutedText { color: #a9bad0; }
QLabel#noticeText { color: #d3e1f5; background: #111e2f; border: 1px solid #405675; border-radius: 7px; padding: 9px; }
QLabel#dialogTitle { font-size: 20px; font-weight: 650; }
QLabel#brandTitle { font-size: 17px; font-weight: 700; }
QLabel#brandSubtitle { color: #9cb0cc; font-size: 9px; font-weight: 650; letter-spacing: 1px; }
QLabel#logoMark { color: #47c8e1; font-size: 28px; font-weight: 700; }
QLabel#pageTitle { font-size: 23px; font-weight: 700; }
QLabel#panelTitle { font-size: 13px; font-weight: 650; }
QLabel#sectionLabel { color: #aabbd2; font-size: 10px; font-weight: 700; padding: 4px 8px; }
QLabel#connectionBadge { color: #3bd49b; background: #142d2b; border: 1px solid #426d62; border-radius: 8px; padding: 7px 10px; }
QLabel#statusBar { background: #121a27; color: #c0ccdc; border-top: 1px solid #354760; padding: 7px 13px; }
QLabel#securityNotice, QFrame#securityCard { background: #151f2e; border: 1px solid #405675; border-radius: 9px; padding: 10px; color: #c0ccdc; }
QFrame#separator { color: #40516a; max-height: 1px; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTreeWidget, QListWidget {
  background: #080e17; color: #e8f1ff; border: 1px solid #405675;
  border-radius: 6px; padding: 7px; selection-background-color: #286cc7;
  selection-color: white; min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTreeWidget:focus, QListWidget:focus { border: 1px solid #4a9bff; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #101a29; color: #e8f1ff; selection-background-color: #2569cb; }
QPushButton { background: #172235; color: #e8f1ff; border: 1px solid #405675; border-radius: 7px; padding: 8px 11px; min-height: 19px; }
QPushButton:hover { background: #22334b; border-color: #87a4ca; }
QPushButton:pressed { background: #0b1422; }
QPushButton:disabled { color: #8293a9; background: #121a26; border-color: #35465c; }
QPushButton#primaryButton { background: #2879e8; color: white; border: 1px solid #438fff; font-weight: 650; }
QPushButton#primaryButton:hover { background: #3987f0; }
QWidget#workspaceNavigation { background: #0d1522; border-bottom: 1px solid #263951; }
QToolButton#navButton { text-align: center; background: transparent; color: #aebed2; border: 1px solid transparent; border-radius: 8px; padding: 9px 13px; }
QToolButton#navButton:hover { background: #18273b; color: #eef6ff; border-color: #354b65; }
QToolButton#navButton:checked { background: #132b42; color: #62dff0; border: 1px solid #285c77; }
QToolButton#navButton:focus { border: 1px solid #5bbdff; }
QLabel#navHint { color: #7187a3; font-size: 9px; font-weight: 650; letter-spacing: 1px; padding-right: 5px; }
QLabel#connectionDetails { color: #a7bad1; font-size: 10px; }
QSplitter::handle { background: #263e58; width: 5px; height: 5px; }
QSplitter::handle:hover { background: #4a9bff; }
QLabel#tourEyebrow { color: #58dcec; font-weight: 700; font-size: 10px; letter-spacing: 1.2px; }
QLabel#tourStep { color: #91a9c4; font-weight: 700; font-size: 10px; }
QLabel#tourTitle { color: #f0f6ff; font-size: 23px; font-weight: 700; }
QFrame#tourCard { background: #111d2d; border: 1px solid #2d425b; border-radius: 10px; }
QLabel#tourNumber { color: #5ddbec; font-size: 10px; font-weight: 750; }
QLabel#tourCardTitle { color: #edf5ff; font-weight: 650; font-size: 12px; }
QLabel#tourCardBody { color: #adc0d5; font-size: 11px; }
QWidget#tourPage { background: transparent; }
QLabel#tourProgress { padding: 0 2px; }
QTabWidget::pane { background: #090f19; border: 1px solid #405675; border-radius: 7px; top: -1px; }
QTabBar::tab { background: #172235; color: #b6c5d9; padding: 9px 12px; border: 1px solid #354760; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 3px; }
QTabBar::tab:selected { background: #090f19; color: #e8f1ff; border-bottom-color: #090f19; }
QTableView { background: #0b121d; alternate-background-color: #101b2a; color: #e8f1ff; gridline-color: #354760; border: 1px solid #405675; selection-background-color: #1d4f88; selection-color: white; }
QHeaderView::section { background: #172235; color: #cad7e7; border: none; border-bottom: 1px solid #405675; padding: 8px; font-weight: 650; }
QTreeWidget, QListWidget { border: none; }
QTreeWidget::item, QListWidget::item { min-height: 25px; padding: 4px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #205ca4; border-radius: 4px; }
QScrollBar:vertical { background: #101927; width: 12px; margin: 1px; }
QScrollBar::handle:vertical { background: #486181; border-radius: 5px; min-height: 24px; }
QScrollBar:horizontal { background: #101927; height: 12px; margin: 1px; }
QScrollBar::handle:horizontal { background: #486181; border-radius: 5px; min-width: 24px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked { background: #080e17; border: 1px solid #6b829e; border-radius: 3px; }
QCheckBox::indicator:checked { background: #2879e8; border: 1px solid #438fff; border-radius: 3px; }
"""

def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MySQL Editor")
    app.setOrganizationName("MySQL Editor")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    for base in (Path(__file__).resolve().parents[2], Path(getattr(sys, "_MEIPASS", "."))):
        icon_path = base / "assets" / "mysql-editor.ico"
        if icon_path.is_file():
            app.setWindowIcon(QIcon(str(icon_path)))
            break

    repository = LocalRepository()
    credentials = CredentialStore()
    worker = DatabaseWorker()
    worker.start()
    windows: dict[str, object] = {"main": None, "connection": None, "reconnect": None}

    def on_connected(profile: dict, config: dict, result: dict):
        if config.get("save_profile"):
            try:
                repository.save_profile(ConnectionProfile(**profile))
                credentials.save(profile["id"], config.get("password", ""))
                repository.set_setting("last_profile_id", profile["id"])
            except Exception as exc:
                if repository.get_setting("last_profile_id") == profile["id"]:
                    repository.set_setting("last_profile_id", "")
                QMessageBox.warning(
                    None, "Connection not remembered",
                    "Connected successfully, but this connection could not be saved securely. "
                    "Its password was not written to a plaintext file.\n\n" + redact_secrets(str(exc)),
                )
        else:
            # Respect the user's decision not to remember this connection.
            repository.set_setting("last_profile_id", "")

        window = MainWindow(worker, repository, credentials, profile, config, result)
        windows["main"] = window
        window.show()
        if repository.get_setting("guided_tour_completed", "false") != "true":
            QTimer.singleShot(450, window._show_product_tour)

    def show_connection_dialog(
        *, master_unlocked: bool = False, preferred_profile_id: str | None = None,
        message: str | None = None,
    ):
        dialog = ConnectionDialog(
            worker, repository, credentials, master_unlocked=master_unlocked,
            preferred_profile_id=preferred_profile_id,
        )
        dialog.connected.connect(on_connected)
        if message:
            dialog.status.setText(message)
        windows["connection"] = dialog
        dialog.show()

    # On repeat launches, unlock the local app first. Then reconnect to the last
    # remembered profile using the credential vault; no database password is typed
    # unless the saved credential is missing, unavailable, or rejected by MySQL.
    if not repository.has_master_password:
        show_connection_dialog()
    else:
        unlock = MasterUnlockDialog(repository)
        if unlock.exec() != QDialog.DialogCode.Accepted or not unlock.is_unlocked:
            worker.shutdown()
            worker.wait(5000)
            repository.close()
            return 0

        last_profile_id = repository.get_setting("last_profile_id")
        profile = next(
            (item for item in repository.profiles() if item.id == last_profile_id),
            None,
        )
        if profile is None:
            show_connection_dialog(
                master_unlocked=True,
                message="Master password verified. Select a connection or create a new profile.",
            )
        else:
            try:
                saved_password = credentials.read(profile.id)
            except Exception:
                saved_password = None

            if saved_password is None:
                show_connection_dialog(
                    master_unlocked=True,
                    preferred_profile_id=profile.id,
                    message=(
                        "Master password verified. The database password wasn't available in "
                        "Windows Credential Manager; enter it to reconnect and save it again."
                    ),
                )
            else:
                config = connection_config_from_profile(profile, saved_password)
                progress = QProgressDialog(
                    f"Unlock successful. Reconnecting to {profile.name}…", "", 0, 0,
                )
                progress.setWindowTitle("MySQL Editor")
                progress.setWindowModality(Qt.WindowModality.ApplicationModal)
                progress.setCancelButton(None)
                progress.setMinimumDuration(0)
                progress.setAutoClose(False)
                windows["reconnect"] = progress
                progress.show()
                app.processEvents()
                task_id = uuid.uuid4().hex

                def finish_auto_connect(completed_id: str, action: str, result: dict):
                    if completed_id != task_id or action != "connect":
                        return
                    try:
                        worker.completed.disconnect(finish_auto_connect)
                    except (RuntimeError, TypeError):
                        pass
                    progress.close()
                    windows["reconnect"] = None
                    if result.get("ok"):
                        on_connected(profile_to_dict(profile), config, result)
                    else:
                        show_connection_dialog(
                            master_unlocked=True,
                            preferred_profile_id=profile.id,
                            message=(
                                "Automatic reconnection failed: "
                                + redact_secrets(result.get("error", "MySQL connection failed."))
                                + "\nCheck the database password/server, then reconnect below."
                            ),
                        )

                worker.completed.connect(finish_auto_connect)
                worker.submit("connect", {"config": config}, task_id)

    exit_code = app.exec()
    if worker.isRunning():
        worker.shutdown()
        worker.wait(5000)
    repository.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
