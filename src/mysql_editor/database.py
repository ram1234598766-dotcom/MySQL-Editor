"""Dedicated database worker thread and disk-backed result cache."""
from __future__ import annotations
import csv
import json
import os
import queue
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from datetime import date, datetime, time as dtime
from decimal import Decimal
from pathlib import Path
from typing import Any
from PySide6.QtCore import QThread, Signal
from mysql_editor.core import ScriptParseError, redact_sql_secrets, safe_identifier, split_sql_statements

MAX_PREVIEW_ROWS = 2000
FETCH_BATCH = 500
RESULT_PAGE_ROWS = 1000

CSV_NULL_TOKEN = r"\N"  # noqa: S105 - CSV marker, not a credential.


def _csv_export_value(value: Any) -> Any:
    """Encode SQL NULL separately from empty text and escape backslash-led strings."""
    if value is None:
        return CSV_NULL_TOKEN
    if isinstance(value, str) and value.startswith("\\"):
        return "\\" + value
    return value

def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (date, datetime, dtime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return "0x" + value.hex()
    return str(value)

def safe_db_error(error: BaseException) -> str:
    # Server/driver errors can echo fragments of submitted SQL. Redact common MySQL
    # account/password syntax as well as conventional key=value secret assignments.
    message = redact_sql_secrets(str(error)).strip().replace("\x00", "")
    if len(message) > 1600:
        message = message[:1600] + "…"
    return message or "The database operation failed. Check the connection and server logs."

def is_connection_lost(error: BaseException) -> bool:
    """Recognize errors that mean the active MySQL session can no longer be used."""
    try:
        error_number = int(getattr(error, "errno", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        error_number = 0
    if error_number in {2006, 2013, 2055}:
        return True
    sqlstate = str(getattr(error, "sqlstate", "") or "").upper()
    if sqlstate.startswith("08"):
        return True
    message = str(error).casefold()
    return any(fragment in message for fragment in (
        "server has gone away",
        "lost connection to mysql server",
        "connection is not available",
        "connection not available",
    ))


def is_query_interrupted(error: BaseException) -> bool:
    """Recognize MySQL's explicit query-interrupted error, not generic failures/timeouts."""
    message = str(error).casefold()
    return (
        getattr(error, "errno", None) == 1317
        or getattr(error, "sqlstate", None) == "70100"
        or "query execution was interrupted" in message
    )


class DatabaseWorker(QThread):
    completed = Signal(str, str, object)
    activity = Signal(str)
    task_activity = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._tasks: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._connection = None
        self._connection_config: dict[str, Any] | None = None
        self._connection_id: int | None = None
        self._lock = threading.Lock()
        self._active_query = False
        self._active_query_task_id: str | None = None
        # Monotonic token prevents a delayed cancellation from targeting a later statement.
        self._active_query_generation = 0
        self._current_task_id: str | None = None
        self._spool_dir = Path(tempfile.mkdtemp(prefix="mysql-editor-results-"))
        self._spool_path = self._spool_dir / "results.sqlite3"
        self._spool: sqlite3.Connection | None = None

    def submit(self, action: str, payload: dict[str, Any] | None = None, task_id: str | None = None) -> str:
        task_id = task_id or uuid.uuid4().hex
        self._tasks.put({"id": task_id, "action": action, "payload": payload or {}})
        return task_id

    def _report_activity(self, message: str) -> None:
        """Tag worker progress with the task that caused it, if there is one."""
        task_id = self._current_task_id
        self._report_task_activity(task_id, message)

    def _report_task_activity(self, task_id: str | None, message: str) -> None:
        if task_id:
            self.task_activity.emit(task_id, message)
        else:
            self.activity.emit(message)

    def _initialize_result_spool(self) -> None:
        """Create the worker-owned on-disk result cache."""
        self._spool = sqlite3.connect(self._spool_path)
        self._spool.execute("PRAGMA journal_mode=WAL")
        self._spool.executescript("""
            CREATE TABLE result_meta (
                result_id TEXT PRIMARY KEY, headers TEXT NOT NULL, statement TEXT NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE result_rows (
                result_id TEXT NOT NULL, row_idx INTEGER NOT NULL, values_json TEXT NOT NULL,
                PRIMARY KEY(result_id,row_idx)
            );
        """)
        self._spool.commit()

    def _cleanup_resources(self) -> None:
        """Release connections and remove the temporary result cache after any exit path."""
        self._close_connection()
        if self._spool is not None:
            spool, self._spool = self._spool, None
            try:
                spool.close()
            except Exception:
                pass
        try:
            # The directory is unique to this worker. Remove sidecars, orphaned files,
            # and any nested cache artifacts instead of leaving partial sensitive data.
            shutil.rmtree(self._spool_dir)
        except OSError:
            # A cache cleanup problem must not mask the original worker result.
            pass

    def run(self) -> None:
        startup_error: str | None = None
        try:
            self._initialize_result_spool()
        except Exception as exc:
            startup_error = (
                "Could not initialize the local result cache: " + safe_db_error(exc)
            )

        try:
            while True:
                task = self._tasks.get()
                if task is None:
                    break
                self._current_task_id = task["id"]
                try:
                    if startup_error is not None:
                        result = {"ok": False, "error": startup_error}
                    else:
                        try:
                            result = self._dispatch(task["action"], task["payload"])
                        except Exception as exc:
                            connection_lost = is_connection_lost(exc)
                            if connection_lost:
                                self._close_connection()
                            result = {
                                "ok": False, "error": safe_db_error(exc),
                                "connection_lost": connection_lost,
                            }
                    self.completed.emit(task["id"], task["action"], result)
                finally:
                    self._current_task_id = None
        finally:
            self._cleanup_resources()

    def shutdown(self) -> None:
        self._tasks.put(None)

    def cancel_current_query(self) -> None:
        """Send best-effort KILL QUERY without allowing it to hit the next statement."""
        with self._lock:
            config = dict(self._connection_config or {})
            connection_id = self._connection_id
            active = self._active_query
            active_task_id = self._active_query_task_id
            active_generation = self._active_query_generation
        if not active or not config or not connection_id:
            self.activity.emit("No cancellable query is currently active.")
            return

        def cancel() -> None:
            try:
                import mysql.connector

                def targets_current_statement() -> bool:
                    return (
                        self._active_query
                        and self._active_query_task_id == active_task_id
                        and self._active_query_generation == active_generation
                        and self._connection_id == connection_id
                    )

                # Do not hold the worker-state lock during network connection setup.
                # A query may finish while the control connection is opening, so validate
                # both before connecting and immediately before issuing KILL QUERY.
                with self._lock:
                    current_before_connect = targets_current_statement()
                if not current_before_connect:
                    self._report_task_activity(
                        active_task_id,
                        "Cancellation skipped because the SQL statement changed or finished.",
                    )
                    return

                control = mysql.connector.connect(**config)
                try:
                    # Serialize the final identity check and KILL with worker state
                    # transitions so a delayed request cannot cancel the next statement.
                    with self._lock:
                        still_targeting_statement = targets_current_statement()
                        if still_targeting_statement:
                            cursor = control.cursor()
                            try:
                                cursor.execute(f"KILL QUERY {int(connection_id)}")
                            finally:
                                cursor.close()
                finally:
                    control.close()

                if not still_targeting_statement:
                    self._report_task_activity(
                        active_task_id,
                        "Cancellation skipped because the SQL statement changed or finished.",
                    )
                else:
                    self._report_task_activity(
                        active_task_id, "Cancellation request sent to MySQL."
                    )
            except Exception as exc:
                self._report_task_activity(
                    active_task_id, "Cancellation could not be confirmed: " + safe_db_error(exc)
                )

        threading.Thread(target=cancel, name="mysql-editor-cancel", daemon=True).start()

    @staticmethod
    def _connect_options(config: dict[str, Any]) -> dict[str, Any]:
        options = {
            "host": config["host"], "port": int(config.get("port", 3306)),
            "user": config["username"], "password": config.get("password", ""),
            "connection_timeout": 10, "read_timeout": max(5, int(config.get("read_timeout", 60))),
            "write_timeout": max(5, int(config.get("write_timeout", 30))),
            "autocommit": False, "use_pure": True, "allow_local_infile": False,
        }
        database = str(config.get("default_schema", "")).strip()
        if database:
            options["database"] = database
        tls_mode = config.get("tls_mode", "Automatic TLS")
        if tls_mode == "Disabled":
            options["ssl_disabled"] = True
        else:
            options["ssl_disabled"] = False
            options["ssl_verify_cert"] = tls_mode == "Verify server identity"
            options["ssl_verify_identity"] = tls_mode == "Verify server identity"
            ca_file = str(config.get("ca_file", "")).strip()
            if ca_file and tls_mode == "Verify server identity":
                options["ssl_ca"] = ca_file
        return options

    def _close_connection(self) -> None:
        with self._lock:
            connection = self._connection
            self._connection = None
            self._connection_id = None
            self._connection_config = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    def _dispatch(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action == "connect":
            import mysql.connector
            config = dict(payload["config"])
            options = self._connect_options(config)
            candidate = None
            try:
                candidate = mysql.connector.connect(**options)
                cursor = candidate.cursor()
                try:
                    cursor.execute("SELECT VERSION(), DATABASE(), CURRENT_USER()")
                    row = cursor.fetchone()
                finally:
                    cursor.close()
                # End any implicit transaction opened by the connection handshake.
                candidate.rollback()
            except Exception:
                # A failed attempt must not discard the currently usable connection.
                if candidate is not None:
                    try:
                        candidate.close()
                    except Exception:
                        pass
                raise

            # Only make the candidate active after both connect and the handshake succeed.
            with self._lock:
                previous = self._connection
                self._connection = candidate
                self._connection_id = int(getattr(candidate, "connection_id", 0) or 0)
                self._connection_config = options
            if previous is not None and previous is not candidate:
                try:
                    previous.close()
                except Exception:
                    pass
            return {
                "ok": True, "server_version": str(row[0]) if row else "Unknown",
                "database": str(row[1] or "") if row else "",
                "current_user": str(row[2] or "") if row else "",
                "transaction_open": bool(getattr(candidate, "in_transaction", False)),
            }
        if action == "test":
            import mysql.connector
            connection = mysql.connector.connect(**self._connect_options(dict(payload["config"])))
            try:
                cursor = connection.cursor()
                try:
                    cursor.execute("SELECT VERSION(), DATABASE()")
                    row = cursor.fetchone()
                finally:
                    cursor.close()
                return {"ok": True, "server_version": str(row[0]) if row else "Unknown",
                        "database": str(row[1] or "") if row else ""}
            finally:
                connection.close()
        if action == "disconnect":
            self._close_connection()
            return {"ok": True}
        # Reading already-fetched rows from the local SQLite spool does not require
        # an active MySQL connection and never re-executes the user's SQL.
        if action == "fetch_result_page":
            return self._fetch_result_page(
                str(payload.get("result_id", "") or ""),
                payload.get("offset", 0),
                payload.get("limit", RESULT_PAGE_ROWS),
            )
        if action in {"query", "schema", "schema_objects", "table_preview", "use_schema", "commit", "rollback"} and self._connection is None:
            return {"ok": False, "error": "Not connected to a MySQL server."}
        if action == "query":
            return self._execute_script(str(payload.get("sql", "")))
        if action == "use_schema":
            # Switch the live session, not just the UI's idea of its default schema.
            # MySQL identifiers cannot be bound as values, so quote the name explicitly.
            schema = str(payload.get("schema", "") or "")
            if not schema.strip():
                return {"ok": False, "error": "A database schema name is required."}
            cursor = self._connection.cursor()
            try:
                cursor.execute(f"USE {safe_identifier(schema)}")
            finally:
                cursor.close()
            with self._lock:
                if self._connection_config is not None:
                    self._connection_config["database"] = schema
            return {
                "ok": True,
                "schema": schema,
                "transaction_open": bool(getattr(self._connection, "in_transaction", False)),
            }
        if action == "schema":
            return self._read_schema(str(payload.get("schema", "")))
        if action == "schema_objects":
            return self._read_schema_objects(str(payload.get("schema", "")))
        if action == "table_preview":
            return self._preview_table(str(payload.get("schema", "")), str(payload.get("table", "")))
        if action == "commit":
            self._connection.commit()
            return {
                "ok": True, "message": "Transaction committed.",
                "transaction_open": bool(getattr(self._connection, "in_transaction", False)),
            }
        if action == "rollback":
            self._connection.rollback()
            return {
                "ok": True, "message": "Transaction rolled back.",
                "transaction_open": bool(getattr(self._connection, "in_transaction", False)),
            }
        if action == "export_csv":
            return self._export_csv(str(payload["result_id"]), str(payload["path"]))
        return {"ok": False, "error": f"Unknown worker action: {action}"}

    def _fetch_result_page(
        self, result_id: str, offset: Any = 0, limit: Any = RESULT_PAGE_ROWS
    ) -> dict[str, Any]:
        """Read a bounded page from a fetched result without contacting MySQL."""
        if self._spool is None:
            return {
                "ok": False,
                "error": "The result cache is no longer available.",
                "result_id": result_id,
                "offset": 0,
                "rows": [],
            }
        try:
            page_offset = int(offset)
        except (TypeError, ValueError, OverflowError):
            return {
                "ok": False, "error": "The result page offset is invalid.",
                "result_id": result_id, "offset": 0, "rows": [],
            }
        if page_offset < 0:
            return {
                "ok": False, "error": "The result page offset cannot be negative.",
                "result_id": result_id, "offset": page_offset, "rows": [],
            }
        try:
            page_limit = int(limit)
        except (TypeError, ValueError, OverflowError):
            page_limit = RESULT_PAGE_ROWS
        page_limit = min(RESULT_PAGE_ROWS, max(1, page_limit))
        chosen_result_id = str(result_id or "").strip()
        if not chosen_result_id:
            return {
                "ok": False, "error": "A result identifier is required.",
                "result_id": chosen_result_id, "offset": page_offset, "rows": [],
            }
        try:
            meta = self._spool.execute(
                "SELECT row_count FROM result_meta WHERE result_id=?",
                (chosen_result_id,),
            ).fetchone()
            if meta is None:
                return {
                    "ok": False,
                    "error": "This query result has expired. Run the query again.",
                    "result_id": chosen_result_id,
                    "offset": page_offset,
                    "rows": [],
                }
            total_rows = max(0, int(meta[0] or 0))
            if page_offset > total_rows:
                return {
                    "ok": False,
                    "error": "The requested result page is beyond the end of this result.",
                    "result_id": chosen_result_id,
                    "offset": page_offset,
                    "rows": [],
                    "row_count": total_rows,
                }
            page = self._spool.execute(
                "SELECT values_json FROM result_rows "
                "WHERE result_id=? ORDER BY row_idx LIMIT ? OFFSET ?",
                (chosen_result_id, page_limit, page_offset),
            ).fetchall()
            rows = [json.loads(value_json) for (value_json,) in page]
        except Exception as exc:
            return {
                "ok": False,
                "error": safe_db_error(exc),
                "result_id": chosen_result_id,
                "offset": page_offset,
                "rows": [],
            }
        return {
            "ok": True,
            "result_id": chosen_result_id,
            "offset": page_offset,
            "rows": rows,
            "row_count": total_rows,
            "page_size": page_limit,
            "has_more": page_offset + len(rows) < total_rows,
        }

    def _save_rows(self, result_id: str, headers: list[str], statement: str, rows: list[list[Any]]) -> None:
        assert self._spool is not None
        self._spool.execute(
            "INSERT INTO result_meta(result_id,headers,statement,row_count) VALUES(?,?,?,?)",
            (result_id, json.dumps(headers), statement, len(rows)),
        )
        self._spool.executemany(
            "INSERT INTO result_rows(result_id,row_idx,values_json) VALUES(?,?,?)",
            [(result_id, i, json.dumps(row, ensure_ascii=False)) for i, row in enumerate(rows)],
        )
        self._spool.commit()

    def _execute_script(self, source: str) -> dict[str, Any]:
        try:
            statements = split_sql_statements(source)
        except ScriptParseError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "results": [],
                "duration_ms": 0,
                "transaction_open": bool(getattr(self._connection, "in_transaction", False)),
            }
        if not statements:
            return {
                "ok": False, "error": "There is no SQL statement to execute.",
                "transaction_open": bool(getattr(self._connection, "in_transaction", False)),
            }
        results: list[dict[str, Any]] = []
        started = time.perf_counter()
        with self._lock:
            self._active_query = True
            self._active_query_task_id = self._current_task_id
        self._report_activity(f"Running {len(statements):,} SQL statement(s)…")
        try:
            for statement_number, sql in enumerate(statements, start=1):
                self._report_activity(f"Running statement {statement_number} of {len(statements)}…")
                statement_start = time.perf_counter()
                connection_lost = False
                result_id: str | None = None
                # Each statement gets its own cancellation generation. The cancel
                # thread holds _lock while sending KILL QUERY; acquiring it here prevents
                # that delayed request from striking the next statement in a script.
                with self._lock:
                    self._active_query_generation += 1
                cursor = self._connection.cursor()
                try:
                    cursor.execute(sql)
                    try:
                        warning_count = max(0, int(getattr(cursor, "warning_count", 0) or 0))
                    except (TypeError, ValueError, OverflowError):
                        warning_count = 0
                    if cursor.with_rows:
                        self._report_activity("Fetching result rows from MySQL…")
                        headers = [str(desc[0]) for desc in (cursor.description or [])]
                        result_id = uuid.uuid4().hex
                        preview: list[list[Any]] = []
                        count = 0
                        next_progress_row = 5000
                        assert self._spool is not None
                        self._spool.execute(
                            "INSERT INTO result_meta(result_id,headers,statement,row_count) VALUES(?,?,?,0)",
                            (result_id, json.dumps(headers), sql),
                        )
                        while True:
                            batch = cursor.fetchmany(FETCH_BATCH)
                            if not batch:
                                break
                            serialized = [[json_value(value) for value in row] for row in batch]
                            preview.extend(serialized[:max(0, MAX_PREVIEW_ROWS - len(preview))])
                            self._spool.executemany(
                                "INSERT INTO result_rows(result_id,row_idx,values_json) VALUES(?,?,?)",
                                [(result_id, count + i, json.dumps(row, ensure_ascii=False))
                                 for i, row in enumerate(serialized)],
                            )
                            count += len(serialized)
                            if count >= next_progress_row:
                                self._report_activity(f"Fetched {count:,} result row(s) so far…")
                                next_progress_row = ((count // 5000) + 1) * 5000
                        self._spool.execute("UPDATE result_meta SET row_count=? WHERE result_id=?",
                                            (count, result_id))
                        self._spool.commit()
                        results.append({
                            "result_id": result_id, "headers": headers, "rows": preview,
                            "row_count": count, "preview_truncated": count > MAX_PREVIEW_ROWS,
                            "kind": "rows", "statement_index": statement_number,
                            "statement_count": len(statements), "warning_count": warning_count,
                            "duration_ms": int((time.perf_counter() - statement_start) * 1000),
                        })
                    else:
                        affected = max(0, int(cursor.rowcount))
                        result_id = uuid.uuid4().hex
                        rows = [["Statement executed", affected]]
                        self._save_rows(result_id, ["Result", "Affected rows"], sql, rows)
                        results.append({
                            "result_id": result_id, "headers": ["Result", "Affected rows"],
                            "rows": rows, "row_count": len(rows), "affected_rows": affected,
                            "kind": "status", "statement_index": statement_number,
                            "statement_count": len(statements), "warning_count": warning_count,
                            "duration_ms": int((time.perf_counter() - statement_start) * 1000),
                        })
                except Exception as exc:
                    interrupted = is_query_interrupted(exc)
                    connection_lost = is_connection_lost(exc)
                    if result_id is not None and self._spool is not None:
                        # A fetch/serialization failure must not leave an invisible partial
                        # result in the session spool. Earlier completed results are retained.
                        try:
                            self._spool.execute(
                                "DELETE FROM result_rows WHERE result_id=?", (result_id,)
                            )
                            self._spool.execute(
                                "DELETE FROM result_meta WHERE result_id=?", (result_id,)
                            )
                            self._spool.commit()
                        except Exception:
                            try:
                                self._spool.rollback()
                            except Exception:
                                pass
                    results.append({
                        "headers": ["Error"], "rows": [[safe_db_error(exc)]], "row_count": 1,
                        "kind": "error", "interrupted": interrupted,
                        "statement_index": statement_number, "statement_count": len(statements),
                        "warning_count": 0, "connection_lost": connection_lost,
                        "duration_ms": int((time.perf_counter() - statement_start) * 1000),
                    })
                    return {
                        "ok": False, "results": results, "error": safe_db_error(exc),
                        "interrupted": interrupted, "connection_lost": connection_lost,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                        "transaction_open": False if connection_lost else bool(
                            getattr(self._connection, "in_transaction", False)
                        ),
                    }
                finally:
                    try:
                        cursor.close()
                    finally:
                        if connection_lost:
                            self._close_connection()
        finally:
            with self._lock:
                self._active_query = False
                self._active_query_task_id = None
        return {
            "ok": True, "results": results,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "transaction_open": bool(getattr(self._connection, "in_transaction", False)),
        }

    def _read_schema(self, schema: str) -> dict[str, Any]:
        cursor = self._connection.cursor()
        try:
            cursor.execute("SHOW DATABASES")
            databases = [str(row[0]) for row in cursor.fetchall()]
        finally:
            cursor.close()
        if not schema:
            cursor = self._connection.cursor()
            try:
                cursor.execute("SELECT DATABASE()")
                row = cursor.fetchone()
                schema = str(row[0] or "") if row else ""
            finally:
                cursor.close()

        objects_result = (
            self._read_schema_objects(schema)
            if schema and schema in databases
            else {
                "ok": True, "schema": schema, "objects": [],
                "columns_by_table": {}, "column_metadata_truncated": False,
            }
        )
        return {"ok": True, "databases": databases, **objects_result}

    def _read_schema_objects(self, schema: str) -> dict[str, Any]:
        """Fetch table/view and column metadata for one schema on demand."""
        schema = str(schema or "").strip()
        if not schema:
            return {"ok": False, "error": "A database schema must be selected."}

        cursor = self._connection.cursor()
        try:
            cursor.execute(f"SHOW FULL TABLES FROM {safe_identifier(schema)}")
            objects = [
                {"name": str(row[0]), "type": str(row[1])}
                for row in cursor.fetchall()
            ]
        finally:
            cursor.close()

        columns_by_table: dict[str, list[str]] = {}
        column_metadata_truncated = False
        # Metadata is bounded so a very wide schema can't flood completion. A lack of
        # optional column privileges must not prevent table/view browsing.
        column_cursor = self._connection.cursor()
        try:
            column_cursor.execute(
                "SELECT TABLE_NAME, COLUMN_NAME "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s "
                "ORDER BY TABLE_NAME, ORDINAL_POSITION LIMIT 10001",
                (schema,),
            )
            column_rows = column_cursor.fetchall()
            column_metadata_truncated = len(column_rows) > 10000
            for table_name, column_name in column_rows[:10000]:
                columns_by_table.setdefault(str(table_name), []).append(str(column_name))
        except Exception:
            columns_by_table = {}
            column_metadata_truncated = False
        finally:
            column_cursor.close()

        return {
            "ok": True, "schema": schema, "objects": objects,
            "columns_by_table": columns_by_table,
            "column_metadata_truncated": column_metadata_truncated,
        }

    def _preview_table(self, schema: str, table: str) -> dict[str, Any]:
        cursor = self._connection.cursor()
        try:
            cursor.execute(f"SELECT * FROM {safe_identifier(schema)}.{safe_identifier(table)} LIMIT 1000")
            headers = [str(desc[0]) for desc in (cursor.description or [])]
            rows = [[json_value(value) for value in row] for row in cursor.fetchall()]
        finally:
            cursor.close()
        result_id = uuid.uuid4().hex
        self._save_rows(result_id, headers, f"Preview {schema}.{table}", rows)
        return {"ok": True, "results": [{
            "result_id": result_id, "headers": headers, "rows": rows, "row_count": len(rows),
            "preview_truncated": False, "kind": "rows", "duration_ms": 0,
        }]}

    def _export_csv(self, result_id: str, path: str) -> dict[str, Any]:
        if self._spool is None:
            return {"ok": False, "error": "The result cache is no longer available."}
        meta = self._spool.execute("SELECT headers FROM result_meta WHERE result_id=?",
                                   (result_id,)).fetchone()
        if not meta:
            return {"ok": False, "error": "This query result has expired. Run the query again."}
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        count = 0

        def report_activity(message: str) -> None:
            reporter = getattr(self, "_report_activity", None)
            if callable(reporter):
                reporter(message)
            else:
                activity = getattr(self, "activity", None)
                if activity is not None:
                    activity.emit(message)

        report_activity("Exporting CSV rows…")
        next_progress_row = 5000
        try:
            with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(json.loads(meta[0]))
                cursor = self._spool.execute(
                    "SELECT values_json FROM result_rows WHERE result_id=? ORDER BY row_idx", (result_id,)
                )
                for (value_json,) in cursor:
                    writer.writerow([_csv_export_value(value) for value in json.loads(value_json)])
                    count += 1
                    if count >= next_progress_row:
                        report_activity(f"Exported {count:,} CSV row(s)…")
                        next_progress_row = ((count // 5000) + 1) * 5000
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return {"ok": True, "path": str(destination), "row_count": count}
