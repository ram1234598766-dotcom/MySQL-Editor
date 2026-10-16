from mysql_editor.core import (
    classify_statement, current_statement, redact_secrets, split_sql_statements,
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
