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



def test_completion_is_suppressed_inside_sql_strings_and_comments(monkeypatch):
    editor = SqlEditor()
    calls = []
    monkeypatch.setattr(editor._completer, "complete", lambda *_args: calls.append(True))

    for sql, marker in (
        ("SELECT 'customers';", "customer"),
        ("SELECT 1 -- customer", "customer"),
        ("/* SELECT customers */", "customers"),
    ):
        editor.setPlainText(sql)
        cursor = editor.textCursor()
        cursor.setPosition(sql.index(marker) + len(marker) - 1)
        editor.setTextCursor(cursor)
        editor._show_completion(force=True)
        assert editor._context_completion_words() == ()

    assert calls == []
    assert not editor._completer.popup().isVisible()


def test_completion_remains_available_in_sql_code(monkeypatch):
    editor = SqlEditor()
    editor.set_completion_context(tables={"customers"}, active_schema="app_db")
    editor.setPlainText("SELECT * FROM cus")
    cursor = editor.textCursor()
    cursor.setPosition(len(editor.toPlainText()))
    editor.setTextCursor(cursor)
    calls = []
    monkeypatch.setattr(editor._completer, "complete", lambda *_args: calls.append(True))

    editor._show_completion(force=True)

    assert calls == [True]


def test_completion_context_handles_unicode_before_cursor():
    editor = SqlEditor()
    editor.set_completion_context(
        tables={"orders", "customers"},
        columns_by_table={"orders": ["order_id"], "customers": ["display_name"]},
        active_schema="app_db",
    )
    sql = "SELECT '😀'; SELECT o.displ FROM customers AS c JOIN orders AS o ON c.id = o.id"
    editor.setPlainText(sql)
    target = sql.index("displ") + len("displ")
    cursor = editor.textCursor()
    cursor.setPosition(target + 1)  # Qt cursor offsets count UTF-16 code units.
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())
    assert "order_id" in candidates
    assert "display_name" not in candidates

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



def test_qualified_completion_ignores_aliases_inside_strings_comments_and_prior_statements():
    editor = SqlEditor()
    editor.set_completion_context(
        tables={"orders", "customers"},
        columns_by_table={
            "orders": ["order_id", "order_total"],
            "customers": ["customer_id", "display_name"],
        },
    )
    source = (
        "SELECT 'FROM orders o'; /* FROM orders o */ "
        "SELECT o.order_i FROM customers AS c"
    )
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(source.index("order_i") + len("order_i"))
    editor.setTextCursor(cursor)

    assert editor._context_completion_words() == ()
    assert editor.toPlainText() == source


def test_qualified_completion_resolves_schema_qualified_backtick_alias():
    editor = SqlEditor()
    editor.set_completion_context(
        tables={"orders", "customers"},
        columns_by_table={
            "orders": ["order_id", "order_total"],
            "customers": ["customer_id", "display_name"],
        },
        active_schema="app_db",
    )
    source = (
        "SELECT ord.order_i FROM `app_db`.`orders` AS ord "
        "JOIN `customers` AS c ON c.customer_id = ord.order_id"
    )
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(source.index("order_i") + len("order_i"))
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())
    assert {"order_id", "order_total"} <= candidates
    assert "customer_id" not in candidates
    assert "display_name" not in candidates
    assert editor.toPlainText() == source


def test_schema_qualified_table_completion_is_limited_to_the_requested_schema():
    editor = SqlEditor()
    editor.set_completion_context(
        databases={"app_db", "analytics"},
        tables={"customers", "orders"},
        columns_by_table={"customers": ["customer_id"], "orders": ["app_order_id"]},
        active_schema="app_db",
        tables_by_schema={
            "app_db": {"customers", "orders"},
            "analytics": {"events", "orders"},
        },
        columns_by_schema_and_table={
            "app_db": {"customers": ["customer_id"], "orders": ["app_order_id"]},
            "analytics": {"events": ["event_id"], "orders": ["analytics_order_id"]},
        },
    )
    source = "SELECT * FROM `analytics`.`eve"
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(len(source))
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())

    assert {"events", "orders"} <= candidates
    assert "customers" not in candidates
    assert "customer_id" not in candidates
    assert editor.toPlainText() == source


