"""Privacy-conscious SQL productivity helpers shared by MySQL IDLE features.

The formatter is deliberately conservative: it changes keyword case and layout
outside quoted strings, quoted identifiers, and comments; it does not parse or
rewrite SQL expressions. EXPLAIN is limited to one SELECT statement.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable

MAX_SNIPPETS = 100
MAX_SNIPPET_NAME = 80
MAX_SNIPPET_SQL_BYTES = 256 * 1024

_KEYWORDS = """
ALL ALTER AND AS ASC BETWEEN BY CASE CAST COLLATE CROSS CURRENT_DATE CURRENT_TIME
CURRENT_TIMESTAMP DATABASE DATABASES DESC DISTINCT ELSE END ESCAPE EXISTS FALSE
FETCH FIRST FOR FROM FULL GROUP GROUPING HAVING IN INNER INTERSECT IS JOIN LEFT
LIKE LIMIT NATURAL NOT NULL OFFSET ON OR ORDER OUTER OVER PARTITION RIGHT ROLLUP
SELECT SET SHOW TABLES THEN TRUE UNION UNKNOWN USE USING VALUES WHEN WHERE WITH
""".split()
_KEYWORD_RE = re.compile(r"\b(?:" + "|".join(sorted(_KEYWORDS, key=len, reverse=True)) + r")\b", re.I)
_CLAUSE_RE = re.compile(
    r"[ \t]+(?=(?:FROM|WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT|UNION(?:\s+ALL)?|"
    r"LEFT(?:\s+OUTER)?\s+JOIN|RIGHT(?:\s+OUTER)?\s+JOIN|INNER\s+JOIN|"
    r"CROSS\s+JOIN|JOIN)\b)",
    re.I,
)
_OPERATOR_RE = re.compile(r"[ \t]*(<=|>=|<>|!=|=|<|>)[ \t]*")


def _segments(sql: str) -> Iterable[tuple[str, str]]:
    """Split SQL into code, quoted literal/identifier, and comment segments."""
    i, n, code_start = 0, len(sql), 0
    while i < n:
        ch = sql[i]
        if ch in ("'", '"', "`"):
            if code_start < i:
                yield "code", sql[code_start:i]
            start, quote = i, ch
            i += 1
            while i < n:
                if sql[i] == "\\" and quote != "`":
                    i = min(n, i + 2)
                    continue
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            yield "opaque", sql[start:i]
            code_start = i
            continue
        if ch == "#" or (
            sql.startswith("--", i)
            and (i + 2 == n or sql[i + 2].isspace() or ord(sql[i + 2]) < 32)
        ):
            if code_start < i:
                yield "code", sql[code_start:i]
            start = i
            newline = sql.find("\n", i)
            i = n if newline < 0 else newline + 1
            yield "opaque", sql[start:i]
            code_start = i
            continue
        if sql.startswith("/*", i):
            if code_start < i:
                yield "code", sql[code_start:i]
            start = i
            end = sql.find("*/", i + 2)
            i = n if end < 0 else end + 2
            yield "opaque", sql[start:i]
            code_start = i
            continue
        i += 1
    if code_start < n:
        yield "code", sql[code_start:]


def _format_code(code: str) -> str:
    code = re.sub(r"\s+", " ", code)
    code = _KEYWORD_RE.sub(lambda match: match.group(0).upper(), code)
    code = _CLAUSE_RE.sub("\n", code)
    code = _OPERATOR_RE.sub(r" \1 ", code)
    code = re.sub(r",[ \t]*", ", ", code)
    code = re.sub(r"[ \t]+\n", "\n", code)
    code = re.sub(r"\n[ \t]+", "\n", code)
    code = re.sub(r"\n{2,}", "\n", code)
    return code


def format_sql(sql: str) -> str:
    """Format SQL without altering strings, backtick identifiers, or comments.

    This is a layout helper rather than a full SQL parser. It preserves the
    user's statement order and leaves each opaque segment byte-for-byte intact.
    """
    if not isinstance(sql, str):
        raise TypeError("SQL must be text.")
    if not sql.strip():
        return sql
    formatted = "".join(
        _format_code(text) if kind == "code" else text
        for kind, text in _segments(sql)
    )
    return formatted.strip()


def explain_sql(sql: str) -> str:
    """Wrap a single SELECT in EXPLAIN; reject writes and multiple statements."""
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("Enter a SELECT statement first.")
    code = "".join(text if kind == "code" else " " for kind, text in _segments(sql))
    code = code.strip()
    if not re.match(r"SELECT\b", code, re.I):
        raise ValueError("Explain Plan only accepts a single SELECT statement.")
    statement_code = code[:-1].rstrip() if code.endswith(";") else code
    if ";" in statement_code:
        raise ValueError("Explain Plan accepts one statement at a time.")
    # Insert EXPLAIN before the first actual SQL token, keeping leading comments
    # in place (especially line comments whose newline affects statement meaning).
    pieces = list(_segments(sql.strip()))
    output: list[str] = []
    inserted = False
    for kind, text in pieces:
        if not inserted and kind == "code":
            match = re.search(r"\S", text)
            if match:
                output.append(text[:match.start()])
                output.append("EXPLAIN ")
                output.append(text[match.start():])
                inserted = True
                continue
        output.append(text)
    if not inserted:
        raise ValueError("Could not locate the SELECT statement.")
    return "".join(output)


def load_snippets(path: str | os.PathLike[str]) -> dict[str, str]:
    """Load explicitly saved SQL snippets; missing or invalid files are ignored."""
    target = Path(path)
    try:
        if target.stat().st_size > 2 * 1024 * 1024:
            return {}
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    result: dict[str, str] = {}
    for name, sql in list(raw.items())[:MAX_SNIPPETS]:
        if (
            isinstance(name, str) and 0 < len(name.strip()) <= MAX_SNIPPET_NAME
            and isinstance(sql, str) and sql.strip()
            and len(sql.encode("utf-8")) <= MAX_SNIPPET_SQL_BYTES
        ):
            result[name.strip()] = sql
    return result


def save_snippets(path: str | os.PathLike[str], snippets: dict[str, str]) -> None:
    """Atomically save a bounded set of user-selected snippets."""
    if not isinstance(snippets, dict) or len(snippets) > MAX_SNIPPETS:
        raise ValueError(f"Save at most {MAX_SNIPPETS} SQL snippets.")
    cleaned: dict[str, str] = {}
    for name, sql in snippets.items():
        if not isinstance(name, str) or not 0 < len(name.strip()) <= MAX_SNIPPET_NAME:
            raise ValueError(f"Snippet names must be 1–{MAX_SNIPPET_NAME} characters.")
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("Snippet SQL cannot be empty.")
        if len(sql.encode("utf-8")) > MAX_SNIPPET_SQL_BYTES:
            raise ValueError("Snippet SQL exceeds the 256 KiB limit.")
        cleaned[name.strip()] = sql
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=target.parent,
            prefix=target.name + ".", suffix=".tmp", delete=False,
        ) as stream:
            temporary_name = stream.name
            json.dump(cleaned, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary_name, target)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
