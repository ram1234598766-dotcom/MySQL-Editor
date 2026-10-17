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


def test_sql_editor_exposes_accessible_identity_and_keyboard_help():
    editor = SqlEditor()
    assert editor.accessibleName() == "SQL query editor"
    assert "Ctrl+Space" in editor.accessibleDescription()
    assert "matching brackets" in editor.accessibleDescription()


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


def test_sql_null_values_sort_last_in_both_directions():
    source = ResultsModel(headers=["id"], rows=[[None], [2], [10], [1], [None]])
    proxy = ResultsFilterProxyModel()
    proxy.setSourceModel(source)

    proxy.sort(0, Qt.SortOrder.AscendingOrder)
    assert [proxy.index(row, 0).data() for row in range(proxy.rowCount())] == [
        "1", "2", "10", "(NULL)", "(NULL)"
    ]

    proxy.sort(0, Qt.SortOrder.DescendingOrder)
    assert [proxy.index(row, 0).data() for row in range(proxy.rowCount())] == [
        "10", "2", "1", "(NULL)", "(NULL)"
    ]


def test_source_model_null_values_sort_last_in_both_directions():
    source = ResultsModel(headers=["id"], rows=[[None], [2], [10], [1], [None]])

    source.sort(0, Qt.SortOrder.AscendingOrder)
    assert source.rows == [[1], [2], [10], [None], [None]]

    source.update(["id"], [[None], [2], [10], [1], [None]])
    source.sort(0, Qt.SortOrder.DescendingOrder)
    assert source.rows == [[10], [2], [1], [None], [None]]



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


def test_unqualified_column_completion_scopes_to_current_statement_tables():
    editor = SqlEditor()
    editor.set_completion_context(
        tables={"customers", "orders", "inventory"},
        columns_by_table={
            "customers": ["customer_id", "display_name"],
            "orders": ["order_id", "order_total"],
            "inventory": ["sku", "warehouse_code"],
        },
        extra_words={"result_label"},
    )

    source = (
        "SELECT disp FROM customers c "
        "JOIN orders o ON c.customer_id = o.order_id WHERE "
    )
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(source.index("disp") + len("disp"))
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())
    assert {"display_name", "customer_id", "order_id", "order_total"} <= candidates
    assert "warehouse_code" not in candidates
    assert "sku" not in candidates
    assert "result_label" in candidates
    assert editor.toPlainText() == source

    next_source = "SELECT ware FROM inventory i WHERE "
    editor.setPlainText(next_source)
    cursor = editor.textCursor()
    cursor.setPosition(len(next_source))
    editor.setTextCursor(cursor)
    candidates = set(editor._context_completion_words())
    assert "warehouse_code" in candidates
    assert "customer_id" not in candidates


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


def _send_text_key(editor, key, text, modifiers=Qt.KeyboardModifier.NoModifier):
    event = QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text)
    QApplication.sendEvent(editor, event)
    _APP.processEvents()


def test_bracket_auto_pairing_covers_parentheses_square_and_curly_brackets():
    cases = [
        (Qt.Key.Key_ParenLeft, "(", ")"),
        (Qt.Key.Key_BracketLeft, "[", "]"),
        (Qt.Key.Key_BraceLeft, "{", "}"),
    ]
    for key, opening, closing in cases:
        editor = SqlEditor()
        editor.setPlainText("SELECT ")
        cursor = editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        editor.setTextCursor(cursor)

        modifiers = (
            Qt.KeyboardModifier.ShiftModifier if opening == "{" else Qt.KeyboardModifier.NoModifier
        )
        _send_text_key(editor, key, opening, modifiers)

        assert editor.toPlainText() == "SELECT " + opening + closing
        assert editor.textCursor().position() == len("SELECT ") + 1

        close_key = {
            ")": Qt.Key.Key_ParenRight,
            "]": Qt.Key.Key_BracketRight,
            "}": Qt.Key.Key_BraceRight,
        }[closing]
        close_modifiers = (
            Qt.KeyboardModifier.ShiftModifier if closing == "}" else Qt.KeyboardModifier.NoModifier
        )
        _send_text_key(editor, close_key, closing, close_modifiers)
        assert editor.toPlainText() == "SELECT " + opening + closing
        assert editor.textCursor().position() == len("SELECT ") + 2
        editor.deleteLater()


def test_bracket_auto_pairing_wraps_selection_and_preserves_multiline_content():
    editor = SqlEditor()
    source = "SELECT value FROM customers"
    editor.setPlainText(source)
    cursor = editor.textCursor()
    start = source.index("value")
    cursor.setPosition(start)
    cursor.setPosition(start + len("value"), QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)

    _send_text_key(editor, Qt.Key.Key_ParenLeft, "(")

    assert editor.toPlainText() == "SELECT (value) FROM customers"
    assert editor.textCursor().position() == start + len("value") + 1

    editor.setPlainText("SELECT value\nFROM customers")
    pasted = "SELECT (\n  value\n)"
    editor.clear()
    editor.insertPlainText(pasted)
    assert editor.toPlainText() == pasted
    editor.deleteLater()


def test_bracket_auto_pairing_does_not_run_inside_sql_strings_or_comments():
    cases = [
        ("SELECT 'value'", "value", Qt.Key.Key_ParenLeft, "("),
        ('SELECT "value"', "value", Qt.Key.Key_ParenLeft, "("),
        ("SELECT `value`", "value", Qt.Key.Key_ParenLeft, "("),
        ("SELECT 1 -- comment", "comment", Qt.Key.Key_ParenLeft, "("),
        ("SELECT /* comment */ 1", "comment", Qt.Key.Key_ParenLeft, "("),
    ]
    for source, token, key, typed in cases:
        editor = SqlEditor()
        editor.setPlainText(source)
        cursor = editor.textCursor()
        cursor.setPosition(source.index(token) + len(token) // 2)
        editor.setTextCursor(cursor)

        before = editor.toPlainText()
        insertion_position = cursor.position()
        _send_text_key(editor, key, typed)

        assert editor.toPlainText() == (
            before[:insertion_position] + typed + before[insertion_position:]
        )
        assert editor.toPlainText().count(typed) == before.count(typed) + 1
        assert editor.toPlainText().count(")") == before.count(")")
        editor.deleteLater()


def test_bracket_auto_pairing_uses_qt_utf16_cursor_offsets_with_unicode():
    editor = SqlEditor()
    editor.setPlainText("SELECT '🧡'; SELECT ")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)

    _send_text_key(editor, Qt.Key.Key_ParenLeft, "(")

    assert editor.toPlainText() == "SELECT '🧡'; SELECT ()"
    assert editor.textCursor().position() == editor.document().characterCount() - 2
    editor.deleteLater()
