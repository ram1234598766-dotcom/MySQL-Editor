"""Disposable MySQL service integration tests.

These checks skip unless MYSQL_EDITOR_TEST_HOST is set. CI runs them against an isolated
MySQL container. Never point this suite at a production database.
"""
from __future__ import annotations

import csv
import os
import sqlite3

import mysql.connector
import pytest

from mysql_editor.database import DatabaseWorker

pytestmark = pytest.mark.skipif(
    not os.environ.get("MYSQL_EDITOR_TEST_HOST"),
    reason="requires the disposable MySQL integration service",
)


def _config(password: str | None = None) -> dict:
    return {
        "host": os.environ["MYSQL_EDITOR_TEST_HOST"],
        "port": int(os.environ.get("MYSQL_EDITOR_TEST_PORT", "3306")),
        "username": os.environ["MYSQL_EDITOR_TEST_USER"],
        "password": password if password is not None else os.environ["MYSQL_EDITOR_TEST_PASSWORD"],
        "default_schema": os.environ.get("MYSQL_EDITOR_TEST_DATABASE", "mysql_editor_test"),
        "tls_mode": "Automatic TLS",
        "ca_file": "",
        "read_timeout": 15,
        "write_timeout": 15,
    }


@pytest.fixture
def worker(tmp_path):
    instance = DatabaseWorker()
    instance._spool = sqlite3.connect(":memory:")
    instance._spool.executescript(
        """
        CREATE TABLE result_meta (
            result_id TEXT PRIMARY KEY, headers TEXT NOT NULL, statement TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE result_rows (
            result_id TEXT NOT NULL, row_idx INTEGER NOT NULL, values_json TEXT NOT NULL,
            PRIMARY KEY(result_id,row_idx)
        );
        """
    )
    instance._spool.commit()
    yield instance
    try:
        instance._dispatch("disconnect", {})
    finally:
        instance._spool.close()
        instance._spool = None
        try:
            instance._spool_dir.rmdir()
        except OSError:
            pass


def test_mysql_query_schema_transaction_and_csv_round_trip(worker, tmp_path):
    connected = worker._dispatch("connect", {"config": _config()})
    assert connected["ok"] is True
    assert connected["database"] == _config()["default_schema"]
    assert connected["server_version"]

    setup = worker._dispatch(
        "query",
        {"sql": """
            DROP TABLE IF EXISTS editor_integration_rows;
            CREATE TABLE editor_integration_rows (
                id INT PRIMARY KEY,
                label VARCHAR(100) NOT NULL,
                note VARCHAR(100) NULL
            );
        """},
    )
    assert setup["ok"] is True
    assert len(setup["results"]) == 2
    assert [item["statement_index"] for item in setup["results"]] == [1, 2]
    assert all(item["statement_count"] == 2 for item in setup["results"])
    assert all("warning_count" in item for item in setup["results"])
    worker._dispatch("commit", {})

    seeded = worker._dispatch(
        "query",
        {"sql": """
            INSERT INTO editor_integration_rows (id, label, note) VALUES
              (1, 'café', NULL),
              (2, '東京', 'keep'),
              (3, 'O''Reilly', 'keep');
        """},
    )
    assert seeded["ok"] is True
    worker._dispatch("commit", {})

    selected = worker._dispatch(
        "query",
        {"sql": "SELECT id, label, note FROM editor_integration_rows ORDER BY id;"},
    )
    assert selected["ok"] is True
    result = selected["results"][-1]
    assert result["row_count"] == 3
    assert result["rows"] == [[1, "café", None], [2, "東京", "keep"], [3, "O'Reilly", "keep"]]

    exported_path = tmp_path / "result.csv"
    exported = worker._dispatch(
        "export_csv", {"result_id": result["result_id"], "path": str(exported_path)}
    )
    assert exported["ok"] is True
    assert exported["row_count"] == 3
    with exported_path.open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.reader(handle))
    assert csv_rows == [
        ["id", "label", "note"],
        ["1", "café", r"\N"],
        ["2", "東京", "keep"],
        ["3", "O'Reilly", "keep"],
    ]

    schema = worker._dispatch("schema", {"schema": _config()["default_schema"]})
    assert schema["ok"] is True
    assert any(obj["name"] == "editor_integration_rows" for obj in schema["objects"])

    procedure = worker._dispatch(
        "query",
        {"sql": """
            DROP PROCEDURE IF EXISTS editor_delimiter_test;
            DELIMITER //
            CREATE PROCEDURE editor_delimiter_test()
            BEGIN
                SET @editor_delimiter_probe = 'semicolon;inside';
                SELECT @editor_delimiter_probe AS marker;
            END//
            DELIMITER ;
            CALL editor_delimiter_test();
            DROP PROCEDURE editor_delimiter_test;
        """},
    )
    assert procedure["ok"] is True, procedure.get("error")
    assert len(procedure["results"]) == 4
    assert procedure["results"][2]["rows"] == [["semicolon;inside"]]

    transaction = worker._dispatch(
        "query",
        {"sql": """
            START TRANSACTION;
            INSERT INTO editor_integration_rows (id, label, note)
            VALUES (4, 'rollback-check', 'not persisted');
        """},
    )
    assert transaction["ok"] is True
    assert worker._dispatch("rollback", {})["ok"] is True
    count = worker._dispatch(
        "query", {"sql": "SELECT COUNT(*) AS n FROM editor_integration_rows;"}
    )
    assert count["ok"] is True
    assert count["results"][-1]["rows"] == [[3]]


def test_mysql_rejects_wrong_password(worker):
    bad = _config(password=os.urandom(32).hex())
    with pytest.raises(mysql.connector.Error):
        worker._dispatch("test", {"config": bad})
