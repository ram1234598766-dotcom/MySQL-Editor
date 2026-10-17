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



def test_context_completion_suggests_tables_after_from_and_databases_after_use():
    editor = SqlEditor()
    editor.set_completion_context(
        databases={"analytics", "app_db"},
        tables={"customers", "orders"},
        columns_by_table={"customers": ["customer_id", "display_name"], "orders": ["order_id"]},
        extra_words={"result_label"},
        active_schema="app_db",
    )

    editor.setPlainText("SELECT * FROM ")
    cursor = editor.textCursor()
    cursor.setPosition(len(editor.toPlainText()))
    editor.setTextCursor(cursor)
    table_candidates = set(editor._context_completion_words())
    assert {"customers", "orders"} <= table_candidates
    assert "customer_id" not in table_candidates
    assert "COUNT" not in table_candidates

    editor.setPlainText("USE ")
    cursor = editor.textCursor()
    cursor.setPosition(len(editor.toPlainText()))
    editor.setTextCursor(cursor)
    database_candidates = set(editor._context_completion_words())
    assert {"analytics", "app_db"} <= database_candidates
    assert "customers" not in database_candidates


def test_context_completion_suggests_columns_for_table_alias_without_mutating_sql():
    editor = SqlEditor()
    source = "SELECT o.order_i FROM orders AS o JOIN customers c ON c.customer_id = o.order_id"
    editor.set_completion_context(
        databases={"app_db"},
        tables={"orders", "customers"},
        columns_by_table={"orders": ["order_id", "order_total"], "customers": ["customer_id", "display_name"]},
        active_schema="app_db",
    )
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(source.index("order_i") + len("order_i"))
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())
    assert {"order_id", "order_total"} <= candidates
    assert "customer_id" not in candidates
    assert editor.toPlainText() == source


def test_context_completion_falls_back_when_schema_metadata_is_unavailable():
    editor = SqlEditor()
    editor.setPlainText("SELECT cou")
    editor.set_completion_context()
    candidates = set(editor._context_completion_words())
    assert {"SELECT", "COUNT"} <= candidates
    assert editor.toPlainText() == "SELECT cou"
