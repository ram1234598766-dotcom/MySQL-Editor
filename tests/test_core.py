import pytest

import mysql_editor.core as core_module

from mysql_editor.core import (
    ScriptParseError, classify_statement, current_statement, current_statement_source,
    format_sql, iter_statement_spans, redact_secrets, sanitize_error_message, split_sql_statements,
)

def test_split_semicolons_respects_strings_and_comments():
    sql = "SELECT 'a;b'; SELECT 2 /* ; ignored */; SELECT \"c;d\";"
    assert split_sql_statements(sql) == [
        "SELECT 'a;b'", "SELECT 2 /* ; ignored */", 'SELECT "c;d"',
    ]

def test_split_handles_escaped_quotes():
    assert split_sql_statements("SELECT 'it\\'s; fine'; SELECT 2;") == [
        "SELECT 'it\\'s; fine'", "SELECT 2"
    ]

def test_current_statement_uses_cursor_position():
    text = "SELECT 1;\nSELECT 'two;still';\nSELECT 3;"
    position = text.index("'two") + 5
    assert current_statement(text, position) == "SELECT 'two;still'"

def test_risk_advisory_flags_destructive_or_unbounded_mutations():
    assert classify_statement("DROP TABLE users")[0] == "high"
    assert classify_statement("DELETE FROM users")[0] == "high"
    assert classify_statement("UPDATE users SET active=0")[0] == "high"
    assert classify_statement("UPDATE users SET active=0 WHERE id=4")[0] == "medium"
    assert classify_statement("SELECT * FROM users")[0] == "low"

def test_redaction_masks_credentials():
    output = redact_secrets("password=secret123 token: abcdef api_key=my-key")
    assert "secret123" not in output
    assert "abcdef" not in output
    assert "my-key" not in output


def test_current_statement_at_delimiter_and_trailing_whitespace():
    source = "SELECT 1;  \nSELECT 2;"
    assert current_statement(source, source.index(";") + 1) == "SELECT 1"
    assert current_statement(source, len(source)) == "SELECT 2"


def test_sql_history_redacts_mysql_account_password_syntax():
    from mysql_editor.core import redact_sql_secrets

    query = (
        "CREATE USER 'app'@'%' IDENTIFIED BY 'db-secret'; "
        "SET PASSWORD FOR 'app'@'%' = 'another-secret'; "
        "CREATE USER 'hash-user'@'%' IDENTIFIED WITH mysql_native_password AS '*HASHVALUE';"
    )
    safe = redact_sql_secrets(query)
    assert "db-secret" not in safe
    assert "another-secret" not in safe
    assert "*HASHVALUE" not in safe
    assert "FOR" in safe
    assert safe.count("[REDACTED]") >= 3


def test_key_value_redaction_masks_common_secret_assignments():
    from mysql_editor.core import redact_secrets

    result = redact_secrets("password=keep-out token: abcdef api_key=my-key")
    assert "keep-out" not in result
    assert "abcdef" not in result
    assert "my-key" not in result



def test_risk_advisory_does_not_treat_where_inside_string_as_a_clause():
    assert classify_statement("DELETE FROM users WHERE note = 'WHERE'")[0] == "medium"
    assert classify_statement("DELETE FROM users /* WHERE id = 1 */")[0] == "high"
    assert classify_statement("UPDATE users SET note = 'WHERE'")[0] == "high"


def test_risk_advisory_requires_outer_where_not_nested_subquery_where():
    query = "UPDATE users SET label = (SELECT label FROM labels WHERE id = 2)"
    assert classify_statement(query)[0] == "high"


def test_risk_advisory_understands_cte_wrapped_mutations():
    assert classify_statement(
        "WITH candidate AS (SELECT id FROM users) DELETE FROM users"
    )[0] == "high"
    assert classify_statement(
        "WITH candidate AS (SELECT id FROM users) "
        "DELETE FROM users WHERE id IN (SELECT id FROM candidate)"
    )[0] == "medium"