def test_schema_qualified_column_completion_does_not_leak_same_named_table_columns():
    editor = SqlEditor()
    editor.set_completion_context(
        databases={"app_db", "analytics"},
        tables={"orders"},
        columns_by_table={"orders": ["app_order_id"]},
        active_schema="app_db",
        tables_by_schema={
            "app_db": {"orders"},
            "analytics": {"orders"},
        },
        columns_by_schema_and_table={
            "app_db": {"orders": ["app_order_id"]},
            "analytics": {"orders": ["analytics_order_id"]},
        },
    )
    source = "SELECT analytics.orders.analytics_ FROM `analytics`.`orders`"
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(source.index("analytics_") + len("analytics_"))
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())

    assert "analytics_order_id" in candidates
    assert "app_order_id" not in candidates
    assert editor.toPlainText() == source


def test_alias_of_schema_qualified_table_uses_its_own_schema_columns():
    editor = SqlEditor()
    editor.set_completion_context(
        databases={"app_db", "analytics"},
        tables={"orders"},
        columns_by_table={"orders": ["app_order_id"]},
        active_schema="app_db",
        tables_by_schema={
            "app_db": {"orders"},
            "analytics": {"orders"},
        },
        columns_by_schema_and_table={
            "app_db": {"orders": ["app_order_id"]},
            "analytics": {"orders": ["analytics_order_id"]},
        },
    )
    source = "SELECT o.analytics_ FROM `analytics`.`orders` AS o"
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(source.index("analytics_") + len("analytics_"))
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())

    assert "analytics_order_id" in candidates
    assert "app_order_id" not in candidates
    assert editor.toPlainText() == source


def test_table_completion_is_available_while_typing_backtick_identifier():
    editor = SqlEditor()
    editor.set_completion_context(
        tables={"customers", "orders"},
        columns_by_table={"customers": ["customer_id"], "orders": ["order_id"]},
    )
    source = "SELECT * FROM `cust"
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(len(source))
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())

    assert {"customers", "orders"} <= candidates
    assert "customer_id" not in candidates
    assert editor.toPlainText() == source


def test_backtick_quoted_column_completion_scopes_to_the_qualified_table_and_inserts_token_only():
    editor = SqlEditor()
    editor.set_completion_context(
        tables={"orders", "customers"},
        columns_by_table={
            "orders": ["order_id", "order_total"],
            "customers": ["customer_id", "display_name"],
            "inventory": ["warehouse_code"],
        },
    )
    source = (
        "SELECT '😀'; "
        "SELECT o.`order_i` FROM `orders` AS o "
        "JOIN `customers` AS c ON c.customer_id = o.order_id"
    )
    editor.setPlainText(source)
    cursor = editor.textCursor()
    # Qt counts UTF-16 code units, so the astral emoji adds one extra cursor unit.
    cursor.setPosition(source.index("order_i") + len("order_i") + 1)
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())

    assert {"order_id", "order_total"} <= candidates
    assert "customer_id" not in candidates
    assert "display_name" not in candidates
    assert "warehouse_code" not in candidates
    assert editor.toPlainText() == source

    editor.insert_completion("order_total")
    assert editor.toPlainText() == source.replace("order_i", "order_total", 1)


def test_unqualified_completion_scopes_tables_with_backtick_quoted_names():
    editor = SqlEditor()
    editor.set_completion_context(
        tables={"customers", "orders", "inventory"},
        columns_by_table={
            "customers": ["customer_id", "display_name"],
            "orders": ["order_id", "order_total"],
            "inventory": ["warehouse_code"],
        },
    )
    source = "SELECT cust_ FROM `customers` AS c JOIN `orders` AS o ON c.customer_id = o.order_id"
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(source.index("cust_") + len("cust_"))
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())

    assert {"customer_id", "display_name", "order_id", "order_total"} <= candidates
    assert "warehouse_code" not in candidates
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


