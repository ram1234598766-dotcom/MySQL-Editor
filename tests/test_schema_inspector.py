"""Tests for the read-only Schema Object Inspector dialog and UI flow."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from mysql_editor.storage import LocalRepository
from mysql_editor.ui import main_window as main_window_module
from mysql_editor.ui.main_window import MainWindow
from mysql_editor.ui.schema_inspector import SchemaObjectInspectorDialog


_APP = QApplication.instance() or QApplication([])


def _sample_metadata(**overrides):
    ddl = (
        "CREATE TABLE " + chr(96) + "teams" + chr(96) +
        " (" + chr(96) + "team_id" + chr(96) + " int NOT NULL)"
    )
    metadata = {
        "ok": True,
        "schema": "analytics",
        "table": "teams",
        "object_type": "BASE TABLE",
        "definition": ddl,
        "properties": {
            "Object type": "BASE TABLE",
            "Storage engine": "InnoDB",
            "Row format": "Dynamic",
            "Estimated rows": 3,
            "Data size (bytes)": 16384,
            "Comment": "team records",
        },
        "columns": [
            {
                "position": 1,
                "name": "team_id",
                "type": "int unsigned",
                "nullable": "NO",
                "default": None,
                "key": "PRI",
                "extra": "auto_increment",
                "charset": "",
                "collation": "",
                "comment": "Primary identifier",
            }
        ],
        "indexes": [
            {
                "name": "PRIMARY",
                "unique": "Yes",
                "position": 1,
                "column": "team_id",
                "expression": None,
                "collation": "A",
                "cardinality": 3,
                "prefix_length": None,
                "type": "BTREE",
                "visible": "YES",
                "comment": "",
            }
        ],
        "constraints": [
            {
                "name": "PRIMARY",
                "type": "PRIMARY KEY",
                "column": "team_id",
                "position": 1,
                "referenced_schema": "",
                "referenced_table": "",
                "referenced_column": "",
            }
        ],
        "warnings": [],
    }
    metadata.update(overrides)
    return metadata


def test_schema_inspector_dialog_exposes_readonly_definition_and_metadata_tabs():
    ddl = (
        "CREATE TABLE " + chr(96) + "teams" + chr(96) +
        " (" + chr(96) + "team_id" + chr(96) + " int NOT NULL)"
    )
    dialog = SchemaObjectInspectorDialog(_sample_metadata(definition=ddl))

    try:
        labels = [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())]
        assert labels == [
            "Definition", "Columns", "Indexes", "Constraints", "Properties", "Messages",
        ]
        assert "analytics" in dialog.windowTitle()
        assert "teams" in dialog.windowTitle()
        assert dialog.definition_view.isReadOnly()
        assert dialog.definition_view.toPlainText() == ddl
        assert dialog.columns_table.rowCount() == 1
        assert dialog.columns_table.item(0, 1).text() == "team_id"
        assert dialog.columns_table.item(0, 4).text() == "(NULL)"
        assert dialog.indexes_table.rowCount() == 1
        assert dialog.indexes_table.item(0, 0).text() == "PRIMARY"
        assert dialog.constraints_table.rowCount() == 1
        assert dialog.properties_table.rowCount() == 6
        assert "No metadata warnings" in dialog.messages_view.toPlainText()

        dialog.copy_ddl_button.click()
        assert QApplication.clipboard().text() == ddl
        assert dialog.copy_status_label.text() == "Copied to clipboard."
    finally:
        dialog.close()
        dialog.deleteLater()
        _APP.processEvents()


def test_schema_inspector_dialog_disables_copy_when_ddl_is_not_available():
    dialog = SchemaObjectInspectorDialog(_sample_metadata(
        definition="",
        warnings=["Definition unavailable: SHOW VIEW command denied."],
        columns=[],
        indexes=[],
        constraints=[],
    ))

    try:
        assert dialog.definition_view.isReadOnly()
        assert not dialog.copy_ddl_button.isEnabled()
        assert dialog.columns_table.rowCount() == 0
        assert dialog.indexes_table.rowCount() == 0
        assert dialog.constraints_table.rowCount() == 0
        assert dialog.tabs.tabText(5) == "Messages (1)"
        assert "SHOW VIEW command denied" in dialog.messages_view.toPlainText()
    finally:
        dialog.close()
        dialog.deleteLater()
        _APP.processEvents()


class StubWorker(QObject):
    completed = Signal(str, str, object)
    activity = Signal(str)

    def __init__(self):
        super().__init__()
        self.submissions = []

    def submit(self, action, payload=None, task_id=None):
        task_id = task_id or f"schema-inspector-{len(self.submissions) + 1}"
        self.submissions.append((action, payload or {}, task_id))
        return task_id

    def cancel_current_query(self):
        pass

    def shutdown(self):
        pass

    def wait(self, _milliseconds=5000):
        return True


def _make_window(tmp_path):
    repository = LocalRepository(tmp_path / "schema-inspector.sqlite3")
    worker = StubWorker()
    window = MainWindow(
        worker,
        repository,
        object(),
        {
            "id": "schema-inspector",
            "name": "Schema Inspector",
            "host": "localhost",
            "port": 3306,
            "username": "tester",
        },
        {
            "host": "localhost",
            "port": 3306,
            "username": "tester",
            "default_schema": "analytics",
        },
        {"server_version": "MySQL test", "database": "analytics"},
    )
    return window, repository, worker


def test_schema_inspection_uses_worker_and_opens_dialog_on_completion(tmp_path, monkeypatch):
    window, repository, worker = _make_window(tmp_path)
    opened = []

    class DialogSpy:
        def __init__(self, metadata, parent=None):
            self.metadata = metadata
            self.parent = parent

        def exec(self):
            opened.append(self.metadata)
            return 1

    monkeypatch.setattr(main_window_module, "SchemaObjectInspectorDialog", DialogSpy)
    metadata = _sample_metadata()
    try:
        window._inspect_schema_object("analytics", "teams", "BASE TABLE")

        action, payload, job_id = worker.submissions[-1]
        assert action == "inspect_schema_object"
        assert payload == {
            "schema": "analytics",
            "table": "teams",
            "object_type": "BASE TABLE",
        }
        assert "Reading definition and metadata" in window.status.text()

        window._on_worker_completed(job_id, "inspect_schema_object", metadata)

        assert opened == [metadata]
        assert "Inspected" in window.status.text()
        assert "no MySQL object or row data was changed" in window.status.text()
    finally:
        window.close()
        repository.close()


def test_schema_inspection_is_not_queued_while_a_query_is_active(tmp_path):
    window, repository, worker = _make_window(tmp_path)
    try:
        window._query_running = True
        before = len(worker.submissions)

        window._inspect_schema_object("analytics", "teams", "BASE TABLE")

        assert len(worker.submissions) == before
        assert "active SQL statement" in window.status.text()
    finally:
        window._query_running = False
        window.close()
        repository.close()
