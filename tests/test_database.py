from mysql_editor.database import DatabaseWorker, is_query_interrupted, safe_db_error


def test_automatic_tls_does_not_require_an_explicit_certificate_file():
    options = DatabaseWorker._connect_options({
        "host": "127.0.0.1",
        "username": "test",
        "password": "not-stored",
        "tls_mode": "Automatic TLS",
        "ca_file": "",
    })
    assert options["ssl_disabled"] is False
    assert options["ssl_verify_cert"] is False
    assert "ssl_ca" not in options


def test_strict_tls_enables_certificate_and_hostname_verification():
    options = DatabaseWorker._connect_options({
        "host": "db.example.invalid",
        "username": "test",
        "password": "not-stored",
        "tls_mode": "Verify server identity",
        "ca_file": "/not/used/in/this/pure-unit-test.pem",
    })
    assert options["ssl_verify_cert"] is True
    assert options["ssl_verify_identity"] is True
    assert options["ssl_ca"] == "/not/used/in/this/pure-unit-test.pem"


def test_disabled_tls_is_an_explicit_choice():
    options = DatabaseWorker._connect_options({
        "host": "localhost",
        "username": "test",
        "password": "",
        "tls_mode": "Disabled",
    })
    assert options["ssl_disabled"] is True


def test_database_errors_are_bounded_and_not_raw_multiline_traces():
    value = safe_db_error(RuntimeError("password=secret\n" + "x" * 1800))
    assert "secret" not in value
    assert len(value) <= 1601


def _csv_spool():
    import sqlite3
    from types import SimpleNamespace

    spool = sqlite3.connect(":memory:")
    spool.executescript("""
        CREATE TABLE result_meta (
            result_id TEXT PRIMARY KEY, headers TEXT NOT NULL,
            statement TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE result_rows (
            result_id TEXT NOT NULL, row_idx INTEGER NOT NULL,
            values_json TEXT NOT NULL, PRIMARY KEY(result_id, row_idx)
        );
    """)
    return SimpleNamespace(_spool=spool)


def test_csv_export_replaces_existing_file_only_after_success(tmp_path):
    import csv
    import json

    spool_owner = _csv_spool()
    result_id = "test-result"
    spool_owner._spool.execute(
        "INSERT INTO result_meta VALUES(?,?,?,?)",
        (result_id, json.dumps(["name", "value"]), "SELECT", 2),
    )
    spool_owner._spool.executemany(
        "INSERT INTO result_rows VALUES(?,?,?)",
        [
            (result_id, 0, json.dumps(["alpha", None])),
            (result_id, 1, json.dumps(["βeta", 42])),
        ],
    )
    destination = tmp_path / "report.csv"
    destination.write_text("previous export must survive a failed write", encoding="utf-8")

    result = DatabaseWorker._export_csv(spool_owner, result_id, str(destination))

    assert result["ok"] is True
    assert result["row_count"] == 2
    with destination.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows == [["name", "value"], ["alpha", ""], ["βeta", "42"]]
    assert list(tmp_path.glob(".report.csv.*.tmp")) == []
    spool_owner._spool.close()


def test_csv_export_failure_preserves_previous_file_and_removes_temp_file(tmp_path):
    import json

    import pytest

    spool_owner = _csv_spool()
    result_id = "broken-result"
    spool_owner._spool.execute(
        "INSERT INTO result_meta VALUES(?,?,?,?)",
        (result_id, json.dumps(["name"]), "SELECT", 1),
    )
    spool_owner._spool.execute(
        "INSERT INTO result_rows VALUES(?,?,?)",
        (result_id, 0, "{not valid json"),
    )
    destination = tmp_path / "report.csv"
    destination.write_text("previous export", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        DatabaseWorker._export_csv(spool_owner, result_id, str(destination))

    assert destination.read_text(encoding="utf-8") == "previous export"
    assert list(tmp_path.glob(".report.csv.*.tmp")) == []
    spool_owner._spool.close()



def test_only_explicit_mysql_interruption_errors_are_classified_as_interrupted():
    class MysqlException(Exception):
        def __init__(self, message, errno=None, sqlstate=None):
            super().__init__(message)
            self.errno = errno
            self.sqlstate = sqlstate

    assert is_query_interrupted(MysqlException("Query execution was interrupted", 1317))
    assert is_query_interrupted(MysqlException("statement interrupted", sqlstate="70100"))
    assert not is_query_interrupted(MysqlException("Lost connection to MySQL server", 2013))
    assert not is_query_interrupted(RuntimeError("Execution timed out"))
