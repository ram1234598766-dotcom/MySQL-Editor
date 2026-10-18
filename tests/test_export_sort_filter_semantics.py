"""Regression gate for sorted/filtered result preview versus complete CSV export."""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from mysql_editor.database import DatabaseWorker
from mysql_editor.ui.main_window import ResultsFilterProxyModel, ResultsModel


_APP = QApplication.instance() or QApplication([])


def test_sorting_and_filtering_preview_preserve_complete_csv_fetch_order(tmp_path):
    fetched_rows = [
        ["zeta", 30],
        ["Alpha", 10],
        ["beta", 20],
        ["Match row", 40],
    ]

    model = ResultsModel(["name", "rank"], fetched_rows)
    proxy = ResultsFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.setFilterKeyColumn(-1)
    proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    proxy.sort(1, Qt.SortOrder.AscendingOrder)
    _APP.processEvents()

    assert [proxy.index(row, 0).data() for row in range(proxy.rowCount())] == [
        "Alpha",
        "beta",
        "zeta",
        "Match row",
    ]
    proxy.setFilterFixedString("MATCH")
    _APP.processEvents()
    assert proxy.rowCount() == 1
    assert proxy.index(0, 0).data() == "Match row"

    # The UI sorts/filters through a proxy. The source model remains in fetch order.
    assert model.rows == fetched_rows

    spool = sqlite3.connect(":memory:")
    spool.executescript(
        """
        CREATE TABLE result_meta (
            result_id TEXT PRIMARY KEY,
            headers TEXT NOT NULL,
            statement TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE result_rows (
            result_id TEXT NOT NULL,
            row_idx INTEGER NOT NULL,
            values_json TEXT NOT NULL,
            PRIMARY KEY(result_id, row_idx)
        );
        """
    )
    result_id = "sorted-filtered-preview"
    spool.execute(
        "INSERT INTO result_meta VALUES(?,?,?,?)",
        (result_id, json.dumps(["name", "rank"]), "SELECT name, rank", len(fetched_rows)),
    )
    spool.executemany(
        "INSERT INTO result_rows VALUES(?,?,?)",
        [
            (result_id, index, json.dumps(row))
            for index, row in enumerate(fetched_rows)
        ],
    )
    destination = tmp_path / "sorted-filtered.csv"
    try:
        result = DatabaseWorker._export_csv(
            SimpleNamespace(_spool=spool), result_id, str(destination)
        )
        assert result["ok"] is True
        assert result["row_count"] == len(fetched_rows)
        with destination.open(encoding="utf-8-sig", newline="") as handle:
            exported = list(csv.reader(handle))
        assert exported == [
            ["name", "rank"],
            ["zeta", "30"],
            ["Alpha", "10"],
            ["beta", "20"],
            ["Match row", "40"],
        ]
        assert list(tmp_path.glob(".sorted-filtered.csv.*.tmp")) == []
    finally:
        spool.close()
        model.deleteLater()
        proxy.deleteLater()
        _APP.processEvents()


def test_appending_pages_preserves_fetch_order_and_updates_the_sorted_filter_proxy():
    source_rows = [["zeta", 30], ["Alpha", 10]]
    page_one = [["Match row", 20]]
    page_two = [["match second", 15]]
    model = ResultsModel(["name", "rank"], source_rows)
    proxy = ResultsFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.setFilterKeyColumn(-1)
    proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    proxy.sort(1, Qt.SortOrder.AscendingOrder)
    proxy.setFilterFixedString("MATCH")
    _APP.processEvents()
    inserted = []
    model.rowsInserted.connect(
        lambda _parent, first, last: inserted.append((first, last))
    )

    try:
        assert proxy.rowCount() == 0

        model.append_rows(page_one)
        _APP.processEvents()
        assert inserted == [(2, 2)]
        assert model.rows == source_rows + page_one
        assert proxy.rowCount() == 1
        assert proxy.index(0, 0).data() == "Match row"

        model.append_rows(page_two)
        _APP.processEvents()
        assert inserted == [(2, 2), (3, 3)]
        assert model.rows == source_rows + page_one + page_two
        assert [proxy.index(row, 0).data() for row in range(proxy.rowCount())] == [
            "match second",
            "Match row",
        ]
    finally:
        model.deleteLater()
        proxy.deleteLater()
        _APP.processEvents()
