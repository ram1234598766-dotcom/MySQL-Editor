import json
from mysql_editor.database import (
    DatabaseWorker, RESULT_PAGE_ROWS, is_connection_lost, is_query_interrupted, safe_db_error,
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


def test_database_errors_redact_echoed_mysql_account_password_syntax():
    echoed_fragments = (
        "syntax error near \"IDENTIFIED BY 'account-password-echo'\"",
        "server rejected SET PASSWORD = 'set-password-echo'",
        "authentication failed: AUTHENTICATION_STRING='auth-string-echo'",
    )

    for fragment in echoed_fragments:
        message = safe_db_error(RuntimeError(fragment))
        assert "[REDACTED]" in message
        assert "account-password-echo" not in message
        assert "set-password-echo" not in message
        assert "auth-string-echo" not in message


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


def test_fetch_result_page_reads_bounded_pages_from_the_local_spool(tmp_path):
    import csv
    import json

    spool_owner = _csv_spool()
    worker = DatabaseWorker()
    worker._spool = spool_owner._spool
    result_id = "large-result"
    total = 3505
    worker._spool.execute(
        "INSERT INTO result_meta VALUES(?,?,?,?)",
        (result_id, json.dumps(["row_number"]), "SELECT row_number", total),
    )
    worker._spool.executemany(
        "INSERT INTO result_rows VALUES(?,?,?)",
        [(result_id, index, json.dumps([index])) for index in range(total)],
    )
    worker._spool.commit()

    try:
        first_page = worker._dispatch(
            "fetch_result_page",
            {"result_id": result_id, "offset": 2000, "limit": 9000},
        )
        assert first_page["ok"] is True
        assert first_page["offset"] == 2000
        assert first_page["row_count"] == total
        assert first_page["page_size"] == RESULT_PAGE_ROWS
        assert len(first_page["rows"]) == RESULT_PAGE_ROWS
        assert first_page["rows"][0] == [2000]
        assert first_page["rows"][-1] == [2999]
        assert first_page["has_more"] is True

        final_page = worker._dispatch(
            "fetch_result_page",
            {"result_id": result_id, "offset": 3000, "limit": 9000},
        )
        assert final_page["ok"] is True
        assert len(final_page["rows"]) == 505
        assert final_page["rows"][0] == [3000]
        assert final_page["rows"][-1] == [3504]
        assert final_page["has_more"] is False

        # Paging reads a copy of rows; the spool and CSV export stay complete.
        destination = tmp_path / "all-rows.csv"
        exported = DatabaseWorker._export_csv(worker, result_id, str(destination))
        assert exported["ok"] is True
        assert exported["row_count"] == total
        with destination.open(encoding="utf-8-sig", newline="") as handle:
            exported_rows = list(csv.reader(handle))
        assert len(exported_rows) == total + 1
        assert exported_rows[1] == ["0"]
        assert exported_rows[-1] == ["3504"]

        missing = worker._dispatch(
            "fetch_result_page",
            {"result_id": "missing-result", "offset": 0},
        )
        assert missing["ok"] is False
        assert "expired" in missing["error"].lower()
        negative = worker._dispatch(
            "fetch_result_page",
            {"result_id": result_id, "offset": -1},
        )
        assert negative["ok"] is False
        assert "negative" in negative["error"].lower()
    finally:
        worker._cleanup_resources()


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
    assert rows == [["name", "value"], ["alpha", r"\N"], ["βeta", "42"]]
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



def test_structured_exports_preserve_fetch_order_null_empty_unicode_and_duplicate_headers(tmp_path):
    import json

    spool_owner = _csv_spool()
    worker = DatabaseWorker()
    worker._spool = spool_owner._spool
    result_id = "structured-result"
    worker._spool.execute(
        "INSERT INTO result_meta VALUES(?,?,?,?)",
        (result_id, json.dumps(["id", "label", "label"]), "SELECT", 2),
    )
    # Insert in reverse order to prove the exporter uses the stable spool row index.
    worker._spool.executemany(
        "INSERT INTO result_rows VALUES(?,?,?)",
        [
            (result_id, 1, json.dumps([2, "βeta", "second"])),
            (result_id, 0, json.dumps([1, None, ""])),
        ],
    )
    worker._spool.commit()
    expected = [
        {"id": 1, "label": None, "label (2)": ""},
        {"id": 2, "label": "βeta", "label (2)": "second"},
    ]
    try:
        json_path = tmp_path / "rows.json"
        json_result = worker._dispatch(
            "export_json", {"result_id": result_id, "path": str(json_path)}
        )
        assert json_result == {
            "ok": True, "path": str(json_path), "row_count": 2, "format": "json"
        }
        assert json.loads(json_path.read_text(encoding="utf-8")) == expected
        assert list(tmp_path.glob(".rows.json.*.tmp")) == []

        ndjson_path = tmp_path / "rows.ndjson"
        ndjson_result = worker._dispatch(
            "export_ndjson", {"result_id": result_id, "path": str(ndjson_path)}
        )
        assert ndjson_result == {
            "ok": True, "path": str(ndjson_path), "row_count": 2, "format": "ndjson"
        }
        ndjson_lines = ndjson_path.read_text(encoding="utf-8").splitlines()
        assert [json.loads(line) for line in ndjson_lines] == expected
        assert len(ndjson_lines) == 2
        assert list(tmp_path.glob(".rows.ndjson.*.tmp")) == []
    finally:
        worker._spool.close()
        worker._spool = None


def test_structured_export_failure_preserves_existing_destination_and_cleans_temporary_file(
    tmp_path
):
    import json

    import pytest

    spool_owner = _csv_spool()
    worker = DatabaseWorker()
    worker._spool = spool_owner._spool
    result_id = "broken-structured-result"
    worker._spool.execute(
        "INSERT INTO result_meta VALUES(?,?,?,?)",
        (result_id, json.dumps(["name"]), "SELECT", 1),
    )
    worker._spool.execute(
        "INSERT INTO result_rows VALUES(?,?,?)",
        (result_id, 0, "{not valid json"),
    )
    worker._spool.commit()
    previous_content = "previous export must survive"
    try:
        for export_format, extension in (("json", ".json"), ("ndjson", ".ndjson")):
            destination = tmp_path / f"report{extension}"
            destination.write_text(previous_content, encoding="utf-8")
            with pytest.raises(json.JSONDecodeError):
                worker._dispatch(
                    f"export_{export_format}",
                    {"result_id": result_id, "path": str(destination)},
                )
            assert destination.read_text(encoding="utf-8") == previous_content
            assert list(tmp_path.glob(f".report{extension}.*.tmp")) == []
    finally:
        worker._spool.close()
        worker._spool = None


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

def test_worker_shutdown_closes_and_removes_result_cache():
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


def test_worker_shutdown_removes_nested_result_cache_files():
    worker = DatabaseWorker()
    spool_dir = worker._spool_dir
    nested_file = spool_dir / "unexpected" / "orphaned-result.bin"
    nested_file.parent.mkdir()
    nested_file.write_bytes(b"temporary result data")

    worker.shutdown()
    worker.run()

    assert not nested_file.exists()
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


def test_cancel_current_query_skips_a_stale_statement_generation(monkeypatch):
    import mysql.connector
    import mysql_editor.database as database_module

    worker = DatabaseWorker()
    worker._connection_config = {"host": "localhost", "user": "tester", "password": "test"}
    worker._connection_id = 17
    worker._active_query = True
    worker._active_query_task_id = "script-task"
    worker._active_query_generation = 4
    messages = []
    connection_attempts = []
    worker.task_activity.connect(lambda task_id, message: messages.append((task_id, message)))

    def unexpected_connect(**kwargs):
        connection_attempts.append(kwargs)
        raise AssertionError("stale cancellation must not open a control connection")

    monkeypatch.setattr(mysql.connector, "connect", unexpected_connect)

    class DelayedThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            # Simulate the worker starting the next statement before the cancellation
            # thread gets CPU time. The generation changes but the script task ID does not.
            with worker._lock:
                worker._active_query_generation += 1
            self.target()

    monkeypatch.setattr(database_module.threading, "Thread", DelayedThread)
    worker.cancel_current_query()

    assert connection_attempts == []
    assert messages == [
        ("script-task", "Cancellation skipped because the SQL statement changed or finished.")
    ]


def test_cancel_current_query_serializes_kill_against_statement_transition(monkeypatch):
    import mysql.connector
    import mysql_editor.database as database_module

    worker = DatabaseWorker()
    worker._connection_config = {"host": "localhost", "user": "tester", "password": "test"}
    worker._connection_id = 17
    worker._active_query = True
    worker._active_query_task_id = "script-task"
    worker._active_query_generation = 5
    messages = []
    executed = []
    worker.task_activity.connect(lambda task_id, message: messages.append((task_id, message)))

    class FakeCursor:
        def execute(self, statement):
            assert worker._lock.locked(), "KILL QUERY must be serialized with statement changes"
            executed.append(statement)

        def close(self):
            pass

    class FakeControlConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    def connect_outside_worker_lock(**_kwargs):
        assert not worker._lock.locked(), "Control connection setup must not hold the worker lock"
        return FakeControlConnection()

    monkeypatch.setattr(mysql.connector, "connect", connect_outside_worker_lock)

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(database_module.threading, "Thread", ImmediateThread)
    worker.cancel_current_query()

    assert executed == ["KILL QUERY 17"]
    assert messages == [("script-task", "Cancellation request sent to MySQL.")]


def test_cancel_current_query_skips_if_generation_changes_during_control_connect(monkeypatch):
    import mysql.connector
    import mysql_editor.database as database_module

    worker = DatabaseWorker()
    worker._connection_config = {"host": "localhost", "user": "tester", "password": "test"}
    worker._connection_id = 17
    worker._active_query = True
    worker._active_query_task_id = "script-task"
    worker._active_query_generation = 6
    messages = []
    executed = []
    closed = []
    worker.task_activity.connect(lambda task_id, message: messages.append((task_id, message)))

    class FakeCursor:
        def execute(self, statement):
            executed.append(statement)

        def close(self):
            pass

    class FakeControlConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            closed.append(True)

    def connect_then_advance(**_kwargs):
        assert not worker._lock.locked(), "Control connection setup must not block worker state"
        with worker._lock:
            worker._active_query_generation += 1
        return FakeControlConnection()

    monkeypatch.setattr(mysql.connector, "connect", connect_then_advance)

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(database_module.threading, "Thread", ImmediateThread)
    worker.cancel_current_query()

    assert executed == []
    assert closed == [True]
    assert messages == [
        ("script-task", "Cancellation skipped because the SQL statement changed or finished.")
    ]


def _fake_mysql_connection(row=("8.4.0", "analytics", "tester@localhost"), connection_id=17, execute_error=None):
    class FakeCursor:
        def __init__(self):
            self.close_calls = 0
            self.executed: list[str] = []

        def execute(self, statement):
            self.executed.append(statement)
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
        "preview_rollback_rows": [],
        "preview_restore_errors": [],
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
        "preview_transaction_finalized": True,
    }
    assert connection.commit_calls == 1
    assert not connection.in_transaction

    connection.in_transaction = True
    rolled_back = worker._dispatch("rollback", {})
    assert rolled_back == {
        "ok": True,
        "message": "Transaction rolled back.",
        "transaction_open": False,
        "preview_rollback_rows": [],
        "preview_restore_errors": [],
        "preview_transaction_finalized": True,
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



def test_csv_export_distinguishes_sql_null_empty_text_and_literal_null_token(tmp_path):
    import csv
    import json

    spool_owner = _csv_spool()
    result_id = "null-vs-empty"
    spool_owner._spool.execute(
        "INSERT INTO result_meta VALUES(?,?,?,?)",
        (result_id, json.dumps(["kind", "value"]), "SELECT", 4),
    )
    spool_owner._spool.executemany(
        "INSERT INTO result_rows VALUES(?,?,?)",
        [
            (result_id, 0, json.dumps(["sql-null", None])),
            (result_id, 1, json.dumps(["empty-text", ""])),
            (result_id, 2, json.dumps(["literal-null-token", r"\N"])),
            (result_id, 3, json.dumps(["path-text", r"\reports\monthly.csv"])),
        ],
    )
    destination = tmp_path / "null-vs-empty.csv"

    result = DatabaseWorker._export_csv(spool_owner, result_id, str(destination))

    assert result["ok"] is True
    with destination.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows == [
        ["kind", "value"],
        ["sql-null", r"\N"],
        ["empty-text", ""],
        ["literal-null-token", r"\\N"],
        ["path-text", r"\\reports\monthly.csv"],
    ]
    assert list(tmp_path.glob(".null-vs-empty.csv.*.tmp")) == []
    spool_owner._spool.close()



def test_malformed_delimiter_script_fails_before_opening_a_cursor():
    class Connection:
        in_transaction = True

        def __init__(self):
            self.cursor_calls = 0

        def cursor(self):
            self.cursor_calls += 1
            raise AssertionError("Malformed scripts must fail before SQL execution")

    worker = DatabaseWorker()
    connection = Connection()
    worker._connection = connection
    worker._report_activity = lambda _message: None
    result = worker._execute_script(
        "SELECT 1;\nDELIMITER $$ extra\nSELECT 2;"
    )

    assert result["ok"] is False
    assert result["results"] == []
    assert "line 2" in result["error"]
    assert "script was not submitted" in result["error"]
    assert result["transaction_open"] is True
    assert connection.cursor_calls == 0

def test_use_schema_switches_the_live_session_with_a_quoted_identifier():
    worker = DatabaseWorker()
    connection = _fake_mysql_connection()
    worker._connection = connection
    worker._connection_config = {"host": "localhost", "database": "old_schema"}
    schema = "sales` archive"

    try:
        result = worker._dispatch("use_schema", {"schema": schema})

        assert result == {
            "ok": True,
            "schema": schema,
            "transaction_open": False,
        }
        assert connection.cursor_instance.executed == ["USE `sales`` archive`"]
        assert connection.cursor_instance.close_calls == 1
        assert worker._connection_config["database"] == schema
    finally:
        worker._cleanup_resources()


def test_failed_schema_switch_does_not_update_worker_connection_context():
    import pytest

    worker = DatabaseWorker()
    connection = _fake_mysql_connection(execute_error=RuntimeError("database access denied"))
    worker._connection = connection
    worker._connection_config = {"host": "localhost", "database": "old_schema"}

    try:
        with pytest.raises(RuntimeError, match="database access denied"):
            worker._dispatch("use_schema", {"schema": "restricted_schema"})

        assert worker._connection_config["database"] == "old_schema"
        assert connection.cursor_instance.executed == ["USE `restricted_schema`"]
        assert connection.cursor_instance.close_calls == 1
    finally:
        worker._cleanup_resources()


def _schema_inspector_connection(*, object_type="BASE TABLE", show_create_error=None, properties_rows=None):
    from mysql_editor.database import safe_identifier

    queries = []
    cursor_instances = []

    properties_fields = [
        "TABLE_TYPE", "ENGINE", "ROW_FORMAT", "TABLE_ROWS", "DATA_LENGTH",
        "INDEX_LENGTH", "AUTO_INCREMENT", "CREATE_TIME", "UPDATE_TIME", "TABLE_COMMENT",
    ]
    column_fields = [
        "ORDINAL_POSITION", "COLUMN_NAME", "COLUMN_TYPE", "IS_NULLABLE",
        "COLUMN_DEFAULT", "COLUMN_KEY", "EXTRA", "CHARACTER_SET_NAME",
        "COLLATION_NAME", "COLUMN_COMMENT",
    ]
    index_fields = [
        "Table", "Non_unique", "Key_name", "Seq_in_index", "Column_name",
        "Collation", "Cardinality", "Sub_part", "Packed", "Null", "Index_type",
        "Comment", "Index_comment", "Visible",
    ]
    constraint_fields = [
        "CONSTRAINT_NAME", "CONSTRAINT_TYPE", "COLUMN_NAME", "ORDINAL_POSITION",
        "REFERENCED_TABLE_SCHEMA", "REFERENCED_TABLE_NAME", "REFERENCED_COLUMN_NAME",
    ]

    class Cursor:
        def __init__(self):
            self.rows = []
            self.description = []
            self.closed = False
            cursor_instances.append(self)

        def execute(self, query, params=None):
            queries.append((query, params))
            if query.startswith("SELECT TABLE_TYPE, ENGINE"):
                self.description = [(name,) for name in properties_fields]
                self.rows = list(properties_rows) if properties_rows is not None else [
                    (
                        object_type, "InnoDB", "Dynamic", 3, 16384, 8192, 4,
                        None, None, "team records",
                    )
                ]
            elif query.startswith("SHOW CREATE TABLE") or query.startswith("SHOW CREATE VIEW"):
                if show_create_error:
                    raise RuntimeError(show_create_error)
                self.description = [("Object",), ("Create " + ("View" if object_type == "VIEW" else "Table"),)]
                tick = chr(96)
                if object_type == "VIEW":
                    self.rows = [
                        ("team_view", "CREATE VIEW " + tick + "team_view" + tick +
                         " AS select 1 AS team_id")
                    ]
                else:
                    self.rows = [
                        ("teams", "CREATE TABLE " + tick + "teams" + tick +
                         " (" + tick + "team_id" + tick + " int NOT NULL)")
                    ]
            elif "information_schema.COLUMNS" in query:
                self.description = [(name,) for name in column_fields]
                self.rows = [
                    (
                        1, "team_id", "int unsigned", "NO", None, "PRI",
                        "auto_increment", None, None, "Primary identifier",
                    ),
                    (
                        2, "team_name", "varchar(80)", "NO", "unknown", "",
                        "", "utf8mb4", "utf8mb4_0900_ai_ci", "Team display name",
                    ),
                ]
            elif query.startswith("SHOW INDEX FROM"):
                self.description = [(name,) for name in index_fields]
                self.rows = [
                    (
                        "teams", 0, "PRIMARY", 1, "team_id", "A", 3,
                        None, None, "", "BTREE", "", "", "YES",
                    ),
                    (
                        "teams", 1, "idx_team_name", 1, "team_name", "A", 3,
                        24, None, "YES", "BTREE", "", "team-name lookup", "YES",
                    ),
                ]
            elif "FROM information_schema.TABLE_CONSTRAINTS AS tc" in query:
                self.description = [(name,) for name in constraint_fields]
                self.rows = [
                    ("PRIMARY", "PRIMARY KEY", "team_id", 1, None, None, None),
                    ("fk_team_owner", "FOREIGN KEY", "owner_id", 1, "analytics", "owners", "owner_id"),
                ]
            else:
                raise AssertionError(f"Unexpected metadata query: {query}")

        def fetchall(self):
            return list(self.rows)

        def close(self):
            self.closed = True

    class Connection:
        def cursor(self):
            return Cursor()

    return Connection(), queries, cursor_instances, safe_identifier


def test_schema_inspector_reads_ddl_columns_indexes_constraints_and_properties():
    worker = DatabaseWorker()
    connection, queries, cursors, safe_identifier = _schema_inspector_connection()
    worker._connection = connection

    result = worker._dispatch(
        "inspect_schema_object",
        {"schema": "analytics", "table": "teams", "object_type": "BASE TABLE"},
    )

    assert result["ok"] is True
    assert result["object_type"] == "BASE TABLE"
    tick = chr(96)
    assert result["definition"] == (
        "CREATE TABLE " + tick + "teams" + tick + " (" + tick + "team_id" + tick + " int NOT NULL)"
    )
    assert result["properties"]["Storage engine"] == "InnoDB"
    assert result["properties"]["Row format"] == "Dynamic"
    assert result["properties"]["Comment"] == "team records"
    assert result["columns"][0] == {
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
    assert result["indexes"][0]["name"] == "PRIMARY"
    assert result["indexes"][0]["unique"] == "Yes"
    assert result["indexes"][1]["name"] == "idx_team_name"
    assert result["indexes"][1]["unique"] == "No"
    assert result["indexes"][1]["prefix_length"] == 24
    assert result["constraints"][0]["type"] == "PRIMARY KEY"
    assert result["constraints"][1]["referenced_table"] == "owners"
    assert result["warnings"] == []
    assert queries[0][1] == ("analytics", "teams")
    assert queries[1][0] == (
        f"SHOW CREATE TABLE {safe_identifier('analytics')}.{safe_identifier('teams')}"
    )
    assert queries[2][1] == ("analytics", "teams")
    assert queries[3][0] == (
        f"SHOW INDEX FROM {safe_identifier('teams')} FROM {safe_identifier('analytics')}"
    )
    assert queries[4][1] == ("analytics", "teams")
    assert all(cursor.closed for cursor in cursors)


def test_schema_inspector_quotes_identifiers_and_uses_bound_metadata_values():
    worker = DatabaseWorker()
    connection, queries, _cursors, safe_identifier = _schema_inspector_connection()
    worker._connection = connection
    schema = "odd" + chr(96) + "schema"
    table = "teams" + chr(96) + " archive"

    result = worker._inspect_schema_object(schema, table, "BASE TABLE")

    assert result["ok"] is True
    assert queries[0][1] == (schema, table)
    assert queries[1][0] == (
        f"SHOW CREATE TABLE {safe_identifier(schema)}.{safe_identifier(table)}"
    )
    assert queries[2][1] == (schema, table)
    assert queries[4][1] == (schema, table)


def test_schema_inspector_keeps_partial_metadata_when_definition_permission_is_denied():
    worker = DatabaseWorker()
    connection, queries, _cursors, safe_identifier = _schema_inspector_connection(
        object_type="VIEW",
        show_create_error="SHOW VIEW command denied for this account",
    )
    worker._connection = connection

    result = worker._inspect_schema_object("analytics", "team_view", "VIEW")

    assert result["ok"] is True
    assert result["object_type"] == "VIEW"
    assert result["definition"] == ""
    assert result["columns"]
    assert any("Definition unavailable" in warning for warning in result["warnings"])
    assert "SHOW VIEW command denied" in "\n".join(result["warnings"])
    assert queries[1][0] == (
        f"SHOW CREATE VIEW {safe_identifier('analytics')}.{safe_identifier('team_view')}"
    )


def test_schema_inspector_reports_missing_or_invisible_objects_without_running_other_queries():
    worker = DatabaseWorker()
    connection, queries, _cursors, _safe_identifier = _schema_inspector_connection(properties_rows=[])
    worker._connection = connection

    result = worker._inspect_schema_object("analytics", "missing_table", "BASE TABLE")

    assert result["ok"] is False
    assert "not found or is no longer visible" in result["error"]
    assert len(queries) == 1


def test_schema_inspector_uses_show_create_view_for_views():
    worker = DatabaseWorker()
    connection, queries, _cursors, safe_identifier = _schema_inspector_connection(object_type="VIEW")
    worker._connection = connection

    result = worker._dispatch(
        "inspect_schema_object",
        {"schema": "analytics", "table": "team_view", "object_type": "VIEW"},
    )

    assert result["ok"] is True
    assert result["object_type"] == "VIEW"
    assert result["definition"].startswith("CREATE VIEW")
    assert queries[1][0] == (
        f"SHOW CREATE VIEW {safe_identifier('analytics')}.{safe_identifier('team_view')}"
    )

def _editable_preview_worker(*, table_type="BASE TABLE", primary_key=("id",), engine="InnoDB", engine_transactions="YES"):
    import sqlite3

    worker = DatabaseWorker()
    worker._spool = sqlite3.connect(":memory:")
    worker._spool.executescript("""
        CREATE TABLE result_meta (
            result_id TEXT PRIMARY KEY, headers TEXT NOT NULL,
            statement TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE result_rows (
            result_id TEXT NOT NULL, row_idx INTEGER NOT NULL, values_json TEXT NOT NULL,
            PRIMARY KEY(result_id, row_idx)
        );
    """)

    state = {
        "rows": [
            {"id": 1, "label": "old", "quantity": 3},
            {"id": 2, "label": "second", "quantity": 4},
        ],
        "table_type": table_type,
        "engine": engine,
        "engine_transactions": engine_transactions,
        "primary_key": list(primary_key),
        "queries": [],
        "commits": 0,
        "rollbacks": 0,
        "transaction_baseline": None,
        "savepoints": {},
    }
    headers = ["id", "label", "quantity"]
    column_rows = [
        ("id", "int", "auto_increment"),
        ("label", "varchar", ""),
        ("quantity", "int", ""),
    ]

    class Cursor:
        def __init__(self):
            self.description = []
            self.rows = []
            self.rowcount = -1
            self.closed = False
            self.with_rows = False

        def execute(self, query, params=None):
            params = tuple(params or ())
            state["queries"].append((query, params))
            self.description = []
            self.rows = []
            self.rowcount = -1
            self.with_rows = False
            normalized_query = query.strip()
            upper_query = normalized_query.upper()
            if upper_query.startswith("ROLLBACK TO "):
                savepoint_name = normalized_query.split()[-1].strip("`")
                snapshot = state["savepoints"].get(savepoint_name)
                if snapshot is None:
                    raise AssertionError(f"Unknown test savepoint: {savepoint_name}")
                state["rows"] = [dict(row) for row in snapshot]
                connection.in_transaction = True
            elif upper_query.startswith("ROLLBACK"):
                connection.rollback()
            elif upper_query.startswith("COMMIT"):
                connection.commit()
            elif upper_query.startswith("SAVEPOINT "):
                savepoint_name = normalized_query.split()[-1].strip("`")
                state["savepoints"][savepoint_name] = [
                    dict(row) for row in state["rows"]
                ]
                connection.in_transaction = True
            elif query.startswith("SELECT * FROM ") and " LIMIT 1000" in query:
                self.description = [(name,) for name in headers]
                self.with_rows = True
                self.rows = [
                    (row["id"], row["label"], row["quantity"])
                    for row in state["rows"]
                ]
            elif query.startswith("SELECT TABLE_TYPE, ENGINE FROM information_schema.TABLES"):
                self.description = [("TABLE_TYPE",), ("ENGINE",)]
                self.rows = [(state["table_type"], state["engine"])]
            elif query.startswith("SELECT TRANSACTIONS FROM information_schema.ENGINES"):
                self.description = [("TRANSACTIONS",)]
                self.rows = [(state["engine_transactions"],)]
            elif query.startswith("SELECT COLUMN_NAME, DATA_TYPE, EXTRA FROM information_schema.COLUMNS"):
                self.description = [("COLUMN_NAME",), ("DATA_TYPE",), ("EXTRA",)]
                self.rows = list(column_rows)
            elif query.startswith("SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE"):
                self.description = [("COLUMN_NAME",)]
                self.rows = [(name,) for name in state["primary_key"]]
            elif query.startswith("UPDATE "):
                new_value, key_value, expected_old = params
                matched = next(
                    (row for row in state["rows"] if row["id"] == key_value),
                    None,
                )
                if matched is not None and matched["label"] == expected_old:
                    if matched["label"] != new_value:
                        if state["transaction_baseline"] is None:
                            state["transaction_baseline"] = [
                                dict(row) for row in state["rows"]
                            ]
                        matched["label"] = new_value
                        self.rowcount = 1
                        connection.in_transaction = True
                    else:
                        self.rowcount = 0
                else:
                    self.rowcount = 0
            elif query.startswith("SELECT * FROM ") and " WHERE " in query:
                self.description = [(name,) for name in headers]
                if " FOR UPDATE" in query.upper():
                    connection.in_transaction = True
                key_value = params[0]
                matched = next(
                    (row for row in state["rows"] if row["id"] == key_value),
                    None,
                )
                self.rows = [] if matched is None else [
                    (matched["id"], matched["label"], matched["quantity"])
                ]
            else:
                raise AssertionError(f"Unexpected cell-edit SQL: {query!r}")

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return list(self.rows)

        def close(self):
            self.closed = True

    class Connection:
        in_transaction = False

        def cursor(self):
            return Cursor()

        def commit(self):
            state["commits"] += 1
            state["transaction_baseline"] = None
            self.in_transaction = False

        def rollback(self):
            state["rollbacks"] += 1
            baseline = state.get("transaction_baseline")
            if baseline is not None:
                state["rows"] = [dict(row) for row in baseline]
            state["transaction_baseline"] = None
            self.in_transaction = False

    connection = Connection()
    worker._connection = connection
    worker._cell_edit_test_state = state
    return worker, state, connection


def test_table_preview_enables_cell_edit_only_for_primary_key_base_tables():
    worker, state, _connection = _editable_preview_worker()
    try:
        preview = worker._preview_table("analytics", "items")
        item = preview["results"][0]
        edit = item["table_edit"]

        assert preview["ok"] is True
        assert edit["enabled"] is True
        assert edit["primary_key_columns"] == ["id"]
        assert edit["primary_key_indices"] == [0]
        assert edit["row_keys"] == [[1], [2]]
        assert edit["editable_column_indices"] == [1, 2]
        assert edit["original_values"]["1"] == ["old", "second"]
        assert state["commits"] == 0
        assert state["rollbacks"] == 0
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()


def test_table_preview_stays_read_only_for_views_and_tables_without_primary_keys():
    view_worker, _view_state, _ = _editable_preview_worker(table_type="VIEW")
    no_key_worker, _no_key_state, _ = _editable_preview_worker(primary_key=())
    try:
        view = view_worker._preview_table("analytics", "items")["results"][0]["table_edit"]
        no_key = no_key_worker._preview_table("analytics", "items")["results"][0]["table_edit"]

        assert view["enabled"] is False
        assert "Only base tables" in view["reason"]
        assert no_key["enabled"] is False
        assert "no primary key" in no_key["reason"]
    finally:
        for worker in (view_worker, no_key_worker):
            worker._spool.close()
            worker._spool = None
            worker._spool_dir.rmdir()


def test_single_cell_update_is_parameterized_optimistic_and_leaves_transaction_open():
    worker, state, connection = _editable_preview_worker()
    try:
        item = worker._preview_table("analytics", "items")["results"][0]
        edit = item["table_edit"]
        result_id = item["result_id"]
        worker._spool.commit()

        result = worker._update_table_cell({
            "result_id": result_id,
            "session_token": edit["session_token"],
            "row_index": 0,
            "column_index": 1,
            "schema": "analytics",
            "table": "items",
            "column_name": "label",
            "primary_key_columns": edit["primary_key_columns"],
            "primary_key_values": edit["row_keys"][0],
            "expected_old": edit["original_values"]["1"][0],
            "new_value": "updated",
        })

        assert result["ok"] is True
        assert result["display_row"] == [1, "updated", 3]
        assert result["raw_row"] == [1, "updated", 3]
        assert result["transaction_open"] is True
        assert state["rows"][0]["label"] == "updated"
        assert state["commits"] == 0
        assert state["rollbacks"] == 0
        update_query, update_params = next(
            pair for pair in state["queries"] if pair[0].startswith("UPDATE ")
        )
        assert "SET `label` = %s" in update_query
        assert "WHERE `id` = %s AND `label` <=> %s" in update_query
        assert update_params == ("updated", 1, "old")

        spool_row = worker._spool.execute(
            "SELECT values_json FROM result_rows WHERE result_id = ? AND row_idx = 0",
            (result_id,),
        ).fetchone()
        assert json.loads(spool_row[0]) == [1, "updated", 3]
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()


def test_single_cell_update_rollback_restores_worker_spool_snapshot():
    worker, state, connection = _editable_preview_worker()
    try:
        item = worker._preview_table("analytics", "items")["results"][0]
        result_id = item["result_id"]
        edit = item["table_edit"]
        worker._spool.commit()

        updated = worker._update_table_cell({
            "result_id": result_id,
            "session_token": edit["session_token"],
            "row_index": 0,
            "column_index": 1,
            "schema": "analytics",
            "table": "items",
            "column_name": "label",
            "primary_key_columns": edit["primary_key_columns"],
            "primary_key_values": edit["row_keys"][0],
            "expected_old": edit["original_values"]["1"][0],
            "new_value": "updated",
        })
        assert updated["ok"] is True
        assert worker._table_preview_undo[(result_id, 0)] == [1, "old", 3]
        cached = worker._spool.execute(
            "SELECT values_json FROM result_rows WHERE result_id = ? AND row_idx = 0",
            (result_id,),
        ).fetchone()
        assert json.loads(cached[0]) == [1, "updated", 3]

        rolled_back = worker._dispatch("rollback", {})

        assert rolled_back["ok"] is True
        assert rolled_back["transaction_open"] is False
        assert rolled_back["preview_transaction_finalized"] is True
        assert rolled_back["preview_rollback_rows"] == [{
            "result_id": result_id,
            "row_index": 0,
            "display_row": [1, "old", 3],
        }]
        assert state["rows"][0]["label"] == "old"
        assert state["rollbacks"] == 1
        assert state["commits"] == 0
        assert worker._table_preview_undo == {}
        cached = worker._spool.execute(
            "SELECT values_json FROM result_rows WHERE result_id = ? AND row_idx = 0",
            (result_id,),
        ).fetchone()
        assert json.loads(cached[0]) == [1, "old", 3]
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()


def test_sql_rollback_restores_preview_cache_after_inline_edit():
    worker, state, connection = _editable_preview_worker()
    try:
        item = worker._preview_table("analytics", "items")["results"][0]
        result_id = item["result_id"]
        edit = item["table_edit"]
        worker._spool.commit()

        updated = worker._update_table_cell({
            "result_id": result_id,
            "session_token": edit["session_token"],
            "row_index": 0,
            "column_index": 1,
            "schema": "analytics",
            "table": "items",
            "column_name": "label",
            "primary_key_columns": edit["primary_key_columns"],
            "primary_key_values": edit["row_keys"][0],
            "expected_old": edit["original_values"]["1"][0],
            "new_value": "updated",
        })
        assert updated["ok"] is True

        result = worker._execute_script("ROLLBACK;")

        assert result["ok"] is True
        assert result["transaction_open"] is False
        assert result["preview_rollback_rows"] == [{
            "result_id": result_id,
            "row_index": 0,
            "display_row": [1, "old", 3],
        }]
        assert state["rows"][0]["label"] == "old"
        assert worker._table_preview_undo == {}
        cached = worker._spool.execute(
            "SELECT values_json FROM result_rows WHERE result_id = ? AND row_idx = 0",
            (result_id,),
        ).fetchone()
        assert json.loads(cached[0]) == [1, "old", 3]
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()


def test_commit_finalizes_cell_edit_and_keeps_updated_preview_snapshot():
    worker, state, connection = _editable_preview_worker()
    try:
        item = worker._preview_table("analytics", "items")["results"][0]
        result_id = item["result_id"]
        edit = item["table_edit"]
        worker._spool.commit()

        result = worker._update_table_cell({
            "result_id": result_id,
            "session_token": edit["session_token"],
            "row_index": 0,
            "column_index": 1,
            "schema": "analytics",
            "table": "items",
            "column_name": "label",
            "primary_key_columns": edit["primary_key_columns"],
            "primary_key_values": edit["row_keys"][0],
            "expected_old": edit["original_values"]["1"][0],
            "new_value": "updated",
        })
        assert result["ok"] is True

        committed = worker._dispatch("commit", {})

        assert committed["ok"] is True
        assert committed["preview_transaction_finalized"] is True
        assert worker._table_preview_undo == {}
        assert state["rows"][0]["label"] == "updated"
        cached = worker._spool.execute(
            "SELECT values_json FROM result_rows WHERE result_id = ? AND row_idx = 0",
            (result_id,),
        ).fetchone()
        assert json.loads(cached[0]) == [1, "updated", 3]
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()


def test_single_cell_update_rejects_stale_values_without_overwriting_server_changes():
    worker, state, _connection = _editable_preview_worker()
    try:
        item = worker._preview_table("analytics", "items")["results"][0]
        edit = item["table_edit"]
        state["rows"][0]["label"] = "changed elsewhere"

        result = worker._update_table_cell({
            "result_id": item["result_id"],
            "session_token": edit["session_token"],
            "row_index": 0,
            "column_index": 1,
            "schema": "analytics",
            "table": "items",
            "column_name": "label",
            "primary_key_columns": edit["primary_key_columns"],
            "primary_key_values": edit["row_keys"][0],
            "expected_old": edit["original_values"]["1"][0],
            "new_value": "overwrite",
        })

        assert result["ok"] is False
        assert "changed on MySQL" in result["error"]
        assert state["rows"][0]["label"] == "changed elsewhere"
        assert state["commits"] == 0
        spool_row = worker._spool.execute(
            "SELECT values_json FROM result_rows WHERE result_id = ? AND row_idx = 0",
            (item["result_id"],),
        ).fetchone()
        assert json.loads(spool_row[0]) == [1, "old", 3]
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()


def test_single_cell_update_rejects_primary_key_columns_and_non_preview_results():
    worker, state, _connection = _editable_preview_worker()
    try:
        item = worker._preview_table("analytics", "items")["results"][0]
        edit = item["table_edit"]
        primary_key_result = worker._update_table_cell({
            "result_id": item["result_id"],
            "session_token": edit["session_token"],
            "row_index": 0,
            "column_index": 0,
            "schema": "analytics",
            "table": "items",
            "column_name": "id",
            "primary_key_columns": edit["primary_key_columns"],
            "primary_key_values": edit["row_keys"][0],
            "expected_old": 1,
            "new_value": 9,
        })
        query_result = worker._update_table_cell({
            "result_id": "result-from-arbitrary-query",
            "session_token": edit["session_token"],
            "row_index": 0,
            "column_index": 1,
            "schema": "analytics",
            "table": "items",
            "column_name": "label",
            "primary_key_columns": ["id"],
            "primary_key_values": [1],
            "expected_old": "old",
            "new_value": "x",
        })

        assert primary_key_result["ok"] is False
        assert "Primary-key cells are read-only" in primary_key_result["error"]
        assert query_result["ok"] is False
        assert "Schema Explorer table preview" in query_result["error"]
        assert state["rows"][0]["id"] == 1
        assert state["rows"][0]["label"] == "old"
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()

def test_single_cell_update_rejects_preview_from_prior_connection_session():
    worker, state, _connection = _editable_preview_worker()
    try:
        item = worker._preview_table("analytics", "items")["results"][0]
        edit = item["table_edit"]
        stale_session = edit["session_token"]
        worker._session_token = f"{stale_session}-new-session"

        result = worker._update_table_cell({
            "result_id": item["result_id"],
            "session_token": stale_session,
            "row_index": 0,
            "column_index": 1,
            "schema": "analytics",
            "table": "items",
            "column_name": "label",
            "primary_key_columns": edit["primary_key_columns"],
            "primary_key_values": edit["row_keys"][0],
            "expected_old": edit["original_values"]["1"][0],
            "new_value": "must not cross connections",
        })

        assert result["ok"] is False
        assert "connection changed" in result["error"]
        assert state["rows"][0]["label"] == "old"
        assert not any(query.startswith("UPDATE ") for query, _params in state["queries"])
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()


def test_table_preview_is_read_only_when_storage_engine_cannot_rollback():
    worker, _state, _connection = _editable_preview_worker(
        engine="MyISAM", engine_transactions="NO"
    )
    try:
        item = worker._preview_table("analytics", "items")["results"][0]
        assert item["table_edit"]["enabled"] is False
        assert "cannot guarantee Rollback" in item["table_edit"]["reason"]
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()


def test_single_cell_update_revalidates_storage_engine_before_writing():
    worker, state, _connection = _editable_preview_worker()
    try:
        item = worker._preview_table("analytics", "items")["results"][0]
        edit = item["table_edit"]
        state["engine"] = "MyISAM"
        state["engine_transactions"] = "NO"

        result = worker._update_table_cell({
            "result_id": item["result_id"],
            "session_token": edit["session_token"],
            "row_index": 0,
            "column_index": 1,
            "schema": "analytics",
            "table": "items",
            "column_name": "label",
            "primary_key_columns": edit["primary_key_columns"],
            "primary_key_values": edit["row_keys"][0],
            "expected_old": edit["original_values"]["1"][0],
            "new_value": "must not write",
        })

        assert result["ok"] is False
        assert "cannot guarantee Rollback" in result["error"]
        assert not any(query.startswith("UPDATE ") for query, _params in state["queries"])
        assert state["rows"][0]["label"] == "old"
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()


def test_single_cell_update_rejects_changes_to_other_columns_before_writing():
    worker, state, _connection = _editable_preview_worker()
    try:
        item = worker._preview_table("analytics", "items")["results"][0]
        edit = item["table_edit"]
        state["rows"][0]["quantity"] = 77

        result = worker._update_table_cell({
            "result_id": item["result_id"],
            "session_token": edit["session_token"],
            "row_index": 0,
            "column_index": 1,
            "schema": "analytics",
            "table": "items",
            "column_name": "label",
            "primary_key_columns": edit["primary_key_columns"],
            "primary_key_values": edit["row_keys"][0],
            "expected_old": edit["original_values"]["1"][0],
            "new_value": "must not overwrite a stale row",
        })

        assert result["ok"] is False
        assert "Another column in this row changed" in result["error"]
        assert state["rows"][0]["label"] == "old"
        assert state["rows"][0]["quantity"] == 77
        assert not any(query.startswith("UPDATE ") for query, _params in state["queries"])
        cached = worker._spool.execute(
            "SELECT values_json FROM result_rows WHERE result_id = ? AND row_idx = 0",
            (item["result_id"],),
        ).fetchone()
        assert json.loads(cached[0]) == [1, "old", 3]
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()

def test_rollback_to_savepoint_invalidates_preview_until_refreshed(tmp_path):
    worker, state, _connection = _editable_preview_worker()
    try:
        item = worker._preview_table("analytics", "items")["results"][0]
        result_id = item["result_id"]
        edit = item["table_edit"]

        savepoint = worker._execute_script("SAVEPOINT before_cell_edit;")
        assert savepoint["ok"] is True
        assert savepoint["transaction_open"] is True

        updated = worker._update_table_cell({
            "result_id": result_id,
            "session_token": edit["session_token"],
            "row_index": 0,
            "column_index": 1,
            "schema": "analytics",
            "table": "items",
            "column_name": "label",
            "primary_key_columns": edit["primary_key_columns"],
            "primary_key_values": edit["row_keys"][0],
            "expected_old": edit["original_values"]["1"][0],
            "new_value": "edited",
        })
        assert updated["ok"] is True
        assert state["rows"][0]["label"] == "edited"
        assert worker._table_preview_undo[(result_id, 0)] == [1, "old", 3]

        rolled_to_savepoint = worker._execute_script("ROLLBACK TO SAVEPOINT before_cell_edit;")

        assert rolled_to_savepoint["ok"] is True
        assert rolled_to_savepoint["transaction_open"] is True
        assert rolled_to_savepoint["preview_invalidated_result_ids"] == [result_id]
        assert result_id in worker._invalid_table_previews
        assert state["rows"][0]["label"] == "old"
        assert worker._table_preview_undo[(result_id, 0)] == [1, "old", 3]

        rejected_edit = worker._update_table_cell({
            "result_id": result_id,
            "session_token": edit["session_token"],
            "row_index": 0,
            "column_index": 1,
            "schema": "analytics",
            "table": "items",
            "column_name": "label",
            "primary_key_columns": edit["primary_key_columns"],
            "primary_key_values": edit["row_keys"][0],
            "expected_old": "edited",
            "new_value": "must not be accepted",
        })
        assert rejected_edit["ok"] is False
        assert "stale after ROLLBACK TO SAVEPOINT" in rejected_edit["error"]

        export_path = tmp_path / "stale-preview.csv"
        rejected_export = worker._export_csv(result_id, str(export_path))
        assert rejected_export["ok"] is False
        assert "stale after ROLLBACK TO SAVEPOINT" in rejected_export["error"]
        assert not export_path.exists()

        # A later full rollback still restores the transaction-start snapshot, but the
        # result remains invalid until a fresh table preview is requested.
        rolled_back = worker._dispatch("rollback", {})
        assert rolled_back["ok"] is True
        assert worker._table_preview_undo == {}
        assert result_id in worker._invalid_table_previews

        refreshed = worker._preview_table("analytics", "items")["results"][0]
        assert refreshed["table_edit"]["enabled"] is True
        assert refreshed["rows"][0] == [1, "old", 3]
        assert refreshed["result_id"] not in worker._invalid_table_previews
    finally:
        worker._spool.close()
        worker._spool = None
        worker._spool_dir.rmdir()

class _FilterSpoolWorker:
    def __init__(self, spool):
        self._spool = spool
        self._invalid_table_previews = set()
        self.activities = []

    def _report_activity(self, message):
        self.activities.append(str(message))


def _make_filter_spool(rows):
    import sqlite3

    spool = sqlite3.connect(":memory:")
    spool.executescript(
        """
        CREATE TABLE result_meta (
            result_id TEXT PRIMARY KEY, headers TEXT NOT NULL,
            statement TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE result_rows (
            result_id TEXT NOT NULL, row_idx INTEGER NOT NULL, values_json TEXT NOT NULL,
            PRIMARY KEY(result_id,row_idx)
        );
        CREATE TABLE result_filter_views (
            view_id TEXT PRIMARY KEY, result_id TEXT NOT NULL,
            query TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX result_filter_views_result_id ON result_filter_views(result_id);
        CREATE TABLE result_filter_view_rows (
            view_id TEXT NOT NULL, view_idx INTEGER NOT NULL, source_idx INTEGER NOT NULL,
            PRIMARY KEY(view_id,view_idx)
        );
        CREATE TABLE result_view_sort_keys (
            view_id TEXT NOT NULL, ordinal INTEGER NOT NULL, source_idx INTEGER NOT NULL,
            null_rank INTEGER NOT NULL, type_rank INTEGER NOT NULL,
            numeric_key TEXT NOT NULL, text_key TEXT NOT NULL,
            PRIMARY KEY(view_id,ordinal)
        );
        """
    )
    result_id = "large-filter-fixture"
    spool.execute(
        "INSERT INTO result_meta(result_id,headers,statement,row_count) VALUES(?,?,?,?)",
        (result_id, json.dumps(["name", "rank"]), "SELECT name, rank", len(rows)),
    )
    spool.executemany(
        "INSERT INTO result_rows(result_id,row_idx,values_json) VALUES(?,?,?)",
        [(result_id, index, json.dumps(row)) for index, row in enumerate(rows)],
    )
    spool.commit()
    return spool, result_id


def test_prepare_result_filter_indexes_all_rows_and_pages_by_filtered_position():
    rows = [
        ["zeta", 0],
        ["Alpha", 1],
        ["beta", 2],
        [None, 3],
        ["alphabet", 4],
        ["ALPHA tail", 5],
        ["", 6],
    ]
    spool, result_id = _make_filter_spool(rows)
    worker = _FilterSpoolWorker(spool)
    try:
        result = DatabaseWorker._prepare_result_filter(
            worker, result_id, "aLpHa", limit=2
        )

        assert result["ok"] is True
        assert result["row_count"] == 3
        assert result["source_row_count"] == len(rows)
        assert result["rows"] == [["Alpha", 1], ["alphabet", 4]]
        assert result["source_offsets"] == [1, 4]
        assert result["has_more"] is True

        second_page = DatabaseWorker._fetch_result_page(
            worker, result_id, offset=2, limit=2, view_id=result["view_id"]
        )
        assert second_page["ok"] is True
        assert second_page["rows"] == [["ALPHA tail", 5]]
        assert second_page["source_offsets"] == [5]
        assert second_page["offset"] == 2
        assert second_page["row_count"] == 3
        assert second_page["source_row_count"] == len(rows)
        assert second_page["has_more"] is False
    finally:
        spool.close()


def test_prepare_result_filter_uses_displayed_null_marker_and_rejects_bad_requests():
    rows = [["value", 1], [None, 2], ["", 3]]
    spool, result_id = _make_filter_spool(rows)
    worker = _FilterSpoolWorker(spool)
    try:
        null_result = DatabaseWorker._prepare_result_filter(worker, result_id, "(NULL)", limit=10)
        assert null_result["ok"] is True
        assert null_result["row_count"] == 1
        assert null_result["rows"] == [[None, 2]]
        assert null_result["source_offsets"] == [1]

        too_long = DatabaseWorker._prepare_result_filter(worker, result_id, "x" * 257)
        assert too_long["ok"] is False
        assert "256-character limit" in too_long["error"]

        missing = DatabaseWorker._prepare_result_filter(worker, "expired-result", "value")
        assert missing["ok"] is False
        assert "expired" in missing["error"].casefold()

        dropped = DatabaseWorker._drop_result_filter(worker, null_result["view_id"])
        assert dropped["ok"] is True
        expired_page = DatabaseWorker._fetch_result_page(
            worker, result_id, offset=0, limit=10, view_id=null_result["view_id"]
        )
        assert expired_page["ok"] is False
        assert "expired" in expired_page["error"].casefold()
    finally:
        spool.close()


def test_prepare_result_filter_streams_large_spool_and_reports_progress():
    rows = [
        [f"match-row-{index}" if index in {4999, 9999} else f"row-{index}", index]
        for index in range(10050)
    ]
    spool, result_id = _make_filter_spool(rows)
    worker = _FilterSpoolWorker(spool)
    try:
        result = DatabaseWorker._prepare_result_filter(worker, result_id, "match-row", limit=1)

        assert result["ok"] is True
        assert result["row_count"] == 2
        assert result["rows"] == [["match-row-4999", 4999]]
        assert result["source_offsets"] == [4999]
        assert any("scanned 5,000" in message for message in worker.activities)
        assert any("scanned 10,000" in message for message in worker.activities)
    finally:
        spool.close()

def test_prepare_result_sort_is_numeric_aware_stable_and_keeps_nulls_last():
    rows = [["10"], ["2"], ["Alpha"], [None], ["alpha"], ["-1"], ["2.0"]]
    spool, result_id = _make_filter_spool(rows)
    worker = _FilterSpoolWorker(spool)
    try:
        ascending = DatabaseWorker._prepare_result_sort(
            worker, result_id, 0, False, limit=3
        )
        assert ascending["ok"] is True
        assert ascending["rows"] == [["-1"], ["2"], ["2.0"]]
        assert ascending["source_offsets"] == [5, 1, 6]
        assert ascending["row_count"] == len(rows)
        assert ascending["source_row_count"] == len(rows)
        assert ascending["has_more"] is True

        page_two = DatabaseWorker._fetch_result_page(
            worker, result_id, offset=3, limit=3, view_id=ascending["view_id"]
        )
        assert page_two["ok"] is True
        assert page_two["rows"] == [["10"], ["Alpha"], ["alpha"]]
        assert page_two["source_offsets"] == [0, 2, 4]

        page_three = DatabaseWorker._fetch_result_page(
            worker, result_id, offset=6, limit=3, view_id=ascending["view_id"]
        )
        assert page_three["ok"] is True
        assert page_three["rows"] == [[None]]
        assert page_three["source_offsets"] == [3]
        assert page_three["has_more"] is False

        descending = DatabaseWorker._prepare_result_sort(
            worker, result_id, 0, True, limit=10
        )
        assert descending["ok"] is True
        assert descending["rows"] == [
            ["Alpha"], ["alpha"], ["10"], ["2"], ["2.0"], ["-1"], [None]
        ]
        assert descending["source_offsets"] == [2, 4, 0, 1, 6, 5, 3]

        # The visible sort must never mutate fetch-order rows used by CSV/JSON export.
        fetched = spool.execute(
            "SELECT row_idx, values_json FROM result_rows WHERE result_id=? ORDER BY row_idx",
            (result_id,),
        ).fetchall()
        assert [json.loads(value_json) for _row_idx, value_json in fetched] == rows
    finally:
        spool.close()


def test_prepare_result_sort_composes_with_filtered_view_and_preserves_source_offsets():
    rows = [
        ["Alpha", 5],
        ["beta", 9],
        ["alphabet", 2],
        ["ALPHA", 1],
        ["other", 6],
    ]
    spool, result_id = _make_filter_spool(rows)
    worker = _FilterSpoolWorker(spool)
    try:
        filtered = DatabaseWorker._prepare_result_filter(
            worker, result_id, "alpha", limit=10
        )
        assert filtered["ok"] is True
        assert filtered["source_offsets"] == [0, 2, 3]

        sorted_view = DatabaseWorker._prepare_result_sort(
            worker,
            result_id,
            1,
            True,
            limit=2,
            base_view_id=filtered["view_id"],
        )
        assert sorted_view["ok"] is True
        assert sorted_view["query"] == "alpha"
        assert sorted_view["row_count"] == 3
        assert sorted_view["source_row_count"] == len(rows)
        assert sorted_view["rows"] == [["Alpha", 5], ["alphabet", 2]]
        assert sorted_view["source_offsets"] == [0, 2]
        assert sorted_view["has_more"] is True

        next_page = DatabaseWorker._fetch_result_page(
            worker,
            result_id,
            offset=2,
            limit=2,
            view_id=sorted_view["view_id"],
        )
        assert next_page["ok"] is True
        assert next_page["rows"] == [["ALPHA", 1]]
        assert next_page["source_offsets"] == [3]
        assert next_page["has_more"] is False

        assert DatabaseWorker._drop_result_filter(worker, sorted_view["view_id"])["ok"]
        assert DatabaseWorker._drop_result_filter(worker, filtered["view_id"])["ok"]
    finally:
        spool.close()


def test_prepare_result_sort_rejects_invalid_column_and_expired_base_view():
    rows = [["one", 1], ["two", 2]]
    spool, result_id = _make_filter_spool(rows)
    worker = _FilterSpoolWorker(spool)
    try:
        invalid = DatabaseWorker._prepare_result_sort(worker, result_id, 99)
        assert invalid["ok"] is False
        assert "sort column is invalid" in invalid["error"]

        expired = DatabaseWorker._prepare_result_sort(
            worker, result_id, 1, base_view_id="does-not-exist"
        )
        assert expired["ok"] is False
        assert "expired" in expired["error"].casefold()
    finally:
        spool.close()

