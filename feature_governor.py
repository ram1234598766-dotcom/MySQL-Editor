"""Central runtime policy engine for MySQL IDLE.

The governor is intentionally local and dependency-free. It classifies SQL,
enforces an optional read-only policy, requires one-time approval for high-impact
statements, and records a bounded audit trail without retaining SQL or secrets.
"""
from __future__ import annotations

from collections import deque
import hashlib
import os
import threading
import time
from datetime import datetime, timezone


AUDIT_LIMIT = 256
APPROVAL_TTL_SECONDS = 45

_MUTATION_WORDS = {
    "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP",
    "TRUNCATE", "RENAME", "GRANT", "REVOKE", "CALL", "LOAD", "IMPORT",
    "LOCK", "UNLOCK", "FLUSH", "RESET", "KILL", "SHUTDOWN", "ANALYZE", "SET",
    "CHANGE", "COMMIT",
    "OPTIMIZE", "REPAIR", "INSTALL", "UNINSTALL", "PREPARE", "EXECUTE",
}
_ADMIN_WORDS = {
    "GRANT", "REVOKE", "SHUTDOWN", "KILL", "FLUSH", "RESET", "INSTALL",
    "UNINSTALL", "LOCK", "UNLOCK", "LOAD", "IMPORT", "PREPARE", "EXECUTE",
}
_DESTRUCTIVE_WORDS = {"DROP", "TRUNCATE", "ALTER", "RENAME"}


def _tokens(sql: str) -> list[str]:
    """Return unquoted SQL keywords while ignoring literals, identifiers and comments."""
    result: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "#" or (sql.startswith("--", i) and
                         (i + 2 == n or sql[i + 2].isspace() or ord(sql[i + 2]) < 32)):
            newline = sql.find("\n", i)
            i = n if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end < 0:
                break
            # MySQL /*! ... */ and MariaDB /*M! ... */ comments can execute
            # SQL on the server; inspect their payload instead of discarding it.
            if sql.startswith("/*!", i) or sql.startswith("/*M!", i):
                payload_start = i + (3 if sql.startswith("/*!", i) else 4)
                while payload_start < end and sql[payload_start].isdigit():
                    payload_start += 1
                result.extend(_tokens(sql[payload_start:end]))
            i = end + 2
            continue
        if ch in ("'", '"', chr(96)):
            quote = ch
            i += 1
            while i < n:
                if sql[i] == "\\":
                    i += 2
                    continue
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] in "_$"):
                j += 1
            result.append(sql[i:j].upper())
            i = j
            continue
        if ch in "();":
            result.append(ch)
        i += 1
    return result


