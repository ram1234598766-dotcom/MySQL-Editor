"""Non-blocking, persistent feedback for CSV export outcomes."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from mysql_editor.ui.main_window import CSV_EXPORT_SEMANTICS, MainWindow


_APP = QApplication.instance() or QApplication([])


class FeedbackWindow:
    def __init__(self):
        self.status = QLabel("Query complete · 25 ms.")
        self.export_feedback = QLabel("")
        self.export_feedback.hide()

    def show_export(self, result, *, update_status=True):
        MainWindow._show_export_notification(self, result, update_status=update_status)


def test_csv_export_success_is_persistent_and_non_modal():
    window = FeedbackWindow()
    path = r"C:\reports\monthly report.csv"

    window.show_export({"ok": True, "row_count": 12_345, "path": path})

    assert window.export_feedback.isVisible()
    assert window.export_feedback.objectName() == "statusSuccess"
    assert "12,345 row(s)" in window.export_feedback.text()
    assert path in window.export_feedback.text()
    assert "grid sorting" in window.export_feedback.text().lower()
    assert path in window.export_feedback.toolTip()
    assert CSV_EXPORT_SEMANTICS in window.export_feedback.accessibleDescription()
    assert window.status.text() == (
        "CSV exported · 12,345 row(s); saved path shown in Results."
    )


def test_deferred_csv_feedback_does_not_overwrite_newer_query_status():
    window = FeedbackWindow()
    window.status.setText("Query complete · 250 ms.")

    window.show_export(
        {"ok": True, "row_count": 3, "path": r"C:\tmp\result.csv"},
        update_status=False,
    )

    assert window.status.text() == "Query complete · 250 ms."
    assert window.export_feedback.isVisible()
    assert "3 row(s)" in window.export_feedback.text()


def test_csv_export_failure_is_visible_and_redacts_secrets():
    window = FeedbackWindow()

    window.show_export({
        "ok": False,
        "error": "Could not write CREATE USER 'app'@'%' IDENTIFIED BY 'sql-export-secret'; password=supersecret to the selected file.",
    })

    assert window.export_feedback.isVisible()
    assert window.export_feedback.objectName() == "statusDanger"
    assert "CSV export failed" in window.export_feedback.text()
    assert "supersecret" not in window.export_feedback.text()
    assert "sql-export-secret" not in window.export_feedback.text()
    assert "sql-export-secret" not in window.export_feedback.toolTip()
    assert window.status.text() == "CSV export failed · see details in Results."
