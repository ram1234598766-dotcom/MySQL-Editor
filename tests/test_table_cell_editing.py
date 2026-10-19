"""UI regression tests for safe, explicit table-preview cell editing."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QDialog

import mysql_editor.ui.main_window as main_window_module
from mysql_editor.storage import LocalRepository
from mysql_editor.ui.main_window import MainWindow

_APP = QApplication.instance() or QApplication([])


class SettingsStub:
    def __init__(self):
        self.values = {}

    def value(self, key, defaultValue=None, type=None):
        result = self.values.get(key, defaultValue)
        if type is not None:
            try:
                return type(result)
            except (TypeError, ValueError):
                return defaultValue
        return result

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        pass


class StubWorker(QObject):
    completed = Signal(str, str, object)
    activity = Signal(str)
    task_activity = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.submissions = []

    def submit(self, action, payload=None, task_id=None):
        task_id = task_id or f"cell-edit-{len(self.submissions) + 1}"
        self.submissions.append((action, payload or {}, task_id))
        return task_id

    def cancel_current_query(self):
        pass

    def shutdown(self):
        pass

    def wait(self, _milliseconds=5000):
        return True


def _make_window(tmp_path, monkeypatch):
    settings = SettingsStub()
    monkeypatch.setattr("mysql_editor.ui.main_window.QSettings", lambda: settings)
    repository = LocalRepository(tmp_path / "cell-edit.sqlite3")
    worker = StubWorker()
    window = MainWindow(
        worker,
        repository,
        object(),
        {
            "id": "cell-edit-profile",
            "name": "Cell edit test",
            "host": "localhost",
            "port": 3306,
            "username": "writer",
        },
        {
            "host": "localhost",
            "port": 3306,
            "username": "writer",
            "default_schema": "analytics",
            "tls_mode": "Automatic TLS",
        },
        {"server_version": "MySQL test", "database": "analytics"},
    )
    return window, repository, worker


def _table_preview_item(*, enabled=True):
    return {
        "result_id": "preview-items-1",
        "kind": "rows",
        "headers": ["id", "label", "quantity"],
        "rows": [[7, "old", 5], [8, "second", 9]],
        "row_count": 2,
        "table_edit": {
            "enabled": enabled,
            "schema": "analytics",
            "table": "items",
            "session_token": "test-preview-session",
            "primary_key_columns": ["id"],
            "primary_key_indices": [0],
            "row_keys": [[7], [8]],
            "original_values": {"1": ["old", "second"], "2": [5, 9]},
            "editable_column_indices": [1, 2] if enabled else [],
            "reason": "" if enabled else "The table has no primary key.",
        },
    }


def _set_current_preview(window, item):
    window._query_results = [item]
    window._current_result_id = item["result_id"]
    window.result_model.update(item["headers"], item["rows"])
    window.result_picker.blockSignals(True)
    window.result_picker.clear()
    window.result_picker.addItem("Table preview", 0)
    window.result_picker.setCurrentIndex(0)
    window.result_picker.blockSignals(False)


def test_only_non_key_cells_from_an_eligible_table_preview_offer_edit_context(
    tmp_path, monkeypatch,
):
    window, repository, _worker = _make_window(tmp_path, monkeypatch)
    try:
        item = _table_preview_item()
        _set_current_preview(window, item)
        editable = window.result_proxy.mapFromSource(window.result_model.index(0, 1))
        primary_key = window.result_proxy.mapFromSource(window.result_model.index(0, 0))

        entry = window._table_cell_edit_entry(editable)
        assert entry["column_name"] == "label"
        assert entry["old_value"] == "old"
        assert entry["primary_key_values"] == [7]
        assert window._table_cell_edit_entry(primary_key) is None

        read_only = _table_preview_item(enabled=False)
        _set_current_preview(window, read_only)
        index = window.result_proxy.mapFromSource(window.result_model.index(0, 1))
        assert window._table_cell_edit_entry(index) is None

        ordinary_query_result = {
            "result_id": "query-result",
            "kind": "rows",
            "headers": ["id", "label"],
            "rows": [[7, "old"]],
            "row_count": 1,
        }
        _set_current_preview(window, ordinary_query_result)
        index = window.result_proxy.mapFromSource(window.result_model.index(0, 1))
        assert window._table_cell_edit_entry(index) is None
    finally:
        window.close()
        repository.close()
        _APP.processEvents()


def test_confirmed_cell_edit_dispatches_one_parameterized_update_without_commit(
    tmp_path, monkeypatch,
):
    window, repository, worker = _make_window(tmp_path, monkeypatch)
    _set_current_preview(window, _table_preview_item())
    editor_instances = []

    class DialogStub:
        def __init__(self, **kwargs):
            editor_instances.append(kwargs)

        def exec(self):
            return QDialog.DialogCode.Accepted

        def new_value(self):
            return "new label"

    monkeypatch.setattr(main_window_module, "EditTableCellDialog", DialogStub)
    try:
        index = window.result_proxy.mapFromSource(window.result_model.index(0, 1))
        window._edit_table_preview_cell(index)

        action, payload, job_id = worker.submissions[-1]
        assert action == "update_table_cell"
        assert payload == {
            "result_id": "preview-items-1",
            "session_token": "test-preview-session",
            "row_index": 0,
            "column_index": 1,
            "schema": "analytics",
            "table": "items",
            "column_name": "label",
            "primary_key_columns": ["id"],
            "primary_key_values": [7],
            "expected_old": "old",
            "new_value": "new label",
        }
        assert editor_instances[0]["current_value"] == "old"
        assert editor_instances[0]["primary_key_summary"] == "id=7"
        assert window._cell_edit_pending is True
        assert window.result_grid.isEnabled() is False
        assert all(submission[0] != "commit" for submission in worker.submissions)

        window._on_worker_completed(job_id, "update_table_cell", {
            "ok": True,
            "result_id": "preview-items-1",
            "row_index": 0,
            "column_index": 1,
            "column_name": "label",
            "display_row": [7, "new label", 5],
            "raw_row": [7, "new label", 5],
            "no_change": False,
            "transaction_open": True,
        })

        assert window._cell_edit_pending is False
        assert window.result_grid.isEnabled() is True
        assert window._transaction_open is True
        assert window._query_results[0]["rows"] == [[7, "new label", 5], [8, "second", 9]]
        assert window.result_model.rows[0] == [7, "new label", 5]
        assert window._query_results[0]["table_edit"]["original_values"]["1"][0] == "new label"
        assert "Commit" in window.status.text()
        assert all(submission[0] != "commit" for submission in worker.submissions)
    finally:
        window.close()
        repository.close()
        _APP.processEvents()


def test_cell_update_conflict_does_not_modify_preview_values(tmp_path, monkeypatch):
    window, repository, _worker = _make_window(tmp_path, monkeypatch)
    _set_current_preview(window, _table_preview_item())
    warnings = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "warning",
        lambda _parent, title, message, *_args: warnings.append((title, message)),
    )
    try:
        window._jobs["failed-edit"] = (
            "update_table_cell",
            {
                "result_id": "preview-items-1",
                "row_index": 0,
                "column_index": 1,
                "column_name": "label",
            },
        )
        window._cell_edit_pending = True
        window.result_grid.setEnabled(False)

        window._on_worker_completed("failed-edit", "update_table_cell", {
            "ok": False,
            "error": "The cell changed on MySQL since this preview.",
            "transaction_open": True,
        })

        assert len(warnings) == 1
        assert "changed on MySQL" in warnings[0][1]
        assert window._cell_edit_pending is False
        assert window.result_grid.isEnabled() is True
        assert window.result_model.rows[0] == [7, "old", 5]
        assert window._transaction_open is True
    finally:
        window.close()
        repository.close()
        _APP.processEvents()

def test_transaction_rollback_restores_display_and_raw_preview_values(tmp_path, monkeypatch):
    window, repository, _worker = _make_window(tmp_path, monkeypatch)
    item = _table_preview_item()
    _set_current_preview(window, item)
    try:
        update_context = {
            "result_id": item["result_id"],
            "row_index": 0,
            "column_index": 1,
            "schema": "analytics",
            "table": "items",
            "column_name": "label",
        }
        window._jobs["cell-edit-rollback-test"] = ("update_table_cell", update_context)
        window._cell_edit_pending = True
        window.result_grid.setEnabled(False)

        window._on_worker_completed("cell-edit-rollback-test", "update_table_cell", {
            "ok": True,
            "result_id": item["result_id"],
            "row_index": 0,
            "column_index": 1,
            "column_name": "label",
            "display_row": [7, "new label", 5],
            "raw_row": [7, "new label", 5],
            "no_change": False,
            "transaction_open": True,
        })

        assert window._query_results[0]["rows"][0] == [7, "new label", 5]
        assert window._query_results[0]["table_edit"]["original_values"]["1"][0] == "new label"
        assert window._pending_table_preview_undo[("preview-items-1", 0)] == {
            "display_row": [7, "old", 5],
            "original_values": {"1": "old", "2": 5},
        }

        window._jobs["rollback-after-cell-edit"] = ("rollback", {})
        window._on_worker_completed("rollback-after-cell-edit", "rollback", {
            "ok": True,
            "message": "Transaction rolled back. Restored 1 table-preview row snapshot(s).",
            "transaction_open": False,
            "preview_transaction_finalized": True,
            "preview_rollback_rows": [{
                "result_id": "preview-items-1",
                "row_index": 0,
                "display_row": [7, "old", 5],
            }],
            "preview_restore_errors": [],
        })

        assert window._query_results[0]["rows"][0] == [7, "old", 5]
        assert window.result_model.rows[0] == [7, "old", 5]
        assert window._query_results[0]["table_edit"]["original_values"]["1"][0] == "old"
        assert window._query_results[0]["table_edit"]["original_values"]["2"][0] == 5
        assert window._pending_table_preview_undo == {}
        assert window._transaction_open is False
        assert "Transaction rolled back" in window.status.text()
    finally:
        window.close()
        repository.close()
        _APP.processEvents()

