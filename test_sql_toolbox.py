"""Regression tests for SQL toolbox behavior and cross-platform UI wiring."""
import tempfile
import unittest
from pathlib import Path

from sql_toolbox import explain_sql, format_sql, load_snippets, save_snippets


class SqlFormatterTests(unittest.TestCase):
    def test_formats_clauses_and_keywords(self):
        formatted = format_sql("select id, name from users where active=1 order by name;")
        self.assertEqual(formatted, "SELECT id, name\nFROM users\nWHERE active = 1\nORDER BY name;")

    def test_literals_backticks_and_comments_are_not_rewritten(self):
        sql = "select 'from where; it''s fine' as `select` from users -- order by private\nwhere name='select';"
        formatted = format_sql(sql)
        self.assertIn("'from where; it''s fine'", formatted)
        self.assertIn("`select`", formatted)
        self.assertIn("-- order by private\n", formatted)
        self.assertIn("WHERE name = 'select';", formatted)

    def test_empty_and_whitespace_input_is_stable(self):
        self.assertEqual(format_sql(""), "")
        self.assertEqual(format_sql("  \n  "), "  \n  ")


class ExplainSqlTests(unittest.TestCase):
    def test_explain_accepts_single_select_and_preserves_literal_semicolons(self):
        self.assertEqual(explain_sql("SELECT 'a;b' FROM sample;"), "EXPLAIN SELECT 'a;b' FROM sample;")

    def test_explain_preserves_leading_line_comments(self):
        self.assertEqual(
            explain_sql("-- review this query\nSELECT 1;"),
            "-- review this query\nEXPLAIN SELECT 1;",
        )

    def test_explain_rejects_writes_and_multiple_statements(self):
        for sql in ("UPDATE users SET enabled=0", "DROP TABLE users", "SELECT 1; SELECT 2;"):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                explain_sql(sql)

    def test_explain_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            explain_sql("  ")


class SavedSnippetTests(unittest.TestCase):
    def test_round_trip_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "snippets.json"
            self.assertEqual(load_snippets(path), {})
            snippets = {"Server version": "SELECT VERSION();", "Tables": "SHOW TABLES;"}
            save_snippets(path, snippets)
            self.assertEqual(load_snippets(path), snippets)
            self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_saving_enforces_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snippets.json"
            with self.assertRaises(ValueError):
                save_snippets(path, {"": "SELECT 1;"})
            with self.assertRaises(ValueError):
                save_snippets(path, {"empty": " "})

    def test_corrupt_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snippets.json"
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(load_snippets(path), {})


class FeatureWiringTests(unittest.TestCase):
    def test_desktop_and_mobile_expose_toolbox_actions(self):
        root = Path(__file__).resolve().parent
        desktop = (root / "mysql_idle.py").read_text(encoding="utf-8")
        mobile = (root / "mobile_companion.py").read_text(encoding="utf-8")
        for marker in ("format_current_sql", "explain_current_sql", "save_sql_snippet", "insert_sql_snippet"):
            self.assertIn(marker, desktop)
        for marker in ('id="formatSqlBtn"', 'id="explainSqlBtn"', 'id="copySqlBtn"', 'id="saveSnippetBtn"'):
            self.assertIn(marker, mobile)


if __name__ == "__main__":
    unittest.main(verbosity=2)
