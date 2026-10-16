"""Focused tests for the feature-governance engine."""
import os
import unittest
from unittest.mock import patch

from feature_governor import FeatureGovernor, classify_sql


class SQLClassificationTests(unittest.TestCase):
    def test_safe_select_has_low_risk(self):
        result = classify_sql("SELECT id FROM accounts WHERE id = 3")
        self.assertEqual(result["risk"], "low")
        self.assertFalse(result["requires_confirmation"])

    def test_quoted_literals_and_comments_do_not_trigger_keywords(self):
        result = classify_sql("SELECT 'DROP TABLE users' AS note /* UPDATE t */")
        self.assertEqual(result["category"], "read")
        self.assertFalse(result["mutation"])

    def test_quoted_identifiers_do_not_trigger_keywords(self):
        sql = "SELECT " + chr(96) + "drop" + chr(96) + ", " + chr(96) + "update" + chr(96) + " FROM " + chr(96) + "table" + chr(96)
        self.assertEqual(classify_sql(sql)["risk"], "low")

    def test_drop_and_truncate_need_confirmation(self):
        for sql in ("DROP TABLE customers", "TRUNCATE TABLE customers", "ALTER TABLE customers ADD x INT"):
            with self.subTest(sql=sql):
                self.assertTrue(classify_sql(sql)["requires_confirmation"])

    def test_unqualified_update_and_delete_need_confirmation(self):
        self.assertTrue(classify_sql("UPDATE users SET active=0")["requires_confirmation"])
        self.assertTrue(classify_sql("DELETE FROM users")["requires_confirmation"])

    def test_where_clause_avoids_full_table_warning(self):
        self.assertFalse(classify_sql("DELETE FROM users WHERE id=7")["requires_confirmation"])
        self.assertFalse(classify_sql("UPDATE users SET active=0 WHERE id=7")["requires_confirmation"])

    def test_nested_subquery_where_does_not_hide_unqualified_update(self):
        result = classify_sql(
            "UPDATE users SET active=(SELECT 0 FROM flags WHERE flags.id=users.id)"
        )
        self.assertTrue(result["requires_confirmation"])

    def test_nested_subquery_where_does_not_hide_unqualified_delete(self):
        result = classify_sql(
            "DELETE FROM users WHERE id IN (SELECT user_id FROM blocked WHERE active=1)"
        )
        # Outer WHERE exists, so this is not an unqualified/full-table delete.
        self.assertFalse(result["requires_confirmation"])
        result = classify_sql(
            "DELETE FROM users /* marker */"
        )
        self.assertTrue(result["requires_confirmation"])

    def test_mysql_executable_comments_are_classified(self):
        result = classify_sql("/*!80000 DROP TABLE users */")
        self.assertTrue(result["requires_confirmation"])
        result = classify_sql("/*M!100100 TRUNCATE TABLE users */")
        self.assertTrue(result["requires_confirmation"])

    def test_stored_procedure_execution_requires_confirmation(self):
        result = classify_sql("CALL maintenance_task()")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["risk"], "high")

    def test_account_file_and_replication_operations_are_high_impact(self):
        for sql in (
            "SET PASSWORD FOR 'user'@'localhost' = 'example'",
            "CHANGE MASTER TO MASTER_HOST='db.example'",
            "RENAME TABLE users TO users_archive",
            "SELECT LOAD_FILE('/etc/passwd')",
        ):
            with self.subTest(sql=sql):
                self.assertTrue(classify_sql(sql)["requires_confirmation"])

    def test_read_only_blocks_session_set_and_account_password_changes(self):
        governor = FeatureGovernor({"read_only": True})
        self.assertEqual(governor.check_sql("SET @sample = 1")["decision"], "block")
        self.assertEqual(
            governor.check_sql("SET PASSWORD FOR 'user'@'localhost' = 'example'")["decision"],
            "block",
        )



    def test_second_statement_is_classified_independently(self):
        result = classify_sql("SELECT 1; DELETE FROM users")
        self.assertTrue(result["requires_confirmation"])



class GovernancePolicyTests(unittest.TestCase):
    def test_high_impact_approval_is_one_time(self):
        governor = FeatureGovernor()
        sql = "DROP TABLE carefully_named"
        self.assertEqual(governor.check_sql(sql)["decision"], "confirm")
        governor.approve_once(sql)
        self.assertEqual(governor.check_sql(sql)["decision"], "allow")
        self.assertEqual(governor.check_sql(sql)["decision"], "confirm")

    def test_read_only_blocks_mutations_but_allows_reads(self):
        governor = FeatureGovernor({"read_only": True})
        self.assertEqual(governor.check_sql("SELECT 1")["decision"], "allow")
        result = governor.check_sql("UPDATE users SET active=0 WHERE id=1")
        self.assertEqual(result["decision"], "block")
        self.assertEqual(governor.check_sql("COMMIT")["decision"], "block")

    def test_environment_read_only_cannot_be_disabled_in_ui(self):
        with patch.dict(os.environ, {"MYSQLIDLE_READ_ONLY": "1"}):
            governor = FeatureGovernor({"read_only": False})
            governor.set_policy(read_only=False)
            self.assertTrue(governor.read_only)

    def test_mobile_kill_switch_cannot_be_overridden_by_config(self):
        with patch.dict(os.environ, {"MYSQLIDLE_DISABLE_MOBILE": "1"}):
            governor = FeatureGovernor({"mobile_companion_enabled": True})
            governor.set_policy(mobile_companion_enabled=True)
            self.assertFalse(governor.feature_enabled("mobile_companion"))

    def test_audit_is_bounded_and_does_not_retain_raw_sql(self):
        governor = FeatureGovernor()
        secret_literal = "SELECT 'super-secret-value'"
        for i in range(300):
            governor.record_decision(secret_literal + f" /* {i} */", "allow", "test event")
        events = governor.audit_events(999)
        self.assertLessEqual(len(events), 256)
        self.assertTrue(all("statement_digest" in event for event in events))
        self.assertTrue(all("sql" not in event and "super-secret-value" not in str(event) for event in events))

    def test_approval_is_bound_to_exact_statement(self):
        governor = FeatureGovernor()
        governor.approve_once("DROP TABLE alpha")
        self.assertEqual(governor.check_sql("DROP TABLE beta")["decision"], "confirm")


if __name__ == "__main__":
    unittest.main(verbosity=2)
