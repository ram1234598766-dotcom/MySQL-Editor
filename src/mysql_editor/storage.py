"""Versioned local persistence; database passwords never enter SQLite."""
from __future__ import annotations
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from platformdirs import user_data_dir

def app_data_dir() -> Path:
    path = Path(user_data_dir("MySQL Editor", "MySQL Editor"))
    path.mkdir(parents=True, exist_ok=True)
    return path

@dataclass(slots=True)
class ConnectionProfile:
    id: str
    name: str
    host: str = "127.0.0.1"
    port: int = 3306
    username: str = "root"
    default_schema: str = ""
    tls_mode: str = "Automatic TLS"
    ca_file: str = ""
    read_timeout: int = 60
    write_timeout: int = 30


def profile_to_dict(profile: ConnectionProfile) -> dict[str, Any]:
    """Return non-secret profile metadata for the UI."""
    return {
        "id": profile.id, "name": profile.name, "host": profile.host,
        "port": profile.port, "username": profile.username,
        "default_schema": profile.default_schema, "tls_mode": profile.tls_mode,
        "ca_file": profile.ca_file, "read_timeout": profile.read_timeout,
        "write_timeout": profile.write_timeout,
    }


def connection_config_from_profile(
    profile: ConnectionProfile, password: str,
) -> dict[str, Any]:
    """Build a one-session connect config; callers must obtain the password securely."""
    return {
        "profile_name": profile.name, "profile_id": profile.id,
        "host": profile.host, "port": profile.port, "username": profile.username,
        "password": password, "default_schema": profile.default_schema,
        "tls_mode": profile.tls_mode, "ca_file": profile.ca_file,
        "read_timeout": profile.read_timeout, "write_timeout": profile.write_timeout,
        "save_profile": True,
    }


class LocalRepository:
    """SQLite metadata store with migrations and no password-bearing columns."""
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "settings.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, timeout=5)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise RuntimeError("The settings database was created by a newer MySQL Editor version.")
        if version < 1:
            with self._db:
                self._db.executescript("""
                    CREATE TABLE IF NOT EXISTS profiles (
                        id TEXT PRIMARY KEY, name TEXT NOT NULL, host TEXT NOT NULL,
                        port INTEGER NOT NULL, username TEXT NOT NULL,
                        default_schema TEXT NOT NULL DEFAULT '',
                        tls_mode TEXT NOT NULL DEFAULT 'Automatic TLS',
                        ca_file TEXT NOT NULL DEFAULT '', read_timeout INTEGER NOT NULL DEFAULT 60,
                        write_timeout INTEGER NOT NULL DEFAULT 30,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS query_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, profile_name TEXT NOT NULL,
                        sql_text TEXT NOT NULL, duration_ms INTEGER NOT NULL,
                        status TEXT NOT NULL, created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS history_created_idx ON query_history(created_at DESC);
                    PRAGMA user_version=1;
                """)
                self._db.execute(
                    "INSERT OR IGNORE INTO settings(key,value) VALUES('query_history_enabled','false')"
                )

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
            )

    @property
    def has_master_password(self) -> bool:
        return bool(self.get_setting("master_password_hash"))

    def save_master_password_hash(self, digest: str) -> None:
        self.set_setting("master_password_hash", digest)

    def save_profile(self, profile: ConnectionProfile) -> None:
        now = self.now()
        with self._db:
            self._db.execute("""
                INSERT INTO profiles
                  (id,name,host,port,username,default_schema,tls_mode,ca_file,read_timeout,write_timeout,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name, host=excluded.host, port=excluded.port,
                  username=excluded.username, default_schema=excluded.default_schema,
                  tls_mode=excluded.tls_mode, ca_file=excluded.ca_file,
                  read_timeout=excluded.read_timeout, write_timeout=excluded.write_timeout,
                  updated_at=excluded.updated_at
            """, (profile.id, profile.name, profile.host, profile.port, profile.username,
                  profile.default_schema, profile.tls_mode, profile.ca_file, profile.read_timeout,
                  profile.write_timeout, now, now))

    def profiles(self) -> list[ConnectionProfile]:
        rows = self._db.execute("SELECT * FROM profiles ORDER BY name COLLATE NOCASE").fetchall()
        return [ConnectionProfile(
            id=row["id"], name=row["name"], host=row["host"], port=row["port"],
            username=row["username"], default_schema=row["default_schema"],
            tls_mode=row["tls_mode"], ca_file=row["ca_file"],
            read_timeout=row["read_timeout"], write_timeout=row["write_timeout"]
        ) for row in rows]

    def delete_profile(self, profile_id: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM profiles WHERE id=?", (profile_id,))

    def history_enabled(self) -> bool:
        return self.get_setting("query_history_enabled", "false") == "true"

    def set_history_enabled(self, enabled: bool) -> None:
        self.set_setting("query_history_enabled", "true" if enabled else "false")
        if not enabled:
            with self._db:
                self._db.execute("DELETE FROM query_history")

    def add_history(self, profile_name: str, sql_text: str, duration_ms: int, status: str) -> None:
        if not self.history_enabled():
            return
        with self._db:
            self._db.execute(
                "INSERT INTO query_history(profile_name,sql_text,duration_ms,status,created_at) VALUES(?,?,?,?,?)",
                (profile_name, sql_text, duration_ms, status, self.now())
            )
            self._db.execute("DELETE FROM query_history WHERE id NOT IN "
                             "(SELECT id FROM query_history ORDER BY id DESC LIMIT 500)")

    def history(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.history_enabled():
            return []
        rows = self._db.execute(
            "SELECT profile_name,sql_text,duration_ms,status,created_at FROM query_history "
            "ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)
        ).fetchall()
        return [dict(row) for row in rows]

class MasterPasswordStore:
    """Argon2id verifier; the actual passphrase is never persisted."""
    def __init__(self, repository: LocalRepository) -> None:
        self.repository = repository
        self._hasher = PasswordHasher()

    @staticmethod
    def validate(password: str) -> None:
        if len(password) < 10:
            raise ValueError("Use at least 10 characters for the local master password.")

    def create(self, password: str, confirmation: str) -> None:
        self.validate(password)
        if password != confirmation:
            raise ValueError("The master password and confirmation do not match.")
        self.repository.save_master_password_hash(self._hasher.hash(password))

    def verify(self, password: str) -> bool:
        digest = self.repository.get_setting("master_password_hash")
        if not digest:
            return False
        try:
            return self._hasher.verify(digest, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

class CredentialStore:
    """Windows Credential Manager adapter; never falls back to plaintext."""
    SERVICE = "MySQLEditor"

    @staticmethod
    def _backend():
        import platform
        import keyring
        if platform.system() != "Windows":
            raise RuntimeError("Saved database passwords require Windows Credential Manager.")
        backend = keyring.get_keyring()
        if "WinVaultKeyring" not in type(backend).__name__:
            raise RuntimeError("Windows Credential Manager is unavailable; database passwords were not saved.")
        return keyring

    def save(self, profile_id: str, password: str) -> None:
        self._backend().set_password(self.SERVICE, profile_id, password)

    def read(self, profile_id: str) -> str | None:
        return self._backend().get_password(self.SERVICE, profile_id)

    def delete(self, profile_id: str) -> None:
        keyring = self._backend()
        try:
            keyring.delete_password(self.SERVICE, profile_id)
        except keyring.errors.PasswordDeleteError:
            pass

def new_profile_id() -> str:
    return secrets.token_hex(12)
