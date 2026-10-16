"""Minimal startup gate: the master password is the only required input."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from mysql_editor.storage import LocalRepository, MasterPasswordStore


class MasterUnlockDialog(QDialog):
    """Verify the local master password without exposing connection credentials."""

    def __init__(self, repository: LocalRepository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.master = MasterPasswordStore(repository)
        self.is_unlocked = False
        self.setWindowTitle("Unlock MySQL Editor")
        self.setModal(True)
        self.setFixedWidth(460)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 24)
        root.setSpacing(14)
        logo = QLabel("MYSQL EDITOR")
        logo.setObjectName("brandTitle")
        root.addWidget(logo)
        title = QLabel("Welcome back")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        intro = QLabel("Enter your local master password to unlock your saved connection.")
        intro.setObjectName("mutedText")
        intro.setWordWrap(True)
        root.addWidget(intro)

        card = QFrame()
        card.setObjectName("securityCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        self.password = QLineEdit()
        self.password.setObjectName("masterPassword")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Master password")
        self.password.setAccessibleName("Local master password")
        self.password.returnPressed.connect(self._unlock)
        card_layout.addWidget(self.password)
        self.status = QLabel("Database passwords, when saved, remain in Windows Credential Manager.")
        self.status.setObjectName("mutedText")
        self.status.setWordWrap(True)
        card_layout.addWidget(self.status)
        root.addWidget(card)

        buttons = QHBoxLayout()
        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(self.reject)
        self.unlock_button = QPushButton("Unlock  →")
        self.unlock_button.setObjectName("primaryButton")
        self.unlock_button.setMinimumHeight(40)
        self.unlock_button.clicked.connect(self._unlock)
        buttons.addWidget(self.exit_button)
        buttons.addStretch(1)
        buttons.addWidget(self.unlock_button)
        root.addLayout(buttons)

    def _unlock(self):
        if self.master.verify(self.password.text()):
            self.is_unlocked = True
            self.accept()
            return
        self.password.clear()
        self.status.setText("That master password didn't match. Try again.")
        self.password.setFocus()
