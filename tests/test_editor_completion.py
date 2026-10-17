"""Offscreen regression tests for SQL completion and result filtering."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import QApplication

from mysql_editor.ui.editor import SqlEditor, _matching_bracket_positions
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



def _send_key(editor, key):
    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(editor, event)
    _APP.processEvents()


def test_enter_and_tab_accept_current_completion_without_changing_other_sql():
    for key in (Qt.Key.Key_Return, Qt.Key.Key_Tab):
        editor = SqlEditor()
        editor.setPlainText("SELECT cou FROM customers")
        cursor = editor.textCursor()
        cursor.setPosition(len("SELECT cou"))
        editor.setTextCursor(cursor)
        editor._completion_model.setStringList(["COUNT", "COALESCE"])
        editor._completer.setCompletionPrefix("CO")
        editor._completer.popup().setCurrentIndex(editor._completer.completionModel().index(0, 0))
        editor._completer.popup().show()
        _send_key(editor, key)

        assert editor.toPlainText() == "SELECT COUNT FROM customers"
        assert not editor._completer.popup().isVisible()


def test_escape_dismisses_completion_without_changing_sql():
    editor = SqlEditor()
    source = "SELECT cou"
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(len(source))
    editor.setTextCursor(cursor)
    editor._completion_model.setStringList(["COUNT", "COALESCE"])
    editor._completer.setCompletionPrefix("CO")
    editor._completer.popup().setCurrentIndex(editor._completer.completionModel().index(0, 0))
    editor._completer.popup().show()

    _send_key(editor, Qt.Key.Key_Escape)

    assert editor.toPlainText() == source
    assert not editor._completer.popup().isVisible()


def test_enter_carries_existing_sql_indentation():
    editor = SqlEditor()
    editor.setPlainText("    SELECT * FROM customers")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)

    _send_key(editor, Qt.Key.Key_Return)

    assert editor.toPlainText() == "    SELECT * FROM customers\n    "


def test_enter_indents_after_open_parenthesis_and_begin_block():
    for source in ("SELECT * FROM (", "BEGIN"):
        editor = SqlEditor()
        editor.setPlainText(source)
        cursor = editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        editor.setTextCursor(cursor)

        _send_key(editor, Qt.Key.Key_Return)

        assert editor.toPlainText() == source + "\n    "


def test_bracket_matching_handles_nested_pairs_and_ignores_strings_and_comments():
    sql = (
        "SELECT wrap((x + y)), '(ignored)', /* (ignored) */ z -- (ignored)\n"
        "WHERE [column_name] = 1"
    )
    opening = sql.index("wrap(") + len("wrap")
    closing = sql.index(")),") + 1
    assert _matching_bracket_positions(sql, opening + 1) == (opening, closing)

    quoted_bracket = sql.index("'(ignored)'") + 1
    block_comment_bracket = sql.index("/* (ignored) */") + 3
    line_comment_bracket = sql.index("-- (ignored)") + 3
    assert _matching_bracket_positions(sql, quoted_bracket) is None
    assert _matching_bracket_positions(sql, block_comment_bracket) is None
    assert _matching_bracket_positions(sql, line_comment_bracket) is None


def test_bracket_matching_works_backwards_and_rejects_unmatched_or_malformed_pairs():
    sql = "SELECT ([column_name])"
    opening = sql.index("(")
    closing = sql.rindex(")")
    assert _matching_bracket_positions(sql, closing + 1) == (opening, closing)

    unmatched = "SELECT (value"
    assert _matching_bracket_positions(unmatched, unmatched.index("(")) is None

    malformed = "SELECT ([value)"
    assert _matching_bracket_positions(malformed, malformed.index("(")) is None

def _send_text_key(editor, key, text):
    event = QKeyEvent(
        QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text
    )
    QApplication.sendEvent(editor, event)
    _APP.processEvents()


def test_parentheses_auto_pair_and_close_bracket_skip_over():
    editor = SqlEditor()
    editor.setPlainText("SELECT ")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)

    _send_text_key(editor, Qt.Key.Key_ParenLeft, "(")

    assert editor.toPlainText() == "SELECT ()"
    assert editor.textCursor().position() == len("SELECT (")

    _send_text_key(editor, Qt.Key.Key_ParenRight, ")")

    assert editor.toPlainText() == "SELECT ()"
    assert editor.textCursor().position() == len("SELECT ()")


def test_parentheses_auto_pair_wraps_selected_expression_without_losing_selection():
    editor = SqlEditor()
    editor.setPlainText("SELECT customer_id FROM customers")
    cursor = editor.textCursor()
    start = len("SELECT ")
    end = start + len("customer_id")
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)

    _send_text_key(editor, Qt.Key.Key_ParenLeft, "(")

    assert editor.toPlainText() == "SELECT (customer_id) FROM customers"
    assert editor.textCursor().selectedText() == "customer_id"


def test_parentheses_are_not_auto_paired_inside_strings_or_comments():
    cases = [
        ("SELECT 'value'", len("SELECT 'val"), "SELECT 'val("),
        ('SELECT "value"', len('SELECT "val'), 'SELECT "val('),
        ("SELECT " + chr(96) + "column" + chr(96), len("SELECT " + chr(96) + "col"),
         "SELECT " + chr(96) + "col("),
        ("SELECT value /* comment */", len("SELECT value /* com"), "SELECT value /* com("),
        ("SELECT value -- comment", len("SELECT value -- com"), "SELECT value -- com("),
        ("SELECT value # comment", len("SELECT value # com"), "SELECT value # com("),
    ]
    for source, position, expected in cases:
        editor = SqlEditor()
        editor.setPlainText(source)
        cursor = editor.textCursor()
        cursor.setPosition(position)
        editor.setTextCursor(cursor)

        _send_text_key(editor, Qt.Key.Key_ParenLeft, "(")

        assert editor.toPlainText() == expected


def test_pasted_parentheses_are_not_auto_paired_or_modified():
    editor = SqlEditor()
    pasted = "SELECT (customer_id)\nFROM customers"
    editor.insertPlainText(pasted)

    assert editor.toPlainText() == pasted


def test_lexical_code_position_handles_escaped_quotes_and_mysql_comments():
    from mysql_editor.ui.editor import _is_sql_code_position

    escaped = "SELECT 'abc" + chr(92) + "' still string"
    assert _is_sql_code_position(escaped, len("SELECT 'abc" + chr(92) + "'")) is False
    assert _is_sql_code_position("SELECT 'abc' + ", len("SELECT 'abc' + ")) is True
    assert _is_sql_code_position("SELECT 1 -- comment\n", len("SELECT 1 -- comment\n")) is True
    assert _is_sql_code_position("SELECT 1 -- comment\\n", len("SELECT 1 -- comment\\n")) is True
    assert _is_sql_code_position("SELECT 1 /* comment */ + ", len("SELECT 1 /* comment */ + ")) is True


