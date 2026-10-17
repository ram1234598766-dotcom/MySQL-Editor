"""Regression tests for result-grid clipboard and long-cell presentation."""
import csv
import io

from mysql_editor.ui.result_tools import (
    cell_detail_text,
    column_headers_tsv,
    rows_tsv,
    selected_cells_tsv,
)


def _parse_tsv(text):
    return list(csv.reader(io.StringIO(text, newline=""), delimiter="\t"))


def test_selected_cells_preserve_rectangle_null_empty_and_embedded_delimiters():
    payload = selected_cells_tsv({
        (2, 1): "line one\nline two",
        (2, 2): "contains\ttab",
        (3, 1): None,
        (3, 2): "",
    })
    assert _parse_tsv(payload) == [
        ["line one\nline two", "contains\ttab"],
        ["NULL", ""],
    ]


def test_selected_cells_leave_unselected_holes_blank_and_empty_selection_empty():
    payload = selected_cells_tsv({(0, 0): "a", (0, 2): "c", (1, 2): "f"})
    assert _parse_tsv(payload) == [["a", "", "c"], ["", "", "f"]]
    assert selected_cells_tsv({}) == ""


def test_rows_and_headers_are_tabular_and_null_is_explicit_when_copied():
    assert _parse_tsv(rows_tsv([["Ada", None], ["Lin", ""]])) == [
        ["Ada", "NULL"],
        ["Lin", ""],
    ]
    assert _parse_tsv(column_headers_tsv(["customer", "note"])) == [["customer", "note"]]


def test_cell_detail_keeps_sql_null_distinct_from_empty_text():
    assert cell_detail_text(None) == "SQL NULL (no value)"
    assert cell_detail_text("") == ""
    assert cell_detail_text(" ") == " "
    assert cell_detail_text("line\nnext") == "line\nnext"



def test_result_filter_message_distinguishes_preview_rows_from_fetched_rows():
    from mysql_editor.ui.result_tools import result_filter_message

    assert result_filter_message("missing", 0, 2000, 4127) == (
        "No rows in the visible preview match 'missing'. "
        "2,000 preview row(s) checked; CSV export still includes all 4,127 fetched row(s)."
    )
    assert result_filter_message("alice", 3, 20, 20) == (
        "Quick filter: 3 of 20 preview row(s) match. "
        "CSV export still includes all 20 fetched row(s)."
    )
    assert result_filter_message("  ", 0, 20, 20) == ""


def test_filter_clear_restores_the_underlying_result_message():
    from mysql_editor.ui.main_window import MainWindow

    class Label:
        def __init__(self):
            self.value = ""

        def setText(self, value):
            self.value = value

    class Model:
        rows = [["Alice"], ["Bob"]]

    class Proxy:
        def __init__(self):
            self.query = ""

        def setFilterFixedString(self, value):
            self.query = value

        def rowCount(self):
            return sum(self.query.casefold() in str(row[0]).casefold() for row in Model.rows)

    class Window:
        result_proxy = Proxy()
        result_model = Model()
        result_message = Label()
        _result_fetched_row_count = 80
        _result_base_message = "Query complete · 80 row(s) · 25 ms."

    window = Window()
    MainWindow._filter_results(window, "missing")
    assert "No rows in the visible preview match 'missing'." in window.result_message.value
    assert "all 80 fetched row(s)" in window.result_message.value

    MainWindow._filter_results(window, "")
    assert window.result_message.value == window._result_base_message



def test_result_summary_distinguishes_empty_rows_from_statements_without_rows():
    from mysql_editor.ui.result_tools import result_summary_message

    assert result_summary_message({"kind": "rows", "row_count": 0}, 0, 0) == (
        "Query completed successfully. No rows were returned."
    )
    assert result_summary_message({"kind": "status", "affected_rows": 0}, 1, 1) == (
        "Statement completed. No rows were affected."
    )
    assert result_summary_message({"kind": "status", "affected_rows": 12}, 1, 1) == (
        "Statement completed. 12 row(s) affected."
    )


def test_result_summary_explains_preview_truncation_and_failure():
    from mysql_editor.ui.result_tools import result_summary_message

    assert result_summary_message({
        "kind": "rows", "row_count": 4321, "preview_truncated": True,
    }, 2000, 4321) == (
        "Rows result · 4,321 row(s) fetched. Showing first 2,000; "
        "CSV export includes all 4,321 fetched row(s)."
    )
    assert result_summary_message({"kind": "error", "row_count": 1}, 1, 1) == (
        "Statement failed. Review the error details in this result."
    )
