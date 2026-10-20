"""Read-only visual presentation for MySQL EXPLAIN FORMAT=JSON output."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ExplainPlanError(ValueError):
    """An EXPLAIN response did not contain a valid MySQL JSON plan."""


# EXPLAIN plans come from a remote server. Bound parsing and widget construction so
# an unexpectedly large or deeply nested response cannot stall the desktop UI.
MAX_EXPLAIN_JSON_CHARS = 2 * 1024 * 1024
MAX_PLAN_TREE_NODES = 3000
MAX_PLAN_TREE_DEPTH = 32
MAX_PLAN_SUMMARY_NODES = 10000


def extract_explain_json(result: Mapping[str, Any]) -> dict[str, Any] | list[Any]:
    """Extract a bounded JSON payload from a successful EXPLAIN query result."""
    if not result.get("ok"):
        detail = str(result.get("error") or "MySQL could not produce an execution plan.")
        raise ExplainPlanError(detail)

    row_results = [
        item for item in (result.get("results") or [])
        if isinstance(item, Mapping) and str(item.get("kind", "")).casefold() == "rows"
    ]
    if not row_results:
        raise ExplainPlanError("MySQL returned no JSON execution-plan row.")

    headers = [str(value).strip().casefold() for value in row_results[0].get("headers", [])]
    rows = row_results[0].get("rows") or []
    if not rows or not rows[0]:
        raise ExplainPlanError("MySQL returned an empty JSON execution-plan row.")

    explain_column = next(
        (index for index, header in enumerate(headers) if "explain" in header),
        0,
    )
    if explain_column >= len(rows[0]):
        raise ExplainPlanError("The execution-plan row did not contain the EXPLAIN column.")

    raw = rows[0][explain_column]
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExplainPlanError("MySQL returned non-text execution-plan data.") from exc
    raw_text = str(raw)
    if len(raw_text) > MAX_EXPLAIN_JSON_CHARS:
        raise ExplainPlanError(
            f"MySQL returned an execution plan larger than the {MAX_EXPLAIN_JSON_CHARS:,}-character limit."
        )
    try:
        plan = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise ExplainPlanError("MySQL returned malformed or excessively nested JSON execution-plan data.") from exc
    if not isinstance(plan, (dict, list)):
        raise ExplainPlanError("The JSON execution plan must be an object or array.")
    return plan


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()


def _compact(value: Any, limit: int = 180) -> str:
    if value is None:
        return "(NULL)"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (dict, list)):
        rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        rendered = str(value)
    return rendered if len(rendered) <= limit else rendered[:limit - 1] + "…"


def _node_label(key: str, value: Any) -> str:
    if isinstance(value, Mapping):
        table_name = value.get("table_name")
        if table_name is not None:
            access = value.get("access_type")
            return f"Table: {table_name}" + (f" · access {access}" if access else "")
        normalized = key.casefold()
        labels = {
            "query_block": "Query block",
            "cost_info": "Cost information",
            "nested_loop": "Nested loop",
            "grouping_operation": "Grouping operation",
            "ordering_operation": "Ordering operation",
            "duplicates_removal": "Duplicate removal",
            "union_result": "Union result",
            "materialized_from_subquery": "Materialized subquery",
            "table": "Table",
        }
        return labels.get(normalized, _humanize(key))
    if isinstance(value, list):
        return f"{_humanize(key)} ({len(value)} item(s))"
    return f"{_humanize(key)}: {_compact(value)}"


def _add_tree_limit_notice(
    parent: QTreeWidgetItem, budget: dict[str, Any], message: str
) -> None:
    if budget["notice_added"]:
        return
    notice = QTreeWidgetItem(parent, [message])
    notice.setToolTip(0, message)
    budget["notice_added"] = True
    budget["nodes"] += 1


def _append_scalar_item(
    parent: QTreeWidgetItem, label: str, value: Any, budget: dict[str, Any]
) -> bool:
    if budget["nodes"] >= MAX_PLAN_TREE_NODES:
        _add_tree_limit_notice(
            parent, budget, "Additional plan details omitted (tree size limit reached)."
        )
        return False
    item = QTreeWidgetItem(parent, [label])
    item.setToolTip(0, str(value))
    budget["nodes"] += 1
    return True


def _append_plan_value(
    parent: QTreeWidgetItem,
    key: str,
    value: Any,
    *,
    depth: int = 0,
    budget: dict[str, Any] | None = None,
) -> bool:
    """Append a plan subtree under explicit depth/node budgets.

    Return False when the global node budget is exhausted so sibling loops can stop
    promptly instead of iterating over an arbitrarily large server-provided object.
    """
    if budget is None:
        budget = {"nodes": 0, "notice_added": False}
    if budget["nodes"] >= MAX_PLAN_TREE_NODES:
        _add_tree_limit_notice(
            parent, budget, "Additional plan details omitted (tree size limit reached)."
        )
        return False

    item = QTreeWidgetItem(parent, [_node_label(key, value)])
    budget["nodes"] += 1
    if isinstance(value, (Mapping, list)) and depth >= MAX_PLAN_TREE_DEPTH:
        if value:
            _add_tree_limit_notice(
                item, budget, "Nested details omitted (maximum plan depth reached)."
            )
        return True

    if isinstance(value, Mapping):
        # Keep a bounded tooltip summary; individual scalar values remain accessible
        # as tree leaves and tooltips.
        details = []
        for name, child_value in value.items():
            if isinstance(child_value, (Mapping, list)):
                continue
            details.append(f"{_humanize(str(name))}: {_compact(child_value, 96)}")
            if len(details) >= 20:
                details.append("Additional scalar values are listed in child rows.")
                break
        if details:
            item.setToolTip(0, "\n".join(details))

        for child_key, child_value in value.items():
            if isinstance(child_value, (Mapping, list)):
                if not _append_plan_value(
                    item, str(child_key), child_value, depth=depth + 1, budget=budget
                ):
                    break
            elif not _append_scalar_item(
                item,
                f"{_humanize(str(child_key))}: {_compact(child_value)}",
                child_value,
                budget,
            ):
                break
    elif isinstance(value, list):
        item.setToolTip(0, f"{len(value)} item(s)")
        for index, child_value in enumerate(value, start=1):
            if isinstance(child_value, (Mapping, list)):
                if not _append_plan_value(
                    item, f"Step {index}", child_value, depth=depth + 1, budget=budget
                ):
                    break
            elif not _append_scalar_item(item, f"Step {index}: {_compact(child_value)}", child_value, budget):
                break
    else:
        item.setToolTip(0, str(value))
    return True


def _walk_mappings(value: Any):
    """Iterate plan mappings without recursion and with a strict visit budget."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    visited = 0
    while stack and visited < MAX_PLAN_SUMMARY_NODES:
        current, depth = stack.pop()
        visited += 1
        if isinstance(current, Mapping):
            yield current
            if depth < MAX_PLAN_TREE_DEPTH:
                stack.extend((child, depth + 1) for child in reversed(tuple(current.values())))
        elif isinstance(current, list) and depth < MAX_PLAN_TREE_DEPTH:
            stack.extend((child, depth + 1) for child in reversed(current))


