"""Dedicated database worker thread and disk-backed result cache."""
from __future__ import annotations
import csv
import json
import os
import queue
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from datetime import date, datetime, time as dtime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from PySide6.QtCore import QThread, Signal
from mysql_editor.core import ScriptParseError, safe_identifier, sanitize_error_message, split_sql_statements

MAX_PREVIEW_ROWS = 2000
FETCH_BATCH = 500
RESULT_PAGE_ROWS = 1000

CSV_NULL_TOKEN = r"\N"  # noqa: S105 - CSV marker, not a credential.


def _decimal_sort_collation(left: str, right: str) -> int:
    """Compare decimal keys without converting arbitrary-precision values to floats."""
    if left == right:
        return 0
    if not left or not right:
        return -1 if left < right else 1
    try:
        first = Decimal(left)
        second = Decimal(right)
        if first < second:
            return -1
        if first > second:
            return 1
        return 0
    except (InvalidOperation, ValueError):
        return -1 if left < right else 1


def _csv_export_value(value: Any) -> Any:
    """Encode SQL NULL separately from empty text and escape backslash-led strings."""
    if value is None:
        return CSV_NULL_TOKEN
    if isinstance(value, str) and value.startswith("\\"):
        return "\\" + value
    return value

def unique_json_export_headers(headers: list[Any]) -> list[str]:
    """Make result-column names unique without silently dropping duplicate-column values."""
    used: set[str] = set()
    result: list[str] = []
    for index, header in enumerate(headers, start=1):
        base = str(header) if header is not None else ""
        if not base:
            base = f"column_{index}"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base} ({suffix})"
            suffix += 1
        used.add(candidate)
        result.append(candidate)
    return result


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
    """Preserve useful database context while sanitizing and bounding driver errors."""
    return sanitize_error_message(
        error,
        fallback="The database operation failed. Check the connection and server logs.",
    )

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


