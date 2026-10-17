"""Compact, keyboard-first Find/Replace bar for SQL text."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget


def count_matches(text: str, query: str, case_sensitive: bool = False) -> int:
    """Return non-overlapping literal matches without interpreting SQL as a regex."""
    if not query:
        return 0
    flags = 0 if case_sensitive else re.IGNORECASE
    return sum(1 for _ in re.finditer(re.escape(query), text, flags))


class FindReplaceBar(QWidget):
    """Inline search controls; query text stays untouched when the bar is dismissed."""

    search_changed = Signal(str, bool)
    find_next_requested = Signal()
    find_previous_requested = Signal()
    replace_requested = Signal()
    replace_all_requested = Signal()
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("findReplaceBar")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(5)

        find_row = QHBoxLayout()
        find_row.setSpacing(6)
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("findInput")
        self.search_input.setPlaceholderText("Find in this query…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setAccessibleName("Find text in SQL query")
        self.search_input.setToolTip("Find literal text in the current SQL editor.")
        self.match_count = QLabel("No matches", self)
        self.match_count.setObjectName("findMatchCount")
        self.match_count.setMinimumWidth(82)
        self.match_count.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.previous_button = QPushButton("↑", self)
        self.previous_button.setObjectName("findPreviousButton")
        self.previous_button.setAccessibleName("Find previous")
        self.previous_button.setToolTip("Find previous match.")
        self.next_button = QPushButton("↓", self)
        self.next_button.setObjectName("findNextButton")
        self.next_button.setAccessibleName("Find next")
        self.next_button.setToolTip("Find next match. Press Enter in the search field.")
        self.match_case_checkbox = QCheckBox("Match case", self)
        self.match_case_checkbox.setObjectName("matchCaseCheckBox")
        self.match_case_checkbox.setAccessibleName("Match case")
        self.close_button = QPushButton("×", self)
        self.close_button.setAccessibleName("Close Find/Replace")
        self.close_button.setToolTip("Close Find/Replace and return focus to the SQL editor.")

        find_row.addWidget(self.search_input, 1)
        find_row.addWidget(self.match_count)
        find_row.addWidget(self.previous_button)
        find_row.addWidget(self.next_button)
        find_row.addWidget(self.match_case_checkbox)
        find_row.addWidget(self.close_button)
        layout.addLayout(find_row)

        self.replace_row = QWidget(self)
        replace_layout = QHBoxLayout(self.replace_row)
        replace_layout.setContentsMargins(0, 0, 0, 0)
        replace_layout.setSpacing(6)
        self.replace_input = QLineEdit(self.replace_row)
        self.replace_input.setObjectName("replaceInput")
        self.replace_input.setPlaceholderText("Replace with…")
        self.replace_input.setClearButtonEnabled(True)
        self.replace_input.setAccessibleName("Replacement text")
        self.replace_button = QPushButton("Replace", self.replace_row)
        self.replace_button.setAccessibleName("Replace current match")
        self.replace_button.setToolTip("Replace the selected matching text, or select the next match.")
        self.replace_all_button = QPushButton("Replace all", self.replace_row)
        self.replace_all_button.setAccessibleName("Replace all matches")
        replace_layout.addWidget(QLabel("Replace with", self.replace_row))
        replace_layout.addWidget(self.replace_input, 1)
        replace_layout.addWidget(self.replace_button)
        replace_layout.addWidget(self.replace_all_button)
        layout.addWidget(self.replace_row)
        self.replace_row.hide()
        self.hide()

        self.search_input.textChanged.connect(self._emit_search_changed)
        self.match_case_checkbox.toggled.connect(self._emit_search_changed)
        self.search_input.returnPressed.connect(self.find_next_requested.emit)
        self.replace_input.returnPressed.connect(self.replace_requested.emit)
        self.previous_button.clicked.connect(self.find_previous_requested.emit)
        self.next_button.clicked.connect(self.find_next_requested.emit)
        self.replace_button.clicked.connect(self.replace_requested.emit)
        self.replace_all_button.clicked.connect(self.replace_all_requested.emit)
        self.close_button.clicked.connect(self.close_bar)

        self._escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        self._escape_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._escape_shortcut.activated.connect(self.close_bar)

    def _emit_search_changed(self, *_):
        self.search_changed.emit(self.search_text(), self.match_case())

    def show_bar(self, replace: bool = False, seed_text: str | None = None):
        self.replace_row.setVisible(replace)
        if seed_text is not None:
            self.search_input.setText(seed_text)
        self.setVisible(True)
        self.search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_input.selectAll()
        self._emit_search_changed()

    def close_bar(self):
        self.hide()
        self.closed.emit()

    def search_text(self) -> str:
        return self.search_input.text()

    def replacement_text(self) -> str:
        return self.replace_input.text()

    def match_case(self) -> bool:
        return self.match_case_checkbox.isChecked()

    def set_match_count(self, count: int):
        count = max(0, int(count))
        if count == 0:
            text = "No matches"
        elif count == 1:
            text = "1 match"
        else:
            text = f"{count:,} matches"
        self.match_count.setText(text)
        self.match_count.setToolTip(text)