def summarize_explain_plan(plan: dict[str, Any] | list[Any]) -> str:
    """Return compact optimizer-estimate context for the top of the plan dialog."""
    tables = []
    costs = []
    estimates = []
    for node in _walk_mappings(plan):
        if node.get("table_name") is not None:
            name = str(node["table_name"])
            access = str(node.get("access_type") or "access method unknown")
            tables.append(f"{name} ({access})")
            rows = node.get("rows_examined_per_scan")
            if rows is not None:
                estimates.append(f"{name}: ~{_compact(rows)} row(s)/scan")
        cost_info = node.get("cost_info")
        if isinstance(cost_info, Mapping) and cost_info.get("query_cost") is not None:
            costs.append(str(cost_info["query_cost"]))

    parts = []
    if tables:
        parts.append("Tables: " + ", ".join(dict.fromkeys(tables)))
    if estimates:
        parts.append("Estimated rows: " + "; ".join(dict.fromkeys(estimates)))
    if costs:
        parts.append("Optimizer cost: " + ", ".join(dict.fromkeys(costs)))
    if not parts:
        parts.append("Plan details are shown in the tree below.")
    parts.append("Row counts and costs are estimates, not actual execution measurements.")
    summary = "  ·  ".join(parts)
    return summary if len(summary) <= 6000 else summary[:5999] + "…"


