"""Regression tests for MySQL JSON execution-plan parsing and presentation."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QLabel, QTreeWidgetItem

import mysql_editor.ui.main_window as main_window_module
import mysql_editor.ui.explain_plan as explain_plan_module
from mysql_editor.storage import LocalRepository
from mysql_editor.ui.explain_plan import (
    ExplainPlanDialog,
    ExplainPlanError,
    extract_explain_json,
)
from mysql_editor.ui.main_window import MainWindow

_APP = QApplication.instance() or QApplication([])


def _sample_plan():
    return {
        "query_block": {
            "select_id": 1,
            "cost_info": {"query_cost": "12.40"},
            "table": {
                "table_name": "orders",
                "access_type": "ALL",
                "rows_examined_per_scan": 250,
                "filtered": "10.00",
                "attached_condition": "status = 'open'",
            },
        }
    }


def _explain_result(plan=None):
    value = _sample_plan() if plan is None else plan
    return {
        "ok": True,
        "duration_ms": 7,
        "results": [{
            "kind": "rows",
            "headers": ["EXPLAIN"],
            "rows": [[json.dumps(value)]],
            "row_count": 1,
        }],
    }


def _tree_contains(item: QTreeWidgetItem, expected: str) -> bool:
    if expected in item.text(0):
        return True
    return any(_tree_contains(item.child(index), expected) for index in range(item.childCount()))


def test_extract_explain_json_reads_mysql_json_result_cell():
    assert extract_explain_json(_explain_result()) == _sample_plan()


def test_extract_explain_json_accepts_utf8_bytes_and_json_arrays():
    plan = [{"query_block": {"select_id": 1}}]
    result = {
        "ok": True,
        "results": [{
            "kind": "rows",
            "headers": ["EXPLAIN"],
            "rows": [[json.dumps(plan).encode("utf-8")]],
        }],
    }

    assert extract_explain_json(result) == plan


@pytest.mark.parametrize(
    ("result", "expected_error"),
    [
        ({"ok": False, "error": "unsupported EXPLAIN format"}, "unsupported EXPLAIN"),
        ({"ok": True, "results": []}, "no JSON execution-plan row"),
        (
            {"ok": True, "results": [{"kind": "rows", "headers": ["EXPLAIN"], "rows": []}]},
            "empty JSON execution-plan row",
        ),
        (
            {"ok": True, "results": [{"kind": "rows", "headers": ["EXPLAIN"], "rows": [["{bad json"]]}]},
            "malformed JSON",
        ),
        (
            {"ok": True, "results": [{"kind": "rows", "headers": ["EXPLAIN"], "rows": [['"scalar"']]}]},
            "object or array",
        ),
    ],
)
def test_extract_explain_json_rejects_failed_empty_and_malformed_responses(result, expected_error):
    with pytest.raises(ExplainPlanError, match=expected_error):
        extract_explain_json(result)


def test_explain_dialog_shows_expandable_table_access_and_copyable_json():
    plan = _sample_plan()
    sql = "SELECT * FROM orders WHERE status = 'open'"
    dialog = ExplainPlanDialog(plan, sql)

    try:
        assert dialog.windowTitle() == "MySQL Execution Plan"
        assert dialog.plan_tree.accessibleName() == "Expandable execution plan operations"
        assert dialog.json_view.isReadOnly()
        assert json.loads(dialog.json_view.toPlainText()) == plan
        assert _tree_contains(dialog.plan_tree.topLevelItem(0), "Table: orders · access ALL")
        assert _tree_contains(dialog.plan_tree.topLevelItem(0), "Rows examined per scan: 250")
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        assert any("Tables: orders (ALL)" in label for label in labels)
        assert any(sql in label for label in labels)

        dialog.copy_json_button.click()
        assert QApplication.clipboard().text() == dialog.raw_json
        assert dialog.copy_status.text() == "JSON copied to clipboard."
    finally:
        dialog.close()
        dialog.deleteLater()
        _APP.processEvents()


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

    def __init__(self):
        super().__init__()
        self.submissions = []

    def submit(self, action, payload=None, task_id=None):
        task_id = task_id or f"explain-plan-{len(self.submissions) + 1}"
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
    repository = LocalRepository(tmp_path / "explain-plan.sqlite3")
    worker = StubWorker()
    window = MainWindow(
        worker,
        repository,
        object(),
        {
            "id": "explain-profile",
            "name": "Explain test",
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
    window._confirm_query_target = lambda _editor: True
    return window, repository, worker


def test_explain_action_dispatches_json_plan_and_opens_visual_dialog(tmp_path, monkeypatch):
    window, repository, worker = _make_window(tmp_path, monkeypatch)
    opened = []

    class DialogSpy:
        def __init__(self, plan, sql, parent=None):
            opened.append((plan, sql, parent))

        def exec(self):
            return 1

    monkeypatch.setattr(main_window_module, "ExplainPlanDialog", DialogSpy)
    sql = "SELECT customer_id FROM orders WHERE status = 'open'"
    try:
        editor = window._current_editor()
        editor.setPlainText(sql)

        window.explain_query()

        action, payload, job_id = worker.submissions[-1]
        assert action == "query"
        assert payload["sql"] == "EXPLAIN FORMAT=JSON " + sql
        context = window._jobs[job_id][1]
        assert context["explain_plan"] is True
        assert context["explained_sql"] == sql

        window._on_worker_completed(job_id, "query", _explain_result())

        assert opened == [(_sample_plan(), sql, window)]
        assert window._query_running is False
        assert window.query_meta.text() == "JSON execution plan"
        assert "SELECT was not executed" in window.status.text()
        assert window._query_results == []
    finally:
        window.close()
        repository.close()
        _APP.processEvents()


def test_explain_failure_is_reported_without_opening_plan_dialog(tmp_path, monkeypatch):
    window, repository, worker = _make_window(tmp_path, monkeypatch)
    warnings = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "warning",
        lambda _parent, title, message, *_args: warnings.append((title, message)),
    )
    sql = "SELECT customer_id FROM orders"
    try:
        editor = window._current_editor()
        editor.setPlainText(sql)
        window.explain_query()
        _action, _payload, job_id = worker.submissions[-1]

        window._on_worker_completed(
            job_id,
            "query",
            {"ok": False, "error": "unsupported EXPLAIN format", "results": [], "duration_ms": 1},
        )

        assert len(warnings) == 1
        assert warnings[0][0] == "Explain SELECT"
        assert "original SELECT was not executed" in warnings[0][1]
        assert "unsupported EXPLAIN format" in warnings[0][1]
        assert window.query_meta.text() == "Execution plan unavailable"
        assert "SELECT was not executed" in window.status.text()
        assert window._query_results == []
    finally:
        window.close()
        repository.close()
        _APP.processEvents()

def _tree_count(item: QTreeWidgetItem) -> int:
    return 1 + sum(_tree_count(item.child(index)) for index in range(item.childCount()))


def test_extract_explain_json_rejects_oversized_and_excessively_nested_payloads(monkeypatch):
    monkeypatch.setattr(explain_plan_module, "MAX_EXPLAIN_JSON_CHARS", 24)
    oversized = {
        "ok": True,
        "results": [{
            "kind": "rows",
            "headers": ["EXPLAIN"],
            "rows": [['{"query_block":{"select_id":1}}']],
        }],
    }
    with pytest.raises(ExplainPlanError, match="larger than the .*character limit"):
        extract_explain_json(oversized)

    monkeypatch.setattr(explain_plan_module, "MAX_EXPLAIN_JSON_CHARS", 100_000)
    deeply_nested = "[" * 1500 + "0" + "]" * 1500
    nested = {
        "ok": True,
        "results": [{
            "kind": "rows",
            "headers": ["EXPLAIN"],
            "rows": [[deeply_nested]],
        }],
    }
    with pytest.raises(ExplainPlanError, match="malformed or excessively nested JSON"):
        extract_explain_json(nested)


def test_explain_tree_enforces_node_budget_for_large_plan(monkeypatch):
    monkeypatch.setattr(explain_plan_module, "MAX_PLAN_TREE_NODES", 18)
    plan = {
        "query_block": {
            "tables": [
                {
                    "table_name": f"table_{index}",
                    "access_type": "ref",
                    "rows_examined_per_scan": index + 1,
                }
                for index in range(80)
            ]
        }
    }
    dialog = ExplainPlanDialog(plan)

    try:
        root = dialog.plan_tree.topLevelItem(0)
        assert _tree_count(root) <= explain_plan_module.MAX_PLAN_TREE_NODES + 1
        assert _tree_contains(root, "tree size limit reached")
        assert json.loads(dialog.json_view.toPlainText()) == plan
    finally:
        dialog.close()
        dialog.deleteLater()
        _APP.processEvents()


def test_explain_tree_enforces_depth_budget_and_keeps_raw_json(monkeypatch):
    monkeypatch.setattr(explain_plan_module, "MAX_PLAN_TREE_DEPTH", 4)
    plan = {"root": {"a": {"b": {"c": {"d": {"e": {"select_id": 1}}}}}}}
    dialog = ExplainPlanDialog(plan)

    try:
        root = dialog.plan_tree.topLevelItem(0)
        assert _tree_contains(root, "maximum plan depth reached")
        assert json.loads(dialog.json_view.toPlainText()) == plan
        # The visual tree is bounded; the unmodified JSON remains available in its tab.
        assert _tree_count(root) < 20
    finally:
        dialog.close()
        dialog.deleteLater()
        _APP.processEvents()

