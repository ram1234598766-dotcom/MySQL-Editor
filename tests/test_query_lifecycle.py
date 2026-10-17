"""Regression tests for truthful SQL lifecycle state mapping."""
import pytest

from mysql_editor.ui.query_lifecycle import classify_query_outcome


@pytest.mark.parametrize("result", [
    {"ok": True},
    {"ok": True, "results": [{"kind": "rows", "row_count": 10}]},
    {"ok": True, "results": [{"kind": "status", "affected_rows": 1}]},
])
def test_successful_query_is_complete(result):
    assert classify_query_outcome(result) == "complete"


def test_mysql_interruption_only_counts_as_cancelled_when_user_requested_it():
    interrupted = {"ok": False, "interrupted": True, "error": "Query execution was interrupted"}
    assert classify_query_outcome(interrupted, cancellation_requested=True) == "cancelled"
    assert classify_query_outcome(interrupted, cancellation_requested=False) == "interrupted"


def test_script_error_after_successful_statement_is_partial_failure():
    result = {
        "ok": False,
        "results": [
            {"kind": "rows", "row_count": 2},
            {"kind": "status", "affected_rows": 1},
            {"kind": "error", "row_count": 1},
        ],
    }
    assert classify_query_outcome(result) == "partial_failure"


def test_standalone_query_error_is_failed_not_partial():
    assert classify_query_outcome({
        "ok": False, "results": [{"kind": "error", "row_count": 1}],
    }) == "failed"


def test_cancellation_request_without_mysql_interruption_is_not_called_cancelled():
    assert classify_query_outcome({"ok": True}, cancellation_requested=True) == "complete"
