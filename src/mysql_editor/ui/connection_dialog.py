"""Connect dialog and first-run master-password setup."""
from __future__ import annotations
import uuid
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)
from mysql_editor.core import redact_secrets
from mysql_editor.storage import (
    ConnectionProfile, CredentialStore, LocalRepository, MasterPasswordStore,
    duplicate_profile_name, new_profile_id,
)
from mysql_editor.ui.tutorial import ProductTourDialog

class ConnectionDialog(QDialog):
    connected = Signal(dict, dict, dict)
    TLS_OPTIONS = ["Automatic TLS", "Verify server identity", "Disabled"]

    def __init__(
        self, worker, repository: LocalRepository, credentials: CredentialStore, parent=None,
        *, master_unlocked: bool = False, preferred_profile_id: str | None = None,
    ):
        super().__init__(parent)
        self.master_unlocked = master_unlocked
        self.preferred_profile_id = preferred_profile_id
        self.worker = worker
        self.repository = repository
        self.credentials = credentials
        self.master = MasterPasswordStore(repository)
        self._pending: dict[str, str] = {}
        self._pending_config: dict[str, dict] = {}
        self._profile_id: str | None = None
        self.setWindowTitle("Connect to MySQL — MySQL Editor")
        self.setModal(True)
        self.setMinimumWidth(540)
        self.setMaximumWidth(660)
        self.setMinimumHeight(665)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._build_ui()
        self.worker.completed.connect(self._on_worker_completed)
        self._load_profiles()
        self._update_master_mode()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setFixedSize(48, 48)
        self._set_logo(logo)
        brand.addWidget(logo)
        text = QVBoxLayout()
        title = QLabel("Connect to MySQL")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("A direct connection from this PC to your database.")
        subtitle.setObjectName("mutedText")
        text.addWidget(title)
        text.addWidget(subtitle)
        brand.addLayout(text, 1)
        root.addLayout(brand)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("separator")
        root.addWidget(divider)

        self.profile = QComboBox()
        self.profile.addItem("+ New connection", "")
        self.profile.currentIndexChanged.connect(self._profile_selected)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Saved profile"))
        profile_row.addWidget(self.profile, 1)
        self.duplicate_profile_button = QPushButton("Duplicate")
        self.duplicate_profile_button.setAccessibleName("Duplicate saved connection profile")
        self.duplicate_profile_button.setToolTip("Copy the selected profile into a new unsaved connection.")
        self.duplicate_profile_button.clicked.connect(self._duplicate_profile)
        self.delete_profile_button = QPushButton("Delete")
        self.delete_profile_button.setAccessibleName("Delete saved connection profile")
        self.delete_profile_button.setToolTip("Delete the selected profile and its stored database password.")
        self.delete_profile_button.clicked.connect(self._delete_profile)
        profile_row.addWidget(self.duplicate_profile_button)
        profile_row.addWidget(self.delete_profile_button)
        root.addLayout(profile_row)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(9)
        self.profile_name = QLineEdit("Local MySQL")
        self.host = QLineEdit("127.0.0.1")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(3306)
        self.username = QLineEdit("root")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Database account password")
        self.schema = QLineEdit()
        self.schema.setPlaceholderText("Optional default database")
        self.tls = QComboBox()
        self.tls.addItems(self.TLS_OPTIONS)
        self.tls_hint = QLabel()
        self.tls_hint.setWordWrap(True)
        self.tls_hint.setObjectName("noticeText")
        self.tls.currentTextChanged.connect(self._update_tls_hint)
        self.ca_file = QLineEdit()
        self.ca_file.setPlaceholderText("Optional CA file for strict verification")
        ca_row = QHBoxLayout()
        ca_row.addWidget(self.ca_file, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_ca)
        ca_row.addWidget(browse)
        self.read_timeout = QSpinBox()
        self.read_timeout.setRange(5, 3600)
        self.read_timeout.setValue(60)
        self.write_timeout = QSpinBox()
        self.write_timeout.setRange(5, 3600)
        self.write_timeout.setValue(30)
        form.addRow("Profile name", self.profile_name)
        form.addRow("Host / IP address", self.host)
        form.addRow("Port", self.port)
        form.addRow("Username", self.username)
        form.addRow("Database password", self.password)
        form.addRow("Default schema", self.schema)
        form.addRow("TLS policy", self.tls)
        form.addRow("CA certificate", ca_row)
        timeout_row = QHBoxLayout()
        timeout_row.addWidget(QLabel("Read"))
        timeout_row.addWidget(self.read_timeout)
        timeout_row.addSpacing(8)
        timeout_row.addWidget(QLabel("Write"))
        timeout_row.addWidget(self.write_timeout)
        form.addRow("Timeout (seconds)", timeout_row)
        root.addLayout(form)
        root.addWidget(self.tls_hint)

        security = QFrame()
        security.setObjectName("securityCard")
        security_form = QFormLayout(security)
        security_form.setContentsMargins(14, 10, 14, 10)
        self.master_label = QLabel("Create local master password")
        self.master_password = QLineEdit()
        self.master_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.master_password.setPlaceholderText("At least 10 characters")
        self.confirm_label = QLabel("Confirm master password")
        self.master_confirm = QLineEdit()
        self.master_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.master_confirm.setPlaceholderText("Type it again to confirm")
        security_form.addRow(self.master_label, self.master_password)
        security_form.addRow(self.confirm_label, self.master_confirm)
        self.security_card = security
        root.addWidget(security)
        self.save_profile_check = QCheckBox(
            "Remember this connection and save its password in Windows Credential Manager"
        )
        self.save_profile_check.setChecked(True)
        root.addWidget(self.save_profile_check)
        self.status = QLabel("The local master password unlocks this app on this PC. It is not your MySQL password.")
        self.status.setObjectName("mutedText")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        buttons = QHBoxLayout()
        self.tour_button = QPushButton("Guided tour")
        self.tour_button.clicked.connect(self._show_product_tour)
        self.test_button = QPushButton("Test connection")
        self.test_button.clicked.connect(self._test_connection)
        self.save_profile_button = QPushButton("Save profile")
        self.save_profile_button.setToolTip("Save profile settings without connecting to the MySQL server.")
        self.save_profile_button.clicked.connect(self._save_profile)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.clicked.connect(self._connect)
        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(self.reject)
        buttons.addWidget(self.tour_button)
        buttons.addWidget(self.test_button)
        buttons.addWidget(self.save_profile_button)
        buttons.addStretch(1)
        buttons.addWidget(self.exit_button)
        buttons.addWidget(self.connect_button)
        root.addLayout(buttons)
        self._update_tls_hint()

    @staticmethod
    def _logo_candidates() -> list[Path]:
        import sys
        roots = [Path(__file__).resolve().parents[3], Path(getattr(sys, "_MEIPASS", "."))]
        return [
            root / "assets" / filename
            for root in roots
            for filename in ("mysql-editor-logo-transparent.png", "mysql-editor-logo.webp")
        ]

    def _set_logo(self, label: QLabel):
        for path in self._logo_candidates():
            if path.is_file():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    label.setPixmap(pixmap.scaled(
                        44, 44, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
                    return

    def _load_profiles(self):
        preferred = self.preferred_profile_id or self.repository.get_setting("last_profile_id")
        self._reload_profiles(preferred)

    def _reload_profiles(self, selected_profile_id: str | None = None, *, apply_selection: bool = True):
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.addItem("+ New connection", "")
        profiles = self.repository.profiles()
        for item in profiles:
            self.profile.addItem(
                f"{item.name} — {item.username}@{item.host}:{item.port}", item.id
            )
        index = self.profile.findData(selected_profile_id) if selected_profile_id else 0
        if index < 0:
            index = 0
        self.profile.setCurrentIndex(index)
        self.profile.blockSignals(False)
        if apply_selection:
            self._profile_selected(index)

    def _reset_profile_fields(self):
        self._profile_id = None
        self.profile_name.setText("Local MySQL")
        self.host.setText("127.0.0.1")
        self.port.setValue(3306)
        self.username.setText("root")
        self.password.clear()
        self.schema.clear()
        self.tls.setCurrentText("Automatic TLS")
        self.ca_file.clear()
        self.read_timeout.setValue(60)
        self.write_timeout.setValue(30)
        self.save_profile_check.setChecked(True)
        self._update_profile_action_buttons()

    def _update_profile_action_buttons(self):
        has_saved_profile = bool(self._profile_id)
        self.duplicate_profile_button.setEnabled(has_saved_profile)
        self.delete_profile_button.setEnabled(has_saved_profile)

    def _duplicate_profile(self):
        if not self._profile_id:
            return
        existing = [profile.name for profile in self.repository.profiles()]
        new_name = duplicate_profile_name(self.profile_name.text(), existing)
        self.profile.blockSignals(True)
        self.profile.setCurrentIndex(0)
        self.profile.blockSignals(False)
        self._profile_id = None
        self.profile_name.setText(new_name)
        self._update_profile_action_buttons()
        self.status.setText(
            "Profile copied into a new connection draft. Save profile to keep it, "
            "or Connect to test and use it."
        )

    def _delete_profile(self):
        profile_id = self._profile_id
        if not profile_id:
            return
        profile_name = self.profile_name.text().strip() or "this profile"
        answer = QMessageBox.question(
            self,
            "Delete saved profile",
            f"Delete '{profile_name}' and its saved database password from Windows Credential Manager? "
            "This cannot be undone. An existing connected session will not be disconnected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.credentials.delete(profile_id)
        except Exception as exc:
            QMessageBox.warning(
                self, "Profile not deleted",
                "The saved password could not be removed securely, so the profile metadata was kept. "
                "No plaintext fallback was used.\n\n" + redact_secrets(str(exc)),
            )
            return
        try:
            self.repository.delete_profile(profile_id)
            if self.repository.get_setting("last_profile_id") == profile_id:
                self.repository.set_setting("last_profile_id", "")
        except Exception as exc:
            QMessageBox.warning(
                self, "Profile metadata not deleted",
                "The credential entry was removed, but the local profile metadata could not be deleted.\n\n"
                + redact_secrets(str(exc)),
            )
            return

        self._reload_profiles(None)
        self.status.setText(
            f"Deleted saved profile '{profile_name}' and its Credential Manager entry. "
            "Any active connection remains open."
        )

    def _save_profile(self):
        config = self._validate()
        if config is None:
            return
        if not self.repository.has_master_password:
            try:
                self.master.create(self.master_password.text(), self.master_confirm.text())
            except ValueError as exc:
                QMessageBox.warning(self, "Master password", str(exc))
                return

        profile_id = self._profile_id or new_profile_id()
        profile = ConnectionProfile(
            id=profile_id,
            name=config["profile_name"],
            host=config["host"],
            port=config["port"],
            username=config["username"],
            default_schema=config["default_schema"],
            tls_mode=config["tls_mode"],
            ca_file=config["ca_file"],
            read_timeout=config["read_timeout"],
            write_timeout=config["write_timeout"],
        )
        try:
            self.repository.save_profile(profile)
        except Exception as exc:
            QMessageBox.warning(
                self, "Profile not saved",
                "Profile metadata could not be saved locally.\n\n" + redact_secrets(str(exc)),
            )
            return

        credential_error = ""
        if config["save_profile"]:
            try:
                self.credentials.save(profile_id, config["password"])
            except Exception as exc:
                credential_error = redact_secrets(str(exc))
        self._profile_id = profile_id
        self._reload_profiles(profile_id, apply_selection=False)
        if credential_error:
            message = (
                "Profile details were saved locally, but the database password was not saved in "
                "Windows Credential Manager. Enter it manually next time. No plaintext fallback was used.\n\n"
                + credential_error
            )
            self.status.setText("Profile saved · password not saved securely.")
            QMessageBox.warning(self, "Password not saved", message)
        elif config["save_profile"]:
            self.status.setText("Profile and database password saved securely in Windows Credential Manager.")
        else:
            self.status.setText(
                "Profile metadata saved locally. Password saving is unchecked; this action did not "
                "change any existing Credential Manager entry."
            )
        self._update_profile_action_buttons()

    def _update_master_mode(self):
        first = not self.repository.has_master_password
        self.security_card.setVisible(not self.master_unlocked)
        self.master_label.setText("Create local master password" if first else "Master password")
        self.master_password.setPlaceholderText("At least 10 characters" if first else "Unlock MySQL Editor")
        self.master_confirm.setVisible(first)
        self.confirm_label.setVisible(first)
        if self.master_unlocked:
            self.status.setText(
                "Master password verified for this session. Database passwords are saved only in "
                "Windows Credential Manager when you enable connection saving."
            )

    def _update_tls_hint(self, *_):
        hints = {
            "Automatic TLS": "Negotiates TLS when supported. No certificate is required, but server identity is not verified in this mode.",
            "Verify server identity": "Enables certificate and hostname verification. Supply a CA file only for a private certificate authority.",
            "Disabled": "Disables TLS explicitly. Use only on trusted local networks; traffic is not encrypted.",
        }
        self.tls_hint.setText(hints[self.tls.currentText()])

    def _browse_ca(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select certificate authority file", "",
            "Certificates (*.pem *.crt *.cer);;All files (*)",
        )
        if path:
            self.ca_file.setText(path)

    def _profile_selected(self, index: int):
        profile_id = self.profile.itemData(index)
        if not profile_id:
            self._reset_profile_fields()
            return
        saved = next((p for p in self.repository.profiles() if p.id == profile_id), None)
        if not saved:
            return
        self._profile_id = saved.id
        self._update_profile_action_buttons()
        self.profile_name.setText(saved.name)
        self.host.setText(saved.host)
        self.port.setValue(saved.port)
        self.username.setText(saved.username)
        self.schema.setText(saved.default_schema)
        self.tls.setCurrentText(saved.tls_mode if saved.tls_mode in self.TLS_OPTIONS else "Automatic TLS")
        self.ca_file.setText(saved.ca_file)
        self.read_timeout.setValue(saved.read_timeout)
        self.write_timeout.setValue(saved.write_timeout)
        try:
            self.password.setText(self.credentials.read(saved.id) or "")
        except Exception:
            self.password.clear()

    def _config(self) -> dict:
        return {
            "profile_name": self.profile_name.text().strip() or "MySQL connection",
            "host": self.host.text().strip() or "127.0.0.1",
            "port": self.port.value(), "username": self.username.text().strip(),
            "password": self.password.text(), "default_schema": self.schema.text().strip(),
            "tls_mode": self.tls.currentText(), "ca_file": self.ca_file.text().strip(),
            "read_timeout": self.read_timeout.value(), "write_timeout": self.write_timeout.value(),
            "save_profile": self.save_profile_check.isChecked(),
        }

    def _validate(self) -> dict | None:
        config = self._config()
        if not config["username"]:
            QMessageBox.warning(self, "Username required", "Enter the MySQL account username.")
            return None
        if config["tls_mode"] == "Verify server identity" and config["ca_file"]:
            if not Path(config["ca_file"]).is_file():
                QMessageBox.warning(self, "Certificate file not found", "Select an existing CA certificate file.")
                return None
        if not self.master_unlocked:
            if not self.repository.has_master_password:
                try:
                    self.master.validate(self.master_password.text())
                    if self.master_password.text() != self.master_confirm.text():
                        raise ValueError("The master password and confirmation do not match.")
                except ValueError as exc:
                    QMessageBox.warning(self, "Master password", str(exc))
                    return None
            elif not self.master.verify(self.master_password.text()):
                QMessageBox.warning(self, "Master password", "The master password is incorrect.")
                return None
        return config

    def _queue(self, action: str, config: dict):
        task_id = uuid.uuid4().hex
        self._pending[task_id] = action
        self._pending_config[task_id] = config
        self._set_busy(True, "Testing connection…" if action == "test" else "Connecting…")
        self.worker.submit(action, {"config": config}, task_id)

    def _show_product_tour(self):
        ProductTourDialog(self, self.repository).exec()

    def _test_connection(self):
        config = self._validate()
        if config is not None:
            self._queue("test", config)

    def _connect(self):
        config = self._validate()
        if config is None:
            return
        if not self.repository.has_master_password:
            try:
                self.master.create(self.master_password.text(), self.master_confirm.text())
            except ValueError as exc:
                QMessageBox.warning(self, "Master password", str(exc))
                return
        profile_id = self._profile_id or new_profile_id()
        config["profile_id"] = profile_id
        self._queue("connect", config)

    def _set_busy(self, busy: bool, message: str):
        self.status.setText(message)
        self.connect_button.setEnabled(not busy)
        self.test_button.setEnabled(not busy)
        self.exit_button.setEnabled(not busy)
        self.tour_button.setEnabled(not busy)
        self.profile.setEnabled(not busy)

    def _on_worker_completed(self, task_id: str, action: str, result: dict):
        expected = self._pending.pop(task_id, None)
        config = self._pending_config.pop(task_id, None)
        if expected is None or config is None:
            return
        self._set_busy(False, "Ready.")
        if not result.get("ok"):
            self.status.setText(result.get("error", "Connection failed."))
            return
        if expected == "test":
            self.status.setText(f"Test succeeded — MySQL {result.get('server_version', 'server')} is reachable.")
            return
        profile_id = config.get("profile_id") or new_profile_id()
        profile = {
            "id": profile_id, "name": config["profile_name"], "host": config["host"],
            "port": config["port"], "username": config["username"],
            "default_schema": config["default_schema"], "tls_mode": config["tls_mode"],
            "ca_file": config["ca_file"], "read_timeout": config["read_timeout"],
            "write_timeout": config["write_timeout"],
        }
        self.connected.emit(profile, config, result)
        self.accept()
