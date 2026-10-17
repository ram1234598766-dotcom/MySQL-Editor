from mysql_editor.core import (
    classify_statement, current_statement, redact_secrets, split_sql_statements,
    unsupported_delimiter_directive_line, unsupported_delimiter_message,
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


def test_risk_advisory_ignores_quoted_identifiers_and_comment_keywords():
    assert classify_statement("UPDATE " + chr(96) + "where" + chr(96) + " SET value = 1")[0] == "high"
    assert classify_statement("SELECT 'DROP TABLE users' /* UPDATE users */")[0] == "low"


def test_unsupported_delimiter_directive_is_detected_with_line_number():
    source = (
        "SELECT 1;\\n"
        "DELIMITER $$\\n"
        "CREATE PROCEDURE refresh_stats()\\n"
        "BEGIN\\n"
        "  SELECT 2;\\n"
        "END$$"
    )
    assert unsupported_delimiter_directive_line(source) == 2
    message = unsupported_delimiter_message(source)
    assert message is not None
    assert "line 2" in message
    assert "entire script was rejected" in message
    assert "no part was submitted" in message


def test_delimiter_like_text_in_comments_and_literals_is_not_a_directive():
    source = (
        "SELECT 'literal start\\nDELIMITER $$';\\n"
        "-- DELIMITER //\\n"
        "/* comment line\\nDELIMITER !\\n*/\\n"
        "SELECT delimiter FROM example_table;"
    )
    assert unsupported_delimiter_directive_line(source) is None
    assert unsupported_delimiter_message(source) is None


def test_delimiter_word_inside_an_unfinished_sql_statement_is_not_a_client_command():
    source = "SELECT\\n  DELIMITER AS a_column\\nFROM example_table;"
    assert unsupported_delimiter_directive_line(source) is None


def test_regular_sql_with_comments_before_delimiter_line_is_still_detected():
    source = "SELECT 1;\\n-- next client command\\n  delimiter //\\n"
    assert unsupported_delimiter_directive_line(source) == 3
