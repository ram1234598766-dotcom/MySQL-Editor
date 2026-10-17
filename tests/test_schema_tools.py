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