def classify_sql(sql: str) -> dict[str, str | bool]:
    """Conservative, lexical risk assessment; never treats SQL text as executable code."""
    tokens = _tokens(sql)
    if not tokens:
        return {"category": "empty", "risk": "low", "reason": "No SQL keywords found.",
                "mutation": False, "requires_confirmation": False}

    # Preserve top-level token positions so a WHERE inside a nested subquery cannot
    # disguise an unqualified UPDATE/DELETE on the outer statement.
    groups: list[list[str]] = []
    current: list[str] = []
    depth = 0
    for token in tokens:
        if token == ";" and depth == 0:
            if current:
                groups.append(current)
            current = []
            continue
        current.append(token)
        if token == "(":
            depth += 1
        elif token == ")":
            depth = max(0, depth - 1)
    if current:
        groups.append(current)

    word_set = {token for token in tokens if token not in {"(", ")", ";"}}
    top_level_groups: list[set[str]] = []
    for group in groups:
        local_depth = 0
        top: set[str] = set()
        for token in group:
            if token == "(":
                local_depth += 1
            elif token == ")":
                local_depth = max(0, local_depth - 1)
            elif local_depth == 0 and token not in {";", "(", ")"}:
                top.add(token)
        top_level_groups.append(top)

    mutation = bool(word_set & _MUTATION_WORDS)
    high_reasons: list[str] = []
    top_level_words = set().union(*top_level_groups) if top_level_groups else set()
    if top_level_words & _DESTRUCTIVE_WORDS:
        high_reasons.append("DDL can irreversibly change or remove database objects.")
    if "CALL" in top_level_words:
        high_reasons.append("Stored procedures may perform broad or privileged database changes.")
    if "LOAD_FILE" in top_level_words:
        high_reasons.append("LOAD_FILE can expose files from the database server to the query result.")
    if "SET" in top_level_words and "PASSWORD" in top_level_words:
        high_reasons.append("Changing database account credentials is a high-impact security operation.")
    if "CHANGE" in top_level_words and top_level_words.intersection({"MASTER", "REPLICATION", "SOURCE"}):
        high_reasons.append("Changing replication configuration can disrupt database availability or consistency.")
    if top_level_words & _ADMIN_WORDS:
        high_reasons.append("Administrative or file-related SQL can affect server-wide state.")
    if {"OUTFILE", "DUMPFILE", "PERSIST"} & top_level_words:
        high_reasons.append("File export or persistent/global settings can expose data or alter server state.")
        mutation = True
    if "GLOBAL" in top_level_words and "SET" in top_level_words:
        high_reasons.append("Global server settings affect other database users.")
        mutation = True

    for top in top_level_groups:
        if "DELETE" in top and "WHERE" not in top:
            high_reasons.append("DELETE without WHERE may remove every row in a table.")
        if "UPDATE" in top and "WHERE" not in top:
            high_reasons.append("UPDATE without WHERE may modify every row in a table.")
        if "CREATE" in top and top.intersection({"USER", "ROLE", "PROCEDURE", "FUNCTION", "EVENT", "TRIGGER"}):
            high_reasons.append("Creating privileged or executable database objects needs deliberate review.")
        if "ALTER" in top and top.intersection({"USER", "ROLE"}):
            high_reasons.append("Changing an account or role may affect database access.")

    reason = " ".join(dict.fromkeys(high_reasons))
    if high_reasons:
        if (
            top_level_words & _ADMIN_WORDS
            or ("GLOBAL" in top_level_words and "SET" in top_level_words)
            or ("SET" in top_level_words and "PASSWORD" in top_level_words)
            or ("CHANGE" in top_level_words and top_level_words.intersection({"MASTER", "REPLICATION", "SOURCE"}))
        ):
            category = "administrative"
        elif top_level_words & _DESTRUCTIVE_WORDS:
            category = "destructive"
        else:
            category = "high-impact"
        return {"category": category, "risk": "high", "reason": reason,
                "mutation": mutation, "requires_confirmation": True}
    if mutation:
        return {"category": "write", "risk": "medium", "reason": "Statement may modify database state.",
                "mutation": True, "requires_confirmation": False}
    return {"category": "read", "risk": "low", "reason": "No high-impact operation detected.",
            "mutation": False, "requires_confirmation": False}


