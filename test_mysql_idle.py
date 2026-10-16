"""Focused regression tests for MySQL IDLE's pure parsing and streaming helpers."""
import csv
import json
import importlib
import logging
import os
import time
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from pathlib import Path


# Keep these helper tests runnable on systems where PyMySQL is not installed.
if importlib.util.find_spec("pymysql") is None:
    pymysql_stub = types.ModuleType("pymysql")
    cursors_stub = types.SimpleNamespace(SSCursor=type("SSCursor", (), {}))
    pymysql_stub.cursors = cursors_stub
    pymysql_stub.__version__ = "test-stub"
    pymysql_stub.connect = lambda **kwargs: None
    sys.modules["pymysql"] = pymysql_stub

import mysql_idle


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.offset = 0
        self.description = None
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql):
        sql = sql.strip().lower()
        if sql.startswith("select synthetic"):
            self.description = (("id",), ("payload",))
            self.rows = [(i, b"x" * 1000) for i in range(1100)]
            self.offset = 0
        elif sql.startswith("select database()"):
            self.description = (("DATABASE()",),)
            self.rows = [("demo",)]
            self.offset = 0
        else:
            self.description = None
            self.rowcount = 1
            self.rows = []
            self.offset = 0

    def fetchone(self):
        batch = self.fetchmany(1)
        return batch[0] if batch else None

    def fetchmany(self, size):
        batch = self.rows[self.offset:self.offset + size]
        self.offset += len(batch)
        return batch


class FakeConnection:
    def ping(self, reconnect=False):
        return None

    def thread_id(self):
        return 456

    def cursor(self, cursorclass=None):
        return FakeCursor([])


class SplitSQLTests(unittest.TestCase):
    def test_semicolons_inside_quotes_and_comments(self):
        sql = "SELECT 'a;b'; SELECT \"x;y\"; SELECT `t;z`; -- ; ignore\nSELECT 4;"
        statements, rest = mysql_idle.split_sql(sql)
        self.assertEqual(len(statements), 4)
        self.assertEqual(rest, "")

    def test_doubled_quote_escape(self):
        statements, rest = mysql_idle.split_sql("SELECT 'it''s; fine'; SELECT 2;")
        self.assertEqual(len(statements), 2)
        self.assertEqual(statements[0], "SELECT 'it''s; fine'")
        self.assertEqual(rest, "")

    def test_incomplete_statement_is_preserved(self):
        statements, rest = mysql_idle.split_sql("SELECT 1; SELECT 'unfinished")
        self.assertEqual(statements, ["SELECT 1"])
        self.assertEqual(rest, " SELECT 'unfinished")

    def test_config_save_never_persists_password(self):
        with tempfile.TemporaryDirectory(prefix="mysql_idle_config_test_") as tmp:
            target = Path(tmp) / "settings.json"
            with patch.object(mysql_idle, "CONFIG_PATH", target), patch.object(mysql_idle, "SAVE_HISTORY", False):
                mysql_idle.save_config({
                    "last_connection": {
                        "host": "localhost", "user": "tester", "password": "never-save-me"
                    },
                    "history": ["SELECT 1;"],
                })
            saved = target.read_text(encoding="utf-8")
            self.assertNotIn("never-save-me", saved)
            self.assertNotIn('"password"', saved)
            self.assertNotIn('"history"', saved)

    def test_legacy_settings_are_migrated_and_secret_removed(self):
        with tempfile.TemporaryDirectory(prefix="mysql_idle_migrate_test_") as tmp:
            root = Path(tmp)
            legacy = root / "old.json"
            target = root / "app" / "settings.json"
            legacy.write_text(json.dumps({
                "last_connection": {
                    "host": "localhost", "user": "tester", "password": "legacy-secret",
                    "tls_verify": True,
                },
                "history": ["SELECT 1;"],
            }), encoding="utf-8")
            with patch.object(mysql_idle, "CONFIG_PATH", target), patch.object(mysql_idle, "LEGACY_CONFIG_PATH", legacy), patch.object(mysql_idle, "SAVE_HISTORY", False):
                cfg = mysql_idle.load_config()
            self.assertTrue(target.is_file())
            self.assertFalse(legacy.exists())
            self.assertEqual(cfg["last_connection"]["user"], "tester")
            self.assertNotIn("password", cfg["last_connection"])
            self.assertFalse(cfg["last_connection"]["tls_verify"])
            self.assertEqual(cfg["last_connection"]["tls_verify_setting_version"], 3)
            self.assertNotIn("history", cfg)
            migrated = target.read_text(encoding="utf-8")
            self.assertNotIn("legacy-secret", migrated)
            self.assertNotIn('"history"', migrated)


    def test_existing_tls_preference_migrates_once_without_overwriting_new_user_choice(self):
        with tempfile.TemporaryDirectory(prefix="mysql_idle_tls_migrate_") as tmp:
            target = Path(tmp) / "settings.json"
            legacy = Path(tmp) / "missing-legacy-settings.json"
            target.write_text(json.dumps({
                "last_connection": {
                    "host": "localhost", "user": "tester", "tls_verify": True,
                    "tls_verify_setting_version": 2,
                }
            }), encoding="utf-8")
            with patch.object(mysql_idle, "CONFIG_PATH", target), patch.object(mysql_idle, "LEGACY_CONFIG_PATH", legacy), patch.object(mysql_idle, "SAVE_HISTORY", False):
                migrated = mysql_idle.load_config()
                self.assertFalse(migrated["last_connection"]["tls_verify"])
                self.assertEqual(migrated["last_connection"]["tls_verify_setting_version"], 3)

                # A new explicit preference is preserved after the one-time migration.
                migrated["last_connection"]["tls_verify"] = True
                mysql_idle.save_config(migrated)
                saved_again = mysql_idle.load_config()
            self.assertTrue(saved_again["last_connection"]["tls_verify"])

    def test_v2_saved_verified_tls_choice_is_reset_after_upgrade(self):
        with tempfile.TemporaryDirectory(prefix="mysql_idle_tls_v2_upgrade_") as tmp:
            target = Path(tmp) / "settings.json"
            target.write_text(json.dumps({
                "last_connection": {
                    "host": "localhost", "port": 3306, "user": "root",
                    "tls_verify": True, "tls_verify_setting_version": 2,
                }
            }), encoding="utf-8")
            legacy = Path(tmp) / "missing-legacy-settings.json"
            with patch.object(mysql_idle, "CONFIG_PATH", target), patch.object(mysql_idle, "LEGACY_CONFIG_PATH", legacy), patch.object(mysql_idle, "SAVE_HISTORY", False):
                migrated = mysql_idle.load_config()
                self.assertFalse(migrated["last_connection"]["tls_verify"])
                self.assertEqual(migrated["last_connection"]["tls_verify_setting_version"], 3)
                saved = json.loads(target.read_text(encoding="utf-8"))
                self.assertFalse(saved["last_connection"]["tls_verify"])
                self.assertEqual(saved["last_connection"]["tls_verify_setting_version"], 3)

    def test_history_can_only_be_persisted_when_explicitly_enabled(self):
        with tempfile.TemporaryDirectory(prefix="mysql_idle_history_optin_") as tmp:
            target = Path(tmp) / "settings.json"
            with patch.object(mysql_idle, "CONFIG_PATH", target), patch.object(mysql_idle, "SAVE_HISTORY", True):
                mysql_idle.save_config({"history": ["SELECT 1;", "SELECT 'private literal';"]})
            saved = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(saved["history"], ["SELECT 1;", "SELECT 'private literal';"])


