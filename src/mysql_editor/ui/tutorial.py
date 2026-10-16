"""Animated, keyboard-friendly quick-start tour for MySQL Editor."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)


class ProductTourDialog(QDialog):
    """A short, local tutorial with animated page changes and real editor actions."""

    def __init__(self, parent=None, repository=None, on_insert_example=None):
        super().__init__(parent)
        self.repository = repository
        self.on_insert_example = on_insert_example
        self._index = 0
        self._pages = [
            (
                "Welcome to your SQL workspace",
                "A focused, local-first workbench for MySQL.",
                [
                    ("01", "Connect", "Choose a saved profile or enter a MySQL host and account."),
                    ("02", "Query", "Write SQL, run one statement, a selection, or the full script."),
                    ("03", "Inspect", "Explore schemas, review result sets, and export fetched rows."),
                ],
            ),
            (
                "Connect with confidence",
                "The app connects directly from this PC to your MySQL server.",
                [
                    ("Host", "127.0.0.1", "Use localhost for a local server, or your server address."),
                    ("Port", "3306", "Use the port configured for your MySQL server."),
                    ("TLS", "Choose intentionally", "Automatic TLS negotiates encryption; strict mode verifies identity."),
                ],
            ),
            (
                "Write and run SQL",
                "Start read-only while learning a database.",
                [
                    ("Ctrl + Enter", "Run statement", "Executes the statement under the editor cursor."),
                    ("Ctrl + Shift + Enter", "Run selection", "Executes only the highlighted SQL."),
                    ("Ctrl + Alt + Enter", "Run script", "Executes the complete SQL script in order."),
                ],
            ),
            (
                "Read results and explore schemas",
                "The editor stays responsive while database work runs in a background worker.",
                [
                    ("Schema", "Browse objects", "Refresh database names and double-click a table for a limited preview."),
                    ("Results", "Inspect data", "Switch between statement results, sort columns, and copy selected cells."),
                    ("CSV", "Export fetched rows", "Exports the complete fetched result set, not only the visible preview."),
                ],
            ),
            (
                "Credentials and safe habits",
                "Your master password protects this local app session; it is not the MySQL account password.",
                [
                    ("Master password", "Unlock this PC", "Only an Argon2id verifier is stored for the local app lock."),
                    ("Saved database password", "Windows Credential Manager", "When saving is enabled, the secret is stored in Windows' credential vault—not SQLite."),
                    ("Destructive SQL", "Review before running", "Confirmation prompts are advisory. Use least-privilege MySQL accounts and backups."),
                ],
            ),
        ]
        self.setWindowTitle("MySQL Editor — Guided Tour")
        self.setModal(True)
        self.setMinimumSize(680, 510)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 22)
        root.setSpacing(16)

        top = QHBoxLayout()
        brand = QLabel("MYSQL EDITOR  /  QUICK START")
        brand.setObjectName("tourEyebrow")
        self.step_label = QLabel()
        self.step_label.setObjectName("tourStep")
        top.addWidget(brand)
        top.addStretch(1)
        top.addWidget(self.step_label)
        root.addLayout(top)

        self.heading = QLabel()
        self.heading.setObjectName("tourTitle")
        self.heading.setWordWrap(True)
        root.addWidget(self.heading)
        self.intro = QLabel()
        self.intro.setObjectName("mutedText")
        self.intro.setWordWrap(True)
        root.addWidget(self.intro)

        self.pages = QStackedWidget()
        self.pages.setObjectName("tourPages")
        self.pages.setMinimumHeight(280)
        for page_index, (title, intro, items) in enumerate(self._pages):
            page = QWidget()
            page.setObjectName("tourPage")
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 6, 0, 6)
            layout.setSpacing(10)
            for number, item_title, detail in items:
                card = QFrame()
                card.setObjectName("tourCard")
                card_layout = QHBoxLayout(card)
                card_layout.setContentsMargins(14, 10, 14, 10)
                card_layout.setSpacing(12)
                number_label = QLabel(number)
                number_label.setObjectName("tourNumber")
                number_label.setMinimumWidth(66)
                card_layout.addWidget(number_label)
                words = QVBoxLayout()
                words.setSpacing(3)
                primary = QLabel(item_title)
                primary.setObjectName("tourCardTitle")
                primary.setWordWrap(True)
                secondary = QLabel(detail)
                secondary.setObjectName("tourCardBody")
                secondary.setWordWrap(True)
                words.addWidget(primary)
                words.addWidget(secondary)
                card_layout.addLayout(words, 1)
                layout.addWidget(card)
            if page_index == 2 and on_insert_example is not None:
                action = QPushButton("Insert a sample SELECT into the editor")
                action.setObjectName("primaryButton")
                action.setMinimumHeight(38)
                action.clicked.connect(on_insert_example)
                layout.addWidget(action)
            layout.addStretch(1)
            self.pages.addWidget(page)
        root.addWidget(self.pages, 1)

        self.progress = QHBoxLayout()
        self.progress.setSpacing(6)
        self.progress_labels = []
        for i in range(len(self._pages)):
            dot = QLabel("●")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setObjectName("tourProgress")
            self.progress.addWidget(dot)
            self.progress_labels.append(dot)
        self.progress.addStretch(1)
        root.addLayout(self.progress)

        footer = QHBoxLayout()
        self.skip_button = QPushButton("Skip tour")
        self.skip_button.clicked.connect(self._skip)
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(lambda: self._go(self._index - 1))
        self.next_button = QPushButton("Next step  →")
        self.next_button.setObjectName("primaryButton")
        self.next_button.setMinimumWidth(132)
        self.next_button.clicked.connect(self._next)
        footer.addWidget(self.skip_button)
        footer.addStretch(1)
        footer.addWidget(self.back_button)
        footer.addWidget(self.next_button)
        root.addLayout(footer)

        self._opacity = QGraphicsOpacityEffect(self.pages)
        self._opacity.setOpacity(1.0)
        self.pages.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(210)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._render_page()

    def _render_page(self):
        title, intro, _items = self._pages[self._index]
        self.heading.setText(title)
        self.intro.setText(intro)
        self.step_label.setText(f"STEP {self._index + 1} OF {len(self._pages)}")
        self.back_button.setEnabled(self._index > 0)
        self.next_button.setText("Finish tour  ✓" if self._index == len(self._pages) - 1 else "Next step  →")
        for index, label in enumerate(self.progress_labels):
            label.setProperty("current", index == self._index)
            label.setStyleSheet(
                "color: #50d9ee; font-size: 14px;" if index == self._index
                else "color: #4a607c; font-size: 12px;"
            )

    def _go(self, index: int):
        index = max(0, min(index, len(self._pages) - 1))
        if index == self._index:
            return
        self._index = index
        self.pages.setCurrentIndex(index)
        self._render_page()
        self._fade.stop()
        self._opacity.setOpacity(0.22)
        self._fade.setStartValue(0.22)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def _next(self):
        if self._index == len(self._pages) - 1:
            self._finish()
        else:
            self._go(self._index + 1)

    def _mark_complete(self):
        if self.repository is not None:
            self.repository.set_setting("guided_tour_completed", "true")

    def _finish(self):
        self._mark_complete()
        self.accept()

    def _skip(self):
        self._mark_complete()
        self.reject()