def test_completion_is_suppressed_inside_escaped_quotes_and_multiline_comments():
    editor = SqlEditor()
    editor.set_completion_context(
        tables={"customers", "orders"},
        columns_by_table={
            "customers": ["customer_id"],
            "orders": ["order_id", "order_total"],
        },
    )

    inside_quoted_strings = [
        r"SELECT 'it\'s customers';",
        "SELECT 'it''s customers';",
        'SELECT "escaped \\" customers";',
    ]
    for source in inside_quoted_strings:
        marker = "customers"
        editor.setPlainText(source)
        cursor = editor.textCursor()
        cursor.setPosition(source.index(marker) + len(marker))
        editor.setTextCursor(cursor)
        assert editor._context_completion_words() == (), source

    comment_sources = [
        "-- customers are only mentioned here\nSELECT * FROM cus",
        "SELECT 1 /* multiline\ncustomers comment */; SELECT * FROM cus",
        "# customers are only mentioned here\nSELECT * FROM cus",
    ]
    for source in comment_sources:
        marker = "customers"
        editor.setPlainText(source)
        cursor = editor.textCursor()
        cursor.setPosition(source.index(marker) + len(marker))
        editor.setTextCursor(cursor)
        assert editor._context_completion_words() == (), source

        # Moving to code after the comment must restore normal suggestions.
        cursor = editor.textCursor()
        cursor.setPosition(source.rindex("cus") + len("cus"))
        editor.setTextCursor(cursor)
        candidates = set(editor._context_completion_words())
        assert "customers" in candidates, source


def test_completion_handles_empty_and_large_multistatement_buffers():
    editor = SqlEditor()
    editor.set_completion_context(
        tables={"customers", "orders"},
        columns_by_table={
            "customers": ["customer_id", "display_name"],
            "orders": ["order_id", "order_total"],
        },
    )

    editor.setPlainText("")
    assert {"SELECT", "COUNT"} <= set(editor._context_completion_words())
    editor._show_completion(force=False)
    assert editor.toPlainText() == ""

    large_prefix = (
        "SELECT 'customers;'; /* comment; */ SELECT * FROM customers AS c; "
    ) * 1200
    source = large_prefix + "SELECT o.order_i FROM orders AS o"
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(source.index("order_i") + len("order_i"))
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())

    assert {"order_id", "order_total"} <= candidates
    assert "customer_id" not in candidates
    assert editor.toPlainText() == source


def test_completion_rejects_malformed_or_unsafe_optional_schema_metadata():
    editor = SqlEditor()
    editor.set_completion_context(
        databases="app_db",
        tables=["customers", "bad-table", None],
        columns_by_table=["not", "a", "mapping"],
        extra_words=17,
        active_schema="app_db",
        tables_by_schema={"analytics": "events", "bad-schema-name": ["unsafe_table"]},
        columns_by_schema_and_table={
            "analytics": {"orders": "analytics_order_id", "bad-table": ["unsafe-column"]},
            "bad-schema-name": {"orders": ["unsafe_schema_column"]},
        },
    )

    assert editor._completion_databases == {"app_db"}
    assert editor._completion_tables == {"customers"}
    assert editor._completion_columns_by_table == {}
    assert editor._extra_completion_words == set()
    assert editor._tables_for_schema("analytics") == {"events"}
    assert editor._columns_for_schema_table("analytics", "orders") == {
        "analytics_order_id"
    }
    assert editor._tables_for_schema("bad-schema-name") == set()
    assert editor.toPlainText() == ""


def test_completion_does_not_mix_columns_when_table_aliases_collide():
    editor = SqlEditor()
    editor.set_completion_context(
        tables={"customers", "orders"},
        columns_by_table={
            "customers": ["customer_id", "display_name"],
            "orders": ["order_id", "order_total"],
        },
    )
    source = "SELECT x. FROM customers AS x JOIN orders AS x ON x.id = x.id"
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(source.index("x.") + len("x."))
    editor.setTextCursor(cursor)

    assert editor._context_completion_words() == ()
    assert editor.toPlainText() == source


def test_qualified_completion_prefers_the_innermost_alias_when_outer_alias_collides():
    editor = SqlEditor()
    editor.set_completion_context(
        tables={"orders", "customers"},
        columns_by_table={
            "orders": ["order_id", "order_total"],
            "customers": ["customer_id", "display_name"],
        },
        active_schema="app_db",
    )
    source = (
        "SELECT o.order_i FROM orders AS o "
        "WHERE EXISTS (SELECT 1 FROM customers AS o WHERE o.customer_i)"
    )
    editor.setPlainText(source)
    cursor = editor.textCursor()
    column_prefix = "customer_i"
    cursor.setPosition(source.index(column_prefix, source.index("WHERE EXISTS")) + len(column_prefix))
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())

    assert {"customer_id", "display_name"} <= candidates
    assert "order_id" not in candidates
    assert "order_total" not in candidates
    assert editor.toPlainText() == source


