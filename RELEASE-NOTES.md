# MySQL Editor 0.1.0-alpha.1 — Release notes

**Status: pre-release. Windows packages are unsigned.** This is an initial clean-room desktop validation build, not a publisher-signed production release.

## Included

- New Windows-only PySide6 desktop SQL editor; Android/mobile project is excluded.
- MySQL connection dialog, SQL tabs/highlighting, background statement execution, schema browser and result grid.
- SQL formatting, Explain SELECT, result selection, sortable previews, CSV export, commit/rollback controls and saved SQL snippets.
- Local Argon2id master-password verifier, opt-in local query history, and Windows Credential Manager-only persistent database password saving.
- PyInstaller application-folder and portable packages, Inno Setup installer, and SHA-256 checksums.
- CI checks for Python 3.12–3.14, unit tests, a disposable MySQL 8.4 integration service, dependency audit, a CycloneDX SBOM, a third-party license inventory, and Windows startup/install/uninstall smoke checks.

## Known limitations

- MySQL DELIMITER directives and compound stored-program parsing are not implemented.
- Query safety checks are advisory; database permissions remain authoritative.
- Automatic TLS can encrypt traffic without authenticating the server. Use strict identity verification for remote/untrusted environments.
- The app has not been signed by a trusted publisher certificate. Windows SmartScreen may show an unknown-publisher warning.
- Manual testing on user Windows systems is still needed for high-DPI scaling, installer upgrades, remote-server TLS, and real credential-manager behavior.

## Install

Download MySQLEditor-Setup.exe for normal installation, or MySQLEditor-Portable.exe to launch without installing. Verify SHA-256 checksums before use. Create a local master password on first launch, then enter the host, port, username and MySQL password for the target database.

This pre-release contains no APK/AAB files or cross-device password synchronization.
