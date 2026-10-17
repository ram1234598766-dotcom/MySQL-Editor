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
    spans = list(iter_statement_spans(source))
    for span in spans:
        if span.start <= cursor_position <= span.end:
            return span.sql
    # Cursor commonly rests immediately after a semicolon or on trailing whitespace.
    for span in reversed(spans):
        if span.end <= cursor_position and source[span.end:cursor_position].strip() in ("", ";"):
            return span.sql
    return ""

_DESTRUCTIVE = re.compile(
    r"^\s*(DROP|TRUNCATE|ALTER)\b|^\s*(GRANT|REVOKE)\b|"
    r"^\s*CREATE\s+(USER|ROLE)\b|^\s*SET\s+GLOBAL\b", re.IGNORECASE
)
_WHERE = re.compile(r"\bWHERE\b", re.IGNORECASE)
_COMMAND = re.compile(r"\b([A-Za-z]+)\b")

def _mask_sql_literals_and_comments(source: str) -> str:
    """Mask strings, quoted identifiers and comments, keeping newlines and offsets."""
    chars = list(source)
    length = len(source)
    i = 0
    state = "normal"
    terminator = ""
    while i < length:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < length else ""
        if state == "line":
            if ch in "\r\n":
                state = "normal"
            else:
                chars[i] = " "
            i += 1
            continue
        if state == "block":
            if ch not in "\r\n":
                chars[i] = " "
            if ch == "*" and nxt == "/":
                chars[i] = chars[i + 1] = " "
                state = "normal"
                i += 2
            else:
                i += 1
            continue
        if state in {"single", "double", "identifier"}:
            if ch not in "\r\n":
                chars[i] = " "
            if ch == "\\" and state != "identifier" and i + 1 < length:
                if source[i + 1] not in "\r\n":
                    chars[i + 1] = " "
                i += 2
                continue
            if ch == terminator:
                if nxt == terminator:
                    if nxt not in "\r\n":
                        chars[i + 1] = " "
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
            if ch == "-":
                chars[i] = chars[i + 1] = " "
                i += 2
            else:
                chars[i] = " "
                i += 1
            continue
        if ch == "/" and nxt == "*":
            chars[i] = chars[i + 1] = " "
            state = "block"
            i += 2
            continue
        if ch in {"'", '"', chr(96)}:
            state = {"'": "single", '"': "double", chr(96): "identifier"}[ch]
            terminator = ch
            chars[i] = " "
            i += 1
            continue
        i += 1
    return "".join(chars)


_TOP_LEVEL_COMMANDS = frozenset({
    "SELECT", "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP",
    "TRUNCATE", "GRANT", "REVOKE", "SET", "CALL", "LOAD", "RENAME",
})


def _main_statement_command(masked_sql: str) -> tuple[str, int]:
    tokens = list(re.finditer(r"[A-Za-z_][A-Za-z0-9_$]*|[()]", masked_sql))
    if not tokens:
        return "UNKNOWN", 0
    first = tokens[0]
    command = first.group().upper()
    if command != "WITH":
        return command, first.start()
    depth = 0
    for token in tokens[1:]:
        value = token.group()
        if value == "(":
            depth += 1
        elif value == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and value.upper() in _TOP_LEVEL_COMMANDS:
            return value.upper(), token.start()
    return command, first.start()


def _has_top_level_keyword(masked_sql: str, keyword: str, start: int) -> bool:
    depth = 0
    for token in re.finditer(r"[A-Za-z_][A-Za-z0-9_$]*|[()]", masked_sql[start:]):
        value = token.group()
        if value == "(":
            depth += 1
        elif value == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and value.upper() == keyword:
            return True
    return False


def transaction_pending_after_sql(
    previous: bool,
    sql: str,
    *,
    complete: bool = False,
    partial: bool = False,
) -> bool:
    """Conservatively track uncommitted writes for safe connection switching.

    Successful COMMIT/ROLLBACK and MySQL implicit-commit DDL clear the pending
    flag. A partially completed script that contains a write keeps the warning
    active because the UI cannot infer exactly which statements reached MySQL.
    """
    statements = split_sql_statements(sql)
    if not complete:
        if partial and any(
            _transaction_effect(statement) == "write" for statement in statements
        ):
            return True
        return previous

    pending = previous
    for statement in statements:
        effect = _transaction_effect(statement)
        if effect == "clear":
            pending = False
        elif effect == "write":
            pending = True
    return pending


