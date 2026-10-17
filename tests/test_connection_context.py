"""Tests for password-free connection identity and query-tab binding."""
from mysql_editor.ui.connection_context import (
    build_connection_context,
    connection_context_label,
    connection_context_matches,
)


def _context(**changes):
    profile = {"id": "profile-a", "name": "Development", "host": "db.example", "port": 3306, "username": "reporter"}
    config = {"host": "db.example", "port": 3306, "username": "reporter",
              "default_schema": "analytics", "tls_mode": "Automatic TLS", "password": "never-copy-me"}
    result = {"database": "analytics", "server_version": "8.4"}
    if "profile" in changes:
        profile.update(changes.pop("profile"))
    config.update(changes)
    return build_connection_context(profile, config, result)


def test_connection_context_contains_display_information_but_no_credentials():
    context = _context()
    assert context == {
        "profile_id": "profile-a",
        "profile_name": "Development",
        "host": "db.example",
        "port": 3306,
        "username": "reporter",
        "schema": "analytics",
        "tls_mode": "Automatic TLS",
    }
    assert "password" not in context
    assert "never-copy-me" not in repr(context)


def test_connection_context_matches_normalized_same_endpoint():
    first = _context()
    equivalent = dict(first, host="DB.EXAMPLE", port="3306", username="REPORTER")
    assert connection_context_matches(first, equivalent)


def test_connection_context_mismatch_requires_confirmation_for_profile_or_endpoint_changes():
    first = _context()
    assert not connection_context_matches(first, _context(profile={"id": "profile-b"}))
    assert not connection_context_matches(first, _context(host="another.example"))
    assert not connection_context_matches(first, _context(port=3307))
    assert not connection_context_matches(first, _context(username="admin"))
    assert not connection_context_matches(first, _context(tls_mode="Verify server identity"))


def test_selected_schema_is_displayed_but_does_not_change_profile_identity():
    first = _context()
    other_schema = dict(first, schema="warehouse")
    assert connection_context_matches(first, other_schema)
    assert "warehouse" in connection_context_label(other_schema)
    assert "reporter@db.example:3306" in connection_context_label(other_schema)
    assert "never-copy-me" not in connection_context_label(other_schema)


def test_incomplete_context_is_not_considered_a_match():
    assert not connection_context_matches(None, _context())
    assert not connection_context_matches(_context(), None)
