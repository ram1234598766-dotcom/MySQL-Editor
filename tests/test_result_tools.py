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
