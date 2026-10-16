"""Dedicated database worker thread and disk-backed result cache."""
from __future__ import annotations
import csv
import json
import queue
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
from mysql_editor.core import redact_secrets, safe_identifier, split_sql_statements

MAX_PREVIEW_ROWS = 2000
FETCH_BATCH = 500

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
    message = redact_secrets(str(error)).strip().replace("\x00", "")
    if len(message) > 1600:
        message = message[:1600] + "…"
    return message or "The database operation failed. Check the connection and server logs."

class DatabaseWorker(QThread):
    completed = Signal(str, str, object)
    activity = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._tasks: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._connection = None
        self._connection_config: dict[str, Any] | None = None
        self._connection_id: int | None = None
        self._lock = threading.Lock()
        self._active_query = False
        self._spool_dir = Path(tempfile.mkdtemp(prefix="mysql-editor-results-"))
        self._spool_path = self._spool_dir / "results.sqlite3"
        self._spool: sqlite3.Connection | None = None

    def submit(self, action: str, payload: dict[str, Any] | None = None, task_id: str | None = None) -> str:
        task_id = task_id or uuid.uuid4().hex
        self._tasks.put({"id": task_id, "action": action, "payload": payload or {}})
        return task_id

    def run(self) -> None:
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
        while True:
            task = self._tasks.get()
            if task is None:
                break
            try:
                result = self._dispatch(task["action"], task["payload"])
            except Exception as exc:
                result = {"ok": False, "error": safe_db_error(exc)}
            self.completed.emit(task["id"], task["action"], result)
        self._close_connection()
        if self._spool:
            self._spool.close()
            self._spool = None
        try:
            for item in self._spool_dir.iterdir():
                item.unlink(missing_ok=True)
            self._spool_dir.rmdir()
        except OSError:
            pass

    def shutdown(self) -> None:
        self._tasks.put(None)

    def cancel_current_query(self) -> None:
        """Send best-effort KILL QUERY on a separate control connection."""
        with self._lock:
            config = dict(self._connection_config or {})
            connection_id = self._connection_id
            active = self._active_query
        if not active or not config or not connection_id:
            self.activity.emit("No cancellable query is currently active.")
            return
        def cancel() -> None:
            try:
                import mysql.connector
                control = mysql.connector.connect(**config)
                try:
                    cursor = control.cursor()
                    cursor.execute(f"KILL QUERY {int(connection_id)}")
                    cursor.close()
                    self.activity.emit("Cancellation request sent to MySQL.")
                finally:
                    control.close()
            except Exception as exc:
                self.activity.emit("Cancellation could not be confirmed: " + safe_db_error(exc))
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
            self._close_connection()
            import mysql.connector
            config = dict(payload["config"])
            options = self._connect_options(config)
            connection = mysql.connector.connect(**options)
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT VERSION(), DATABASE(), CURRENT_USER()")
                row = cursor.fetchone()
            finally:
                cursor.close()
            with self._lock:
                self._connection = connection
                self._connection_id = int(getattr(connection, "connection_id", 0) or 0)
                self._connection_config = options
            return {
                "ok": True, "server_version": str(row[0]) if row else "Unknown",
                "database": str(row[1] or "") if row else "",
                "current_user": str(row[2] or "") if row else "",
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
        if action in {"query", "schema", "table_preview", "commit", "rollback"} and self._connection is None:
            return {"ok": False, "error": "Not connected to a MySQL server."}
        if action == "query":
            return self._execute_script(str(payload.get("sql", "")))
        if action == "schema":
            return self._read_schema(str(payload.get("schema", "")))
        if action == "table_preview":
            return self._preview_table(str(payload.get("schema", "")), str(payload.get("table", "")))
        if action == "commit":
            self._connection.commit()
            return {"ok": True, "message": "Transaction committed."}
        if action == "rollback":
            self._connection.rollback()
            return {"ok": True, "message": "Transaction rolled back."}
        if action == "export_csv":
            return self._export_csv(str(payload["result_id"]), str(payload["path"]))
        return {"ok": False, "error": f"Unknown worker action: {action}"}

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
        statements = split_sql_statements(source)
        if not statements:
            return {"ok": False, "error": "There is no SQL statement to execute."}
        results: list[dict[str, Any]] = []
        started = time.perf_counter()
        with self._lock:
            self._active_query = True
        self.activity.emit("Executing SQL in the background…")
        try:
            for sql in statements:
                statement_start = time.perf_counter()
                cursor = self._connection.cursor()
                try:
                    cursor.execute(sql)
                    if cursor.with_rows:
                        headers = [str(desc[0]) for desc in (cursor.description or [])]
                        result_id = uuid.uuid4().hex
                        preview: list[list[Any]] = []
                        count = 0
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
                        self._spool.execute("UPDATE result_meta SET row_count=? WHERE result_id=?",
                                            (count, result_id))
                        self._spool.commit()
                        results.append({
                            "result_id": result_id, "headers": headers, "rows": preview,
                            "row_count": count, "preview_truncated": count > MAX_PREVIEW_ROWS,
                            "kind": "rows",
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
                            "kind": "status",
                            "duration_ms": int((time.perf_counter() - statement_start) * 1000),
                        })
                except Exception as exc:
                    results.append({
                        "headers": ["Error"], "rows": [[safe_db_error(exc)]], "row_count": 1,
                        "kind": "error",
                        "duration_ms": int((time.perf_counter() - statement_start) * 1000),
                    })
                    return {"ok": False, "results": results, "error": safe_db_error(exc),
                            "duration_ms": int((time.perf_counter() - started) * 1000)}
                finally:
                    cursor.close()
        finally:
            with self._lock:
                self._active_query = False
        return {"ok": True, "results": results,
                "duration_ms": int((time.perf_counter() - started) * 1000)}

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
        objects: list[dict[str, str]] = []
        if schema and schema in databases:
            cursor = self._connection.cursor()
            try:
                cursor.execute(f"SHOW FULL TABLES FROM {safe_identifier(schema)}")
                objects = [{"name": str(row[0]), "type": str(row[1])} for row in cursor.fetchall()]
            finally:
                cursor.close()
        return {"ok": True, "databases": databases, "schema": schema, "objects": objects}

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
        with destination.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(json.loads(meta[0]))
            cursor = self._spool.execute(
                "SELECT values_json FROM result_rows WHERE result_id=? ORDER BY row_idx", (result_id,)
            )
            count = 0
            for (value_json,) in cursor:
                writer.writerow(json.loads(value_json))
                count += 1
        return {"ok": True, "path": str(destination), "row_count": count}