def _leading_transaction_command(sql: str) -> str:
    """Return COMMIT, ROLLBACK, ROLLBACK_TO or empty after leading SQL comments."""
    source = str(sql or "")
    while True:
        source = source.lstrip()
        if source.startswith("/*"):
            end = source.find("*/", 2)
            if end < 0:
                return ""
            source = source[end + 2:]
            continue
        if source.startswith("#") or (
            source.startswith("--")
            and (len(source) == 2 or source[2].isspace())
        ):
            newline = source.find("\n")
            if newline < 0:
                return ""
            source = source[newline + 1:]
            continue
        break
    match = re.match(r"(?i)^(COMMIT|ROLLBACK)\b", source)
    if match is None:
        return ""
    command = match.group(1).upper()
    if command == "ROLLBACK" and re.match(r"(?i)^ROLLBACK\s+(?:WORK\s+)?TO\b", source):
        return "ROLLBACK_TO"
    return command


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
        # Prevent a stale preview from one connection being edited after a session switch.
        self._session_token = uuid.uuid4().hex
        # Snapshot each preview row once while an inline edit belongs to an open transaction.
        self._table_preview_undo: dict[tuple[str, int], list[Any]] = {}
        # Rollback-to-savepoint can invalidate a cached preview without ending the transaction.
        self._invalid_table_previews: set[str] = set()
        # Keyset paging state for active Schema Explorer table previews.
        self._table_preview_pages: dict[str, dict[str, Any]] = {}
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
        # Large view sorts must spill to disk instead of building a million-row
        # in-memory temporary B-tree alongside the bounded Qt model.
        self._spool.execute("PRAGMA temp_store=FILE")
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
            CREATE TABLE result_filter_views (
                view_id TEXT PRIMARY KEY, result_id TEXT NOT NULL,
                query TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX result_filter_views_result_id
                ON result_filter_views(result_id);
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
                            preview_restore = {
                                "preview_rollback_rows": [],
                                "preview_restore_errors": [],
                            }
                            if connection_lost:
                                preview_restore = self._close_connection()
                            result = {
                                "ok": False, "error": safe_db_error(exc),
                                "connection_lost": connection_lost,
                                **preview_restore,
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

    def _restore_table_preview_undo(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Restore local preview snapshots when an uncommitted edit is rolled back."""
        if not self._table_preview_undo:
            return [], []

        restored: list[dict[str, Any]] = []
        errors: list[str] = []
        try:
            for (result_id, row_index), baseline in list(self._table_preview_undo.items()):
                if self._spool is None:
                    errors.append("The local result cache is unavailable.")
                else:
                    cursor = self._spool.execute(
                        "UPDATE result_rows SET values_json = ? WHERE result_id = ? AND row_idx = ?",
                        (json.dumps(baseline, ensure_ascii=False), result_id, row_index),
                    )
                    if cursor.rowcount != 1:
                        errors.append(
                            "A local preview row is no longer cached; re-preview that table before exporting."
                        )
                # Restore the UI snapshot even if its disk-backed row has expired.
                restored.append({
                    "result_id": result_id,
                    "row_index": row_index,
                    "display_row": list(baseline),
                })
            if self._spool is not None:
                self._spool.commit()
        except Exception as exc:
            if self._spool is not None:
                try:
                    self._spool.rollback()
                except Exception:
                    pass
            # The MySQL rollback has already happened. Keep enough information for the
            # UI to restore its in-memory rows, but discard these snapshots so a later
            # transaction can never reuse stale undo state.
            restored = [
                {
                    "result_id": result_id,
                    "row_index": row_index,
                    "display_row": list(baseline),
                }
                for (result_id, row_index), baseline in self._table_preview_undo.items()
            ]
            self._table_preview_undo.clear()
            return restored, [
                "MySQL rolled back the transaction, but the local preview cache could not be restored: "
                + safe_db_error(exc)
            ]

        self._table_preview_undo.clear()
        return restored, errors

    def _invalidate_table_previews(self) -> list[str]:
        """Mark cached Schema Explorer previews stale after partial transaction rollback."""
        if self._spool is None:
            result_ids = {result_id for result_id, _row_index in self._table_preview_undo}
        else:
            try:
                rows = self._spool.execute(
                    "SELECT result_id FROM result_meta WHERE statement LIKE 'Preview %'"
                ).fetchall()
                result_ids = {str(row[0]) for row in rows if row and row[0]}
            except sqlite3.Error:
                result_ids = {result_id for result_id, _row_index in self._table_preview_undo}
        self._invalid_table_previews.update(result_ids)
        return sorted(result_ids)

    def _close_connection(self) -> dict[str, Any]:
        # Closing a connection can implicitly roll back uncommitted cell edits. Keep
        # the local result cache and the visible table-preview snapshot consistent.
        preview_rows, preview_errors = self._restore_table_preview_undo()
        with self._lock:
            connection = self._connection
            self._connection = None
            self._connection_id = None
            self._connection_config = None
            self._session_token = uuid.uuid4().hex
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        return {
            "preview_rollback_rows": preview_rows,
            "preview_restore_errors": preview_errors,
        }

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
                self._session_token = uuid.uuid4().hex
            preview_restore = {"preview_rollback_rows": [], "preview_restore_errors": []}
            if previous is not None and previous is not candidate:
                # Replacing the session implicitly rolls back a pending transaction on
                # the previous connection, so restore its preview snapshots as well.
                restored_rows, restore_errors = self._restore_table_preview_undo()
                preview_restore = {
                    "preview_rollback_rows": restored_rows,
                    "preview_restore_errors": restore_errors,
                }
                try:
                    previous.close()
                except Exception:
                    pass
            return {
                "ok": True, "server_version": str(row[0]) if row else "Unknown",
                "database": str(row[1] or "") if row else "",
                "current_user": str(row[2] or "") if row else "",
                "transaction_open": bool(getattr(candidate, "in_transaction", False)),
                **preview_restore,
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
            preview_restore = self._close_connection()
            return {"ok": True, **preview_restore}
        # Reading already-fetched rows from the local SQLite spool does not require
        # an active MySQL connection and never re-executes the user's SQL.
        if action == "fetch_result_page":
            return self._fetch_result_page(
                str(payload.get("result_id", "") or ""),
                payload.get("offset", 0),
                payload.get("limit", RESULT_PAGE_ROWS),
                view_id=str(payload.get("view_id", "") or "") or None,
            )
        if action == "filter_result_spool":
            return self._prepare_result_filter(
                str(payload.get("result_id", "") or ""),
                str(payload.get("query", "") or ""),
                payload.get("limit", RESULT_PAGE_ROWS),
                sort_column=payload.get("sort_column"),
                sort_descending=bool(payload.get("sort_descending", False)),
            )
        if action == "sort_result_spool":
            return self._prepare_result_sort(
                str(payload.get("result_id", "") or ""),
                payload.get("column", -1),
                bool(payload.get("descending", False)),
                payload.get("limit", RESULT_PAGE_ROWS),
                base_view_id=str(payload.get("base_view_id", "") or "") or None,
            )
        if action == "drop_result_filter":
            return self._drop_result_filter(str(payload.get("view_id", "") or ""))
        if action in {
            "query", "schema", "schema_objects", "table_preview", "inspect_schema_object",
            "update_table_cell", "use_schema", "commit", "rollback",
        } and self._connection is None:
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
        if action == "update_table_cell":
            result = self._update_table_cell(dict(payload))
            result.setdefault(
                "transaction_open",
                bool(getattr(self._connection, "in_transaction", False))
                if self._connection is not None else False,
            )
            return result
        if action == "inspect_schema_object":
            return self._inspect_schema_object(
                str(payload.get("schema", "") or ""),
                str(payload.get("table", "") or ""),
                str(payload.get("object_type", "") or ""),
            )
        if action == "commit":
            self._connection.commit()
            self._table_preview_undo.clear()
            return {
                "ok": True, "message": "Transaction committed.",
                "transaction_open": bool(getattr(self._connection, "in_transaction", False)),
                "preview_transaction_finalized": True,
            }
        if action == "rollback":
            self._connection.rollback()
            preview_rows, preview_errors = self._restore_table_preview_undo()
            message = "Transaction rolled back."
            if preview_rows:
                message += f" Restored {len(preview_rows):,} table-preview row snapshot(s)."
            if preview_errors:
                message += " Some local preview snapshots could not be restored; refresh affected previews."
            return {
                "ok": True, "message": message,
                "transaction_open": bool(getattr(self._connection, "in_transaction", False)),
                "preview_rollback_rows": preview_rows,
                "preview_restore_errors": preview_errors,
                "preview_transaction_finalized": True,
            }
        if action == "export_csv":
            return self._export_csv(str(payload["result_id"]), str(payload["path"]))
        if action == "export_json":
            return self._export_json(str(payload["result_id"]), str(payload["path"]))
        if action == "export_ndjson":
            return self._export_ndjson(str(payload["result_id"]), str(payload["path"]))
        return {"ok": False, "error": f"Unknown worker action: {action}"}

    def _fetch_result_page(
        self,
        result_id: str,
        offset: Any = 0,
        limit: Any = RESULT_PAGE_ROWS,
        *,
        view_id: str | None = None,
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
        if chosen_result_id in getattr(self, "_invalid_table_previews", set()):
            return {
                "ok": False,
                "error": "This table preview may be stale after ROLLBACK TO SAVEPOINT. Refresh the table before loading more rows.",
                "result_id": chosen_result_id,
                "offset": page_offset,
                "rows": [],
            }
        preview_context = getattr(self, "_table_preview_pages", {}).get(chosen_result_id)
        if preview_context is not None and not view_id:
            loaded_count = max(0, int(preview_context.get("loaded_count", 0) or 0))
            if page_offset >= loaded_count:
                return self._fetch_table_preview_page(chosen_result_id, page_offset, page_limit)
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
            source_row_count = max(0, int(meta[0] or 0))
            source_offsets: list[int] = []
            if view_id:
                view_meta = self._spool.execute(
                    "SELECT result_id, query, row_count FROM result_filter_views WHERE view_id=?",
                    (view_id,),
                ).fetchone()
                if view_meta is None or str(view_meta[0]) != chosen_result_id:
                    return {
                        "ok": False,
                        "error": "This filtered result view has expired. Apply the filter again.",
                        "result_id": chosen_result_id,
                        "view_id": view_id,
                        "offset": page_offset,
                        "rows": [],
                    }
                total_rows = max(0, int(view_meta[2] or 0))
                if page_offset > total_rows:
                    return {
                        "ok": False,
                        "error": "The requested filtered page is beyond the end of this result.",
                        "result_id": chosen_result_id,
                        "view_id": view_id,
                        "offset": page_offset,
                        "rows": [],
                        "row_count": total_rows,
                    }
                page = self._spool.execute(
                    "SELECT r.values_json, v.source_idx "
                    "FROM result_filter_view_rows AS v "
                    "JOIN result_rows AS r ON r.result_id=? AND r.row_idx=v.source_idx "
                    "WHERE v.view_id=? ORDER BY v.view_idx LIMIT ? OFFSET ?",
                    (chosen_result_id, view_id, page_limit, page_offset),
                ).fetchall()
                rows = [json.loads(value_json) for value_json, _source_idx in page]
                source_offsets = [int(source_idx) for _value_json, source_idx in page]
            else:
                total_rows = source_row_count
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
                source_offsets = list(range(page_offset, page_offset + len(rows)))
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
            "view_id": view_id,
            "offset": page_offset,
            "rows": rows,
            "source_offsets": source_offsets,
            "row_count": total_rows,
            "source_row_count": source_row_count,
            "page_size": page_limit,
            "has_more": page_offset + len(rows) < total_rows,
        }

    def _prepare_result_filter(
        self,
        result_id: str,
        query: str,
        limit: Any = RESULT_PAGE_ROWS,
        *,
        sort_column: Any | None = None,
        sort_descending: bool = False,
    ) -> dict[str, Any]:
        """Build a disk-backed, ordered index of rows matching a case-insensitive substring."""
        if self._spool is None:
            return {"ok": False, "error": "The local result cache is no longer available."}
        chosen_result_id = str(result_id or "").strip()
        needle = str(query or "").strip()
        if not chosen_result_id:
            return {"ok": False, "error": "A result identifier is required for filtering."}
        if not needle:
            return {"ok": False, "error": "The full-result filter query cannot be empty."}
        if len(needle) > 256:
            return {"ok": False, "error": "The filter query is longer than the 256-character limit."}
        folded_needle = needle.casefold()
        if chosen_result_id in getattr(self, "_invalid_table_previews", set()):
            return {
                "ok": False,
                "error": "This table preview may be stale after ROLLBACK TO SAVEPOINT. Refresh the table before filtering it.",
            }
        incomplete_preview = self._incomplete_table_preview_error(chosen_result_id, "filter")
        if incomplete_preview:
            return {"ok": False, "error": incomplete_preview, "result_id": chosen_result_id, "query": needle}

        view_id = uuid.uuid4().hex
        try:
            meta = self._spool.execute(
                "SELECT headers, row_count FROM result_meta WHERE result_id=?",
                (chosen_result_id,),
            ).fetchone()
            if meta is None:
                return {
                    "ok": False,
                    "error": "This query result has expired. Run the query again.",
                    "result_id": chosen_result_id,
                    "query": needle,
                }
            try:
                headers = json.loads(meta[0])
            except (TypeError, json.JSONDecodeError):
                headers = []
            source_row_count = max(0, int(meta[1] or 0))
            sort_column_index: int | None = None
            if sort_column is not None:
                try:
                    sort_column_index = int(sort_column)
                except (TypeError, ValueError, OverflowError):
                    sort_column_index = -1
                if not 0 <= sort_column_index < len(headers):
                    return {
                        "ok": False,
                        "error": "The requested sort column is invalid for this result.",
                        "result_id": chosen_result_id,
                        "query": needle,
                    }
            self._spool.commit()
            self._spool.execute("BEGIN")
            self._spool.execute(
                "INSERT INTO result_filter_views(view_id,result_id,query,row_count) VALUES(?,?,?,0)",
                (view_id, chosen_result_id, needle),
            )
            cursor = self._spool.execute(
                "SELECT row_idx, values_json FROM result_rows WHERE result_id=? ORDER BY row_idx",
                (chosen_result_id,),
            )
            scanned = 0
            matched = 0
            try:
                page_rows = int(limit or RESULT_PAGE_ROWS)
            except (TypeError, ValueError, OverflowError):
                page_rows = RESULT_PAGE_ROWS
            page_rows = max(1, min(RESULT_PAGE_ROWS, page_rows))
            while True:
                batch = cursor.fetchmany(RESULT_PAGE_ROWS)
                if not batch:
                    break
                mappings = []
                for source_idx, values_json in batch:
                    values = json.loads(values_json)
                    if not isinstance(values, list):
                        raise ValueError("A cached result row is not a JSON array.")
                    if any(
                        folded_needle in ("(NULL)" if value is None else str(value)).casefold()
                        for value in values
                    ):
                        mappings.append((view_id, matched, int(source_idx)))
                        matched += 1
                if mappings:
                    self._spool.executemany(
                        "INSERT INTO result_filter_view_rows(view_id,view_idx,source_idx) VALUES(?,?,?)",
                        mappings,
                    )
                scanned += len(batch)
                if scanned and scanned % 5000 < len(batch):
                    self._report_activity(
                        f"Searching the local result cache · scanned {scanned:,} of {source_row_count:,} rows; "
                        f"{matched:,} match(es)…"
                    )
            self._spool.execute(
                "UPDATE result_filter_views SET row_count=? WHERE view_id=?",
                (matched, view_id),
            )
            if sort_column_index is not None:
                self._sort_result_view_rows(
                    view_id, sort_column_index, descending=bool(sort_descending)
                )
            self._spool.commit()
            first_page = self._spool.execute(
                "SELECT r.values_json, v.source_idx "
                "FROM result_filter_view_rows AS v "
                "JOIN result_rows AS r ON r.result_id=? AND r.row_idx=v.source_idx "
                "WHERE v.view_id=? ORDER BY v.view_idx LIMIT ? OFFSET 0",
                (chosen_result_id, view_id, page_rows),
            ).fetchall()
            return {
                "ok": True,
                "result_id": chosen_result_id,
                "view_id": view_id,
                "query": needle,
                "offset": 0,
                "rows": [json.loads(value_json) for value_json, _source_idx in first_page],
                "source_offsets": [int(source_idx) for _value_json, source_idx in first_page],
                "row_count": matched,
                "source_row_count": source_row_count,
                "page_size": page_rows,
                "has_more": len(first_page) < matched,
                "sort_column": sort_column_index,
                "sort_descending": bool(sort_descending) if sort_column_index is not None else None,
            }
        except Exception as exc:
            try:
                self._spool.rollback()
                self._spool.execute("DELETE FROM result_view_sort_keys WHERE view_id=?", (view_id,))
                self._spool.execute("DELETE FROM result_filter_view_rows WHERE view_id=?", (view_id,))
                self._spool.execute("DELETE FROM result_filter_views WHERE view_id=?", (view_id,))
                self._spool.commit()
            except Exception:
                pass
            return {
                "ok": False,
                "error": safe_db_error(exc),
                "result_id": chosen_result_id,
                "query": needle,
            }

    def _sort_result_view_rows(
        self,
        view_id: str,
        column: int,
        *,
        descending: bool = False,
    ) -> None:
        """Sort a disk-backed view without materializing all row values in Python memory.

        Keys are computed in bounded batches and stored in SQLite. Numeric values use a
        DECIMAL collation so integers, decimal strings, and large numeric values keep the
        same numeric-aware semantics as ResultsFilterProxyModel without float precision
        loss. NULLs stay at the bottom in either direction, and equal keys retain the
        incoming view order.
        """
        if self._spool is None:
            raise RuntimeError("The local result cache is no longer available.")
        self._spool.create_collation("DECIMAL", _decimal_sort_collation)
        meta = self._spool.execute(
            "SELECT result_id, row_count FROM result_filter_views WHERE view_id=?",
            (view_id,),
        ).fetchone()
        if meta is None:
            raise ValueError("This result view has expired. Apply the view again.")
        result_id = str(meta[0])
        expected_rows = max(0, int(meta[1] or 0))
        column_index = int(column)
        self._spool.execute(
            "DELETE FROM result_view_sort_keys WHERE view_id=?",
            (view_id,),
        )
        cursor = self._spool.execute(
            "SELECT v.view_idx, v.source_idx, r.values_json "
            "FROM result_filter_view_rows AS v "
            "JOIN result_rows AS r ON r.result_id=? AND r.row_idx=v.source_idx "
            "WHERE v.view_id=? ORDER BY v.view_idx",
            (result_id, view_id),
        )
        scanned = 0
        while True:
            batch = cursor.fetchmany(RESULT_PAGE_ROWS)
            if not batch:
                break
            keys = []
            for ordinal, source_idx, values_json in batch:
                values = json.loads(values_json)
                if not isinstance(values, list):
                    raise ValueError("A cached result row is not a JSON array.")
                value = values[column_index] if column_index < len(values) else None
                if value is None:
                    null_rank, type_rank, numeric_key, text_key = 1, 0, "", ""
                else:
                    number = None
                    try:
                        candidate = Decimal(str(value))
                        if candidate.is_finite():
                            number = candidate
                    except (InvalidOperation, TypeError, ValueError):
                        number = None
                    if number is not None:
                        null_rank, type_rank = 0, 0
                        numeric_key, text_key = str(number), ""
                    else:
                        null_rank, type_rank = 0, 1
                        numeric_key, text_key = "", str(value).casefold()
                keys.append((
                    view_id, int(ordinal), int(source_idx), null_rank,
                    type_rank, numeric_key, text_key,
                ))
            if keys:
                self._spool.executemany(
                    "INSERT INTO result_view_sort_keys"
                    "(view_id,ordinal,source_idx,null_rank,type_rank,numeric_key,text_key) "
                    "VALUES(?,?,?,?,?,?,?)",
                    keys,
                )
            scanned += len(batch)
            if scanned and scanned % 5000 < len(batch):
                self._report_activity(
                    f"Preparing full-result sort · indexed {scanned:,} of {expected_rows:,} row(s)…"
                )

        if scanned != expected_rows:
            raise ValueError(
                "The result view changed while it was being sorted. Please sort it again."
            )

        self._spool.execute(
            "DELETE FROM result_filter_view_rows WHERE view_id=?",
            (view_id,),
        )
        direction = "DESC" if descending else "ASC"
        ordered = self._spool.execute(
            "SELECT source_idx FROM result_view_sort_keys WHERE view_id=? "
            "ORDER BY null_rank ASC, type_rank " + direction
            + ", numeric_key COLLATE DECIMAL " + direction
            + ", text_key COLLATE BINARY " + direction
            + ", ordinal ASC",
            (view_id,),
        )
        next_index = 0
        while True:
            batch = ordered.fetchmany(RESULT_PAGE_ROWS)
            if not batch:
                break
            mappings = [
                (view_id, next_index + index, int(row[0]))
                for index, row in enumerate(batch)
            ]
            self._spool.executemany(
                "INSERT INTO result_filter_view_rows(view_id,view_idx,source_idx) VALUES(?,?,?)",
                mappings,
            )
            next_index += len(mappings)
        self._spool.execute(
            "DELETE FROM result_view_sort_keys WHERE view_id=?",
            (view_id,),
        )

    def _prepare_result_sort(
        self,
        result_id: str,
        column: Any,
        descending: bool = False,
        limit: Any = RESULT_PAGE_ROWS,
        *,
        base_view_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a globally sorted disk-backed view of a result or an existing view."""
        if self._spool is None:
            return {"ok": False, "error": "The local result cache is no longer available."}
        chosen_result_id = str(result_id or "").strip()
        if not chosen_result_id:
            return {"ok": False, "error": "A result identifier is required for sorting."}
        try:
            column_index = int(column)
        except (TypeError, ValueError, OverflowError):
            column_index = -1
        try:
            page_limit = int(limit or RESULT_PAGE_ROWS)
        except (TypeError, ValueError, OverflowError):
            page_limit = RESULT_PAGE_ROWS
        page_limit = max(1, min(RESULT_PAGE_ROWS, page_limit))
        if chosen_result_id in getattr(self, "_invalid_table_previews", set()):
            return {
                "ok": False,
                "error": "This table preview may be stale after ROLLBACK TO SAVEPOINT. Refresh it before sorting.",
                "result_id": chosen_result_id,
            }
        incomplete_preview = self._incomplete_table_preview_error(chosen_result_id, "sort")
        if incomplete_preview:
            return {"ok": False, "error": incomplete_preview, "result_id": chosen_result_id}

        view_id = uuid.uuid4().hex
        try:
            result_meta = self._spool.execute(
                "SELECT headers, row_count FROM result_meta WHERE result_id=?",
                (chosen_result_id,),
            ).fetchone()
            if result_meta is None:
                return {
                    "ok": False,
                    "error": "This query result has expired. Run the query again.",
                    "result_id": chosen_result_id,
                }
            try:
                headers = json.loads(result_meta[0])
            except (TypeError, json.JSONDecodeError):
                headers = []
            if not 0 <= column_index < len(headers):
                return {
                    "ok": False,
                    "error": "The requested sort column is invalid for this result.",
                    "result_id": chosen_result_id,
                }
            source_row_count = max(0, int(result_meta[1] or 0))
            query = ""
            if base_view_id:
                base_meta = self._spool.execute(
                    "SELECT result_id, query, row_count FROM result_filter_views WHERE view_id=?",
                    (str(base_view_id),),
                ).fetchone()
                if base_meta is None or str(base_meta[0]) != chosen_result_id:
                    return {
                        "ok": False,
                        "error": "The current result view has expired. Apply the filter or sort again.",
                        "result_id": chosen_result_id,
                        "view_id": base_view_id,
                    }
                query = str(base_meta[1] or "")
                view_row_count = max(0, int(base_meta[2] or 0))
            else:
                view_row_count = source_row_count

            self._spool.commit()
            self._spool.execute("BEGIN")
            self._spool.execute(
                "INSERT INTO result_filter_views(view_id,result_id,query,row_count) VALUES(?,?,?,?)",
                (view_id, chosen_result_id, query, view_row_count),
            )
            if base_view_id:
                self._spool.execute(
                    "INSERT INTO result_filter_view_rows(view_id,view_idx,source_idx) "
                    "SELECT ?, view_idx, source_idx FROM result_filter_view_rows "
                    "WHERE view_id=? ORDER BY view_idx",
                    (view_id, str(base_view_id)),
                )
            else:
                self._spool.execute(
                    "INSERT INTO result_filter_view_rows(view_id,view_idx,source_idx) "
                    "SELECT ?, row_idx, row_idx FROM result_rows WHERE result_id=? ORDER BY row_idx",
                    (view_id, chosen_result_id),
                )
            self._sort_result_view_rows(
                view_id, column_index, descending=bool(descending)
            )
            self._spool.commit()
            first_page = self._spool.execute(
                "SELECT r.values_json, v.source_idx "
                "FROM result_filter_view_rows AS v "
                "JOIN result_rows AS r ON r.result_id=? AND r.row_idx=v.source_idx "
                "WHERE v.view_id=? ORDER BY v.view_idx LIMIT ? OFFSET 0",
                (chosen_result_id, view_id, page_limit),
            ).fetchall()
            return {
                "ok": True,
                "result_id": chosen_result_id,
                "view_id": view_id,
                "query": query,
                "offset": 0,
                "rows": [json.loads(value_json) for value_json, _source_idx in first_page],
                "source_offsets": [int(source_idx) for _value_json, source_idx in first_page],
                "row_count": view_row_count,
                "source_row_count": source_row_count,
                "page_size": page_limit,
                "has_more": len(first_page) < view_row_count,
                "sort_column": column_index,
                "sort_descending": bool(descending),
            }
        except Exception as exc:
            try:
                self._spool.rollback()
                self._spool.execute("DELETE FROM result_view_sort_keys WHERE view_id=?", (view_id,))
                self._spool.execute("DELETE FROM result_filter_view_rows WHERE view_id=?", (view_id,))
                self._spool.execute("DELETE FROM result_filter_views WHERE view_id=?", (view_id,))
                self._spool.commit()
            except Exception:
                pass
            return {
                "ok": False,
                "error": safe_db_error(exc),
                "result_id": chosen_result_id,
            }

    def _drop_result_filter(self, view_id: str) -> dict[str, Any]:
        """Remove one temporary disk-backed filter view from the session spool."""
        if self._spool is None:
            return {"ok": False, "error": "The local result cache is no longer available."}
        chosen_view_id = str(view_id or "").strip()
        if not chosen_view_id:
            return {"ok": False, "error": "A filter view identifier is required."}
        try:
            self._spool.execute(
                "DELETE FROM result_view_sort_keys WHERE view_id=?",
                (chosen_view_id,),
            )
            self._spool.execute(
                "DELETE FROM result_filter_view_rows WHERE view_id=?",
                (chosen_view_id,),
            )
            self._spool.execute(
                "DELETE FROM result_filter_views WHERE view_id=?",
                (chosen_view_id,),
            )
            self._spool.commit()
        except Exception as exc:
            return {"ok": False, "error": safe_db_error(exc)}
        return {"ok": True, "view_id": chosen_view_id}

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
        preview_rollback_rows: list[dict[str, Any]] = []
        preview_restore_errors: list[str] = []
        preview_invalidated_result_ids: list[str] = []
        preview_transaction_finalized = False
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
                transaction_open_before = bool(
                    getattr(self._connection, "in_transaction", False)
                )
                transaction_command = _leading_transaction_command(sql)
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

                    transaction_open_after = bool(
                        getattr(self._connection, "in_transaction", False)
                    )
                    if transaction_command == "ROLLBACK_TO":
                        # A savepoint rollback can undo only some work while leaving the
                        # transaction open. We do not have per-savepoint row snapshots, so
                        # invalidate cached table previews instead of claiming their rows
                        # still reflect MySQL. Keep transaction-start undo snapshots for a
                        # possible later full ROLLBACK.
                        preview_invalidated_result_ids.extend(
                            result_id for result_id in self._invalidate_table_previews()
                            if result_id not in preview_invalidated_result_ids
                        )
                    elif self._table_preview_undo and not transaction_open_after:
                        if transaction_command == "ROLLBACK":
                            restored, restore_errors = self._restore_table_preview_undo()
                            preview_rollback_rows.extend(restored)
                            preview_restore_errors.extend(restore_errors)
                        elif transaction_open_before:
                            # COMMIT or a MySQL statement with implicit-commit
                            # semantics ended the transaction. The visible/cache values
                            # are now final and must not later be "rolled back" locally.
                            self._table_preview_undo.clear()
                            preview_transaction_finalized = True
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
                        "preview_rollback_rows": preview_rollback_rows,
                        "preview_restore_errors": preview_restore_errors,
                        "preview_invalidated_result_ids": preview_invalidated_result_ids,
                        "preview_transaction_finalized": preview_transaction_finalized,
                    }
                finally:
                    try:
                        cursor.close()
                    finally:
                        if connection_lost:
                            preview_restore = self._close_connection()
                            preview_rollback_rows.extend(
                                preview_restore.get("preview_rollback_rows", [])
                            )
                            preview_restore_errors.extend(
                                preview_restore.get("preview_restore_errors", [])
                            )
        finally:
            with self._lock:
                self._active_query = False
                self._active_query_task_id = None
        return {
            "ok": True, "results": results,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "transaction_open": bool(getattr(self._connection, "in_transaction", False)),
            "preview_rollback_rows": preview_rollback_rows,
            "preview_restore_errors": preview_restore_errors,
            "preview_invalidated_result_ids": preview_invalidated_result_ids,
            "preview_transaction_finalized": preview_transaction_finalized,
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

    def _inspect_schema_object(
        self, schema: str, table: str, object_type: str = ""
    ) -> dict[str, Any]:
        """Read table/view definition and metadata without executing object SQL."""
        schema = str(schema or "")
        table = str(table or "")
        if not schema or not table:
            return {"ok": False, "error": "A schema and table/view name are required."}
        if self._connection is None:
            return {"ok": False, "error": "Not connected to a MySQL server."}

        warnings: list[str] = []

        def read_rows(query: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
            cursor = self._connection.cursor()
            try:
                if params is None:
                    cursor.execute(query)
                else:
                    cursor.execute(query, params)
                field_names = [str(description[0]) for description in (cursor.description or [])]
                return [
                    dict(zip(field_names, row, strict=False))
                    for row in cursor.fetchall()
                ]
            finally:
                cursor.close()

        def field(record: dict[str, Any], *names: str) -> Any:
            lowered = {str(key).casefold(): value for key, value in record.items()}
            for name in names:
                if name.casefold() in lowered:
                    return lowered[name.casefold()]
            return None

        def text_value(value: Any, *, null: str = "") -> str:
            return null if value is None else str(value)

        def query_failure(section: str, exc: Exception) -> dict[str, Any] | None:
            """Return a terminal connection-loss result, or record an optional metadata warning."""
            detail = safe_db_error(exc)
            if is_connection_lost(exc):
                return {
                    "ok": False,
                    "schema": schema,
                    "table": table,
                    "object_type": object_type,
                    "definition": "",
                    "properties": {},
                    "columns": [],
                    "indexes": [],
                    "constraints": [],
                    "warnings": warnings + [f"{section}: {detail}"],
                    "error": detail,
                    "connection_lost": True,
                }
            warnings.append(f"{section}: {detail}")
            return None

        try:
            properties_rows = read_rows(
                "SELECT TABLE_TYPE, ENGINE, ROW_FORMAT, TABLE_ROWS, DATA_LENGTH, "
                "INDEX_LENGTH, AUTO_INCREMENT, CREATE_TIME, UPDATE_TIME, TABLE_COMMENT "
                "FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                (schema, table),
            )
        except Exception as exc:
            terminal = query_failure("Object properties unavailable", exc)
            if terminal is not None:
                return terminal
            return {
                "ok": False,
                "schema": schema,
                "table": table,
                "object_type": object_type,
                "definition": "",
                "properties": {},
                "columns": [],
                "indexes": [],
                "constraints": [],
                "warnings": warnings,
                "error": (
                    "Could not read this object's metadata. Check the MySQL account's "
                    "metadata permissions and confirm the object still exists."
                ),
            }

        if not properties_rows:
            return {
                "ok": False,
                "schema": schema,
                "table": table,
                "object_type": object_type,
                "definition": "",
                "properties": {},
                "columns": [],
                "indexes": [],
                "constraints": [],
                "warnings": [],
                "error": (
                    f"{safe_identifier(schema)}.{safe_identifier(table)} was not found "
                    "or is no longer visible to this MySQL account."
                ),
            }

        raw_properties = properties_rows[0]
        actual_type = text_value(field(raw_properties, "TABLE_TYPE"), null=object_type or "MySQL object")
        normalized_type = "VIEW" if actual_type.casefold() == "view" else "BASE TABLE"
        properties = {
            "Object type": actual_type,
            "Storage engine": field(raw_properties, "ENGINE"),
            "Row format": field(raw_properties, "ROW_FORMAT"),
            "Estimated rows": field(raw_properties, "TABLE_ROWS"),
            "Data size (bytes)": field(raw_properties, "DATA_LENGTH"),
            "Index size (bytes)": field(raw_properties, "INDEX_LENGTH"),
            "Next auto-increment": field(raw_properties, "AUTO_INCREMENT"),
            "Created": field(raw_properties, "CREATE_TIME"),
            "Last updated": field(raw_properties, "UPDATE_TIME"),
            "Comment": field(raw_properties, "TABLE_COMMENT"),
        }

        definition = ""
        ddl_query = (
            f"SHOW CREATE VIEW {safe_identifier(schema)}.{safe_identifier(table)}"
            if normalized_type == "VIEW"
            else f"SHOW CREATE TABLE {safe_identifier(schema)}.{safe_identifier(table)}"
        )
        try:
            ddl_rows = read_rows(ddl_query)
            if ddl_rows:
                ddl_record = ddl_rows[0]
                ddl_field = next(
                    (
                        key for key in ddl_record
                        if str(key).casefold().startswith("create ")
                    ),
                    None,
                )
                if ddl_field is not None:
                    definition = text_value(ddl_record.get(ddl_field))
                else:
                    values = list(ddl_record.values())
                    definition = text_value(values[1]) if len(values) > 1 else ""
            if not definition:
                warnings.append("Definition: MySQL returned no CREATE statement for this object.")
        except Exception as exc:
            terminal = query_failure("Definition unavailable", exc)
            if terminal is not None:
                return terminal

        columns: list[dict[str, Any]] = []
        try:
            column_rows = read_rows(
                "SELECT ORDINAL_POSITION, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, "
                "COLUMN_DEFAULT, COLUMN_KEY, EXTRA, CHARACTER_SET_NAME, COLLATION_NAME, "
                "COLUMN_COMMENT "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                "ORDER BY ORDINAL_POSITION",
                (schema, table),
            )
            for record in column_rows:
                columns.append({
                    "position": field(record, "ORDINAL_POSITION"),
                    "name": text_value(field(record, "COLUMN_NAME")),
                    "type": text_value(field(record, "COLUMN_TYPE")),
                    "nullable": text_value(field(record, "IS_NULLABLE")),
                    "default": field(record, "COLUMN_DEFAULT"),
                    "key": text_value(field(record, "COLUMN_KEY")),
                    "extra": text_value(field(record, "EXTRA")),
                    "charset": text_value(field(record, "CHARACTER_SET_NAME")),
                    "collation": text_value(field(record, "COLLATION_NAME")),
                    "comment": text_value(field(record, "COLUMN_COMMENT")),
                })
        except Exception as exc:
            terminal = query_failure("Column metadata unavailable", exc)
            if terminal is not None:
                return terminal

        indexes: list[dict[str, Any]] = []
        try:
            index_rows = read_rows(
                f"SHOW INDEX FROM {safe_identifier(table)} FROM {safe_identifier(schema)}"
            )
            for record in index_rows:
                non_unique = field(record, "Non_unique")
                try:
                    unique = int(non_unique) == 0
                except (TypeError, ValueError, OverflowError):
                    unique = False
                indexes.append({
                    "name": text_value(field(record, "Key_name")),
                    "unique": "Yes" if unique else "No",
                    "position": field(record, "Seq_in_index"),
                    "column": field(record, "Column_name"),
                    "expression": field(record, "Expression"),
                    "collation": field(record, "Collation"),
                    "cardinality": field(record, "Cardinality"),
                    "prefix_length": field(record, "Sub_part"),
                    "type": text_value(field(record, "Index_type")),
                    "visible": text_value(
                        field(record, "Visible"),
                        null="Not reported by this MySQL version",
                    ),
                    "comment": text_value(field(record, "Index_comment", "Comment")),
                })
        except Exception as exc:
            terminal = query_failure("Index metadata unavailable", exc)
            if terminal is not None:
                return terminal

        constraints: list[dict[str, Any]] = []
        try:
            constraint_rows = read_rows(
                "SELECT tc.CONSTRAINT_NAME, tc.CONSTRAINT_TYPE, kcu.COLUMN_NAME, "
                "kcu.ORDINAL_POSITION, kcu.REFERENCED_TABLE_SCHEMA, "
                "kcu.REFERENCED_TABLE_NAME, kcu.REFERENCED_COLUMN_NAME "
                "FROM information_schema.TABLE_CONSTRAINTS AS tc "
                "LEFT JOIN information_schema.KEY_COLUMN_USAGE AS kcu "
                "ON tc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA "
                "AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA "
                "AND tc.TABLE_NAME = kcu.TABLE_NAME "
                "AND tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME "
                "WHERE tc.TABLE_SCHEMA = %s AND tc.TABLE_NAME = %s "
                "ORDER BY tc.CONSTRAINT_NAME, kcu.ORDINAL_POSITION",
                (schema, table),
            )
            for record in constraint_rows:
                constraints.append({
                    "name": text_value(field(record, "CONSTRAINT_NAME")),
                    "type": text_value(field(record, "CONSTRAINT_TYPE")),
                    "column": text_value(field(record, "COLUMN_NAME")),
                    "position": field(record, "ORDINAL_POSITION"),
                    "referenced_schema": text_value(field(record, "REFERENCED_TABLE_SCHEMA")),
                    "referenced_table": text_value(field(record, "REFERENCED_TABLE_NAME")),
                    "referenced_column": text_value(field(record, "REFERENCED_COLUMN_NAME")),
                })
        except Exception as exc:
            terminal = query_failure("Constraint metadata unavailable", exc)
            if terminal is not None:
                return terminal

        return {
            "ok": True,
            "schema": schema,
            "table": table,
            "object_type": actual_type,
            "definition": definition,
            "properties": properties,
            "columns": columns,
            "indexes": indexes,
            "constraints": constraints,
            "warnings": warnings,
        }

    def _preview_table(self, schema: str, table: str) -> dict[str, Any]:
        if self._connection is None:
            return {"ok": False, "error": "Not connected to a MySQL server."}
        cursor = self._connection.cursor()
        try:
            cursor.execute(f"SELECT * FROM {safe_identifier(schema)}.{safe_identifier(table)} LIMIT 1000")
            headers = [str(desc[0]) for desc in (cursor.description or [])]
            raw_rows = [tuple(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

        rows = [[json_value(value) for value in row] for row in raw_rows]
        result_id = uuid.uuid4().hex
        statement = f"Preview {schema}.{table}"
        self._save_rows(result_id, headers, statement, rows)
        table_edit = self._table_preview_edit_context(schema, table, headers, raw_rows)
        return {"ok": True, "results": [{
            "result_id": result_id, "headers": headers, "rows": rows, "row_count": len(rows),
            "preview_truncated": False, "kind": "rows", "duration_ms": 0,
            "table_edit": table_edit,
        }]}

    def _table_preview_edit_context(
        self, schema: str, table: str, headers: list[str], raw_rows: list[tuple[Any, ...]]
    ) -> dict[str, Any]:
        """Describe only edits that can be safely targeted through a live primary key."""
        disabled = {
            "enabled": False,
            "schema": schema,
            "table": table,
            "session_token": self._session_token,
            "reason": "This preview is read-only because MySQL could not verify an eligible primary-key table.",
        }
        if self._connection is None:
            disabled["reason"] = "The MySQL connection is no longer available."
            return disabled

        cursor = None
        try:
            cursor = self._connection.cursor()
            cursor.execute(
                "SELECT TABLE_TYPE, ENGINE FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                (schema, table),
            )
            table_row = cursor.fetchone()
            if not table_row:
                disabled["reason"] = "The table metadata is no longer available; refresh the schema."
                return disabled
            if str(table_row[0] or "").casefold() != "base table":
                disabled["reason"] = "Only base tables can be edited; views and other objects stay read-only."
                return disabled
            engine = str(table_row[1] or "").strip()
            if not engine:
                disabled["reason"] = "The table storage engine could not be verified; keep this preview read-only."
                return disabled
            cursor.execute(
                "SELECT TRANSACTIONS FROM information_schema.ENGINES WHERE ENGINE = %s",
                (engine,),
            )
            engine_row = cursor.fetchone()
            if not engine_row or str(engine_row[0] or "").casefold() != "yes":
                disabled["reason"] = (
                    "Only tables using a transactional MySQL storage engine can be edited; "
                    "this engine cannot guarantee Rollback."
                )
                return disabled

            cursor.execute(
                "SELECT COLUMN_NAME, DATA_TYPE, EXTRA FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
                (schema, table),
            )
            column_rows = cursor.fetchall()
            column_metadata = {
                str(row[0]).casefold(): {
                    "name": str(row[0]),
                    "data_type": str(row[1] or "").casefold(),
                    "extra": str(row[2] or "").casefold(),
                }
                for row in column_rows
            }
            current_columns = [str(row[0]) for row in column_rows]
            if [column.casefold() for column in headers] != [
                column.casefold() for column in current_columns
            ]:
                disabled["reason"] = "The table columns changed while the preview loaded; refresh before editing."
                return disabled

            cursor.execute(
                "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                "AND CONSTRAINT_NAME = 'PRIMARY' ORDER BY ORDINAL_POSITION",
                (schema, table),
            )
            primary_key_columns = [str(row[0]) for row in cursor.fetchall()]
            if not primary_key_columns:
                disabled["reason"] = "The table has no primary key, so rows cannot be targeted safely for editing."
                return disabled

            header_index = {
                column.casefold(): index for index, column in enumerate(headers)
            }
            if any(column.casefold() not in header_index for column in primary_key_columns):
                disabled["reason"] = "The primary key is not present in the table preview."
                return disabled
            primary_key_indices = [header_index[column.casefold()] for column in primary_key_columns]
            key_names = {column.casefold() for column in primary_key_columns}
            unsupported_types = {
                "binary", "varbinary", "tinyblob", "blob", "mediumblob", "longblob",
                "bit", "geometry", "point", "linestring", "polygon", "multipoint",
                "multilinestring", "multipolygon", "geometrycollection",
            }
            editable_column_indices = []
            for index, column_name in enumerate(headers):
                info = column_metadata.get(column_name.casefold())
                if info is None or column_name.casefold() in key_names:
                    continue
                extra = info["extra"]
                if "auto_increment" in extra or "generated" in extra:
                    continue
                if info["data_type"] in unsupported_types:
                    continue
                editable_column_indices.append(index)

            if not editable_column_indices:
                disabled["reason"] = (
                    "The table has no safely editable non-primary-key columns in the current preview."
                )
                return disabled

            row_keys = [
                [row[index] for index in primary_key_indices]
                for row in raw_rows
            ]
            original_values = {
                str(index): [row[index] for row in raw_rows]
                for index in editable_column_indices
            }
            return {
                "enabled": True,
                "schema": schema,
                "table": table,
                "session_token": self._session_token,
                "primary_key_columns": primary_key_columns,
                "primary_key_indices": primary_key_indices,
                "row_keys": row_keys,
                "original_values": original_values,
                "editable_column_indices": editable_column_indices,
                "reason": "",
            }
        except Exception as exc:
            disabled["reason"] = (
                "The preview remains read-only because MySQL metadata could not be verified: "
                + safe_db_error(exc)
            )
            return disabled
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass

    @staticmethod
    def _same_cell_value(left: Any, right: Any) -> bool:
        if left is None or right is None:
            return left is None and right is None
        if left == right:
            return True
        return str(left) == str(right)

    def _update_table_cell(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Update one non-key cell from a verified Schema Explorer preview.

        The worker revalidates the table, columns, primary key and local result-spool
        identity. Values are bound parameters; only server-confirmed identifiers are
        quoted into SQL. The operation never commits or rolls back the user's session.
        """
        connection = self._connection
        result_id = str(payload.get("result_id", "") or "")
        if result_id in getattr(self, "_invalid_table_previews", set()):
            return {
                "ok": False,
                "error": "This table preview may be stale after ROLLBACK TO SAVEPOINT. Refresh the table before editing.",
                "transaction_open": bool(getattr(connection, "in_transaction", False))
                if connection is not None else False,
            }
        if connection is None:
            return {"ok": False, "error": "Not connected to a MySQL server."}
        preview_session_token = str(payload.get("session_token", "") or "")
        if not preview_session_token or preview_session_token != self._session_token:
            return {
                "ok": False,
                "error": "The MySQL connection changed after this preview was loaded. Refresh the table before editing.",
            }
        if self._spool is None:
            return {"ok": False, "error": "The local table-preview cache is no longer available."}

        cursor = None
        update_applied = False
        try:
            schema = str(payload.get("schema", "") or "")
            table = str(payload.get("table", "") or "")
            column_name = str(payload.get("column_name", "") or "")
            try:
                row_index = int(payload.get("row_index"))
                column_index = int(payload.get("column_index"))
            except (TypeError, ValueError, OverflowError):
                return {"ok": False, "error": "The selected preview cell is invalid."}
            if not schema or not table or not column_name or row_index < 0 or column_index < 0:
                return {"ok": False, "error": "A schema, table, column and valid preview cell are required."}

            meta = self._spool.execute(
                "SELECT headers, statement FROM result_meta WHERE result_id = ?",
                (result_id,),
            ).fetchone()
            if meta is None or str(meta[1]) != f"Preview {schema}.{table}":
                return {
                    "ok": False,
                    "error": "Only cells from the current Schema Explorer table preview can be edited.",
                }
            headers = json.loads(meta[0])
            cached_row = self._spool.execute(
                "SELECT values_json FROM result_rows WHERE result_id = ? AND row_idx = ?",
                (result_id, row_index),
            ).fetchone()
            if cached_row is None:
                return {"ok": False, "error": "The selected preview row is no longer available; refresh it."}
            cached_values = json.loads(cached_row[0])
            if (
                column_index >= len(headers)
                or column_index >= len(cached_values)
                or str(headers[column_index]) != column_name
            ):
                return {"ok": False, "error": "The selected cell no longer matches the preview; refresh it."}

            primary_key_columns = payload.get("primary_key_columns")
            primary_key_values = payload.get("primary_key_values")
            if (
                not isinstance(primary_key_columns, list)
                or not primary_key_columns
                or not isinstance(primary_key_values, (list, tuple))
                or len(primary_key_columns) != len(primary_key_values)
                or any(value is None for value in primary_key_values)
            ):
                return {"ok": False, "error": "The primary-key row identity is incomplete."}
            expected_old = payload.get("expected_old")
            new_value = payload.get("new_value")
            if json_value(expected_old) != cached_values[column_index]:
                return {
                    "ok": False,
                    "error": "The preview cell changed locally. Refresh the table preview before editing.",
                }

            cursor = connection.cursor()
            cursor.execute(
                "SELECT TABLE_TYPE, ENGINE FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                (schema, table),
            )
            table_info = cursor.fetchone()
            if not table_info or str(table_info[0] or "").casefold() != "base table":
                return {"ok": False, "error": "The target is no longer a base table; the cell was not updated."}
            engine = str(table_info[1] or "").strip()
            if not engine:
                return {
                    "ok": False,
                    "error": "The table storage engine could not be verified; the cell was not updated.",
                }
            cursor.execute(
                "SELECT TRANSACTIONS FROM information_schema.ENGINES WHERE ENGINE = %s",
                (engine,),
            )
            engine_row = cursor.fetchone()
            if not engine_row or str(engine_row[0] or "").casefold() != "yes":
                return {
                    "ok": False,
                    "error": "This MySQL storage engine cannot guarantee Rollback; the cell was not updated.",
                }

            cursor.execute(
                "SELECT COLUMN_NAME, DATA_TYPE, EXTRA FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
                (schema, table),
            )
            column_rows = cursor.fetchall()
            current_columns = [str(row[0]) for row in column_rows]
            if [name.casefold() for name in current_columns] != [
                str(name).casefold() for name in headers
            ]:
                return {
                    "ok": False,
                    "error": "The table structure changed since the preview. Refresh before editing.",
                }
            column_lookup = {
                str(row[0]).casefold(): {
                    "name": str(row[0]),
                    "data_type": str(row[1] or "").casefold(),
                    "extra": str(row[2] or "").casefold(),
                }
                for row in column_rows
            }
            column_info = column_lookup.get(column_name.casefold())
            if column_info is None:
                return {"ok": False, "error": "The target column no longer exists."}

            cursor.execute(
                "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                "AND CONSTRAINT_NAME = 'PRIMARY' ORDER BY ORDINAL_POSITION",
                (schema, table),
            )
            actual_primary_key = [str(row[0]) for row in cursor.fetchall()]
            if [name.casefold() for name in actual_primary_key] != [
                str(name).casefold() for name in primary_key_columns
            ]:
                return {
                    "ok": False,
                    "error": "The table primary key changed since the preview. Refresh before editing.",
                }
            if column_name.casefold() in {name.casefold() for name in actual_primary_key}:
                return {"ok": False, "error": "Primary-key cells are read-only in this editor."}
            extra = column_info["extra"]
            if "auto_increment" in extra or "generated" in extra:
                return {"ok": False, "error": "Generated columns are read-only in this editor."}
            if column_info["data_type"] in {
                "binary", "varbinary", "tinyblob", "blob", "mediumblob", "longblob",
                "bit", "geometry", "point", "linestring", "polygon", "multipoint",
                "multilinestring", "multipolygon", "geometrycollection",
            }:
                return {"ok": False, "error": "Binary and spatial columns are read-only in this editor."}

            header_index = {name.casefold(): index for index, name in enumerate(headers)}
            try:
                primary_key_indices = [header_index[name.casefold()] for name in actual_primary_key]
            except KeyError:
                return {"ok": False, "error": "The primary key is not present in the cached preview."}
            if any(
                json_value(primary_key_values[index]) != cached_values[primary_key_indices[index]]
                for index in range(len(primary_key_values))
            ):
                return {
                    "ok": False,
                    "error": "The row identity no longer matches the cached preview. Refresh before editing.",
                }

            qualified_table = f"{safe_identifier(schema)}.{safe_identifier(table)}"
            safe_column = safe_identifier(column_name)
            where_keys = " AND ".join(
                f"{safe_identifier(name)} = %s" for name in actual_primary_key
            )
            # Lock and re-read the target row before changing it. This both prevents a
            # concurrent writer from changing another column during a manual transaction
            # and avoids accepting stale preview data as the rollback baseline.
            cursor.execute(
                f"SELECT * FROM {qualified_table} WHERE {where_keys} FOR UPDATE",
                tuple(primary_key_values),
            )
            locked_row = cursor.fetchone()
            if locked_row is None:
                return {
                    "ok": False,
                    "error": "The row no longer exists. Refresh the table preview.",
                    "transaction_open": bool(getattr(connection, "in_transaction", False)),
                }
            if len(locked_row) != len(cached_values):
                return {
                    "ok": False,
                    "error": "The row shape changed since the preview. Refresh the table preview.",
                    "transaction_open": bool(getattr(connection, "in_transaction", False)),
                }
            if not self._same_cell_value(locked_row[column_index], expected_old):
                return {
                    "ok": False,
                    "error": "The cell changed on MySQL since this preview. Refresh and try again.",
                    "transaction_open": bool(getattr(connection, "in_transaction", False)),
                }
            if [json_value(value) for value in locked_row] != cached_values:
                return {
                    "ok": False,
                    "error": "Another column in this row changed on MySQL since the preview. Refresh before editing.",
                    "transaction_open": bool(getattr(connection, "in_transaction", False)),
                }

            cursor.execute(
                f"UPDATE {qualified_table} SET {safe_column} = %s "
                f"WHERE {where_keys} AND {safe_column} <=> %s",
                tuple([new_value, *primary_key_values, expected_old]),
            )
            affected = int(cursor.rowcount or 0)
            update_applied = affected > 0
            transaction_open = bool(getattr(connection, "in_transaction", False))
            if update_applied and transaction_open:
                # Keep the first value seen in this transaction: multiple inline
                # edits to the same cell must all roll back to the original preview.
                self._table_preview_undo.setdefault(
                    (result_id, row_index), list(cached_values)
                )
            if affected > 1:
                return {
                    "ok": False,
                    "error": "MySQL updated more than one row for a primary-key edit. Inspect the active transaction and use Rollback if those changes were not intended.",
                    "update_applied": True,
                    "transaction_open": bool(getattr(connection, "in_transaction", False)),
                }

            cursor.execute(f"SELECT * FROM {qualified_table} WHERE {where_keys}", tuple(primary_key_values))
            current_row = cursor.fetchone()
            if current_row is None:
                return {
                    "ok": False,
                    "error": "The row no longer exists. Refresh the table preview.",
                    "update_applied": update_applied,
                    "transaction_open": bool(getattr(connection, "in_transaction", False)),
                }
            if affected == 0:
                current_value = current_row[column_index]
                if self._same_cell_value(current_value, new_value):
                    no_change = True
                elif not self._same_cell_value(current_value, expected_old):
                    return {
                        "ok": False,
                        "error": "The cell changed on MySQL since this preview. Refresh and try again.",
                        "transaction_open": bool(getattr(connection, "in_transaction", False)),
                    }
                else:
                    return {
                        "ok": False,
                        "error": "MySQL reported no changed row. Refresh the preview before retrying.",
                        "transaction_open": bool(getattr(connection, "in_transaction", False)),
                    }
            else:
                no_change = False

            display_row = [json_value(value) for value in current_row]
            cursor.close()
            cursor = None
            cache_update = self._spool.execute(
                "UPDATE result_rows SET values_json = ? WHERE result_id = ? AND row_idx = ?",
                (json.dumps(display_row, ensure_ascii=False), result_id, row_index),
            )
            if cache_update.rowcount != 1:
                return {
                    "ok": False,
                    "error": "MySQL accepted the update, but the local preview cache could not be refreshed. Re-preview the table.",
                    "update_applied": update_applied,
                    "transaction_open": bool(getattr(connection, "in_transaction", False)),
                }
            self._spool.commit()
            return {
                "ok": True,
                "result_id": result_id,
                "row_index": row_index,
                "column_index": column_index,
                "column_name": column_name,
                "display_row": display_row,
                "raw_row": list(current_row),
                "no_change": no_change,
                "transaction_open": bool(getattr(connection, "in_transaction", False)),
                "message": "Cell value updated in the active MySQL session.",
            }
        except Exception as exc:
            connection_lost = is_connection_lost(exc)
            preview_restore = {
                "preview_rollback_rows": [],
                "preview_restore_errors": [],
            }
            if connection_lost:
                preview_restore = self._close_connection()
            try:
                transaction_open = bool(getattr(connection, "in_transaction", False))
            except Exception:
                transaction_open = False
            return {
                "ok": False,
                "error": safe_db_error(exc),
                "update_applied": update_applied,
                "transaction_open": transaction_open,
                "connection_lost": connection_lost,
                **preview_restore,
            }
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass


    def _export_csv(self, result_id: str, path: str) -> dict[str, Any]:
        if result_id in getattr(self, "_invalid_table_previews", set()):
            return {
                "ok": False,
                "error": "This table preview may be stale after ROLLBACK TO SAVEPOINT. Refresh the table before exporting.",
            }
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

        return {"ok": True, "path": str(destination), "row_count": count, "format": "csv"}

    def _export_json(self, result_id: str, path: str) -> dict[str, Any]:
        """Atomically export every spooled result row as a JSON array of row objects."""
        return self._export_structured(result_id, path, export_format="json")

    def _export_ndjson(self, result_id: str, path: str) -> dict[str, Any]:
        """Atomically export every spooled result row as newline-delimited JSON objects."""
        return self._export_structured(result_id, path, export_format="ndjson")

    def _export_structured(
        self, result_id: str, path: str, *, export_format: str
    ) -> dict[str, Any]:
        if export_format not in {"json", "ndjson"}:
            return {"ok": False, "error": "The requested structured export format is unsupported."}
        if result_id in getattr(self, "_invalid_table_previews", set()):
            return {
                "ok": False,
                "error": (
                    "This table preview may be stale after ROLLBACK TO SAVEPOINT. "
                    "Refresh the table before exporting."
                ),
            }
        if self._spool is None:
            return {"ok": False, "error": "The result cache is no longer available."}
        meta = self._spool.execute(
            "SELECT headers FROM result_meta WHERE result_id=?",
            (result_id,),
        ).fetchone()
        if not meta:
            return {"ok": False, "error": "This query result has expired. Run the query again."}
        headers = json.loads(meta[0])
        if not isinstance(headers, list):
            return {"ok": False, "error": "The cached result column metadata is invalid."}
        column_names = unique_json_export_headers(headers)

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        count = 0
        next_progress_row = 5000
        label = "JSON" if export_format == "json" else "NDJSON"

        def report_activity(message: str) -> None:
            reporter = getattr(self, "_report_activity", None)
            if callable(reporter):
                reporter(message)
            else:
                activity = getattr(self, "activity", None)
                if activity is not None:
                    activity.emit(message)

        report_activity(f"Exporting {label} rows…")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                if export_format == "json":
                    handle.write("[")
                cursor = self._spool.execute(
                    "SELECT row_idx, values_json FROM result_rows "
                    "WHERE result_id=? ORDER BY row_idx",
                    (result_id,),
                )
                for row_idx, value_json in cursor:
                    values = json.loads(value_json)
                    if not isinstance(values, list) or len(values) != len(column_names):
                        raise ValueError(
                            f"Cached result row {int(row_idx) + 1:,} does not match its column metadata."
                        )
                    record = dict(zip(column_names, values, strict=True))
                    if export_format == "json":
                        handle.write("\n" if count == 0 else ",\n")
                        json.dump(
                            record,
                            handle,
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                        )
                    else:
                        handle.write(json.dumps(
                            record,
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                        ))
                        handle.write("\n")
                    count += 1
                    if count >= next_progress_row:
                        report_activity(f"Exported {count:,} {label} row(s)…")
                        next_progress_row = ((count // 5000) + 1) * 5000
                if export_format == "json":
                    if count:
                        handle.write("\n")
                    handle.write("]\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return {
            "ok": True,
            "path": str(destination),
            "row_count": count,
            "format": export_format,
        }
