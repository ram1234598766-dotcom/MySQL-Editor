"""Regression tests for result-grid clipboard and long-cell presentation."""
import csv
import io

from mysql_editor.ui.result_tools import (
    cell_copy_text,
    cell_detail_text,
    column_headers_tsv,
    result_export_target,
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
        "No rows in the current grid window match 'missing'. "
        "2,000 window row(s) checked; data export includes all 4,127 result row(s)."
    )
    assert result_filter_message("alice", 3, 20, 20) == (
        "Quick filter: 3 of 20 current-window row(s) match. "
        "Data export includes all 20 result row(s)."
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
    assert "No rows in the current grid window match 'missing'." in window.result_message.value
    assert "all 80 result row(s)" in window.result_message.value

    MainWindow._filter_results(window, "")
    assert window.result_message.value == window._result_base_message



def test_result_window_message_discloses_bounded_memory_and_absolute_range():
    from mysql_editor.ui.result_tools import result_window_message

    message = result_window_message(
        {"kind": "rows", "row_count": 100_000},
        window_start=25_000,
        window_rows=5_000,
        total_rows=100_000,
    )
    assert message == (
        "Rows result · showing rows 25,001–30,000 of 100,000. "
        "The grid retains at most 5,000 row(s) in memory; the local spool and data exports "
        "keep the full 100,000-row result. "
        "Scroll to the top for earlier rows or to the bottom for later rows."
    )

    single_window = result_window_message(
        {"kind": "rows"},
        window_start=0,
        window_rows=12,
        total_rows=12,
    )
    assert "All rows fit in the current grid window." in single_window


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
        "data export includes all 4,321 fetched row(s)."
    )
    assert result_summary_message({"kind": "error", "row_count": 1}, 1, 1) == (
        "Statement failed. Review the error details in this result."
    )


def test_result_picker_label_identifies_script_statement_and_warnings():
    from mysql_editor.ui.result_tools import result_picker_label

    assert result_picker_label({
        "kind": "rows", "row_count": 12, "statement_index": 2,
        "statement_count": 3, "warning_count": 1,
    }, 2) == "Statement 2 of 3 · Result 2 · Rows · 12 row(s) · 1 warning(s)"
    assert result_picker_label({"kind": "status", "row_count": 1}, 1) == (
        "Result 1 · Status · 1 row(s)"
    )


def test_result_picker_label_handles_malformed_metadata_safely():
    from mysql_editor.ui.result_tools import result_picker_label

    assert result_picker_label({
        "kind": "error", "row_count": "invalid", "statement_index": 4,
        "statement_count": 2, "warning_count": -2,
    }, 0) == "Statement 4 · Result 1 · Error · 0 row(s)"


def test_column_width_samples_are_bounded_and_keep_full_result_data_untouched():
    from mysql_editor.ui.result_tools import column_width_samples

    long_value = "x" * 600
    headers = ["id", "note"]
    rows = [[index, long_value] for index in range(100)]
    samples = column_width_samples(headers, rows, max_sample_rows=12, max_chars=40)

    assert samples[0] == ["id"] + [str(index) for index in range(12)]
    assert len(samples[1]) == 13
    assert samples[1][0] == "note"
    assert samples[1][1] == "x" * 40 + "…"
    assert len(rows) == 100
    assert rows[0][1] == long_value


def test_column_width_samples_clamp_extreme_settings_and_handle_empty_columns():
    from mysql_editor.ui.result_tools import column_width_samples

    assert column_width_samples(["a"], [[index] for index in range(100)], max_sample_rows=10000)[0][0:2] == ["a", "0"]
    assert len(column_width_samples(["a"], [[index] for index in range(100)], max_sample_rows=10000)[0]) == 65
    assert column_width_samples([], [[1, 2]], max_sample_rows=10) == []
    assert column_width_samples(["a"], [[1]], max_sample_rows="invalid") == [["a", "1"]]



def test_cell_copy_text_preserves_scalar_values_and_marks_sql_null():
    assert cell_copy_text(None) == "NULL"
    assert cell_copy_text("") == ""
    assert cell_copy_text(" ") == " "
    assert cell_copy_text(0) == "0"
    assert cell_copy_text("line\nnext") == "line\nnext"

def test_result_export_target_uses_selected_filter_and_canonical_suffix():
    assert result_export_target("report", "JSON array (*.json)") == ("report.json", "json")
    assert result_export_target("report.csv", "NDJSON files (*.ndjson)") == (
        "report.ndjson", "ndjson"
    )
    assert result_export_target("events.jsonl", "") == ("events.ndjson", "ndjson")
    assert result_export_target("report.txt", "CSV files (*.csv)") == ("report.csv", "csv")
    assert result_export_target("", "JSON array (*.json)") == ("", "")