class FeatureGovernor:
    """Thread-safe feature policy, one-time query approvals, and privacy-preserving audit log."""

    def __init__(self, config: dict | None = None):
        config = config if isinstance(config, dict) else {}
        env_readonly = os.environ.get("MYSQLIDLE_READ_ONLY")
        env_mobile_disabled = os.environ.get("MYSQLIDLE_DISABLE_MOBILE", "").strip().lower() in {"1", "true", "yes"}
        self._forced_read_only = env_readonly is not None and env_readonly.strip().lower() in {"1", "true", "yes", "on"}
        self._forced_mobile_disabled = env_mobile_disabled
        self._read_only = self._forced_read_only or bool(config.get("read_only", False))
        self._mobile_enabled = not self._forced_mobile_disabled and bool(config.get("mobile_companion_enabled", True))
        self._lock = threading.RLock()
        self._approvals: dict[str, float] = {}
        self._audit = deque(maxlen=AUDIT_LIMIT)

    @staticmethod
    def _digest(sql: str) -> str:
        """Full digest for approval binding; never store this full value in the audit log."""
        return hashlib.sha256(sql.encode("utf-8", "replace")).hexdigest()

    @classmethod
    def fingerprint(cls, sql: str) -> str:
        """Short, user-facing audit fingerprint."""
        return cls._digest(sql)[:16]

    @property
    def read_only(self) -> bool:
        with self._lock:
            return self._read_only

    @property
    def mobile_companion_enabled(self) -> bool:
        with self._lock:
            return self._mobile_enabled

    def feature_enabled(self, feature: str) -> bool:
        with self._lock:
            if feature == "mobile_companion":
                return self._mobile_enabled
            if feature in {"database_write", "schema_change"}:
                return not self._read_only
            if feature == "persistent_history":
                return os.environ.get("MYSQLIDLE_SAVE_HISTORY", "").strip().lower() in {"1", "true", "yes"}
            return True

    def set_policy(self, *, read_only: bool | None = None, mobile_companion_enabled: bool | None = None) -> None:
        with self._lock:
            if read_only is not None:
                self._read_only = self._forced_read_only or bool(read_only)
            if mobile_companion_enabled is not None:
                self._mobile_enabled = (not self._forced_mobile_disabled) and bool(mobile_companion_enabled)
            self._approvals.clear()

    def snapshot(self) -> dict[str, bool | str]:
        with self._lock:
            return {
                "mode": "read-only" if self._read_only else "guarded",
                "read_only": self._read_only,
                "mobile_companion_enabled": self._mobile_enabled,
                "high_impact_confirmation": True,
            }

    def inspect_sql(self, sql: str) -> dict[str, str | bool]:
        assessment = classify_sql(sql)
        with self._lock:
            read_only = self._read_only
        if read_only and assessment["mutation"]:
            return {
                **assessment, "decision": "block",
                "reason": "Read-only policy is active; modifying or administrative SQL is blocked.",
            }
        if assessment["requires_confirmation"]:
            return {**assessment, "decision": "confirm"}
        return {**assessment, "decision": "allow"}

    def approve_once(self, sql: str) -> None:
        digest = self._digest(sql)
        with self._lock:
            now = time.monotonic()
            self._approvals = {key: expiry for key, expiry in self._approvals.items() if expiry > now}
            self._approvals[digest] = now + APPROVAL_TTL_SECONDS

    def check_sql(self, sql: str, *, externally_approved: bool = False) -> dict[str, str | bool]:
        """Recheck at the execution boundary; consume desktop approvals exactly once."""
        result = self.inspect_sql(sql)
        if result["decision"] == "confirm":
            digest = self._digest(sql)
            allowed = bool(externally_approved)
            if not allowed:
                with self._lock:
                    expiry = self._approvals.pop(digest, 0.0)
                    allowed = expiry > time.monotonic()
            result = {**result, "decision": "allow" if allowed else "confirm"}
            if allowed:
                result["reason"] = "High-impact SQL was explicitly approved for this execution."
        self.record_decision(sql, str(result["decision"]), str(result["reason"]),
                             str(result["category"]), str(result["risk"]))
        return result

    def record_decision(self, sql: str, decision: str, reason: str,
                        category: str | None = None, risk: str | None = None) -> None:
        assessment = classify_sql(sql)
        event = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "decision": str(decision)[:32],
            "category": str(category or assessment["category"])[:32],
            "risk": str(risk or assessment["risk"])[:16],
            "reason": str(reason)[:240],
            "statement_digest": self.fingerprint(sql),
        }
        with self._lock:
            self._audit.append(event)

    def audit_events(self, limit: int = 50) -> list[dict[str, str]]:
        count = max(0, min(int(limit), AUDIT_LIMIT))
        with self._lock:
            return [dict(item) for item in list(self._audit)[-count:]] if count else []

    @property
    def forced_policy_notes(self) -> list[str]:
        notes = []
        if self._forced_read_only:
            notes.append("MYSQLIDLE_READ_ONLY forces read-only mode.")
        if self._forced_mobile_disabled:
            notes.append("MYSQLIDLE_DISABLE_MOBILE disables the mobile companion.")
        return notes
