"""Offscreen regression tests for SQL completion and result filtering."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from mysql_editor.ui.editor import SqlEditor
from mysql_editor.ui.main_window import ResultsFilterProxyModel, ResultsModel


_APP = QApplication.instance() or QApplication([])


def test_completion_contains_mysql_keywords_functions_and_safe_schema_names():
    editor = SqlEditor()
    editor.set_completion_words(["customers", "order_items", "invalid-name", "table name"])
    candidates = set(editor.completion_words())
    assert {"SELECT", "WITH", "JSON_TABLE", "COUNT", "customers", "order_items"} <= candidates
    assert "invalid-name" not in candidates
    assert "table name" not in candidates


def test_result_filter_is_case_insensitive_and_does_not_mutate_source_rows():
    source = ResultsModel(
        headers=["id", "customer"],
        rows=[[2, "Bob"], [10, "Alice"], [30, "Alina"]],
    )
    proxy = ResultsFilterProxyModel()
    proxy.setSourceModel(source)
    proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    proxy.setFilterKeyColumn(-1)
    proxy.setFilterFixedString("ali")

    assert proxy.rowCount() == 2
    assert [proxy.index(row, 1).data() for row in range(proxy.rowCount())] == ["Alice", "Alina"]
    assert source.rows == [[2, "Bob"], [10, "Alice"], [30, "Alina"]]
    proxy.setFilterFixedString("bob")
    assert proxy.rowCount() == 1
    assert proxy.index(0, 1).data() == "Bob"


def test_result_proxy_keeps_numeric_sorting():
    source = ResultsModel(headers=["id"], rows=[[2], [10], [1]])
    proxy = ResultsFilterProxyModel()
    proxy.setSourceModel(source)
    proxy.sort(0, Qt.SortOrder.AscendingOrder)
    assert [proxy.index(row, 0).data() for row in range(proxy.rowCount())] == ["1", "2", "10"]