@pytest.mark.parametrize(
    "query",
    [
        "WITH candidate AS (SELECT id FROM users WHERE active=0) DELETE FROM users",
        "WITH candidate AS (SELECT id FROM users WHERE active=0) UPDATE users SET active=1",
        (
            "WITH RECURSIVE candidate(id) AS ("
            "SELECT id FROM users WHERE active=0 "
            "UNION ALL SELECT id FROM candidate WHERE id < 100"
            ") DELETE FROM users"
        ),
        (
            "WITH first_candidates AS (SELECT id FROM users WHERE active=0), "
            "second_candidates AS (SELECT id FROM first_candidates WHERE id > 10) "
            "DELETE FROM users"
        ),
    ],
)
def test_cte_internal_where_clauses_do_not_bound_outer_mutations(query):
    risk, message = classify_statement(query)

    assert risk == "high"
    assert "top-level WHERE clause" in message


def test_cte_with_top_level_where_stays_medium_despite_nested_where_clauses():
    query = (
        "WITH candidate AS (SELECT id FROM users WHERE active=0) "
        "UPDATE users SET active=1 WHERE id IN (SELECT id FROM candidate WHERE id > 10)"
    )

    assert classify_statement(query)[0] == "medium"


def test_risk_advisory_ignores_quoted_identifiers_and_comment_keywords():
    assert classify_statement("UPDATE " + chr(96) + "where" + chr(96) + " SET value = 1")[0] == "high"
    assert classify_statement("SELECT 'DROP TABLE users' /* UPDATE users */")[0] == "low"


def test_risk_advisory_detects_mutations_in_mysql_executable_comments():
    risk, message = classify_statement("/*!50000 DROP TABLE users */")
    assert risk == "high"
    assert "executable" in message.lower()

    risk, message = classify_statement("SELECT 1 /*!50000 DELETE FROM users */")
    assert risk == "high"
    assert "executable" in message.lower()


def test_risk_advisory_detects_mariadb_executable_comment_dml():
    unbounded, _message = classify_statement(
        "SELECT 1 /*M!100100 UPDATE users SET active=0 */"
    )
    bounded, message = classify_statement(
        "SELECT 1 /*M!100100 UPDATE users SET active=0 WHERE id=9 */"
    )

    assert unbounded == "high"
    assert bounded == "medium"
    assert "executable" in message.lower()


def test_risk_advisory_does_not_scan_executable_comment_markers_inside_strings_or_plain_comments():
    assert classify_statement(
        "SELECT '/*!50000 DROP TABLE users */' AS example"
    )[0] == "low"
    assert classify_statement(
        "SELECT 1 /* ordinary prose mentioning /*!50000 DROP TABLE users */ */"
    )[0] == "low"
    assert classify_statement(
        "SELECT 1 -- /*!50000 DROP TABLE users */\\n"
    )[0] == "low"



def test_split_supports_custom_delimiters_for_compound_stored_programs():
    source = (
        "DELIMITER //\n"
        "CREATE PROCEDURE example()\n"
        "BEGIN\n"
        "  SET @delimiter_probe = 'contains;semicolon';\n"
        "  SELECT @delimiter_probe;\n"
        "END//\n"
        "DELIMITER ;\n"
        "SELECT 7;"
    )

    spans = list(iter_statement_spans(source))

    assert [span.sql for span in spans] == [
        "CREATE PROCEDURE example()\n"
        "BEGIN\n"
        "  SET @delimiter_probe = 'contains;semicolon';\n"
        "  SELECT @delimiter_probe;\n"
        "END",
        "SELECT 7",
    ]
    assert source[spans[0].start:spans[0].end] == spans[0].sql
    assert source[spans[1].start:spans[1].end] == spans[1].sql
    assert "DELIMITER" not in "\n".join(span.sql for span in spans)


def test_split_supports_multiple_delimiter_changes_and_cursor_context():
    source = (
        "DELIMITER $$\n"
        "SELECT 1$$\n"
        "DELIMITER //\n"
        "SELECT 2//\n"
        "DELIMITER ;\n"
        "SELECT 3;"
    )

    assert split_sql_statements(source) == ["SELECT 1", "SELECT 2", "SELECT 3"]
    assert current_statement(source, source.index("SELECT 2") + 3) == "SELECT 2"


