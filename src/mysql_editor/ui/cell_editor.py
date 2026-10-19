"""Explicit, single-cell editor for eligible Schema Explorer table previews."""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class EditTableCellDialog(QDialog):
    """Prepare one explicit cell update; applying it never commits the transaction."""

    def __init__(
        self,
        *,
        schema: str,
        table: str,
        column: str,
        current_value: Any,
        primary_key_summary: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.schema = str(schema)
        self.table = str(table)
        self.column = str(column)
        self.current_value = current_value

        self.setWindowTitle(f"Edit cell · {self.column}")
        self.setMinimumSize(560, 390)
        self.resize(720, 500)

        layout = QVBoxLayout(self)
        heading = QLabel(f"{self.schema}.{self.table} · {self.column}", self)
        heading.setObjectName("panelTitle")
        heading.setAccessibleName("Table cell being edited")
        layout.addWidget(heading)

        details = QLabel(
            f"Row identity: {primary_key_summary}\n"
            "Only this non-primary-key cell will be updated. The statement is parameterized; "
            "table/column names and row identity are revalidated before MySQL receives it.",
            self,
        )
        details.setWordWrap(True)
        details.setObjectName("mutedText")
        layout.addWidget(details)

        warning = QLabel(
            "This writes to the connected MySQL session. It does not commit or roll back. "
            "Use Commit to persist the current transaction or Rollback to undo its pending changes.",
            self,
        )
        warning.setWordWrap(True)
        warning.setObjectName("statusWarning")
        warning.setAccessibleName("Cell edit transaction warning")
        layout.addWidget(warning)

        self.value_editor = QPlainTextEdit(self)
        self.value_editor.setObjectName("editTableCellValue")
        self.value_editor.setAccessibleName(f"New value for column {self.column}")
        self.value_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.value_editor.setPlaceholderText("Enter the new value. Leave blank for an empty string.")
        self.value_editor.setPlainText("" if current_value is None else str(current_value))
        layout.addWidget(self.value_editor, 1)

        self.set_null_checkbox = QCheckBox("Set SQL NULL (different from an empty string)", self)
        self.set_null_checkbox.setObjectName("editTableCellSetNull")
        self.set_null_checkbox.setAccessibleName("Set value to SQL NULL")
        self.set_null_checkbox.setChecked(current_value is None)
        self.set_null_checkbox.toggled.connect(self.value_editor.setDisabled)
        self.value_editor.setDisabled(current_value is None)
        layout.addWidget(self.set_null_checkbox)

        buttons = QDialogButtonBox(self)
        self.apply_button = buttons.addButton(
            "Apply UPDATE", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.apply_button.setObjectName("applyTableCellUpdate")
        self.apply_button.setAccessibleName("Apply one table cell UPDATE")
        self.cancel_button = buttons.addButton(
            QDialogButtonBox.StandardButton.Cancel
        )
        self.cancel_button.setAccessibleName("Cancel cell edit")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def new_value(self) -> str | None:
        """Return None only when SQL NULL was explicitly selected."""
        if self.set_null_checkbox.isChecked():
            return None
        return self.value_editor.toPlainText()
