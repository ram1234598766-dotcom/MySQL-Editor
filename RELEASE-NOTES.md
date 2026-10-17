# MySQL Editor 0.1.0-alpha.1 — Release notes

**Status: pre-release. Windows packages are unsigned.** This is an initial clean-room desktop validation build, not a publisher-signed production release.

## Included

- New Windows-only PySide6 desktop SQL editor; Android/mobile project is excluded.
- MySQL connection dialog, SQL tabs/highlighting, background statement execution, schema browser and result grid.
- SQL formatting, Explain SELECT, result selection, sortable previews, CSV export, commit/rollback controls and saved SQL snippets.
- Local Argon2id master-password verifier, opt-in local query history, and Windows Credential Manager-only persistent database password saving.
- PyInstaller application-folder and portable packages, Inno Setup installer, and SHA-256 checksums.
- CI checks for Python 3.12–3.14, unit tests, a disposable MySQL 8.4 integration service, dependency audit, a CycloneDX SBOM, a third-party license inventory, and Windows startup/install/uninstall smoke checks.

## Quality improvements in the latest Windows preview

- Fixed the SQL editor's Qt import so `QTextEdit` is imported from `PySide6.QtWidgets`; Windows CI now imports the full application module before packaging.
- Added local persistence for window geometry, split-pane sizing, inspector selection, and SQL-editor font size.
- SQL file read/write failures now show recoverable dialogs and preserve the current editor buffer.
- Replaced modal Find/Replace prompts with an inline bar featuring match counts, case-sensitive search, previous/next navigation, Replace, and Replace all.
- Added a live editor status indicator for line, column, and selected character count.
- CSV exports are written to a temporary sibling file and atomically moved into place after a complete successful write; a failed export no longer truncates an existing destination.

## Known limitations

- MySQL DELIMITER directives and compound stored-program parsing are not implemented.
- Query safety checks are advisory; database permissions remain authoritative.
- Automatic TLS can encrypt traffic without authenticating the server. Use strict identity verification for remote/untrusted environments.
- The app has not been signed by a trusted publisher certificate. Windows SmartScreen may show an unknown-publisher warning.
- Manual testing on user Windows systems is still needed for high-DPI scaling, installer upgrades, remote-server TLS, and real credential-manager behavior.

## Install

Download MySQLEditor-Setup.exe for normal installation, or MySQLEditor-Portable.exe to launch without installing. Verify SHA-256 checksums before use. Create a local master password on first launch, then enter the host, port, username and MySQL password for the target database.

This pre-release contains no APK/AAB files or cross-device password synchronization.


## Workspace and onboarding refresh

- Replaced the fixed vertical left navigation with a horizontal workspace bar for SQL Editor, Connections, Schema Explorer, Query History, and Saved Queries.
- The editor/results boundary is a draggable vertical splitter and its ratio is remembered between launches. The schema inspector remains a separately resizable side panel.
- Added an animated multi-step guided tour (workspace header, connection form and Help → Guided tour / F1). The tour can insert an actual sample SELECT into the editor.
- After the first setup, startup asks for only the local master password and automatically reconnects to the last remembered profile when the password is available in Windows Credential Manager. If vault data is missing or MySQL rejects the saved password, the connection form is shown.
- The branded icon and UI assets now use an alpha-bearing PNG created by removing only edge-connected near-white matte pixels from the original artwork. Enclosed white artwork is preserved, and the tracked source logo remains unchanged.