def test_delimiter_like_text_inside_literals_and_comments_is_not_a_directive():
    source = (
        "SELECT 'literal;\nDELIMITER $$\ncontinues';\n"
        "-- DELIMITER //\n"
        "/* comment line\nDELIMITER !\n*/\n"
        "SELECT delimiter FROM example_table;"
    )

    statements = split_sql_statements(source)

    assert len(statements) == 2
    assert "DELIMITER $$" in statements[0]
    assert "SELECT delimiter FROM example_table" in statements[1]
    assert "DELIMITER //" in statements[1]
    assert "DELIMITER !" in statements[1]


def test_delimiter_word_inside_an_unfinished_sql_statement_is_not_a_directive():
    source = "SELECT\n  DELIMITER AS a_column\nFROM example_table;"

    assert split_sql_statements(source) == [
        "SELECT\n  DELIMITER AS a_column\nFROM example_table"
    ]


def test_comments_before_a_standalone_delimiter_command_are_preserved():
    source = (
        "SELECT 1;\n"
        "-- next client command\n"
        "DELIMITER //\n"
        "SELECT 2//\n"
        "DELIMITER ;\n"
    )

    statements = split_sql_statements(source)

    assert statements[0] == "SELECT 1"
    assert "next client command" in statements[1]
    assert "SELECT 2" in statements[1]
    assert "DELIMITER" not in statements[1]


@pytest.mark.parametrize(
    ("source", "line"),
    [
        ("DELIMITER\nSELECT 1;", 1),
        ("SELECT 1;\nDELIMITER $$ extra\nSELECT 2;", 2),
        ("DELIMITER // -- trailing text\nSELECT 1//", 1),
        ("DELIMITER $$'bad\nSELECT 1$$", 1),
    ],
)
def test_malformed_delimiter_directive_fails_closed(source, line):
    with pytest.raises(ScriptParseError, match=f"line {line}") as caught:
        split_sql_statements(source)

    assert caught.value.line == line
    assert "script was not submitted" in str(caught.value).lower()


def test_compound_routine_without_an_early_delimiter_fails_closed():
    source = (
        "CREATE PROCEDURE example()\n"
        "BEGIN\n"
        "  SELECT 1;\n"
        "  DELIMITER $$\n"
        "END$$"
    )

    with pytest.raises(ScriptParseError, match="DELIMITER to be set before") as caught:
        split_sql_statements(source)

    assert caught.value.line == 1
    assert "script was not submitted" in str(caught.value).lower()


def test_current_statement_source_keeps_delimiter_context_for_routine_execution():
    source = (
        "DELIMITER //\n"
        "CREATE PROCEDURE example()\n"
        "BEGIN\n"
        "  SET @value = 'one;two';\n"
        "END//\n"
        "DELIMITER ;\n"
        "SELECT 7;"
    )
    position = source.index("CREATE PROCEDURE")

    assert current_statement(source, position).startswith("CREATE PROCEDURE")
    execution_source = current_statement_source(source, position)
    assert execution_source.startswith("DELIMITER //")
    assert len(split_sql_statements(execution_source)) == 1
    assert "CREATE PROCEDURE example()" in split_sql_statements(execution_source)[0]


def test_current_statement_source_does_not_include_previous_statements():
    source = (
        "DELIMITER //\n"
        "CREATE PROCEDURE example()\n"
        "BEGIN\n"
        "  SELECT 1;\n"
        "END//\n"
        "SELECT 2//"
    )
    position = source.index("SELECT 2")

    execution_source = current_statement_source(source, position)

    assert execution_source.startswith("DELIMITER //")
    assert "CREATE PROCEDURE" not in execution_source
    assert split_sql_statements(execution_source) == ["SELECT 2"]


