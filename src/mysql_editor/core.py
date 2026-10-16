"""Pure domain helpers for SQL boundaries, risk advisories, formatting and redaction."""
from __future__ import annotations
import re
from dataclasses import dataclass
from collections.abc import Iterator

try:
    from sqlglot import format as format_sqlglot
except ImportError:  # pragma: no cover
    format_sqlglot = None

@dataclass(frozen=True, slots=True)
class StatementSpan:
    sql: str
    start: int
    end: int

def iter_statement_spans(source: str) -> Iterator[StatementSpan]:
    """Split ordinary SQL on real semicolons, not semicolons in strings/comments.

    MySQL DELIMITER directives and compound stored-program bodies are not interpreted in v1.
    """
    start = 0
    i = 0
    state = "normal"
    length = len(source)
    while i < length:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < length else ""
        if state == "line":
            if ch in "\r\n":
                state = "normal"
            i += 1
            continue
        if state == "block":
            if ch == "*" and nxt == "/":
                state = "normal"
                i += 2
            else:
                i += 1
            continue
        if state in ("single", "double", "identifier"):
            terminator = {"single": "'", "double": '"', "identifier": chr(96)}[state]
            if ch == "\\" and state != "identifier" and i + 1 < length:
                i += 2
                continue
            if ch == terminator:
                if nxt == terminator:
                    i += 2
                    continue
                state = "normal"
            i += 1
            continue
        if ch == "#" or (
            ch == "-" and nxt == "-" and
            (i + 2 >= length or source[i + 2].isspace())
        ):
            state = "line"
            i += 2 if ch == "-" else 1
            continue
        if ch == "/" and nxt == "*":
            state = "block"
            i += 2
            continue
        if ch == "'":
            state = "single"
            i += 1
            continue
        if ch == '"':
            state = "double"
            i += 1
            continue
        if ch == chr(96):
            state = "identifier"
            i += 1
            continue
        if ch == ";":
            raw = source[start:i]
            trimmed = raw.strip()
            if trimmed:
                left = len(raw) - len(raw.lstrip())
                yield StatementSpan(trimmed, start + left, i)
            start = i + 1
        i += 1
    raw = source[start:]
    trimmed = raw.strip()
    if trimmed:
        left = len(raw) - len(raw.lstrip())
        yield StatementSpan(trimmed, start + left, length)

def split_sql_statements(source: str) -> list[str]:
    return [span.sql for span in iter_statement_spans(source)]

def current_statement(source: str, cursor_position: int) -> str:
    for span in iter_statement_spans(source):
        if span.start <= cursor_position <= span.end:
            return span.sql
    return ""

_DESTRUCTIVE = re.compile(
    r"^\s*(DROP|TRUNCATE|ALTER)\b|^\s*(GRANT|REVOKE)\b|"
    r"^\s*CREATE\s+(USER|ROLE)\b|^\s*SET\s+GLOBAL\b", re.IGNORECASE
)
_WHERE = re.compile(r"\bWHERE\b", re.IGNORECASE)
_COMMAND = re.compile(r"\b([A-Za-z]+)\b")

def classify_statement(sql: str) -> tuple[str, str]:
    """Return (risk, explanation); guidance only, never an access-control boundary."""
    without_comments = re.sub(r"/\*.*?\*/|--[^\r\n]*|#[^\r\n]*", " ", sql, flags=re.S)
    first = _COMMAND.search(without_comments)
    command = first.group(1).upper() if first else "UNKNOWN"
    if _DESTRUCTIVE.search(without_comments):
        return "high", f"{command} can change schema, permissions, or server-wide settings."
    if command in {"UPDATE", "DELETE"} and not _WHERE.search(without_comments):
        return "high", f"{command} has no WHERE clause and may affect every row."
    if command in {"INSERT", "UPDATE", "DELETE", "REPLACE", "LOAD", "CALL", "CREATE", "RENAME"}:
        return "medium", f"{command} may change data or database objects."
    return "low", "No high-impact pattern was detected by the local advisory check."

def format_sql(sql: str) -> str:
    """Format SQL without executing it."""
    if format_sqlglot is None:
        raise RuntimeError("SQL formatter is unavailable. Install the SQLGlot dependency.")
    return format_sqlglot(sql, dialect="mysql", pretty=True, comments=True)

_SECRET = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)\b(\s*[:=]\s*|\s+)"
    r"('[^']*'|\"[^\"]*\"|[^\s,;]+)"
)

def redact_secrets(text: str) -> str:
    return _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)

def safe_identifier(name: str) -> str:
    tick = chr(96)
    return tick + name.replace(tick, tick + tick) + tick
