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
    active_delimiter: str | None = None


class ScriptParseError(ValueError):
    """A script error that prevents the complete script from being submitted."""

    def __init__(self, line: int, detail: str) -> None:
        self.line = line
        super().__init__(
            f"MySQL script parsing failed on line {line}: {detail}. "
            "The script was not submitted."
        )


_DELIMITER_PREFIX = re.compile(r"^[ \t]*DELIMITER\b", re.IGNORECASE)
_DELIMITER_DIRECTIVE = re.compile(
    r"[ \t]*DELIMITER[ \t]+(\S+)[ \t]*", re.IGNORECASE
)
_COMPOUND_ROUTINE_START = re.compile(
    r"^\s*CREATE\s+(?:(?:OR\s+REPLACE)\s+)?(?:DEFINER\s*=\s*.*?)?"
    r"(?:PROCEDURE|FUNCTION|TRIGGER|EVENT)\b.*?\bBEGIN\b",
    re.IGNORECASE | re.DOTALL,
)


def iter_statement_spans(source: str) -> Iterator[StatementSpan]:
    """Split SQL on the active separator, interpreting standalone DELIMITER client commands.

    Client directives are blanked in a same-length working copy, so statement offsets continue
    to refer to the original editor buffer. This is a statement-boundary scanner, not a full
    MySQL grammar or semantic validator.
    """
    length = len(source)
    masked = _mask_sql_literals_and_comments(source)
    masked_clean = list(masked)
    clean = list(source)
    directive_lines: dict[int, tuple[str, int, int]] = {}
    line_offset = 0

    for line_number, raw_line in enumerate(source.splitlines(keepends=True), start=1):
        line = raw_line.rstrip("\r\n")
        line_end = line_offset + len(line)
        masked_line = masked[line_offset:line_end]
        # Requiring the directive to be visible in both strings excludes quoted text and
        # directives that merely appear inside line or block comments.
        if _DELIMITER_PREFIX.match(line) and _DELIMITER_PREFIX.match(masked_line):
            directive_lines[line_offset] = (line, line_end, line_number)
        line_offset += len(raw_line)

    start = 0
    i = 0
    delimiter = ";"
    state = "normal"

    while i < length:
        directive = directive_lines.get(i)
        if directive and state == "normal" and not "".join(masked_clean[start:i]).strip():
            line, line_end, line_number = directive
            match = _DELIMITER_DIRECTIVE.fullmatch(line)
            if match is None:
                raise ScriptParseError(
                    line_number,
                    "expected DELIMITER followed by exactly one non-whitespace token "
                    "on its own line",
                )
            next_delimiter = match.group(1)
            if (
                any(char in next_delimiter for char in ("'", '"', chr(96)))
                or next_delimiter.startswith("#")
                or next_delimiter.startswith("--")
                or next_delimiter.startswith("/*")
            ):
                raise ScriptParseError(
                    line_number,
                    "the delimiter must not contain quote characters or begin with "
                    "SQL comment syntax",
                )
            for position in range(i, line_end):
                clean[position] = " "
                masked_clean[position] = " "
            delimiter = next_delimiter
            i = line_end
            continue

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
            ch == "-" and nxt == "-"
            and (i + 2 >= length or source[i + 2].isspace())
        ):
            state = "line"
            i += 2 if ch == "-" else 1
            continue

        if ch == "/" and nxt == "*":
            state = "block"
            i += 2
            continue

        # Comment and quote openers take priority over a custom separator that begins with
        # the same characters. Separators are only active in normal SQL text.
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

        if source.startswith(delimiter, i):
            statement_code = "".join(masked_clean[start:i])
            if delimiter == ";" and _COMPOUND_ROUTINE_START.match(statement_code):
                leading = len(statement_code) - len(statement_code.lstrip())
                line_number = source.count("\n", 0, start + leading) + 1
                raise ScriptParseError(
                    line_number,
                    "compound stored-program bodies require DELIMITER to be set before "
                    "the CREATE statement",
                )
            raw = "".join(clean[start:i])
            trimmed = raw.strip()
            if trimmed:
                left = len(raw) - len(raw.lstrip())
                yield StatementSpan(trimmed, start + left, i, delimiter if delimiter != ";" else None)
            start = i + len(delimiter)
            i = start
            continue

        i += 1

    remaining_code = "".join(masked_clean[start:length])
    if delimiter == ";" and _COMPOUND_ROUTINE_START.match(remaining_code):
        leading = len(remaining_code) - len(remaining_code.lstrip())
        line_number = source.count("\n", 0, start + leading) + 1
        raise ScriptParseError(
            line_number,
            "compound stored-program bodies require DELIMITER to be set before "
            "the CREATE statement",
        )
    raw = "".join(clean[start:length])
    trimmed = raw.strip()
    if trimmed:
        left = len(raw) - len(raw.lstrip())
        yield StatementSpan(trimmed, start + left, length, delimiter if delimiter != ";" else None)


