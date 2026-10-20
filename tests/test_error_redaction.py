"""Regression tests for sanitized database error presentation."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from mysql_editor.ui.main_window import MainWindow

_APP = QApplication.instance() or QApplication([])


class QueryOutcomeWindow:
    def __init__(self):
        self.query_meta = QLabel("")
        self.status = QLabel("")
        self.result_message = ""

    def _set_result_message(self, message):
        self.result_message = message


def test_failed_query_ui_does_not_expose_credentials_echoed_by_server():
    window = QueryOutcomeWindow()
    error = (
        "MySQL syntax error after CREATE USER 'reporter'@'%' "
        "IDENTIFIED BY 'sql-account-secret'; "
        "password=key-value-secret token:token-secret"
    )

    MainWindow._apply_query_outcome(window, "failed", {"ok": False, "error": error})

    for secret in ("sql-account-secret", "key-value-secret", "token-secret"):
        assert secret not in window.status.text()
        assert secret not in window.result_message
    assert "IDENTIFIED BY" in window.result_message
    assert "[REDACTED]" in window.result_message
    assert window.query_meta.text() == "Query failed"


def test_failed_query_ui_uses_safe_fallback_for_missing_error():
    window = QueryOutcomeWindow()

    MainWindow._apply_query_outcome(window, "failed", {"ok": False, "error": "\x00  "})

    assert window.status.text() == "Query failed."
    assert window.result_message == "Query failed."
    assert window.query_meta.text() == "Query failed"
