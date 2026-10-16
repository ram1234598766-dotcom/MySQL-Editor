---
name: mysql-security-review
description: "Use when changing connection profiles, TLS, credentials, query history, SQL execution, database errors, result caching, or CSV export."
---

# MySQL and Local-Data Security Review

- Database passwords may only be stored via Windows Credential Manager. Never add a plaintext fallback or put passwords in profile metadata, SQLite, logs, test artifacts, or saved snippets.
- Master-password verification uses Argon2id. The local app lock is device-local and must not be described as account synchronization.
- Keep query history off by default. Redact common MySQL account/password syntax before any history persistence.
- Explain TLS correctly: automatic TLS can encrypt without verifying server identity; strict mode verifies certificate and hostname; disabled TLS is an explicit choice for trusted local use.
- Validate/quote identifiers before composing SQL. Prefer parameterized values wherever SQL syntax permits.
- SQL safety prompts are guidance only. MySQL grants and least-privilege accounts remain the enforcement boundary.
- Treat temporary result databases and CSV exports as sensitive. Clean temporary data on success and failure.
- Write exports to a temporary file and atomically replace the destination only after the export completes; a failed export must not corrupt a previous file.
- Redact credential-like fragments from user-visible errors. Never state that redaction catches every possible secret pattern.
- Add tests covering rejected TLS modes, secret redaction, failed operations, rollback, and export cleanup.
