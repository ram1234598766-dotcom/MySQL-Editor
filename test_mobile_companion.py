"""End-to-end tests for the mobile companion using a synthetic MySQL server."""
import csv
import importlib.util
import io
import json
import re
import ssl
import sys
import types
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

# Let the source tests run without requiring a locally installed MySQL driver.
if "pymysql" not in sys.modules:
    try:
        _pymysql_spec = importlib.util.find_spec("pymysql")
    except (ImportError, ValueError):
        _pymysql_spec = None
    if _pymysql_spec is None:
        pymysql_stub = types.ModuleType("pymysql")
        pymysql_stub.cursors = types.SimpleNamespace(SSCursor=type("SSCursor", (), {}))
        pymysql_stub.__version__ = "test-stub"
        pymysql_stub.connect = lambda **kwargs: None
        sys.modules["pymysql"] = pymysql_stub

import mobile_companion
import password_auth


class FakeCursor:
    def __init__(self):
        self.description = None
        self.rowcount = -1
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql):
        if sql.strip().lower().startswith("select synthetic"):
            self.description = (("id",), ("payload",))
            self.offset = 0
        elif sql.strip().lower().startswith("select wide"):
            self.description = tuple((f"wide_{i}",) for i in range(70))
            self.offset = 0
        elif sql.strip().lower() == "select database()":
            self.description = (("DATABASE()",),)
        else:
            self.description = None
            self.rowcount = 1

    def fetchmany(self, size):
        if self.description and self.description[0][0] == "id":
            start = self.offset
            stop = min(start + size, 1100)
            self.offset = stop
            return [(i, "x" * 1000) for i in range(start, stop)]
        if self.description and self.description[0][0] == "wide_0" and self.offset == 0:
            self.offset = 1
            return [tuple(range(70))]
        return []

    def fetchone(self):
        return ("demo",)