class ExplainPlanDialog(QDialog):
    """Expandable tree and raw JSON view for an already-computed MySQL execution plan."""

    def __init__(
        self,
        plan: dict[str, Any] | list[Any],
        sql: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.plan = plan
        self.sql = str(sql or "")
        self.raw_json = json.dumps(plan, indent=2, ensure_ascii=False)
        self.setWindowTitle("MySQL Execution Plan")
        self.setMinimumSize(860, 580)
        self.resize(1120, 760)

        layout = QVBoxLayout(self)
        heading = QLabel("Execution plan · EXPLAIN FORMAT=JSON")
        heading.setObjectName("panelTitle")
        heading.setAccessibleName("Visual MySQL execution plan")
        layout.addWidget(heading)

        summary = QLabel(summarize_explain_plan(plan))
        summary.setObjectName("mutedText")
        summary.setWordWrap(True)
        summary.setAccessibleName("Execution plan summary")
        layout.addWidget(summary)

        tabs = QTabWidget(self)
        tabs.setAccessibleName("Execution plan views")
        layout.addWidget(tabs, 1)

        tree_page = QWidget(tabs)
        tree_layout = QVBoxLayout(tree_page)
        note = QLabel(
            "Expand operation nodes to inspect table access, optimizer estimates, "
            "cost information, filters, and nested operations."
        )
        note.setObjectName("mutedText")
        note.setWordWrap(True)
        tree_layout.addWidget(note)

        self.plan_tree = QTreeWidget(tree_page)
        self.plan_tree.setObjectName("explainPlanTree")
        self.plan_tree.setAccessibleName("Expandable execution plan operations")
        self.plan_tree.setHeaderHidden(True)
        self.plan_tree.setUniformRowHeights(True)
        root = QTreeWidgetItem(self.plan_tree, ["JSON execution plan"])
        budget: dict[str, Any] = {"nodes": 1, "notice_added": False}
        if isinstance(plan, Mapping):
            for key, value in plan.items():
                if not _append_plan_value(root, str(key), value, budget=budget):
                    break
        else:
            for index, value in enumerate(plan, start=1):
                if not _append_plan_value(root, f"Step {index}", value, budget=budget):
                    break
        root.setExpanded(True)
        self.plan_tree.expandToDepth(2)
        tree_layout.addWidget(self.plan_tree, 1)
        tabs.addTab(tree_page, "Visual plan")

        self.json_view = QPlainTextEdit(tabs)
        self.json_view.setObjectName("explainPlanJson")
        self.json_view.setAccessibleName("Raw JSON execution plan")
        self.json_view.setReadOnly(True)
        self.json_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.json_view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.json_view.setPlainText(self.raw_json)
        tabs.addTab(self.json_view, "Raw JSON")

        if self.sql:
            sql_note = QLabel("Plan requested for: " + self.sql)
            sql_note.setObjectName("mutedText")
            sql_note.setWordWrap(True)
            layout.addWidget(sql_note)

        footer = QHBoxLayout()
        self.copy_json_button = QPushButton("Copy JSON")
        self.copy_json_button.setAccessibleName("Copy raw execution plan JSON")
        self.copy_json_button.clicked.connect(self._copy_json)
        footer.addWidget(self.copy_json_button)

        self.copy_status = QLabel("")
        self.copy_status.setObjectName("statusSuccess")
        self.copy_status.setAccessibleName("Execution plan copy status")
        footer.addWidget(self.copy_status, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)

    def _copy_json(self) -> None:
        QApplication.clipboard().setText(self.raw_json)
        self.copy_status.setText("JSON copied to clipboard.")