def test_qualified_completion_can_resolve_a_correlated_outer_alias():
    editor = SqlEditor()
    editor.set_completion_context(
        tables={"orders", "customers"},
        columns_by_table={
            "orders": ["order_id", "order_total"],
            "customers": ["customer_id", "display_name"],
        },
        active_schema="app_db",
    )
    source = (
        "SELECT * FROM orders AS o WHERE EXISTS "
        "(SELECT 1 FROM customers AS c WHERE c.customer_id = o.order_i)"
    )
    editor.setPlainText(source)
    cursor = editor.textCursor()
    column_prefix = "order_i"
    cursor.setPosition(source.index(column_prefix) + len(column_prefix))
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())

    assert {"order_id", "order_total"} <= candidates
    assert "customer_id" not in candidates
    assert "display_name" not in candidates
    assert editor.toPlainText() == source


def test_unqualified_completion_excludes_tables_from_sibling_subqueries():
    editor = SqlEditor()
    editor.set_completion_context(
        tables={"customers", "orders", "inventory"},
        columns_by_table={
            "customers": ["customer_id", "display_name"],
            "orders": ["order_id", "order_total"],
            "inventory": ["sku", "warehouse_code"],
        },
        active_schema="app_db",
    )
    source = (
        "SELECT * FROM customers AS c "
        "WHERE EXISTS (SELECT 1 FROM orders AS o WHERE o.order_id = 1) "
        "AND EXISTS (SELECT 1 FROM inventory AS i WHERE ware)"
    )
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(source.index("ware") + len("ware"))
    editor.setTextCursor(cursor)

    candidates = set(editor._context_completion_words())

    # Local tables and correlated outer-scope tables are visible. The unrelated
    # table inside the first EXISTS subquery is not in the current scope.
    assert {"warehouse_code", "sku", "customer_id", "display_name"} <= candidates
    assert "order_id" not in candidates
    assert "order_total" not in candidates
    assert editor.toPlainText() == source


def test_pasted_multiline_sql_is_preserved_without_auto_pairing():
    editor = SqlEditor()
    original_clipboard = QApplication.clipboard().text()
    pasted = "SELECT (customer_id)\nFROM customers\nWHERE display_name = 'it''s ok';"
    QApplication.clipboard().setText(pasted)
    editor.setPlainText("-- draft\n")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)

    try:
        _send_key(editor, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert editor.toPlainText() == "-- draft\n" + pasted
    finally:
        QApplication.clipboard().setText(original_clipboard)
        editor.deleteLater()
        _APP.processEvents()


def test_typing_remains_available_while_schema_metadata_is_loading():
    editor = SqlEditor()
    # A schema refresh clears the old context until worker metadata arrives.
    editor.set_completion_context()
    editor.setPlainText("SELECT ")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)

    for key, character in (
        (Qt.Key.Key_C, "c"),
        (Qt.Key.Key_O, "o"),
        (Qt.Key.Key_U, "u"),
    ):
        _send_text_key(editor, key, character)

    source = "SELECT cou"
    assert editor.toPlainText() == source
    assert "COUNT" in set(editor._context_completion_words())

    # Receiving schema metadata updates suggestions, but never rewrites the query.
    cursor_position = editor.textCursor().position()
    editor.set_completion_context(
        tables={"customers"},
        columns_by_table={"customers": ["customer_id"]},
        active_schema="app_db",
    )
    assert editor.toPlainText() == source
    assert editor.textCursor().position() == cursor_position
    assert "customers" in set(editor.completion_words())


def test_context_completion_falls_back_when_schema_metadata_is_unavailable():
    editor = SqlEditor()
    editor.setPlainText("SELECT cou")
    editor.set_completion_context()
    candidates = set(editor._context_completion_words())
    assert {"SELECT", "COUNT"} <= candidates
    assert editor.toPlainText() == "SELECT cou"



def _send_key(editor, key, modifiers=Qt.KeyboardModifier.NoModifier):
    event = QKeyEvent(QEvent.Type.KeyPress, key, modifiers)
    QApplication.sendEvent(editor, event)
    _APP.processEvents()


