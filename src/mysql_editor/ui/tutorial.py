"""Animated, keyboard-friendly quick-start tour for MySQL Editor."""
from __future__ import annotations

from PySide6.QtCore import QSettings, QEasingCurve, QPropertyAnimation, Qt
from mysql_editor.ui.animations import TOUR_DURATION_MS, reduce_motion_enabled
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)


class ProductTourDialog(QDialog):
    """A short, local tutorial with animated page changes and real editor actions."""

    def __init__(self, parent=None, repository=None, on_insert_example=None, settings=None):
        super().__init__(parent)
        self.repository = repository
        self._settings = settings if settings is not None else QSettings()
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
        for page_index, (_title, _intro, items) in enumerate(self._pages):
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
        for _i in range(len(self._pages)):
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

        # Animate the compact content stack, not the top-level native window.
        # This is more predictable across Windows window managers and easy to detach.
        self._fade: QPropertyAnimation | None = None
        self._fade_effect: QGraphicsOpacityEffect | None = None
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
            # Dynamic properties select the shared theme rule for both Light and Dark.
            # Repolish so Qt immediately applies the changed current/non-current state.
            style = label.style()
            style.unpolish(label)
            style.polish(label)
            label.update()

    def _go(self, index: int):
        index = max(0, min(index, len(self._pages) - 1))
        if index == self._index:
            return
        self._stop_page_transition()
        self._index = index
        self.pages.setCurrentIndex(index)
        self._render_page()
        if reduce_motion_enabled(self._settings):
            return

        effect = QGraphicsOpacityEffect(self.pages)
        effect.setOpacity(0.84)
        self.pages.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(TOUR_DURATION_MS)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(0.84)
        animation.setEndValue(1.0)
        animation.finished.connect(
            lambda: self._complete_page_transition(animation, effect)
        )
        self._fade_effect = effect
        self._fade = animation
        animation.start()

    def _complete_page_transition(
        self, animation: QPropertyAnimation, effect: QGraphicsOpacityEffect
    ) -> None:
        """Restore the page stack and detach an animation that reached its final state."""
        if self._fade is not animation:
            return
        self._fade = None
        if self._fade_effect is effect:
            animation.stop()
            animation.setTargetObject(None)
            self.pages.setGraphicsEffect(None)
            self._fade_effect = None
        animation.deleteLater()

    def _stop_page_transition(self) -> None:
        """Interrupt an active transition without leaving an opacity effect attached."""
        animation = self._fade
        effect = self._fade_effect
        self._fade = None
        self._fade_effect = None
        if animation is not None:
            animation.stop()
            animation.setTargetObject(None)
            animation.deleteLater()
        if effect is not None:
            self.pages.setGraphicsEffect(None)

    def _finish_animation(self):
        """Stop page motion and restore the content stack before closing."""
        self._stop_page_transition()

    def done(self, result: int) -> None:
        self._finish_animation()
        super().done(result)

    def closeEvent(self, event) -> None:
        self._finish_animation()
        super().closeEvent(event)

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
