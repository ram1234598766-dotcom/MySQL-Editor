"""Desktop application startup and shared product theme."""
from __future__ import annotations
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, Qt
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

from mysql_editor.ui.theme import stylesheet_for_theme

def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MySQL Editor")
    app.setOrganizationName("MySQL Editor")
    app.setStyle("Fusion")
    theme_preference = QSettings().value("ui/theme", "dark", type=str)
    app.setStyleSheet(stylesheet_for_theme(theme_preference))
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
