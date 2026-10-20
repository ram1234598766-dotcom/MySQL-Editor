"""UI regression tests for bounded Schema Explorer table-preview paging."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

import mysql_editor.ui.main_window as main_window_module
from mysql_editor.storage import LocalRepository
from mysql_editor.ui.main_window import MainWindow

_APP = QApplication.instance() or QApplication([])


class SettingsStub:
    def __init__(self):
        self.values = {}

    def value(self, key, defaultValue=None, type=None):
        value = self.values.get(key, defaultValue)
        if type is not None:
            try:
                return type(value)
            except (TypeError, ValueError):
                return defaultValue
        return value

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        pass


class StubWorker(QObject):
    completed = Signal(str, str, object)
    activity = Signal(str)

    def __init__(self):
        super().__init__()
        self.submissions = []

    def submit(self, action, payload=None, task_id=None):
        task_id = task_id or f"table-preview-ui-{len(self.submissions) + 1}"
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
    repository = LocalRepository(tmp_path / "table-preview-ui.sqlite3")
    worker = StubWorker()
    window = MainWindow(
        worker,
        repository,
        object(),
        {
            "id": "table-preview-ui",
            "name": "Table preview test",
            "host": "localhost",
            "port": 3306,
            "username": "reader",
        },
        {
            "host": "localhost",
            "port": 3306,
            "username": "reader",
            "default_schema": "analytics",
            "tls_mode": "Automatic TLS",
        },
        {"server_version": "MySQL test", "database": "analytics"},
    )
    return window, repository, worker


def _item(*, row_start=1, row_count=1203, rows_count=1000, paging_enabled=True):
    rows = [
        [row_start + index, f"row-{row_start + index}", row_start + index + 2]
        for index in range(rows_count)
    ]
    ids = [row[0] for row in rows]
    labels = [row[1] for row in rows]
    quantities = [row[2] for row in rows]
    reason = "" if paging_enabled else "Automatic paging is disabled because MySQL did not provide a verified primary key."
    return {
        "result_id": "preview-result",
        "headers": ["id", "label", "quantity"],
        "rows": rows,
        "row_count": row_count,
        "kind": "rows",
        "window_start_offset": row_start - 1,
        "preview_truncated": rows_count < row_count,
        "table_preview_complete": rows_count >= row_count,
        "table_preview_paging": {
            "enabled": paging_enabled,
            "page_size": 1000,
            "row_count": row_count,
            "cached_rows": rows_count,
            "complete": rows_count >= row_count,
            "reason": reason,
        },
        "table_edit": {
            "enabled": True,
            "schema": "analytics",
            "table": "orders",
            "session_token": "session-test",
            "primary_key_columns": ["id"],
            "primary_key_indices": [0],
            "row_keys": [[value] for value in ids],
            "editable_column_indices": [1, 2],
            "original_values": {"1": labels, "2": quantities},
        },
    }


def _set_current_result(window, item):
    window._query_results = [item]
    window._current_result_id = item["result_id"]
    window.result_model.update(
        item["headers"],
        item["rows"],
        base_offset=item.get("window_start_offset", 0),
        total_rows=item["row_count"],
    )
    window._sync_result_view_interactions(item)
    window._set_result_controls()


def test_incomplete_primary_key_preview_offers_paging_but_blocks_filter_sort_and_export(tmp_path, monkeypatch):
    window, repository, _worker = _make_window(tmp_path, monkeypatch)
    item = _item(paging_enabled=True)
    try:
        _set_current_result(window, item)

        assert window.fetch_more_button.isEnabled()
        assert "Fetch +" in window.fetch_more_button.text()
        assert not window.export_button.isEnabled()
        assert not window.result_filter.isEnabled()
        assert not window.result_grid.isSortingEnabled()
        assert "primary-key" in window.fetch_more_button.toolTip()
    finally:
        window.close()
        repository.close()
        _APP.processEvents()


def test_incomplete_preview_without_primary_key_is_read_only_and_cannot_fetch_more(tmp_path, monkeypatch):
    window, repository, _worker = _make_window(tmp_path, monkeypatch)
    item = _item(paging_enabled=False)
    item["page_load_unavailable"] = True
    try:
        _set_current_result(window, item)

        assert not window.fetch_more_button.isEnabled()
        assert window.fetch_more_button.text() == "Fetch Unavailable"
        assert not window.export_button.isEnabled()
        assert not window.result_filter.isEnabled()
        assert not window.result_grid.isSortingEnabled()
    finally:
        window.close()
        repository.close()
        _APP.processEvents()


def test_edit_metadata_tracks_the_bounded_visible_window_when_rows_are_evicted(tmp_path, monkeypatch):
    window, repository, _worker = _make_window(tmp_path, monkeypatch)
    item = _item(row_start=1001, row_count=7000, rows_count=5000, paging_enabled=True)
    # Existing active window covers IDs 1,001–6,000 after appending the next 1,000 rows.
    new_page = [[value, f"row-{value}", value + 2] for value in range(6001, 7001)]
    page_data = {
        "row_keys": [[row[0]] for row in new_page],
        "original_values": {
            "1": [row[1] for row in new_page],
            "2": [row[2] for row in new_page],
        },
    }
    try:
        window._sync_table_edit_page_metadata(item, page_data, direction="next", evicted=1000)

        assert len(item["table_edit"]["row_keys"]) == 5000
        assert item["table_edit"]["row_keys"][0] == [1001]
        assert item["table_edit"]["row_keys"][-1] == [7000]
        assert item["table_edit"]["original_values"]["1"][0] == "row-1001"
        assert item["table_edit"]["original_values"]["1"][-1] == "row-7000"
    finally:
        window.close()
        repository.close()
        _APP.processEvents()


def test_cell_edit_entry_maps_visible_row_to_absolute_spool_offset(tmp_path, monkeypatch):
    window, repository, _worker = _make_window(tmp_path, monkeypatch)
    item = _item(row_start=1001, row_count=3000, rows_count=1000, paging_enabled=True)
    try:
        _set_current_result(window, item)
        entry = window._table_cell_edit_entry(window.result_proxy.index(0, 1))

        assert entry is not None
        assert entry["row_index"] == 1000
        assert entry["display_row_index"] == 0
        assert entry["primary_key_values"] == [1001]
        assert entry["old_value"] == "row-1001"
    finally:
        window.close()
        repository.close()
        _APP.processEvents()