def test_ctrl_space_opens_completion_on_demand_without_moving_editor_focus(monkeypatch):
    editor = SqlEditor()
    source = "SELECT cou"
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(len(source))
    editor.setTextCursor(cursor)
    editor.show()
    editor.setFocus()
    _APP.processEvents()
    calls = []
    monkeypatch.setattr(editor, "_show_completion", lambda force=False: calls.append(force))

    _send_key(editor, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)

    assert calls == [True]
    assert editor.toPlainText() == source
    assert editor.textCursor().position() == len(source)
    assert editor.hasFocus()


def test_up_and_down_navigate_completion_without_moving_sql_caret():
    editor = SqlEditor()
    source = "SELECT cou FROM customers"
    editor.setPlainText(source)
    cursor = editor.textCursor()
    cursor.setPosition(len("SELECT cou"))
    editor.setTextCursor(cursor)
    editor._completion_model.setStringList(["COUNT", "COALESCE", "CONCAT"])
    editor._completer.setCompletionPrefix("CO")
    popup = editor._completer.popup()
    popup.setCurrentIndex(editor._completer.completionModel().index(0, 0))
    editor.show()
    editor.setFocus()
    popup.show()
    _APP.processEvents()
    original_position = editor.textCursor().position()

    assert popup.currentIndex().data() == "COUNT"
    _send_key(editor, Qt.Key.Key_Down)
    assert popup.currentIndex().data() == "COALESCE"
    assert editor.textCursor().position() == original_position
    assert editor.toPlainText() == source

    _send_key(editor, Qt.Key.Key_Up)
    assert popup.currentIndex().data() == "COUNT"
    _send_key(editor, Qt.Key.Key_Up)
    assert popup.currentIndex().data() == "COUNT"
    assert editor.textCursor().position() == original_position
    assert editor.toPlainText() == source
    assert editor.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert popup.focusPolicy() == Qt.FocusPolicy.NoFocus
    editor.close()


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



def test_comma_separated_column_completion_scopes_to_the_active_clause():
    cases = [
        ("SELECT display_name, customer_ FROM customers AS c", "customer_"),
        ("SELECT * FROM customers c ORDER BY display_name, customer_", None),
        ("SELECT * FROM customers c GROUP BY display_name, customer_", None),
        ("UPDATE customers SET display_name = 'x', customer_", None),
    ]
    for source, cursor_token in cases:
        editor = SqlEditor()
        try:
            editor.set_completion_context(
                tables={"customers", "orders"},
                columns_by_table={
                    "customers": ["customer_id", "display_name", "created_at"],
                    "orders": ["order_id", "order_total"],
                },
                active_schema="app_db",
            )
            editor.setPlainText(source)
            cursor = editor.textCursor()
            if cursor_token:
                cursor.setPosition(source.index(cursor_token) + len(cursor_token))
            else:
                cursor.movePosition(cursor.MoveOperation.End)
            editor.setTextCursor(cursor)

            candidates = set(editor._context_completion_words())
            assert {"customer_id", "display_name", "created_at"} <= candidates, source
            assert "order_id" not in candidates, source
            assert editor.toPlainText() == source
        finally:
            editor.deleteLater()
            _APP.processEvents()



def test_tab_width_controls_explicit_tab_and_automatic_indentation():
    for width in (2, 4, 8):
        editor = SqlEditor()
        try:
            editor.set_tab_width(width)
            editor.setPlainText("BEGIN")
            cursor = editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            editor.setTextCursor(cursor)

            _send_key(editor, Qt.Key.Key_Return)
            assert editor.toPlainText() == "BEGIN\n" + (" " * width)

            _send_key(editor, Qt.Key.Key_Tab)
            assert editor.toPlainText() == "BEGIN\n" + (" " * (width * 2))
        finally:
            editor.deleteLater()
    _APP.processEvents()


def test_line_number_and_current_line_preferences_preserve_bracket_feedback():
    editor = SqlEditor()
    try:
        source = "SELECT (1)"
        editor.setPlainText(source)
        cursor = editor.textCursor()
        cursor.setPosition(source.index("(") + 1)
        editor.setTextCursor(cursor)

        assert editor.line_number_area_width() > 0
        assert len(editor.extraSelections()) == 3

        editor.set_line_numbers_visible(False)
        assert editor.line_number_area.isHidden()
        assert editor.line_number_area_width() == 0

        editor.set_current_line_highlight_enabled(False)
        assert len(editor.extraSelections()) == 2
        assert editor.toPlainText() == source

        editor.set_line_numbers_visible(True)
        editor.set_current_line_highlight_enabled(True)
        assert not editor.line_number_area.isHidden()
        assert editor.line_number_area_width() > 0
        assert len(editor.extraSelections()) == 3
    finally:
        editor.deleteLater()
        _APP.processEvents()

