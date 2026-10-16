"""Master-password hashing and storage for MySQL IDLE.

The password itself is never persisted. Only a salted PBKDF2-HMAC-SHA256
verifier is stored in the current Windows user's application-data directory.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000
MIN_ITERATIONS = 200_000
MAX_ITERATIONS = 1_000_000
SALT_BYTES = 16
DIGEST_BYTES = 32
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 1024


def create_password_record(password: str) -> dict[str, Any]:
    """Create a salted password verifier; do not return or store the raw password."""
    if not isinstance(password, str):
        raise TypeError("Password must be text.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Master password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"Master password must not exceed {MAX_PASSWORD_LENGTH} characters.")

    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=DIGEST_BYTES
    )
    return {
        "version": 1,
        "algorithm": ALGORITHM,
        "iterations": PBKDF2_ITERATIONS,
        "salt": salt.hex(),
        "digest": digest.hex(),
    }


def is_password_record(record: Any) -> bool:
    """Return True only for a supported and bounded stored verifier record."""
    if not isinstance(record, dict):
        return False
    if set(record) != {"version", "algorithm", "iterations", "salt", "digest"}:
        return False
    if type(record.get("version")) is not int or record.get("version") != 1:
        return False
    if record.get("algorithm") != ALGORITHM:
        return False
    iterations = record.get("iterations")
    if type(iterations) is not int or not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
        return False
    try:
        salt = bytes.fromhex(record["salt"])
        digest = bytes.fromhex(record["digest"])
    except (KeyError, TypeError, ValueError):
        return False
    return len(salt) == SALT_BYTES and len(digest) == DIGEST_BYTES


def verify_password(password: Any, record: Any) -> bool:
    """Constant-time compare a candidate password to a validated verifier."""
    if not isinstance(password, str) or len(password) > MAX_PASSWORD_LENGTH:
        return False
    if not is_password_record(record):
        return False
    salt = bytes.fromhex(record["salt"])
    expected = bytes.fromhex(record["digest"])
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, record["iterations"], dklen=DIGEST_BYTES
    )
    return hmac.compare_digest(actual, expected)


def load_password_record(path: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Load a verifier. Missing means first run; a corrupt file fails closed."""
    target = Path(path)
    if not target.exists():
        return None
    if not target.is_file():
        raise ValueError("Master-password verifier is not a regular file.")
    try:
        record = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Master-password verifier could not be read.") from exc
    if not is_password_record(record):
        raise ValueError("Master-password verifier is invalid or unsupported.")
    return record


def save_password_record(
    path: str | os.PathLike[str], password: str
) -> dict[str, Any]:
    """Atomically persist the verifier only, with restrictive POSIX mode where available."""
    target = Path(path)
    record = create_password_record(password)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
    )
    temp_path = Path(temp_name)
    try:
        if os.name != "nt":
            os.chmod(temp_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, ensure_ascii=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target)
        if os.name != "nt":
            os.chmod(target, 0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise
    return record
