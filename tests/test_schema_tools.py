"""Regression tests for safely generated schema-tree SQL."""
import pytest

from mysql_editor.ui.schema_tools import qualified_identifier, select_preview_sql


def test_qualified_identifier_quotes_schema_and_table_independently():
    assert qualified_identifier("customer db", "order`items") == "`customer db`.`order``items`"


def test_select_preview_sql_is_limited_and_never_executes_on_creation():
    assert select_preview_sql("app_db", "orders") == "SELECT *\nFROM `app_db`.`orders`\nLIMIT 1000;"
    assert select_preview_sql("odd`schema", "table with space", 25) == (
        "SELECT *\nFROM `odd``schema`.`table with space`\nLIMIT 25;"
    )


@pytest.mark.parametrize("limit", [0, -1, 10001, True, 1.5, "10"])
def test_select_preview_sql_rejects_invalid_or_unbounded_limits(limit):
    with pytest.raises(ValueError):
        select_preview_sql("app_db", "orders", limit)



def test_schema_status_message_handles_empty_and_missing_metadata_states():
    from mysql_editor.ui.schema_tools import schema_status_message

    assert schema_status_message({"ok": False}) == (
        "Schema metadata could not be loaded. Check the connection and try again."
    )
    assert schema_status_message({"ok": True, "databases": []}) == (
        "No databases are visible to this MySQL account."
    )
    assert schema_status_message({
        "ok": True, "databases": ["app_db", "analytics"], "schema": "",
    }) == "2 database(s) loaded. Select a database to inspect its tables and views."
    assert schema_status_message({
        "ok": True, "databases": ["app_db"], "schema": "missing",
    }) == "1 database(s) loaded. The active schema 'missing' is not in the visible database list."
    assert schema_status_message({
        "ok": True, "databases": ["app_db"], "schema": "app_db", "objects": [],
    }) == "No tables or views were found in 'app_db'."


def test_schema_status_message_reports_loaded_object_count():
    from mysql_editor.ui.schema_tools import schema_status_message

    message = schema_status_message({
        "ok": True,
        "databases": ["app_db", "analytics"],
        "schema": "app_db",
        "objects": [{"name": "customers"}, {"name": "orders"}],
    })

    assert message == "2 database(s) loaded · 2 table(s)/view(s) in 'app_db'."
