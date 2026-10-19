"""Tests for the explicit single-cell UPDATE confirmation dialog."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from mysql_editor.ui.cell_editor import EditTableCellDialog

_APP = QApplication.instance() or QApplication([])


def test_edit_dialog_keeps_sql_null_distinct_from_empty_text():
    dialog = EditTableCellDialog(
        schema="analytics",
        table="items",
        column="label",
        current_value=None,
        primary_key_summary="id=42",
    )
    try:
        assert dialog.set_null_checkbox.isChecked()
        assert dialog.value_editor.isDisabled()
        assert dialog.new_value() is None

        dialog.set_null_checkbox.setChecked(False)
        assert dialog.value_editor.isEnabled()
        assert dialog.value_editor.toPlainText() == ""
        assert dialog.new_value() == ""

        dialog.value_editor.setPlainText("new label")
        assert dialog.new_value() == "new label"

        dialog.set_null_checkbox.setChecked(True)
        assert dialog.new_value() is None
    finally:
        dialog.close()
        dialog.deleteLater()
        _APP.processEvents()


def test_edit_dialog_discloses_transaction_behavior_and_explicit_apply_action():
    dialog = EditTableCellDialog(
        schema="analytics",
        table="items",
        column="quantity",
        current_value=5,
        primary_key_summary="id=7",
    )
    try:
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        assert any("Only this non-primary-key cell" in text for text in labels)
        assert any("does not commit or roll back" in text for text in labels)
        assert dialog.apply_button.text() == "Apply UPDATE"
        assert dialog.cancel_button.accessibleName() == "Cancel cell edit"
        assert dialog.value_editor.toPlainText() == "5"
    finally:
        dialog.close()
        dialog.deleteLater()
        _APP.processEvents()
