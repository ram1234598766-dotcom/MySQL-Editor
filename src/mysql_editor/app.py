"""Desktop application startup and shared product theme."""
from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox
from mysql_editor.database import DatabaseWorker
from mysql_editor.storage import CredentialStore, ConnectionProfile, LocalRepository
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
QToolButton#navButton { text-align: left; background: transparent; border: 1px solid transparent; padding: 8px 10px; }
QToolButton#navButton:hover { background: #192639; border-color: #405675; }
QSplitter::handle { background: #2e425a; width: 1px; height: 1px; }
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
    windows = {"main": None}

    def on_connected(profile: dict, config: dict, result: dict):
        if config.get("save_profile"):
            try:
                repository.save_profile(ConnectionProfile(**profile))
                credentials.save(profile["id"], config.get("password", ""))
            except Exception as exc:
                QMessageBox.warning(
                    None, "Profile not saved",
                    "Connected successfully, but the connection could not be saved to secure storage. "
                    "The password was not written to a plaintext file.\n\n" + str(exc),
                )
        window = MainWindow(worker, repository, credentials, profile, config, result)
        windows["main"] = window
        window.show()

    dialog = ConnectionDialog(worker, repository, credentials)
    dialog.connected.connect(on_connected)
    dialog.show()
    exit_code = app.exec()
    if worker.isRunning():
        worker.shutdown()
        worker.wait(5000)
    repository.close()
    return exit_code

if __name__ == "__main__":
    raise SystemExit(main())
