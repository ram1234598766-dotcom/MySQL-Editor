"""Generous, deterministic performance budgets for representative desktop workloads."""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QTableView

import mysql_editor.ui.main_window as main_window_module
from mysql_editor.database import DatabaseWorker
from mysql_editor.storage import LocalRepository
from mysql_editor.ui.editor import SqlEditor
from mysql_editor.ui.main_window import MainWindow, ResultsModel

_APP = QApplication.instance() or QApplication([])


class MemorySettings:
    def __init__(self, *_args, **_kwargs):
        self.values = {}

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is not None and value is not None:
            try:
                return type(value)
            except (TypeError, ValueError):
                return default
        return value

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        pass


class StartupWorker(QObject):
    completed = Signal(str, str, object)
    activity = Signal(str)
    task_activity = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.submissions = []

    def submit(self, action, payload=None, task_id=None):
        chosen_id = task_id or f"perf-task-{len(self.submissions) + 1}"
        self.submissions.append((action, payload or {}, chosen_id))
        return chosen_id

    def cancel_current_query(self):
        pass

    def shutdown(self):
        pass

    def wait(self, _milliseconds=5000):
        return True


def test_main_window_construction_stays_within_startup_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(main_window_module, "QSettings", MemorySettings)
    repository = LocalRepository(tmp_path / "performance.sqlite3")
    worker = StartupWorker()
    profile = {
        "id": "performance-profile",
        "name": "Performance test",
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
    window = None
    try:
        started = time.perf_counter()
        window = MainWindow(
            worker,
            repository,
            object(),
            profile,
            config,
            {"server_version": "MySQL test", "database": ""},
        )
        elapsed = time.perf_counter() - started
        assert window.windowTitle() == "MySQL Editor"
        assert window.editors.count() >= 1
        assert elapsed < 15.0, f"Main-window construction took {elapsed:.2f}s"
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
        repository.close()
        _APP.processEvents()


def test_large_sql_buffer_load_and_single_edit_stay_within_latency_budgets():
    editor = SqlEditor()
    source = "\n".join(
        "SELECT `customer_id`, 'sample' AS label, 42 AS number "
        "FROM `customers` WHERE `customer_id` = 123;"
        for _ in range(1500)
    )
    try:
        started = time.perf_counter()
        editor.setPlainText(source)
        _APP.processEvents()
        load_elapsed = time.perf_counter() - started
        assert editor.document().blockCount() == 1500
        assert load_elapsed < 12.0, f"Loading the SQL buffer took {load_elapsed:.2f}s"

        cursor = editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        editor.setTextCursor(cursor)
        started = time.perf_counter()
        cursor.insertText("\nSELECT 1;")
        editor.setTextCursor(cursor)
        _APP.processEvents()
        edit_elapsed = time.perf_counter() - started
        assert editor.toPlainText().endswith("\nSELECT 1;")
        assert edit_elapsed < 4.0, f"Single SQL edit took {edit_elapsed:.2f}s"
    finally:
        editor.deleteLater()
        _APP.processEvents()


def test_result_grid_handles_a_large_preview_within_render_budget():
    headers = [f"column_{index}" for index in range(16)]
    rows = [
        [f"value-{row}-{column}" if column % 5 else row * column for column in range(16)]
        for row in range(2000)
    ]
    model = ResultsModel()
    table = QTableView()
    table.resize(1100, 520)
    try:
        started = time.perf_counter()
        model.update(headers, rows)
        table.setModel(model)
        table.show()
        _APP.processEvents()
        elapsed = time.perf_counter() - started
        assert model.rowCount() == 2000
        assert model.columnCount() == 16
        assert model.data(model.index(1999, 15)) == "29985"
        assert elapsed < 8.0, f"Updating and showing a result preview took {elapsed:.2f}s"
    finally:
        table.close()
        table.deleteLater()
        _APP.processEvents()


def test_schema_metadata_processing_respects_budget_and_column_cap():
    objects = [(f"table_{index}", "BASE TABLE") for index in range(1200)]
    columns = [
        (f"table_{index % 1200}", f"column_{index}")
        for index in range(10001)
    ]

    class Cursor:
        def __init__(self, connection):
            self.connection = connection
            self.sql = ""

        def execute(self, sql, _parameters=None):
            self.sql = sql

        def fetchall(self):
            return self.connection.objects if "SHOW FULL TABLES" in self.sql else self.connection.columns

        def close(self):
            pass

    class Connection:
        def __init__(self):
            self.objects = objects
            self.columns = columns

        def cursor(self):
            return Cursor(self)

    worker = DatabaseWorker()
    worker._connection = Connection()
    try:
        started = time.perf_counter()
        result = worker._read_schema_objects("performance_schema")
        elapsed = time.perf_counter() - started
        assert result["ok"] is True
        assert len(result["objects"]) == 1200
        assert result["column_metadata_truncated"] is True
        assert sum(len(value) for value in result["columns_by_table"].values()) == 10000
        assert elapsed < 6.0, f"Processing schema metadata took {elapsed:.2f}s"
    finally:
        worker._connection = None
        worker._spool_dir.rmdir()


def test_csv_export_of_twenty_five_thousand_rows_stays_within_budget(tmp_path):
    worker = DatabaseWorker()
    worker._initialize_result_spool()
    result_id = "performance-export"
    headers = ["label", "id", "optional", "description"]
    rows = [
        [f"row-{index}", index, None if index % 17 == 0 else index / 10, "sample payload"]
        for index in range(25000)
    ]
    destination = tmp_path / "performance.csv"
    try:
        worker._save_rows(result_id, headers, "SELECT performance data", rows)
        started = time.perf_counter()
        result = worker._export_csv(result_id, str(destination))
        elapsed = time.perf_counter() - started

        assert result["ok"] is True
        assert result["row_count"] == 25000
        assert destination.is_file()
        assert destination.stat().st_size > 500000
        assert elapsed < 15.0, f"Exporting 25,000 CSV rows took {elapsed:.2f}s"
    finally:
        worker._cleanup_resources()