class ConnectionSecurityTests(unittest.TestCase):
    def test_mysql_connect_requires_verified_tls_and_forwards_ca_path(self):
        events = __import__("queue").Queue()
        worker = mysql_idle.DatabaseWorker.__new__(mysql_idle.DatabaseWorker)
        worker.events = events
        worker.conn = None
        worker.conn_info = {}
        worker.current_db = None
        worker.identifiers = set()
        worker._credentials = None
        worker.output = lambda *args, **kwargs: None
        worker._refresh_state = lambda: None
        fake_connection = types.SimpleNamespace(
            get_server_info=lambda: "8.0-test",
            close=lambda: None,
        )
        captured = {}
        with tempfile.TemporaryDirectory(prefix="mysql_idle_tls_") as tmp:
            ca_path = Path(tmp) / "mysql-ca.pem"
            ca_path.write_text("test-only CA placeholder", encoding="ascii")
            with patch.object(mysql_idle.pymysql, "connect", side_effect=lambda **kwargs: (captured.update(kwargs) or fake_connection)):
                worker._connect({
                    "host": "db.example.test",
                    "port": 3306,
                    "user": "tester",
                    "password": "test-password",
                    "database": "sample",
                    "ssl_ca": str(ca_path),
                    "tls_verify": True,
                    "autocommit": True,
                })
        self.assertTrue(captured["ssl_verify_cert"])
        self.assertTrue(captured["ssl_verify_identity"])
        self.assertEqual(captured["ssl_ca"], str(ca_path))
        self.assertTrue(worker._credentials["tls_verify"])
        self.assertEqual(worker._credentials["ssl_ca"], str(ca_path))

    def test_mysql_connect_defaults_to_certificate_optional_tls_without_ca(self):
        events = __import__("queue").Queue()
        worker = mysql_idle.DatabaseWorker.__new__(mysql_idle.DatabaseWorker)
        worker.events = events
        worker.conn = None
        worker.conn_info = {}
        worker.current_db = None
        worker.identifiers = set()
        worker._credentials = None
        worker.output = lambda *args, **kwargs: None
        worker._refresh_state = lambda: None
        fake_connection = types.SimpleNamespace(
            get_server_info=lambda: "8.0-test",
            close=lambda: None,
        )
        captured = {}
        with patch.object(mysql_idle.pymysql, "connect", side_effect=lambda **kwargs: (captured.update(kwargs) or fake_connection)):
            worker._connect({
                "host": "localhost",
                "port": 3306,
                "user": "tester",
                "password": "test-password",
                "database": None,
                # A stale optional CA path must not block the default mode.
                "ssl_ca": "/path/that/does/not/exist/mysql-ca.pem",
                "autocommit": True,
            })
        self.assertNotIn("ssl_verify_cert", captured)
        self.assertNotIn("ssl_verify_identity", captured)
        self.assertNotIn("ssl_ca", captured)
        self.assertFalse(worker._credentials["tls_verify"])


