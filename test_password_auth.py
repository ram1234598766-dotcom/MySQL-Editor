"""Tests for shared Windows/Android master-password storage."""
import json
import tempfile
import unittest
from pathlib import Path

import password_auth


class PasswordAuthTests(unittest.TestCase):
    def test_password_record_verifies_without_storing_plaintext(self):
        password = "This is a test master password!"
        record = password_auth.create_password_record(password)
        self.assertTrue(password_auth.verify_password(password, record))
        self.assertFalse(password_auth.verify_password("a different password", record))
        self.assertNotIn(password, json.dumps(record))
        self.assertTrue(password_auth.is_password_record(record))

    def test_creation_rejects_weak_or_oversized_passwords(self):
        with self.assertRaises(ValueError):
            password_auth.create_password_record("short")
        with self.assertRaises(ValueError):
            password_auth.create_password_record("p" * (password_auth.MAX_PASSWORD_LENGTH + 1))

    def test_verification_fails_closed_for_malformed_records(self):
        self.assertFalse(password_auth.verify_password("correct password", None))
        record = password_auth.create_password_record("a sufficiently long password")
        tampered = dict(record, iterations=10_000_000_000)
        self.assertFalse(password_auth.verify_password("a sufficiently long password", tampered))
        tampered = dict(record, digest="00")
        self.assertFalse(password_auth.verify_password("a sufficiently long password", tampered))

    def test_verifier_is_saved_atomically_and_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "master_password.json"
            password = "Persistent master password"
            saved = password_auth.save_password_record(path, password)
            loaded = password_auth.load_password_record(path)
            self.assertEqual(loaded, saved)
            self.assertTrue(password_auth.verify_password(password, loaded))
            self.assertNotIn(password, path.read_text(encoding="utf-8"))
            self.assertIsNone(password_auth.load_password_record(Path(tmp) / "missing.json"))

    def test_corrupt_existing_file_does_not_trigger_first_run_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "master_password.json"
            path.write_text('{"password":"plaintext"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                password_auth.load_password_record(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
