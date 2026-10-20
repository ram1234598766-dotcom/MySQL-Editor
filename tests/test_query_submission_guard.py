"""Regression tests for single-query execution and connection-context safety."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

import mysql_editor.ui.main_window as main_window_module
from mysql_editor.storage import LocalRepository
from mysql_editor.ui.main_window import MainWindow


_APP = QApplication.instance() or QApplication([])


class StubWorker(QObject):
    completed = Signal(str, str, object)
    activity = Signal(str)

    def __init__(self):
        super().__init__()
        self.submissions = []

    def submit(self, action, payload=None, task_id=None):
        self.submissions.append((action, payload or {}, task_id))
        return task_id or f"query-guard-{len(self.submissions)}"

    def cancel_current_query(self):
        pass

    def shutdown(self):
        pass

    def wait(self, _milliseconds=5000):
        return True


def _make_window(tmp_path):
    repository = LocalRepository(tmp_path / "query-guard.sqlite3")
    worker = StubWorker()
    profile = {
        "id": "profile-one",
        "name": "QA profile",
        "host": "127.0.0.1",
        "port": 3306,
        "username": "tester",
    }
    config = {
        "host": "127.0.0.1",
        "port": 3306,
        "username": "tester",
        "default_schema": "",
        "tls_mode": "Automatic TLS",
    }
    window = MainWindow(
        worker, repository, object(), profile, config,
        {"server_version": "MySQL test", "database": ""},
    )
    return window, repository, worker


def test_fetch_more_rows_uses_local_cache_and_preserves_active_filter(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    item = {
        "result_id": "paged-result",
        "kind": "rows",
        "headers": ["name"],
        "rows": [["Alpha"], ["Bravo"]],
        "row_count": 4,
        "preview_truncated": True,
        "table_edit": {"enabled": False, "reason": "read-only table preview"},
        "duration_ms": 7,
    }
    window._query_results = [item]
    try:
        window._select_result(0, total_duration=12)
        assert window.fetch_more_button.isEnabled()
        assert window.fetch_more_button.text() == "Fetch +2"
        window.result_filter.setText("alpha")
        assert window.result_proxy.rowCount() == 1

        # Paging is temporarily disabled while a SQL statement is active.
        before = len(worker.submissions)
        window._query_running = True
        window._set_result_controls()
        assert not window.fetch_more_button.isEnabled()
        window.fetch_more_result_rows()
        assert len(worker.submissions) == before
        window._query_running = False
        window._set_result_controls()

        window.fetch_more_result_rows()
        job_id = worker.submissions[-1][2]
        action, payload, _task_id = worker.submissions[-1]
        assert action == "fetch_result_page"
        assert payload == {
            "result_id": "paged-result",
            "offset": 2,
            "limit": main_window_module.RESULT_PAGE_ROWS,
        }
        assert window.fetch_more_button.text() == "Loading…"
        assert not window.fetch_more_button.isEnabled()

        # Repeated clicks while a page is outstanding cannot enqueue duplicate reads.
        window.fetch_more_result_rows()
        assert len(worker.submissions) == before + 1
        assert not any(
            submitted_action == "query"
            for submitted_action, _submitted_payload, _submitted_id in worker.submissions[before:]
        )

        window._on_worker_completed(
            job_id,
            "fetch_result_page",
            {
                "ok": True,
                "result_id": "paged-result",
                "offset": 2,
                "rows": [["Alpha again"], ["Delta"]],
                "row_count": 4,
                "page_size": 1000,
                "has_more": False,
            },
        )

        assert item["rows"] == [["Alpha"], ["Bravo"], ["Alpha again"], ["Delta"]]
        assert window.result_model.rowCount() == 4
        assert window.result_filter.text() == "alpha"
        assert window.result_proxy.rowCount() == 2
        assert window.fetch_more_button.text() == "All Rows Loaded"
        assert not window.fetch_more_button.isEnabled()
        assert "SQL was not rerun" in window.status.text()
        assert "Quick filter: 2 of 4 current-window row(s) match." in window.result_message.text()
        assert "Data export includes all 4 result row(s)." in window.result_message.text()
    finally:
        window._query_running = False
        window.close()
        repository.close()


def test_second_sql_submission_is_rejected_while_query_is_active(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    try:
        window._query_running = True
        before = len(worker.submissions)

        window._execute_sql("SELECT 1;")
        result = window._dispatch("query", {"sql": "SELECT 2;"})

        assert result is None
        assert len(worker.submissions) == before
        assert "already active" in window.status.text().lower()
    finally:
        window._query_running = False
        window.close()
        repository.close()


def test_connection_dialog_does_not_open_during_active_query(tmp_path, monkeypatch):
    window, repository, _worker = _make_window(tmp_path)

    def unexpected_dialog(*_args, **_kwargs):
        raise AssertionError("Connection dialog must not open during an active query")

    monkeypatch.setattr(main_window_module, "ConnectionDialog", unexpected_dialog)
    try:
        window._query_running = True
        window.open_connection_dialog()

        assert "connection change blocked" in window.status.text().lower()
    finally:
        window._query_running = False
        window.close()
        repository.close()


def test_connection_switch_callback_cannot_change_context_mid_query(tmp_path):
    window, repository, _worker = _make_window(tmp_path)
    original_profile = dict(window.profile)
    original_config = dict(window.config)
    original_result = dict(window.connect_result)
    try:
        window._query_running = True
        window._switch_connection(
            {"id": "profile-two", "name": "Unexpected", "host": "db2.example.test"},
            {"host": "db2.example.test", "port": 3307, "username": "other"},
            {"server_version": "other server", "database": "other_schema"},
        )

        assert window.profile == original_profile
        assert window.config == original_config
        assert window.connect_result == original_result
        assert "connection change blocked" in window.status.text().lower()
    finally:
        window._query_running = False
        window.close()
        repository.close()


def test_transaction_controls_disable_during_query_and_restore_after_completion(tmp_path):
    window, repository, _worker = _make_window(tmp_path)
    try:
        job_id = window._dispatch("query", {"sql": "SELECT 1;"})
        assert job_id is not None
        assert window._query_running is True
        assert not window.commit_button.isEnabled()
        assert not window.rollback_button.isEnabled()

        window._on_worker_completed(
            job_id, "query", {"ok": True, "results": [], "duration_ms": 1}
        )

        assert window._query_running is False
        assert window.commit_button.isEnabled()
        assert window.rollback_button.isEnabled()
        assert not window.stop_button.isEnabled()
    finally:
        window._query_running = False
        window.close()
        repository.close()


def test_export_progress_and_completion_do_not_overwrite_a_newer_query(
    tmp_path, monkeypatch
):
    window, repository, _worker = _make_window(tmp_path)

    def unexpected_modal(*_args, **_kwargs):
        raise AssertionError("CSV export feedback must not block the workspace")

    monkeypatch.setattr(main_window_module.QMessageBox, "information", unexpected_modal)
    monkeypatch.setattr(main_window_module.QMessageBox, "warning", unexpected_modal)
    try:
        export_job = window._dispatch(
            "export_csv", {"result_id": "result-1", "path": "results.csv"}
        )
        query_job = window._dispatch("query", {"sql": "SELECT 1;"})
        assert window._query_running is True
        assert window.status.text() == "Query queued…"

        window._on_activity("Exporting CSV rows…")
        window._on_activity("Exported 10 CSV row(s) so far…")
        assert window.status.text() == "Query queued…"

        window._on_worker_completed(
            export_job,
            "export_csv",
            {"ok": True, "row_count": 10, "path": "results.csv"},
        )
        assert window.status.text() == "Query queued…"
        assert len(window._deferred_export_notifications) == 1
        assert window.export_feedback.isHidden()

        window._on_worker_completed(
            query_job, "query", {"ok": True, "results": [], "duration_ms": 1}
        )
        assert window._query_running is False
        assert not window.export_feedback.isHidden()
        assert "10 row(s)" in window.export_feedback.text()
        assert "results.csv" in window.export_feedback.text()
        assert window.export_feedback.objectName() == "statusSuccess"
        assert window.status.text().startswith("Statement complete")
        assert window._deferred_export_notifications == []
    finally:
        window._query_running = False
        window.close()
        repository.close()

def test_multi_statement_high_impact_warning_numbers_risks_without_echoing_sql(
    tmp_path, monkeypatch
):
    window, repository, worker = _make_window(tmp_path)
    warnings = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "warning",
        lambda _parent, title, message, *_args: (
            warnings.append((title, message)) or main_window_module.QMessageBox.StandardButton.Cancel
        ),
    )
    sql = "SELECT 'token=private-value'; DELETE FROM users; DROP TABLE audit_log;"
    try:
        window._execute_sql(sql)

        assert len(warnings) == 1
        title, message = warnings[0]
        assert title == "High-impact SQL script"
        assert "2 high-impact statement(s)" in message
        assert "\nStatement 2:" in message
        assert "DELETE has no top-level WHERE clause" in message
        assert "\nStatement 3:" in message
        assert "DROP can change schema" in message
        assert "private-value" not in message
        assert "audit_log" not in message
        assert not any(action == "query" for action, _payload, _task_id in worker.submissions)
    finally:
        window.close()
        repository.close()


def test_multi_statement_high_impact_script_runs_only_after_explicit_confirmation(
    tmp_path, monkeypatch
):
    window, repository, worker = _make_window(tmp_path)
    warnings = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "warning",
        lambda _parent, title, message, *_args: (
            warnings.append((title, message)) or main_window_module.QMessageBox.StandardButton.Yes
        ),
    )
    sql = "UPDATE users SET active=0; DROP TABLE old_audit;"
    try:
        window._execute_sql(sql)

        assert len(warnings) == 1
        assert "2 high-impact statement(s)" in warnings[0][1]
        submissions = [
            payload for action, payload, _task_id in worker.submissions if action == "query"
        ]
        assert len(submissions) == 1
        assert submissions[0]["sql"] == sql
        assert window._query_running is True
    finally:
        window._query_running = False
        window.close()
        repository.close()




def test_cell_detail_copy_button_copies_full_value_null_marker_and_empty_text(
    tmp_path, monkeypatch
):
    window, repository, _worker = _make_window(tmp_path)

    def click_copy_button(dialog):
        button = dialog.findChild(main_window_module.QPushButton, "copyCellValueButton")
        assert button is not None
        assert button.accessibleName().startswith("Copy full cell value")
        button.click()
        return 0

    monkeypatch.setattr(main_window_module.QDialog, "exec", click_copy_button)
    clipboard = QApplication.clipboard()
    try:
        for value, expected in (
            ("line one\nline two", "line one\nline two"),
            (None, "NULL"),
            ("", ""),
        ):
            window.result_model.update(["payload"], [[value]])
            clipboard.clear()
            index = window.result_proxy.index(0, 0)
            assert index.isValid()
            window.show_cell_details(index)
            assert clipboard.text() == expected
            assert "Copied full cell value" in window.status.text()
            assert "SQL NULL is copied as NULL" in window.status.text()
    finally:
        window.close()
        repository.close()



def test_malformed_delimiter_script_is_rejected_before_queueing_any_query(tmp_path, monkeypatch):
    window, repository, worker = _make_window(tmp_path)
    warnings = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "warning",
        lambda _parent, title, message, *_args: warnings.append((title, message)),
    )
    script = "SELECT 1;\nDELIMITER $$ extra\nSELECT 2;"
    try:
        before = len(worker.submissions)
        window._execute_sql(script)

        assert len(worker.submissions) == before
        assert not any(action == "query" for action, _payload, _task_id in worker.submissions)
        assert len(warnings) == 1
        assert warnings[0][0] == "SQL script parsing failed"
        assert "line 2" in warnings[0][1]
        assert "script was not submitted" in warnings[0][1].lower()
        assert "not submitted" in window.status.text().lower()
    finally:
        window.close()
        repository.close()

def test_late_export_progress_and_completion_cannot_overwrite_newer_query_status(
    tmp_path, monkeypatch
):
    window, repository, _worker = _make_window(tmp_path)

    def unexpected_modal(*_args, **_kwargs):
        raise AssertionError("export feedback must stay non-modal while preserving query status")

    monkeypatch.setattr(main_window_module.QMessageBox, "information", unexpected_modal)
    monkeypatch.setattr(main_window_module.QMessageBox, "warning", unexpected_modal)
    try:
        export_job = window._dispatch(
            "export_csv", {"result_id": "result-older", "path": "older-results.csv"}
        )
        query_job = window._dispatch("query", {"sql": "SELECT 1;"})
        assert window._task_sequences[export_job] < window._task_sequences[query_job]

        # Simulate the newer query's completion being handled before a progress or
        # completion signal that was already queued by the older export.
        window._on_worker_completed(
            query_job, "query", {"ok": True, "results": [], "duration_ms": 1}
        )
        query_status = window.status.text()
        assert query_status.startswith("Statement complete")

        window._on_task_activity(export_job, "Exporting CSV rows…")
        window._on_task_activity(export_job, "Exported 10 CSV row(s) so far…")
        assert window.status.text() == query_status

        window._on_worker_completed(
            export_job,
            "export_csv",
            {"ok": True, "row_count": 10, "path": "older-results.csv"},
        )

        assert window.status.text() == query_status
        assert not window.export_feedback.isHidden()
        assert "10 row(s)" in window.export_feedback.text()
        assert "older-results.csv" in window.export_feedback.text()
        assert export_job not in window._task_sequences
        assert query_job not in window._task_sequences
    finally:
        window._query_running = False
        window.close()
        repository.close()

def test_large_result_filter_scans_spool_pages_matches_and_preserves_export_total(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    item = {
        "result_id": "full-filter-result",
        "kind": "rows",
        "headers": ["name", "rank"],
        "rows": [["Alpha preview", 1], ["Bravo preview", 2]],
        "row_count": 8,
        "preview_truncated": True,
        "duration_ms": 7,
    }
    window._query_results = [item]
    window._current_result_id = item["result_id"]
    window.result_model.update(item["headers"], item["rows"], total_rows=8)
    window._result_fetched_row_count = 8
    window.result_proxy.setFilterFixedString("")
    try:
        window.result_filter.setText("alpha")
        window._filter_debounce_timer.stop()
        pending = dict(window._pending_spool_filter)
        assert pending["query"] == "alpha"
        assert pending["result_id"] == item["result_id"]

        window._dispatch_spool_filter()
        action, payload, job_id = worker.submissions[-1]
        assert action == "filter_result_spool"
        assert payload == {
            "result_id": item["result_id"],
            "query": "alpha",
            "limit": main_window_module.RESULT_PAGE_ROWS,
        }
        assert window._spool_filter_request["job_id"] == job_id

        window._on_worker_completed(
            job_id,
            action,
            {
                "ok": True,
                "result_id": item["result_id"],
                "view_id": "view-alpha",
                "query": "alpha",
                "offset": 0,
                "rows": [["Alpha row", 10], ["alphabet row", 20]],
                "source_offsets": [1, 4],
                "row_count": 4,
                "source_row_count": 8,
                "page_size": 2,
                "has_more": True,
            },
        )

        assert item["view_id"] == "view-alpha"
        assert item["view_query"] == "alpha"
        assert item["view_row_count"] == 4
        assert item["row_count"] == 8
        assert window.result_model.rows == [["Alpha row", 10], ["alphabet row", 20]]
        assert window.result_model.absolute_row_index(0) == 1
        assert window.result_model.absolute_row_index(1) == 4
        assert window.result_model.total_rows == 4
        assert "4 of 8 fetched row(s) match" in window.result_message.text()
        assert "exports still include all 8" in window.result_message.text()

        window.fetch_more_result_rows()
        action, payload, page_job_id = worker.submissions[-1]
        assert action == "fetch_result_page"
        assert payload["view_id"] == "view-alpha"
        assert payload["offset"] == 2

        window._on_worker_completed(
            page_job_id,
            action,
            {
                "ok": True,
                "result_id": item["result_id"],
                "view_id": "view-alpha",
                "offset": 2,
                "rows": [["ALPHA next", 30], ["Alpha last", 40]],
                "source_offsets": [6, 7],
                "row_count": 4,
                "source_row_count": 8,
                "page_size": 2,
                "has_more": False,
            },
        )

        assert window.result_model.rows[-2:] == [["ALPHA next", 30], ["Alpha last", 40]]
        assert window.result_model.absolute_row_index(2) == 6
        assert window.result_model.absolute_row_index(3) == 7
        assert window._result_fetched_row_count == 8
        assert item["row_count"] == 8

        window.result_filter.clear()
        assert "view_id" not in item
        assert item["rows"] == [["Alpha preview", 1], ["Bravo preview", 2]]
        assert window.result_model.rows == item["rows"]
        assert window.result_model.total_rows == 8
        assert window._result_fetched_row_count == 8
        assert worker.submissions[-1][0] == "drop_result_filter"
    finally:
        window._filter_debounce_timer.stop()
        window.close()
        repository.close()
        _APP.processEvents()

def test_replacing_query_results_releases_the_previous_disk_filter_view(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    old_item = {
        "result_id": "old-filtered-result",
        "kind": "rows",
        "headers": ["name"],
        "rows": [["Alpha match"]],
        "initial_rows": [["Alpha"], ["Bravo"]],
        "row_count": 10,
        "window_start_offset": 0,
        "view_id": "old-filter-view",
        "view_query": "alpha",
        "view_row_count": 1,
        "source_offsets": [4],
    }
    window._query_results = [old_item]
    window._current_result_id = old_item["result_id"]
    try:
        job_id = window._dispatch("query", {"sql": "SELECT id FROM next_result;"})
        window._on_worker_completed(
            job_id,
            "query",
            {
                "ok": True,
                "results": [{
                    "result_id": "new-result",
                    "kind": "rows",
                    "headers": ["id"],
                    "rows": [[7]],
                    "row_count": 1,
                    "duration_ms": 2,
                }],
                "duration_ms": 2,
            },
        )

        assert window._current_result_id == "new-result"
        assert "view_id" not in old_item
        assert old_item["rows"] == [["Alpha"], ["Bravo"]]
        cleanup_requests = [
            payload
            for action, payload, _task_id in worker.submissions
            if action == "drop_result_filter"
        ]
        assert cleanup_requests == [{"view_id": "old-filter-view"}]
    finally:
        window._filter_debounce_timer.stop()
        window.close()
        repository.close()
        _APP.processEvents()


def test_programmatic_long_filter_is_clamped_to_the_visible_256_character_limit(tmp_path):
    window, repository, _worker = _make_window(tmp_path)
    item = {
        "result_id": "long-filter-result",
        "kind": "rows",
        "headers": ["name"],
        "rows": [["sample"]],
        "row_count": 10,
        "preview_truncated": True,
    }
    window._query_results = [item]
    window._current_result_id = item["result_id"]
    window.result_model.update(item["headers"], item["rows"], total_rows=10)
    try:
        window._filter_results("x" * 300)

        assert len(window.result_filter.text()) == 256
        assert window._pending_spool_filter is not None
        assert window._pending_spool_filter["query"] == window.result_filter.text()
        assert len(window._pending_spool_filter["query"]) == 256
    finally:
        window._filter_debounce_timer.stop()
        window.close()
        repository.close()
        _APP.processEvents()

def test_spool_backed_global_sort_dispatches_and_keeps_absolute_source_rows(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    item = {
        "result_id": "global-sort-result",
        "kind": "rows",
        "headers": ["name", "score"],
        "rows": [["old-window-first", 2], ["old-window-second", 1]],
        "row_count": 8,
        "preview_truncated": True,
    }
    window._query_results = [item]
    window._current_result_id = item["result_id"]
    window.result_model.update(item["headers"], item["rows"], total_rows=8)
    window._result_fetched_row_count = 8
    try:
        window._on_result_sort_indicator_changed(1, Qt.SortOrder.DescendingOrder)
        window._filter_debounce_timer.stop()

        pending = dict(window._pending_spool_filter)
        assert pending["operation"] == "sort"
        assert pending["sort_column"] == 1
        assert pending["sort_descending"] is True
        assert pending["result_id"] == item["result_id"]

        window._dispatch_spool_filter()
        action, payload, job_id = worker.submissions[-1]
        assert action == "sort_result_spool"
        assert payload == {
            "result_id": item["result_id"],
            "column": 1,
            "descending": True,
            "base_view_id": None,
            "limit": main_window_module.RESULT_PAGE_ROWS,
        }
        assert window._spool_filter_request["job_id"] == job_id

        window._on_worker_completed(
            job_id,
            action,
            {
                "ok": True,
                "result_id": item["result_id"],
                "view_id": "global-desc-score",
                "query": "",
                "offset": 0,
                "rows": [["highest", 99], ["next", 90]],
                "source_offsets": [6, 2],
                "row_count": 8,
                "source_row_count": 8,
                "page_size": 2,
                "has_more": True,
                "sort_column": 1,
                "sort_descending": True,
            },
        )

        assert item["view_id"] == "global-desc-score"
        assert item["sort_column"] == 1
        assert item["sort_descending"] is True
        assert item["row_count"] == 8
        assert item["view_row_count"] == 8
        assert window.result_model.rows == [["highest", 99], ["next", 90]]
        assert window.result_model.absolute_row_index(0) == 6
        assert window.result_model.absolute_row_index(1) == 2
        assert window.result_model.total_rows == 8
        assert window._result_fetched_row_count == 8
        assert worker.submissions[-1][0] == "sort_result_spool"
        assert "original MySQL fetch order" in window.status.text()
    finally:
        window._filter_debounce_timer.stop()
        window.close()
        repository.close()
        _APP.processEvents()


def test_full_result_filter_carries_global_sort_and_paging_context(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    item = {
        "result_id": "filter-sort-result",
        "kind": "rows",
        "headers": ["name", "score"],
        "rows": [["preview alpha", 1], ["preview beta", 2]],
        "row_count": 8,
        "preview_truncated": True,
        "sort_column": 1,
        "sort_descending": True,
    }
    window._query_results = [item]
    window._current_result_id = item["result_id"]
    window.result_model.update(item["headers"], item["rows"], total_rows=8)
    try:
        window.result_filter.setText("alpha")
        window._filter_debounce_timer.stop()
        window._dispatch_spool_filter()

        action, payload, job_id = worker.submissions[-1]
        assert action == "filter_result_spool"
        assert payload["query"] == "alpha"
        assert payload["sort_column"] == 1
        assert payload["sort_descending"] is True

        window._on_worker_completed(
            job_id,
            action,
            {
                "ok": True,
                "result_id": item["result_id"],
                "view_id": "filtered-desc-score",
                "query": "alpha",
                "offset": 0,
                "rows": [["Alpha high", 95], ["alphabet middle", 60]],
                "source_offsets": [6, 3],
                "row_count": 3,
                "source_row_count": 8,
                "page_size": 2,
                "has_more": True,
                "sort_column": 1,
                "sort_descending": True,
            },
        )

        assert item["view_id"] == "filtered-desc-score"
        assert item["view_query"] == "alpha"
        assert item["sort_column"] == 1
        assert item["sort_descending"] is True
        assert item["row_count"] == 8
        assert item["view_row_count"] == 3
        assert item["source_offsets"] == [6, 3]
        assert window.result_model.rows == [["Alpha high", 95], ["alphabet middle", 60]]
        assert window._result_fetched_row_count == 8
        assert "exports still include all 8" in window.result_message.text()
    finally:
        window._filter_debounce_timer.stop()
        window.close()
        repository.close()
        _APP.processEvents()


def test_sorting_an_existing_filtered_view_sorts_that_view_not_the_source_query(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    item = {
        "result_id": "filtered-sort-result",
        "kind": "rows",
        "headers": ["name", "score"],
        "rows": [["Alpha", 1], ["alphabet", 2]],
        "initial_rows": [["Alpha", 1], ["beta", 9], ["alphabet", 2], ["other", 6]],
        "row_count": 8,
        "view_id": "active-alpha-view",
        "view_query": "alpha",
        "view_row_count": 3,
        "source_offsets": [0, 2],
        "window_start_offset": 0,
        "sort_column": 0,
        "sort_descending": False,
    }
    window._query_results = [item]
    window._current_result_id = item["result_id"]
    window.result_model.update(item["headers"], item["rows"], source_offsets=[0, 2], total_rows=3)
    window._result_fetched_row_count = 8
    try:
        window.result_filter.setText("alpha")
        window._on_result_sort_indicator_changed(1, Qt.SortOrder.DescendingOrder)
        window._filter_debounce_timer.stop()
        window._dispatch_spool_filter()

        action, payload, job_id = worker.submissions[-1]
        assert action == "sort_result_spool"
        assert payload == {
            "result_id": item["result_id"],
            "column": 1,
            "descending": True,
            "base_view_id": "active-alpha-view",
            "limit": main_window_module.RESULT_PAGE_ROWS,
        }

        window._on_worker_completed(
            job_id,
            action,
            {
                "ok": True,
                "result_id": item["result_id"],
                "view_id": "active-alpha-view-sorted",
                "query": "alpha",
                "offset": 0,
                "rows": [["Alpha", 95], ["alphabet", 80]],
                "source_offsets": [0, 2],
                "row_count": 3,
                "source_row_count": 8,
                "page_size": 2,
                "has_more": True,
                "sort_column": 1,
                "sort_descending": True,
            },
        )
        assert item["view_id"] == "active-alpha-view-sorted"
        assert item["view_query"] == "alpha"
        assert item["sort_column"] == 1
        assert item["sort_descending"] is True
        assert item["row_count"] == 8
        assert item["view_row_count"] == 3
        assert window.result_model.rows == [["Alpha", 95], ["alphabet", 80]]
        assert window.result_model.absolute_row_index(0) == 0
    finally:
        window._filter_debounce_timer.stop()
        window.close()
        repository.close()
        _APP.processEvents()

def test_reapplying_same_filter_text_does_not_invalidate_queued_spool_sort_or_filter(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    item = {
        "result_id": "queued-filter-result",
        "kind": "rows",
        "headers": ["name", "score"],
        "rows": [["Alpha preview", 1], ["Bravo preview", 2]],
        "row_count": 8,
        "preview_truncated": True,
    }
    window._query_results = [item]
    window._current_result_id = item["result_id"]
    window.result_model.update(item["headers"], item["rows"], total_rows=8)
    try:
        window.result_filter.setText("alpha")
        window._filter_debounce_timer.stop()
        pending_before = dict(window._pending_spool_filter)
        generation_before = window._filter_generation

        # The paging-completion path reapplies the unchanged filter text. That must
        # not make an already queued full-spool filter/sort request stale.
        window._filter_results("alpha")

        assert window._filter_generation == generation_before
        assert window._pending_spool_filter == pending_before
        assert window._pending_spool_filter["query"] == "alpha"
        assert window._pending_spool_filter["result_id"] == item["result_id"]
        assert window._filter_debounce_timer.isActive()
        assert not worker.submissions
    finally:
        window._filter_debounce_timer.stop()
        window.close()
        repository.close()
        _APP.processEvents()

