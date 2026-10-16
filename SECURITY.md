# Security policy — MySQL Editor desktop

## Scope

This policy covers the clean-room Windows desktop implementation under src/mysql_editor. The application connects directly from the user's computer to the configured MySQL server. It does not implement a mobile pairing service, cloud relay, telemetry endpoint or hosted account system.

## Reporting

Use GitHub's private vulnerability reporting feature where available, or open a minimal issue asking for a private channel. Do not post database passwords, production connection strings, tokens, customer data or query result rows publicly.

## Security controls and limits

- The local master password is stored as an Argon2id verifier, not reversibly. It protects this PC only and is not synchronized to other devices.
- Saved database passwords are stored through Windows Credential Manager only. No plaintext file fallback is available.
- Database passwords should never be pasted into SQL text or saved SQL files.
- TLS behavior is explicit. Automatic TLS may encrypt transport without verifying server identity. Strict mode enables certificate and hostname verification. Disabled TLS is an explicit choice for trusted local use only.
- Query history is opt-in and stores SQL text when enabled.
- The temporary result spool can contain the query's fetched rows. Treat the local app data directory and exports as potentially sensitive.
- Errors are redacted before display; query result contents are not emitted to telemetry because this build has no telemetry.
- High-impact SQL confirmations are advisory only. MySQL server grants and least-privilege accounts enforce database permissions.

## Recommended use

Use a dedicated least-privilege MySQL account, prefer identity-verified TLS on remote or untrusted networks, keep MySQL patched, back up data and review destructive SQL.

## Release checks

Build from reviewed source, audit dependencies, test packages on a clean Windows account and publish SHA-256 hashes. Only claim publisher verification after signing with a trusted code-signing certificate and verifying the final signature. CI success does not prove the install, upgrade and uninstall flows have been manually tested.