def test_ctrl_slash_toggles_mysql_comment_on_current_line_and_undoes_atomically():
    editor = SqlEditor()
    source = "  SELECT 'a/b' AS value;"
    try:
        editor.setPlainText(source)
        cursor = editor.textCursor()
        cursor.setPosition(len(source))
        editor.setTextCursor(cursor)

        _send_key(editor, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)

        assert editor.toPlainText() == "  -- SELECT 'a/b' AS value;"
        assert editor.textCursor().position() == len(source) + 3

        # The entire comment toggle is one undo item.
        editor.undo()
        assert editor.toPlainText() == source

        cursor = editor.textCursor()
        cursor.setPosition(len(source))
        editor.setTextCursor(cursor)
        _send_key(editor, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)
        _send_key(editor, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)

        assert editor.toPlainText() == source
        assert editor.textCursor().position() == len(source)
    finally:
        editor.deleteLater()
        _APP.processEvents()


def test_ctrl_slash_toggles_selected_block_preserving_indent_blank_lines_and_selection():
    editor = SqlEditor()
    source = "    SELECT x\n\tFROM t\n\nWHERE y = 1"
    expected_commented = "    -- SELECT x\n\t-- FROM t\n-- \nWHERE y = 1"
    selection_end = source.index("WHERE")
    try:
        editor.setPlainText(source)
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(selection_end, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)

        _send_key(editor, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)

        assert editor.toPlainText() == expected_commented
        assert editor.textCursor().hasSelection()
        assert editor.textCursor().anchor() == 0
        assert editor.textCursor().position() == selection_end + 9
        assert editor.toPlainText().endswith("WHERE y = 1")

        # One undo restores every selected line, including the originally blank line.
        editor.undo()
        assert editor.toPlainText() == source

        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(selection_end, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        _send_key(editor, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)
        _send_key(editor, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)

        assert editor.toPlainText() == source
        assert editor.textCursor().hasSelection()
        assert editor.textCursor().anchor() == 0
        assert editor.textCursor().position() == selection_end
    finally:
        editor.deleteLater()
        _APP.processEvents()


def test_ctrl_slash_uncomments_existing_mysql_line_comments_and_preserves_text():
    editor = SqlEditor()
    source = "  -- SELECT 1\n\t--\tFROM t\n-- "
    expected = "  SELECT 1\n\tFROM t\n"
    try:
        editor.setPlainText(source)
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(len(source), QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)

        _send_key(editor, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)

        assert editor.toPlainText() == expected
        assert editor.textCursor().hasSelection()

        editor.undo()
        assert editor.toPlainText() == source
    finally:
        editor.deleteLater()
        _APP.processEvents()


def test_sql_editor_keyboard_help_documents_comment_toggle():
    editor = SqlEditor()
    try:
        assert editor.accessibleName() == "SQL query editor"
        assert "Ctrl+/" in editor.accessibleDescription()
    finally:
        editor.deleteLater()
        _APP.processEvents()

def test_ctrl_slash_preserves_reverse_selection_direction():
    editor = SqlEditor()
    source = "SELECT x\nFROM t"
    expected_commented = "-- SELECT x\n-- FROM t"
    try:
        editor.setPlainText(source)
        cursor = editor.textCursor()
        cursor.setPosition(len(source))
        cursor.setPosition(0, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)

        _send_key(editor, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)

        assert editor.toPlainText() == expected_commented
        assert editor.textCursor().hasSelection()
        assert editor.textCursor().anchor() == len(expected_commented)
        assert editor.textCursor().position() == 0

        _send_key(editor, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)

        assert editor.toPlainText() == source
        assert editor.textCursor().hasSelection()
        assert editor.textCursor().anchor() == len(source)
        assert editor.textCursor().position() == 0
    finally:
        editor.deleteLater()
        _APP.processEvents()