def test_definer_routine_without_delimiter_fails_closed_even_without_spaces():
    source = (
        "CREATE DEFINER='routine_user'@'localhost' PROCEDURE example()\n"
        "BEGIN\n"
        "  SELECT 1;\n"
        "END"
    )

    with pytest.raises(ScriptParseError, match="DELIMITER to be set before") as caught:
        split_sql_statements(source)

    assert caught.value.line == 1

def test_sanitize_error_message_redacts_mysql_account_sql_and_key_value_secrets():
    message = (
        "Server error: CREATE USER 'app'@'%' IDENTIFIED BY 'account-secret'; "
        "SET PASSWORD FOR 'app'@'%' = 'password-secret'; "
        "password=kv-secret token: token-secret api_key=api-secret"
    )

    safe = sanitize_error_message(message)

    for secret in (
        "account-secret",
        "password-secret",
        "kv-secret",
        "token-secret",
        "api-secret",
    ):
        assert secret not in safe
    assert safe.count("[REDACTED]") >= 5
    assert "CREATE USER" in safe
    assert "IDENTIFIED BY" in safe


def test_sanitize_error_message_bounds_controls_empty_values_and_fallbacks():
    safe = sanitize_error_message(" driver error\x00\x01 password=hidden " + "x" * 100, limit=32)

    assert "hidden" not in safe
    assert "\x00" not in safe
    assert "\x01" not in safe
    assert len(safe) <= 33
    assert safe.endswith("…")
    assert sanitize_error_message(None, fallback="") == ""
    assert sanitize_error_message("  \x00  ", fallback="Safe fallback") == "Safe fallback"



@pytest.mark.parametrize(
    ("sql", "expected_risk"),
    [
        (
            "UPDATE users AS u JOIN flags AS f ON f.user_id = u.id "
            "SET u.active = 0 WHERE EXISTS "
            "(SELECT 1 FROM permissions p WHERE p.user_id = u.id)",
            "medium",
        ),
        (
            "WITH flagged AS (SELECT id FROM users WHERE active = 0) "
            "UPDATE users SET active = 1",
            "high",
        ),
        (
            "WITH flagged AS (SELECT id FROM users WHERE active = 0) "
            "DELETE FROM users WHERE id IN (SELECT id FROM flagged)",
            "medium",
        ),
        (
            "DELETE FROM users WHERE id IN "
            "(SELECT user_id FROM user_map WHERE active = 0)",
            "medium",
        ),
    ],
)
def test_parser_backed_mutation_advisory_uses_outer_where(sql, expected_risk):
    assert classify_statement(sql)[0] == expected_risk


def test_mutation_advisory_falls_back_when_sqlglot_is_unavailable(monkeypatch):
    monkeypatch.setattr(core_module, "_sqlglot_parse_one", None)

    assert classify_statement("DELETE FROM users")[0] == "high"
    assert classify_statement("UPDATE users SET active = 0 WHERE id = 5")[0] == "medium"


def test_parseable_mutations_use_sqlglot_ast_before_heuristic_fallback(monkeypatch):
    parsed_delete = core_module._sqlglot_parse_one("DELETE FROM users", read="mysql")
    assert isinstance(parsed_delete, core_module.sqlglot_exp.Delete), type(parsed_delete).__name__

    def fail_if_fallback(sql):
        pytest.fail(f"SQLGlot parsed the mutation, but the heuristic fallback ran: {sql}")

    monkeypatch.setattr(core_module, "_classify_statement_core_heuristic", fail_if_fallback)

    assert classify_statement("DELETE FROM users")[0] == "high"
    assert classify_statement("UPDATE users SET active = 0 WHERE id = 5")[0] == "medium"


def test_sqlglot_formatter_formats_multiple_statements_without_dropping_them():
    formatted = format_sql("select id,name from users where id=1; select count(*) from orders;")

    assert "SELECT" in formatted
    assert "FROM users" in formatted
    assert "COUNT(*)" in formatted
    assert formatted.count(";") == 2
    assert "\n\n" in formatted


def test_sqlglot_formatter_returns_empty_for_whitespace_only():
    assert format_sql("  \n\t ") == ""
