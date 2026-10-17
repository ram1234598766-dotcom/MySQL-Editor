"""Safe SQL snippets generated from schema-tree object names."""
from __future__ import annotations

from mysql_editor.core import safe_identifier

MAX_GENERATED_PREVIEW_ROWS = 1000
MAX_ALLOWED_PREVIEW_ROWS = 10000


def qualified_identifier(schema: str, object_name: str) -> str:
    """Quote each identifier independently, including embedded backticks."""
    if not schema or not object_name:
        raise ValueError("Both schema and object names are required.")
    return f"{safe_identifier(schema)}.{safe_identifier(object_name)}"


def select_preview_sql(schema: str, table: str, limit: int = MAX_GENERATED_PREVIEW_ROWS) -> str:
    """Build a non-executing preview query with a validated bounded row limit."""
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("Preview row limit must be an integer.")
    if not 1 <= limit <= MAX_ALLOWED_PREVIEW_ROWS:
        raise ValueError(f"Preview row limit must be between 1 and {MAX_ALLOWED_PREVIEW_ROWS}.")
    return f"SELECT *\nFROM {qualified_identifier(schema, table)}\nLIMIT {limit};"


def schema_status_message(result: dict) -> str:
    """Return explicit, user-facing status text for a schema tree result."""
    if not result.get("ok"):
        return "Schema metadata could not be loaded. Check the connection and try again."

    databases = [str(name) for name in (result.get("databases") or [])]
    active_schema = str(result.get("schema") or "")
    objects = result.get("objects") or []

    if not databases:
        return "No databases are visible to this MySQL account."
    if not active_schema:
        return f"{len(databases):,} database(s) loaded. Select a database to inspect its tables and views."
    if active_schema not in databases:
        return (
            f"{len(databases):,} database(s) loaded. "
            f"The active schema {active_schema!r} is not in the visible database list."
        )
    if not objects:
        return f"No tables or views were found in {active_schema!r}."
    return (
        f"{len(databases):,} database(s) loaded · "
        f"{len(objects):,} table(s)/view(s) in {active_schema!r}."
    )
