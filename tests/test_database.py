from mysql_editor.database import (
    DatabaseWorker, is_connection_lost, is_query_interrupted, safe_db_error,
)


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

def test_result_cache_startup_failure_completes_every_queued_task_and_cleans_up(monkeypatch):
    import sqlite3

    import mysql_editor.database as database_module

    worker = DatabaseWorker()
    events = []
    spool_dir = worker._spool_dir

    def fail_connect(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk is full")

    monkeypatch.setattr(database_module.sqlite3, "connect", fail_connect)
    worker.completed.connect(lambda job_id, action, result: events.append((job_id, action, result)))
    worker.submit("query", {"sql": "SELECT 1"}, task_id="query-pending")
    worker.submit("schema", {"schema": "analytics"}, task_id="schema-pending")
    worker.shutdown()

    worker.run()

    assert [(job_id, action) for job_id, action, _result in events] == [
        ("query-pending", "query"),
        ("schema-pending", "schema"),
    ]
    assert all(result["ok"] is False for _job_id, _action, result in events)
    assert all("local result cache" in result["error"].lower() for _job_id, _action, result in events)
    assert all("disk is full" in result["error"] for _job_id, _action, result in events)
    assert worker._spool is None
    assert not spool_dir.exists()


def test_partial_result_cache_initialization_closes_spool_and_fails_tasks(monkeypatch):
    import sqlite3

    import mysql_editor.database as database_module

    class BrokenSpool:
        closed = False

        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("journal mode unavailable")

        def close(self):
            self.closed = True

    spool = BrokenSpool()
    worker = DatabaseWorker()
    events = []
    spool_dir = worker._spool_dir

    monkeypatch.setattr(database_module.sqlite3, "connect", lambda *_args, **_kwargs: spool)
    worker.completed.connect(lambda job_id, action, result: events.append((job_id, action, result)))
    worker.submit("export_csv", {"result_id": "r", "path": "ignored.csv"}, task_id="partial-init")
    worker.shutdown()

    worker.run()

    assert len(events) == 1
    assert events[0][0:2] == ("partial-init", "export_csv")
    assert events[0][2]["ok"] is False
    assert "journal mode unavailable" in events[0][2]["error"]
    assert spool.closed is True
    assert worker._spool is None
    assert not spool_dir.exists()

def test_worker_shutdown_closes_and_removes_result_cache(tmp_path):
    worker = DatabaseWorker()
    events = []
    spool_dir = worker._spool_dir
    worker.completed.connect(lambda job_id, action, result: events.append((job_id, action, result)))
    worker.submit("unsupported-test-action", {}, task_id="shutdown-cleanup")
    worker.shutdown()

    worker.run()

    assert len(events) == 1
    assert events[0][0:2] == ("shutdown-cleanup", "unsupported-test-action")
    assert events[0][2]["ok"] is False
    assert "Unknown worker action" in events[0][2]["error"]
    assert worker._spool is None
    assert not spool_dir.exists()


def test_worker_recovers_from_task_exception_and_completes_following_tasks(monkeypatch):
    worker = DatabaseWorker()
    events = []
    spool_dir = worker._spool_dir
    worker.completed.connect(lambda job_id, action, result: events.append((job_id, action, result)))

    def dispatch(action, payload):
        if payload.get("explode"):
            raise RuntimeError("password=exception-secret")
        return {"ok": True, "action": action}

    monkeypatch.setattr(worker, "_dispatch", dispatch)
    worker.submit("query", {"explode": True}, task_id="failing-task")
    worker.submit("schema", {"schema": "analytics"}, task_id="following-task")
    worker.shutdown()

    worker.run()

    assert [(job_id, action) for job_id, action, _result in events] == [
        ("failing-task", "query"),
        ("following-task", "schema"),
    ]
    assert events[0][2]["ok"] is False
    assert "exception-secret" not in events[0][2]["error"]
    assert events[0][2]["error"] == "password=[REDACTED]"
    assert events[1][2] == {"ok": True, "action": "schema"}
    assert worker._spool is None
    assert not spool_dir.exists()

def _fake_mysql_connection(row=("8.4.0", "analytics", "tester@localhost"), connection_id=17, execute_error=None):
    class FakeCursor:
        def __init__(self):
            self.close_calls = 0

        def execute(self, _statement):
            if execute_error is not None:
                raise execute_error

        def fetchone(self):
            return row

        def close(self):
            self.close_calls += 1

    class FakeConnection:
        def __init__(self):
            self.connection_id = connection_id
            self.cursor_instance = FakeCursor()
            self.close_calls = 0
            self.in_transaction = False
            self.rollback_calls = 0
            self.commit_calls = 0

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            self.commit_calls += 1
            self.in_transaction = False

        def rollback(self):
            self.rollback_calls += 1
            self.in_transaction = False

        def close(self):
            self.close_calls += 1

    return FakeConnection()


def test_new_connection_replaces_old_only_after_successful_handshake(monkeypatch):
    import mysql.connector

    worker = DatabaseWorker()
    previous = _fake_mysql_connection(connection_id=11)
    candidate = _fake_mysql_connection(connection_id=22)
    old_config = {"host": "old.example.test", "password": "old-secret"}
    worker._connection = previous
    worker._connection_id = 11
    worker._connection_config = old_config
    candidate.in_transaction = True  # Simulate the handshake having opened an implicit transaction.
    monkeypatch.setattr(mysql.connector, "connect", lambda **_options: candidate)

    result = worker._dispatch("connect", {"config": {
        "host": "new.example.test", "username": "reporter", "password": "new-secret",
    }})

    assert result == {
        "ok": True,
        "server_version": "8.4.0",
        "database": "analytics",
        "current_user": "tester@localhost",
        "transaction_open": False,
    }
    assert candidate.rollback_calls == 1
    assert not candidate.in_transaction
    assert worker._connection is candidate
    assert worker._connection_id == 22
    assert worker._connection_config["host"] == "new.example.test"
    assert previous.close_calls == 1
    assert candidate.close_calls == 0
    assert candidate.cursor_instance.close_calls == 1


def test_failed_new_connection_handshake_preserves_old_and_closes_candidate(monkeypatch):
    import mysql.connector
    import pytest

    worker = DatabaseWorker()
    previous = _fake_mysql_connection(connection_id=11)
    failure = RuntimeError("new server rejected connection")
    candidate = _fake_mysql_connection(connection_id=22, execute_error=failure)
    old_config = {"host": "old.example.test", "password": "old-secret"}
    worker._connection = previous
    worker._connection_id = 11
    worker._connection_config = old_config
    monkeypatch.setattr(mysql.connector, "connect", lambda **_options: candidate)

    with pytest.raises(RuntimeError, match="rejected connection"):
        worker._dispatch("connect", {"config": {
            "host": "new.example.test", "username": "reporter", "password": "new-secret",
        }})

    assert worker._connection is previous
    assert worker._connection_id == 11
    assert worker._connection_config is old_config
    assert previous.close_calls == 0
    assert candidate.close_calls == 1
    assert candidate.cursor_instance.close_calls == 1


def test_connection_creation_failure_leaves_existing_connection_usable(monkeypatch):
    import mysql.connector
    import pytest

    worker = DatabaseWorker()
    previous = _fake_mysql_connection(connection_id=11)
    old_config = {"host": "old.example.test", "password": "old-secret"}
    worker._connection = previous
    worker._connection_id = 11
    worker._connection_config = old_config

    def fail_connect(**_options):
        raise RuntimeError("authentication rejected")

    monkeypatch.setattr(mysql.connector, "connect", fail_connect)
    with pytest.raises(RuntimeError, match="authentication rejected"):
        worker._dispatch("connect", {"config": {
            "host": "new.example.test", "username": "reporter", "password": "new-secret",
        }})

    assert worker._connection is previous
    assert worker._connection_id == 11
    assert worker._connection_config is old_config
    assert previous.close_calls == 0




def test_commit_and_rollback_return_updated_transaction_state():
    worker = DatabaseWorker()
    connection = _fake_mysql_connection()
    worker._connection = connection
    connection.in_transaction = True

    committed = worker._dispatch("commit", {})
    assert committed == {
        "ok": True,
        "message": "Transaction committed.",
        "transaction_open": False,
    }
    assert connection.commit_calls == 1
    assert not connection.in_transaction

    connection.in_transaction = True
    rolled_back = worker._dispatch("rollback", {})
    assert rolled_back == {
        "ok": True,
        "message": "Transaction rolled back.",
        "transaction_open": False,
    }
    assert connection.rollback_calls == 1
    assert not connection.in_transaction



def test_worker_progress_emits_the_task_id_that_caused_it():
    worker = DatabaseWorker()
    tagged = []
    untagged = []
    worker.task_activity.connect(lambda task_id, message: tagged.append((task_id, message)))
    worker.activity.connect(lambda message: untagged.append(message))

    worker._current_task_id = "query-1"
    worker._report_activity("Fetched 5 result row(s) so far…")
    assert tagged == [("query-1", "Fetched 5 result row(s) so far…")]
    assert untagged == []

    worker._current_task_id = None
    worker._report_activity("No cancellable query is currently active.")
    assert untagged == ["No cancellable query is currently active."]



def test_schema_objects_fetch_is_scoped_and_returns_table_columns():
    from mysql_editor.database import DatabaseWorker

    queries = []

    class Cursor:
        def __init__(self):
            self.rows = []

        def execute(self, query, params=None):
            queries.append((query, params))
            if query.startswith("SHOW FULL TABLES"):
                self.rows = [("teams", "BASE TABLE"), ("team_view", "VIEW")]
            elif "information_schema.COLUMNS" in query:
                self.rows = [("teams", "team_id"), ("teams", "team_name")]
            else:
                raise AssertionError(f"Unexpected schema query: {query}")

        def fetchall(self):
            return list(self.rows)

        def close(self):
            pass

    class Connection:
        def cursor(self):
            return Cursor()

    worker = DatabaseWorker()
    worker._connection = Connection()

    result = worker._read_schema_objects("analytics")

    assert result == {
        "ok": True,
        "schema": "analytics",
        "objects": [
            {"name": "teams", "type": "BASE TABLE"},
            {"name": "team_view", "type": "VIEW"},
        ],
        "columns_by_table": {"teams": ["team_id", "team_name"]},
        "column_metadata_truncated": False,
    }
    assert queries[0] == ("SHOW FULL TABLES FROM `analytics`", None)
    assert queries[1][1] == ("analytics",)



def test_csv_export_preserves_fetch_order_for_unsorted_rows(tmp_path):
    import csv
    import json

    spool_owner = _csv_spool()
    result_id = "fetch-order"
    spool_owner._spool.execute(
        "INSERT INTO result_meta VALUES(?,?,?,?)",
        (result_id, json.dumps(["name", "rank"]), "SELECT", 3),
    )
    # Deliberately differs from both ascending and descending lexical order.
    fetched_rows = [
        ["zeta", 30],
        ["Alpha", 10],
        ["beta", 20],
    ]
    spool_owner._spool.executemany(
        "INSERT INTO result_rows VALUES(?,?,?)",
        [(result_id, index, json.dumps(row)) for index, row in enumerate(fetched_rows)],
    )
    destination = tmp_path / "fetch-order.csv"

    result = DatabaseWorker._export_csv(spool_owner, result_id, str(destination))

    assert result["ok"] is True
    assert result["row_count"] == 3
    with destination.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows == [["name", "rank"], ["zeta", "30"], ["Alpha", "10"], ["beta", "20"]]
    spool_owner._spool.close()


def test_connection_loss_classifier_recognizes_mysql_disconnects_only():
    class MysqlError(Exception):
        def __init__(self, message, errno=None, sqlstate=None):
            super().__init__(message)
            self.errno = errno
            self.sqlstate = sqlstate

    assert is_connection_lost(MysqlError("gone away", errno=2006))
    assert is_connection_lost(MysqlError("lost while fetching", errno=2013))
    assert is_connection_lost(MysqlError("connection reset", sqlstate="08S01"))
    assert is_connection_lost(MysqlError("Lost connection to MySQL server during query"))
    assert not is_connection_lost(MysqlError("Access denied", errno=1045))
    assert not is_connection_lost(MysqlError("Syntax error", errno=1064, sqlstate="42000"))


def test_query_disconnect_closes_the_dead_session_and_marks_result(tmp_path):
    import sqlite3

    class MysqlError(Exception):
        errno = 2013
        sqlstate = "HY000"

    class Cursor:
        with_rows = False
        rowcount = -1
        warning_count = 0
        description = None

        def execute(self, _sql):
            raise MysqlError("Lost connection to MySQL server during query")

        def close(self):
            self.closed = True

    class Connection:
        in_transaction = True

        def __init__(self):
            self.closed = False
            self.cursor_object = Cursor()

        def cursor(self):
            return self.cursor_object

        def close(self):
            self.closed = True

    worker = DatabaseWorker()
    connection = Connection()
    worker._connection = connection
    worker._report_activity = lambda _message: None
    worker._spool = sqlite3.connect(":memory:")
    worker._spool.executescript("""
        CREATE TABLE result_meta (
            result_id TEXT PRIMARY KEY, headers TEXT NOT NULL,
            statement TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE result_rows (
            result_id TEXT NOT NULL, row_idx INTEGER NOT NULL,
            values_json TEXT NOT NULL, PRIMARY KEY(result_id,row_idx)
        );
    """)
    try:
        result = worker._execute_script("SELECT 1;")
        assert result["ok"] is False
        assert result["connection_lost"] is True
        assert result["transaction_open"] is False
        assert result["results"][0]["connection_lost"] is True
        assert worker._connection is None
        assert connection.closed is True
        assert connection.cursor_object.closed is True
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()


def test_mid_fetch_disconnect_discards_partial_spool_and_closes_session():
    import sqlite3

    class MysqlError(Exception):
        errno = 2013
        sqlstate = "HY000"

    class Cursor:
        with_rows = True
        rowcount = -1
        warning_count = 0
        description = [("value",)]

        def __init__(self):
            self.fetch_calls = 0
            self.closed = False

        def execute(self, _sql):
            pass

        def fetchmany(self, _batch_size):
            self.fetch_calls += 1
            if self.fetch_calls == 1:
                return [("partial row",)]
            raise MysqlError("Lost connection to MySQL server during query")

        def close(self):
            self.closed = True

    class Connection:
        in_transaction = True

        def __init__(self):
            self.cursor_object = Cursor()
            self.closed = False

        def cursor(self):
            return self.cursor_object

        def close(self):
            self.closed = True

    worker = DatabaseWorker()
    connection = Connection()
    worker._connection = connection
    worker._report_activity = lambda _message: None
    worker._spool = sqlite3.connect(":memory:")
    worker._spool.executescript("""
        CREATE TABLE result_meta (
            result_id TEXT PRIMARY KEY, headers TEXT NOT NULL,
            statement TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE result_rows (
            result_id TEXT NOT NULL, row_idx INTEGER NOT NULL,
            values_json TEXT NOT NULL, PRIMARY KEY(result_id,row_idx)
        );
    """)
    try:
        result = worker._execute_script("SELECT value FROM large_table;")
        assert result["ok"] is False
        assert result["connection_lost"] is True
        assert result["transaction_open"] is False
        assert len(result["results"]) == 1
        assert result["results"][0]["kind"] == "error"
        assert worker._spool.execute("SELECT COUNT(*) FROM result_meta").fetchone()[0] == 0
        assert worker._spool.execute("SELECT COUNT(*) FROM result_rows").fetchone()[0] == 0
        assert connection.closed is True
        assert connection.cursor_object.closed is True
        assert worker._connection is None
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()
