"""Non-secret connection identity helpers for query-tab safety."""
from __future__ import annotations

from typing import Any


def build_connection_context(profile: dict[str, Any], config: dict[str, Any],
                             connect_result: dict[str, Any] | None = None) -> dict[str, str | int]:
    """Build the displayable connection context without copying credentials."""
    result = connect_result or {}
    try:
        port = int(config.get("port", profile.get("port", 3306)))
    except (TypeError, ValueError):
        port = 3306
    host = str(config.get("host") or profile.get("host") or "MySQL").strip()
    username = str(config.get("username") or profile.get("username") or "").strip()
    schema = str(config.get("default_schema") or result.get("database") or "").strip()
    return {
        "profile_id": str(profile.get("id") or "").strip(),
        "profile_name": str(profile.get("name") or "Connection").strip() or "Connection",
        "host": host or "MySQL",
        "port": port,
        "username": username,
        "schema": schema,
        "tls_mode": str(config.get("tls_mode") or "Automatic TLS").strip(),
    }


def connection_context_matches(left: dict[str, Any] | None,
                               right: dict[str, Any] | None) -> bool:
    """Compare server/profile identity, deliberately excluding the selected schema.

    Schema selection is a query context within a profile, while profile/endpoint/user/TLS
    changes require an explicit confirmation before sending an existing tab to that target.
    """
    if not left or not right:
        return False
    keys = ("profile_id", "host", "port", "username", "tls_mode")
    for key in keys:
        a, b = left.get(key), right.get(key)
        if key in {"host", "username", "tls_mode"}:
            a, b = str(a or "").strip().casefold(), str(b or "").strip().casefold()
        elif key == "port":
            try:
                a = int(a)
            except (TypeError, ValueError):
                a = 3306
            try:
                b = int(b)
            except (TypeError, ValueError):
                b = 3306
        else:
            a, b = str(a or "").strip(), str(b or "").strip()
        if a != b:
            return False
    return True


def connection_context_label(context: dict[str, Any] | None) -> str:
    """Return a concise, password-free label suitable for a tooltip or prompt."""
    if not context:
        return "an unknown connection"
    profile = str(context.get("profile_name") or "Connection")
    username = str(context.get("username") or "user")
    host = str(context.get("host") or "MySQL")
    try:
        port = int(context.get("port", 3306))
    except (TypeError, ValueError):
        port = 3306
    schema = str(context.get("schema") or "(no default schema)")
    tls = str(context.get("tls_mode") or "Automatic TLS")
    return f"{profile} · {username}@{host}:{port} · {schema} · {tls}"