def _transaction_effect(statement: str) -> str:
    """Classify the transaction-state effect of one ordinary SQL statement."""
    masked = _mask_sql_literals_and_comments(statement)
    command, _start = _main_statement_command(masked)
    normalized = " ".join(masked.strip().upper().split())

    if command in {"COMMIT", "ROLLBACK", "BEGIN", "START"}:
        return "clear"
    if command in {"CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME", "GRANT", "REVOKE"}:
        return "clear"
    if command == "SET" and re.match(
        r"SET\s+(?:SESSION\s+)?AUTOCOMMIT\s*=\s*(?:1|ON)\b",
        normalized,
    ):
        return "clear"
    if command in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CALL", "LOAD"}:
        return "write"
    return "none"


def classify_statement(sql: str) -> tuple[str, str]:
    """Conservative SQL advisory, excluding strings/comments and understanding CTE DML.

    This is guidance, not authorization; MySQL privileges remain the enforcement boundary.
    """
    masked = _mask_sql_literals_and_comments(sql)
    command, command_start = _main_statement_command(masked)
    body = masked[command_start:].lstrip().upper()
    if command in {"DROP", "TRUNCATE", "ALTER", "GRANT", "REVOKE"}:
        return "high", f"{command} can change schema, permissions, or server-wide settings."
    if command == "CREATE" and re.match(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:USER|ROLE)\b", body
    ):
        return "high", "CREATE USER or CREATE ROLE changes database access."
    if command == "SET" and re.match(r"SET\s+GLOBAL\b", body):
        return "high", "SET GLOBAL changes server-wide settings."
    if command in {"UPDATE", "DELETE"} and not _has_top_level_keyword(
        masked, "WHERE", command_start
    ):
        return "high", f"{command} has no top-level WHERE clause and may affect every row."
    if command in {
        "INSERT", "UPDATE", "DELETE", "REPLACE", "LOAD", "CALL", "CREATE", "RENAME",
    }:
        return "medium", f"{command} may change data or database objects."
    return "low", "No high-impact pattern was detected by the local advisory check."

def format_sql(sql: str) -> str:
    """Format SQL without executing it."""
    if format_sqlglot is None:
        raise RuntimeError("SQL formatter is unavailable. Install the SQLGlot dependency.")
    return format_sqlglot(sql, dialect="mysql", pretty=True, comments=True)

_SECRET = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)\b(\s*[:=]\s*)"
    r"('[^']*'|\"[^\"]*\"|[^\s,;]+)"
)

_SQL_VALUE = r"""(?:'(?:''|\\.|[^'])*'|"(?:\"\"|\\.|[^"])*"|[^\s,;]+)"""
_SQL_SECRET_PATTERNS = (
    re.compile(r"(?is)(\bIDENTIFIED\s+BY\s+(?:PASSWORD\s+)?)" + _SQL_VALUE),
    re.compile(r"(?is)(\bIDENTIFIED\s+WITH\s+[A-Za-z0-9_]+\s+BY\s+)" + _SQL_VALUE),
    re.compile(r"(?is)(\bIDENTIFIED\s+WITH\s+[A-Za-z0-9_]+\s+AS\s+)" + _SQL_VALUE),
    re.compile(r"(?is)(\bSET\s+PASSWORD(?:\s+FOR\s+[^=;]+)?\s*=\s*)" + _SQL_VALUE),
    re.compile(r"(?is)(\b(?:PASSWORD|AUTHENTICATION_STRING|TOKEN|SECRET|API_KEY)\s*=\s*)" + _SQL_VALUE),
)


def redact_secrets(text: str) -> str:
    """Redact credential-like key/value assignments in text."""
    return _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


def redact_sql_secrets(sql: str) -> str:
    """Redact common MySQL account/password syntax before opt-in query history is persisted."""
    redacted = sql
    for pattern in _SQL_SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: match.group(1) + "[REDACTED]", redacted)
    return redact_secrets(redacted)


def safe_identifier(name: str) -> str:
    tick = chr(96)
    return tick + name.replace(tick, tick + tick) + tick