def split_sql_statements(source: str) -> list[str]:
    """Return every SQL statement, excluding client-only DELIMITER directives."""
    return [span.sql for span in iter_statement_spans(source)]


def _span_at_cursor(source: str, cursor_position: int) -> StatementSpan | None:
    spans = list(iter_statement_spans(source))
    for span in spans:
        if span.start <= cursor_position <= span.end:
            return span
    # Cursor commonly rests immediately after a delimiter or on trailing whitespace.
    for span in reversed(spans):
        if span.end <= cursor_position:
            gap = source[span.end:cursor_position]
            if not any(ch.isalnum() or ch == "_" for ch in gap):
                return span
    return None


def current_statement(source: str, cursor_position: int) -> str:
    """Return the statement under the cursor without client delimiter directives."""
    span = _span_at_cursor(source, cursor_position)
    return span.sql if span is not None else ""


def current_statement_source(source: str, cursor_position: int) -> str:
    """Return the statement under the cursor with the delimiter context needed to execute it."""
    span = _span_at_cursor(source, cursor_position)
    if span is None:
        return ""
    if span.active_delimiter is not None:
        # Recreate only the client directive needed to preserve the statement's separator
        # semantics; do not include preceding statements from the full editor buffer.
        return f"DELIMITER {span.active_delimiter}\n{span.sql}"
    return span.sql

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


def _executable_sql_comment_bodies(source: str) -> list[str]:
    """Extract MySQL/MariaDB executable-comment bodies without scanning string literals.

    MySQL /*! ... */ comments and MariaDB /*M! ... */ comments can contain SQL that the
    server executes. Treat them separately for the risk advisory instead of masking them
    like ordinary comments. The server remains authoritative on version-specific behavior.
    """
    bodies: list[str] = []
    length = len(source)
    i = 0

    while i < length:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < length else ""

        if ch in {"'", '"', chr(96)}:
            quote = ch
            i += 1
            while i < length:
                current = source[i]
                following = source[i + 1] if i + 1 < length else ""
                if quote != chr(96) and current == "\\" and i + 1 < length:
                    i += 2
                    continue
                if current == quote:
                    if following == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue

        if ch == "#" or (
            ch == "-" and nxt == "-"
            and (i + 2 >= length or source[i + 2].isspace())
        ):
            newline = source.find("\n", i + (1 if ch == "#" else 2))
            i = length if newline < 0 else newline + 1
            continue

        if ch == "/" and nxt == "*":
            mysql_comment = source.startswith("/*!", i)
            mariadb_comment = source[i:i + 4].upper() == "/*M!"
            body_start = i + (3 if mysql_comment else 4 if mariadb_comment else 2)
            end = source.find("*/", body_start)
            if end < 0:
                break
            if mysql_comment or mariadb_comment:
                bodies.append(source[body_start:end])
            i = end + 2
            continue

        i += 1

    return bodies


def _classify_statement_core(sql: str) -> tuple[str, str]:
    """Classify the visible outer statement without recursively inspecting comments."""
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


def classify_statement(sql: str) -> tuple[str, str]:
    """Conservative SQL advisory, including executable comments and CTE-wrapped DML.

    Ordinary strings/comments are excluded. MySQL/MariaDB executable comments are inspected
    independently because the server may execute SQL embedded inside them. This is guidance,
    not authorization; MySQL privileges remain the enforcement boundary.
    """
    base_risk, base_message = _classify_statement_core(sql)
    risk_rank = {"low": 0, "medium": 1, "high": 2}
    highest_risk, highest_message = base_risk, base_message

    for body in _executable_sql_comment_bodies(sql):
        comment_risk, comment_message = _classify_statement_core(body)
        if risk_rank[comment_risk] > risk_rank[highest_risk]:
            highest_risk = comment_risk
            highest_message = f"Executable MySQL/MariaDB comment: {comment_message}"

    return highest_risk, highest_message

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