class RuntimeBootstrapTests(unittest.TestCase):
    def test_runtime_setup_creates_per_user_log_directory(self):
        logger = logging.getLogger()
        original_handlers = list(logger.handlers)
        with tempfile.TemporaryDirectory(prefix="mysql_idle_bootstrap_test_") as tmp:
            root = Path(tmp)
            try:
                with patch.object(mysql_idle, "APP_DATA_DIR", root / "app"), patch.object(mysql_idle, "LOG_DIR", root / "app" / "logs"), patch.object(mysql_idle.tempfile, "gettempdir", return_value=tmp):
                    mysql_idle.setup_runtime_environment()
                    self.assertTrue((root / "app" / "logs" / "application.log").is_file())
                    self.assertIn("Application version:", mysql_idle.runtime_diagnostics())
                    live = root / "mysql_idle_mobile_live_test"
                    stale = root / "mysql_idle_mobile_stale_test"
                    live.mkdir()
                    (live / ".owner_pid").write_text(str(os.getpid()), encoding="ascii")
                    stale.mkdir()
                    os.utime(live, (time.time() - 8 * 86400, time.time() - 8 * 86400))
                    os.utime(stale, (time.time() - 8 * 86400, time.time() - 8 * 86400))
                    mysql_idle.setup_runtime_environment()
                    self.assertTrue(live.exists(), "an active process's spool must never be deleted")
                    self.assertFalse(stale.exists(), "old unowned spools should be cleaned up")
            finally:
                # Close the test-created file handler before TemporaryDirectory cleanup (Windows).
                for handler in list(logger.handlers):
                    if handler not in original_handlers:
                        logger.removeHandler(handler)
                        handler.close()


class ResultStreamingTests(unittest.TestCase):
    def test_result_is_spooled_and_preview_is_bounded(self):
        events = __import__("queue").Queue()
        worker = mysql_idle.DatabaseWorker.__new__(mysql_idle.DatabaseWorker)
        worker.events = events
        worker.conn = FakeConnection()
        worker.conn_info = {"host": "localhost", "port": 3306, "user": "tester"}
        worker.current_db = "demo"
        worker.identifiers = set()
        worker._credentials = None
        worker._active_lock = __import__("threading").Lock()
        worker._active_thread_id = None
        with tempfile.TemporaryDirectory(prefix="mysql_idle_test_") as tmp:
            worker._temp_dir = types.SimpleNamespace(name=tmp)
            self.assertTrue(worker._execute_statement("SELECT synthetic"))
            kind, columns, preview, count, elapsed, path = events.get_nowait()
            self.assertEqual(kind, "result")
            self.assertEqual(columns, ["id", "payload"])
            self.assertEqual(count, 1100)
            self.assertEqual(len(preview), mysql_idle.MAX_DISPLAY_ROWS)
            self.assertLessEqual(len(preview[0][1]), mysql_idle.MAX_CELL_WIDTH)
            self.assertTrue(os.path.exists(path))
            with open(path, "r", newline="", encoding="utf-8-sig") as fh:
                reader = csv.reader(fh)
                header = next(reader)
                rows = list(reader)
            self.assertEqual(header, columns)
            self.assertEqual(len(rows), 1100)
            self.assertEqual(len(rows[0][1]), 1000)  # full data remains exportable


if __name__ == "__main__":
    unittest.main(verbosity=2)