class FakeConnection:
    def cursor(self, cursorclass=None):
        return FakeCursor()

    def get_server_info(self):
        return "8.0-test"

    def close(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


class MobileCompanionHTTPTests(unittest.TestCase):
    def setUp(self):
        self.master_password = "MySQL Editor test master password 42!"
        self.password_record = password_auth.create_password_record(self.master_password)
        self.server = mobile_companion.MobileCompanionServer(
            port=0, bind_host="127.0.0.1", password_record=self.password_record
        )
        self.server.start()
        self.base = f"https://127.0.0.1:{self.server.port}"
        # This is test-only: the companion uses a temporary self-signed cert.
        self.ssl_context = ssl._create_unverified_context()

    def tearDown(self):
        self.server.stop()

    def request_json(self, path, payload=None, token=None, method=None):
        data = None if method == "GET" else json.dumps(payload or {}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = Request(self.base + path, data=data, headers=headers, method=method)
        with urlopen(req, timeout=5, context=self.ssl_context) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def pair(self):
        status, result = self.request_json("/api/pair", {
            "code": self.server.pairing_code,
            "masterPassword": self.master_password,
        })
        self.assertEqual(status, 200)
        return result["token"]

    def test_mobile_page_is_responsive_app(self):
        with urlopen(self.base + "/", timeout=5, context=self.ssl_context) as response:
            body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(response.headers.get("Cache-Control"), "no-store, max-age=0")
            self.assertEqual(response.headers.get("Cross-Origin-Resource-Policy"), "same-origin")
            csp = response.headers.get("Content-Security-Policy", "")
            self.assertIn("object-src 'none'", csp)
            nonce_match = re.search(r"script-src 'nonce-([^']+)'", csp)
            self.assertIsNotNone(nonce_match)
            self.assertIn(f'<script nonce="{nonce_match.group(1)}">', body)
            self.assertRegex(self.server.certificate_fingerprint, r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")
            self.assertIn("Android companion", body)
            self.assertIn("viewport", body)
            self.assertIn('src="/brand/mysql-editor-logo.jpg"', body)
            self.assertIn('alt="MySQL Editor logo"', body)
            self.assertIn('id="masterPassword"', body)
            self.assertIn('id="masterPasswordToggle"', body)
            self.assertIn("master password you set on Windows", body)
            self.assertIn("masterPassword:$('masterPassword').value", body)
            self.assertNotIn("sessionStorage.setItem('mysqlIdleMobileSession'", body)
            self.assertIn('id="historyBackBtn"', body)
            self.assertIn('id="historyForwardBtn"', body)
            self.assertIn('id="templateSelect"', body)
            self.assertIn('id="passwordToggle"', body)
            self.assertIn('id="tlsVerify"', body)
            self.assertIn('id="tlsCa"', body)
            self.assertIn('aria-label="Show password"', body)
            self.assertIn('aria-pressed="false"', body)
            self.assertIn("$(" + "'passwordToggle'" + ").onclick", body)
            self.assertIn("queryHistory.push(sql)", body)
            self.assertIn("50 queries in memory", body)
            self.assertIn("Run SQL", body)

    def test_mobile_page_serves_original_logo_asset(self):
        with urlopen(
            self.base + "/brand/mysql-editor-logo.jpg",
            timeout=5,
            context=self.ssl_context,
        ) as response:
            data = response.read()
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers.get("Content-Type", "").startswith("image/jpeg"))
            self.assertEqual(response.headers.get("Cache-Control"), "no-store, max-age=0")

        expected = (Path(__file__).resolve().parent / "assets" / "mysql-editor-logo.jpg").read_bytes()
        self.assertEqual(data, expected, "Mobile companion must serve the exact shared logo asset.")

    def test_companion_refuses_to_start_without_master_password_verifier(self):
        with self.assertRaisesRegex(ValueError, "Set a master password"):
            mobile_companion.MobileCompanionServer(port=0, bind_host="127.0.0.1")

    def test_pairing_requires_both_master_password_and_pairing_code(self):
        with self.assertRaises(HTTPError) as err:
            self.request_json("/api/pair", {
                "code": self.server.pairing_code,
                "masterPassword": "not the Windows password",
            })
        self.assertEqual(err.exception.code, 401)

        with self.assertRaises(HTTPError) as err:
            self.request_json("/api/pair", {
                "code": "wrong-code",
                "masterPassword": self.master_password,
            })
        self.assertEqual(err.exception.code, 401)

        token = self.pair()
        status, state = self.request_json("/api/state", token=token, method="GET")
        self.assertEqual(status, 200)
        self.assertTrue(state["ok"])
        self.assertFalse(state["connected"])

    def test_large_query_preview_is_bounded_and_full_csv_is_exportable(self):
        original_connect = mobile_companion.pymysql.connect
        captured = {}
        def fake_connect(**kwargs):
            captured.update(kwargs)
            return FakeConnection()
        mobile_companion.pymysql.connect = fake_connect
        token = self.pair()
        try:
            status, connected = self.request_json("/api/connect", {
                "host": "localhost", "port": 3306, "user": "tester", "password": "not-persisted",
                "database": "demo", "autocommit": True,
            }, token=token)
            self.assertEqual(status, 200)
            self.assertTrue(connected["ok"])
            self.assertTrue(captured["ssl_verify_cert"], "MySQL TLS verification must be enabled by default")
            self.assertTrue(captured["ssl_verify_identity"], "MySQL host identity must be verified by default")

            status, result = self.request_json("/api/query", {"sql": "SELECT synthetic"}, token=token)
            self.assertEqual(status, 200)
            self.assertEqual(result["rowCount"], 1100)
            self.assertEqual(len(result["preview"]), mobile_companion.MAX_PREVIEW_ROWS)
            self.assertTrue(result["truncated"])
            self.assertLessEqual(len(result["preview"][0][1]), mobile_companion.MAX_PREVIEW_CELL_CHARS)

            req = Request(self.base + "/api/export", headers={"Authorization": "Bearer " + token})
            with urlopen(req, timeout=5, context=self.ssl_context) as response:
                csv_text = response.read().decode("utf-8-sig")
            rows = list(csv.reader(io.StringIO(csv_text)))
            self.assertEqual(rows[0], ["id", "payload"])
            self.assertEqual(len(rows) - 1, 1100)
            self.assertEqual(len(rows[1][1]), 1000)
        finally:
            mobile_companion.pymysql.connect = original_connect

    def test_high_impact_mobile_query_requires_single_use_approval(self):
        original_connect = mobile_companion.pymysql.connect
        mobile_companion.pymysql.connect = lambda **kwargs: FakeConnection()
        token = self.pair()
        try:
            self.request_json("/api/connect", {
                "host": "localhost", "port": 3306, "user": "tester",
            }, token=token)
            req = Request(
                self.base + "/api/query",
                data=json.dumps({"sql": "DROP TABLE sample"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
                method="POST",
            )
            with self.assertRaises(HTTPError) as challenge_error:
                urlopen(req, timeout=5, context=self.ssl_context)
            self.assertEqual(challenge_error.exception.code, 409)
            challenge = json.loads(challenge_error.exception.read().decode("utf-8"))
            self.assertTrue(challenge["approval_required"])
            self.assertTrue(challenge["approvalToken"])
            self.assertIn("irreversibly", challenge["reason"])

            status, result = self.request_json(
                "/api/query",
                {"sql": "DROP TABLE sample", "approvalToken": challenge["approvalToken"]},
                token=token,
            )
            self.assertEqual(status, 200)
            self.assertTrue(result["ok"])

            replay = Request(
                self.base + "/api/query",
                data=json.dumps({
                    "sql": "DROP TABLE sample",
                    "approvalToken": challenge["approvalToken"],
                }).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
                method="POST",
            )
            with self.assertRaises(HTTPError) as replay_error:
                urlopen(replay, timeout=5, context=self.ssl_context)
            self.assertEqual(replay_error.exception.code, 403)
        finally:
            mobile_companion.pymysql.connect = original_connect

    def test_read_only_governance_blocks_mobile_mutations(self):
        original_connect = mobile_companion.pymysql.connect
        mobile_companion.pymysql.connect = lambda **kwargs: FakeConnection()
        self.server.governor.set_policy(read_only=True)
        token = self.pair()
        try:
            self.request_json("/api/connect", {
                "host": "localhost", "port": 3306, "user": "tester",
            }, token=token)
            req = Request(
                self.base + "/api/query",
                data=json.dumps({"sql": "UPDATE users SET active=0 WHERE id=7"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
                method="POST",
            )
            with self.assertRaises(HTTPError) as blocked:
                urlopen(req, timeout=5, context=self.ssl_context)
            self.assertEqual(blocked.exception.code, 403)
            payload = json.loads(blocked.exception.read().decode("utf-8"))
            self.assertTrue(payload["governance_blocked"])
            self.assertIn("Read-only policy", payload["error"])

            with self.assertRaises(HTTPError) as commit_blocked:
                self.request_json("/api/transaction", {"action": "commit"}, token=token)
            self.assertEqual(commit_blocked.exception.code, 403)
            commit_payload = json.loads(commit_blocked.exception.read().decode("utf-8"))
            self.assertTrue(commit_payload["governance_blocked"])
            self.assertIn("blocks COMMIT", commit_payload["error"])
        finally:
            mobile_companion.pymysql.connect = original_connect

    def test_wide_results_keep_preview_bounded_but_export_all_columns(self):
        original_connect = mobile_companion.pymysql.connect
        mobile_companion.pymysql.connect = lambda **kwargs: FakeConnection()
        token = self.pair()
        try:
            self.request_json("/api/connect", {"host": "localhost", "port": 3306, "user": "tester"}, token=token)
            status, result = self.request_json("/api/query", {"sql": "SELECT wide"}, token=token)
            self.assertEqual(status, 200)
            self.assertEqual(result["totalColumns"], 70)
            self.assertEqual(len(result["columns"]), mobile_companion.MAX_PREVIEW_COLUMNS)
            self.assertTrue(result["truncatedColumns"])
            req = Request(self.base + "/api/export", headers={"Authorization": "Bearer " + token})
            with urlopen(req, timeout=5, context=self.ssl_context) as response:
                header = next(csv.reader(io.StringIO(response.read().decode("utf-8-sig"))))
            self.assertEqual(len(header), 70)
        finally:
            mobile_companion.pymysql.connect = original_connect

    def test_host_header_rejects_unexpected_hostname(self):
        req = Request(self.base + "/", headers={"Host": "attacker.example"})
        with self.assertRaises(HTTPError) as err:
            urlopen(req, timeout=5, context=self.ssl_context)
        self.assertEqual(err.exception.code, 403)

    def test_host_header_rejects_mismatched_port(self):
        req = Request(self.base + "/", headers={"Host": "localhost:1"})
        with self.assertRaises(HTTPError) as err:
            urlopen(req, timeout=5, context=self.ssl_context)
        self.assertEqual(err.exception.code, 403)

    def test_oversized_request_body_returns_413(self):
        req = Request(
            self.base + "/api/pair",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(mobile_companion.MAX_BODY_BYTES + 1),
            },
            method="POST",
        )
        with self.assertRaises(HTTPError) as err:
            urlopen(req, timeout=5, context=self.ssl_context)
        self.assertEqual(err.exception.code, 413)
        body = json.loads(err.exception.read().decode("utf-8"))
        self.assertIn("limit", body["error"].lower())


    def test_non_json_post_is_rejected(self):
        req = Request(
            self.base + "/api/pair",
            data=b"code=123",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as err:
            urlopen(req, timeout=5, context=self.ssl_context)
        self.assertEqual(err.exception.code, 415)

    def test_http_origin_is_rejected_for_post(self):
        req = Request(
            self.base + "/api/pair",
            data=json.dumps({"code": self.server.pairing_code}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{self.server.port}",
            },
            method="POST",
        )
        with self.assertRaises(HTTPError) as err:
            urlopen(req, timeout=5, context=self.ssl_context)
        self.assertEqual(err.exception.code, 403)

    def test_wildcard_bind_is_rejected(self):
        with self.assertRaises(ValueError):
            mobile_companion.MobileCompanionServer(port=0, bind_host="0.0.0.0")

    def test_large_result_file_is_stopped_at_limit(self):
        original_connect = mobile_companion.pymysql.connect
        original_limit = mobile_companion.MAX_RESULT_BYTES
        mobile_companion.pymysql.connect = lambda **kwargs: FakeConnection()
        mobile_companion.MAX_RESULT_BYTES = 1
        token = self.pair()
        try:
            self.request_json("/api/connect", {"host": "localhost", "port": 3306, "user": "tester"}, token=token)
            with self.assertRaises(HTTPError) as err:
                self.request_json("/api/query", {"sql": "SELECT synthetic"}, token=token)
            self.assertEqual(err.exception.code, 413)
            body = json.loads(err.exception.read().decode("utf-8"))
            self.assertIn("export limit", body["error"].lower())
        finally:
            mobile_companion.pymysql.connect = original_connect
            mobile_companion.MAX_RESULT_BYTES = original_limit

if __name__ == "__main__":
    unittest.main(verbosity=2)
