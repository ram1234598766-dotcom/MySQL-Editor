"""Regression coverage for theme-aware SQL NULL cell rendering."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from mysql_editor.ui.main_window import ResultsModel
from mysql_editor.ui.theme import color_for_theme


_APP = QApplication.instance() or QApplication([])


def test_null_cell_foreground_tracks_theme_without_mutating_results():
    model = ResultsModel(
        headers=["nullable_value", "empty_text"],
        rows=[[None, ""]],
        theme="dark",
    )
    try:
        null_index = model.index(0, 0)
        empty_index = model.index(0, 1)
        original_rows = model.rows
        updates = []
        model.dataChanged.connect(
            lambda top_left, bottom_right, roles: updates.append(
                (top_left, bottom_right, roles)
            )
        )

        assert model.data(null_index, Qt.ItemDataRole.DisplayRole) == "(NULL)"
        assert model.data(null_index, Qt.ItemDataRole.ForegroundRole) == QColor(
            color_for_theme("text_muted", "dark")
        )
        assert model.data(empty_index, Qt.ItemDataRole.DisplayRole) == ""
        assert model.data(empty_index, Qt.ItemDataRole.ForegroundRole) is None

        model.set_theme("light")

        assert model.rows is original_rows
        assert model.rows == [[None, ""]]
        assert model.data(null_index, Qt.ItemDataRole.ForegroundRole) == QColor(
            color_for_theme("text_muted", "light")
        )
        assert updates
        assert Qt.ItemDataRole.ForegroundRole in updates[-1][2]
    finally:
        model.deleteLater()
        _APP.processEvents()
