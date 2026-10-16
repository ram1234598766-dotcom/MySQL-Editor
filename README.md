# MySQL Editor — Windows Desktop

MySQL Editor is a clean-room, native Windows desktop SQL workspace for MySQL. The independent product lives under src/mysql_editor and does not import or use components from the legacy MySQL IDLE application.

**This rebuild targets Windows desktop only. Android APK/AAB, the mobile companion, cloud relay, and cross-device account/password synchronization are out of scope for this phase.**

## Implemented in this branch

- Native PySide6/Qt shell with horizontal workspace navigation, resizable editor/results and schema inspector, SQL tabs, syntax highlighting, line numbers and results grid.
- Animated guided tour available from the workspace header, the connection dialog, and Help (F1); the tour can insert a real sample SELECT into the editor.
- First launch creates a local master password. Later launches request only that master password, then auto-reconnect to the last remembered MySQL profile using Windows Credential Manager when the saved password is available; missing/stale credentials fall back to the connection form.
- Argon2id master-password verifier, local settings database and Windows Credential Manager-only saved-password adapter.
- mysql-connector-python direct server access, configurable TLS choices and finite connection/read/write timeouts.
- Dedicated database worker thread so SQL execution and schema navigation do not run on the Qt UI event loop.
- Multi-statement query execution, statement/selection/script run actions, SQL formatter and Explain SELECT.
- Schema navigation for databases, tables and views; double-click tables for a capped preview.
- Result switching between statements, sortable result grid, copy selected cells, bounded preview and CSV export of the fetched result set.
- Commit and rollback controls, high-impact SQL warnings, opt-in local query history, saved SQL snippets, open/save SQL files.
- Product-specific PyInstaller onedir spec, portable executable build, original-logo multi-size ICO plus setup-wizard artwork, and Inno Setup installer with the desktop shortcut enabled by default. The CI pipeline exercises unit/integration tests and installer install/uninstall.
- Remembers window geometry, split-pane sizes, the active inspector tab, and SQL-editor font size for the current Windows user; editor font size can be changed from the View menu.
- Handles SQL-file open/save errors inside the app without discarding the current buffer, and writes CSV exports atomically so an interrupted export preserves any previous destination file.

This is a development implementation, not yet a release-approved or manually QA-certified binary. Review the workflow results and test the installer on a clean Windows account before distributing it.

## Architecture

- src/mysql_editor/core.py — SQL boundaries, risk advisories, formatting and redaction.
- src/mysql_editor/storage.py — local versioned SQLite metadata, history, Argon2id verifier and Credential Manager.
- src/mysql_editor/database.py — background thread, MySQL operations, result spool and CSV export.
- src/mysql_editor/ui/editor.py — editor widget and syntax highlighter.
- src/mysql_editor/ui/connection_dialog.py — connection and first-run lock dialog.
- src/mysql_editor/ui/main_window.py — query tabs, result picker, schema/history/snippets and transaction controls.
- src/mysql_editor/app.py — startup and shared product theme.

The application connects directly from the user's computer to the configured MySQL server. It does not require a web account, cloud relay or companion service.

## Requirements

- Windows 10/11 x64 for packaged use.
- A reachable MySQL server and credentials with only the permissions needed for the user's work.
- Python 3.12–3.14 for running from source.
- Windows Credential Manager to persist database passwords.

## Run from source

From PowerShell at the repository root:

~~~powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python tools/build_brand_assets.py
python -m mysql_editor
~~~

The app begins in the Connect to MySQL dialog. On first launch, create the local master password and enter it again to confirm. This is a local app lock, not a MySQL credential and not a password shared with Android or another device.

## Build Windows packages

Build on Windows x64 with Inno Setup installed. Run the branding step before launching from source to generate the transparent logo PNG and the multi-size Windows icon:

~~~powershell
python -m pip install -e ".[dev]" pyinstaller
python tools/build_brand_assets.py
python -m PyInstaller --clean --noconfirm pyinstaller/mysql_editor.spec
python -m PyInstaller --clean --noconfirm --onefile --windowed --name MySQLEditor-Portable --icon assets/mysql-editor.ico --add-data "assets/mysql-editor-logo.webp;assets" --add-data "assets/mysql-editor.ico;assets" --paths src src/mysql_editor/__main__.py
iscc installer/MySQLEditor.iss
~~~

Expected outputs: dist/MySQLEditor/ (onedir package), dist/MySQLEditor-Portable.exe, dist/installer/MySQLEditor-Setup.exe, dist/MySQLEditor-Folder.zip, dist/SHA256SUMS, a CycloneDX SBOM, a third-party license inventory, release notes, and a Windows signing-status note. The setup wizard and desktop icon are derived from the tracked logo.

## Repository agent skills and AI review

Project-local skills live in `.agents/skills/` and cover surgical coding practices, Qt desktop UX/accessibility, MySQL security, CodeRabbit review, and Windows release verification. `AGENTS.md` contains always-on repository rules, while `.coderabbit.yaml` supplies repository-specific path instructions for automated pull-request review. These are development tools and documentation; they are not runtime app dependencies.

Use the skill that matches the changed subsystem and verify the change with a regression test. Base44 web-app workflows and NVIDIA GPU tooling are not part of this native PySide6 Windows product.

## Security and local data

- Database passwords are not stored in SQLite, SQL files, query history or ordinary logs.
- Saved passwords are only written through Windows Credential Manager. If that backend is unavailable, the app has no plaintext fallback.
- The master password is stored as an Argon2id verifier. It unlocks this installation only and does not synchronize.
- Query history is off by default. If enabled, SQL text, profile label, result status, duration and timestamp are stored locally; disabling history clears it.
- Automatic TLS negotiates encryption when supported but does not verify server identity. Strict mode verifies certificate and hostname; Disabled is an explicit option for trusted local networks only.
- SQL danger prompts are advisory and cannot replace server-side grants, least-privilege accounts or backups.
- Result previews are capped, while fetched result rows are session-spooled for CSV export. Treat local result data and exported CSVs as sensitive.
- No telemetry is included.

See SECURITY.md and PRIVACY_POLICY.md.

## Quality checks

~~~powershell
python -m ruff check src tests tools
python -m compileall -q src tests tools
python -m pytest
~~~

The CI workflow runs lint, compilation and unit tests on Python 3.12–3.14, and checks for legacy application imports. A separate integration job runs query execution, schema inspection, transaction rollback and CSV export against a disposable MySQL 8.4 container. Windows CI runs an offscreen Qt UI smoke test for saved preferences and file-error recovery, builds the onedir package, portable executable and installer, smoke-launches the apps, and exercises a silent install/uninstall cycle. Release packages include a CycloneDX SBOM, third-party license inventory, release notes, signing-status note and SHA-256 manifest. Manual testing remains necessary for high-DPI layout, upgrade behavior and Windows Credential Manager.

## Known v1 limitations

- MySQL DELIMITER directives and compound stored-program bodies are not supported by the initial statement splitter.
- Table preview is limited to 1,000 rows. The result grid previews up to 2,000 rows per result, while CSV export includes all rows fetched into the current session spool.
- Query cancellation is best-effort and does not guarantee immediate server-side cancellation.
- Some DDL implicitly commits on MySQL, regardless of application transaction controls.
- The repository's tracked logo image is the asset source. The build creates an alpha-bearing PNG by making edge-connected near-white background pixels transparent while preserving enclosed white artwork; the original source remains unchanged. Icon resizing cannot add information missing from the source image.

## References

- Repository: https://github.com/ram1234598766-dotcom/MySQL-Editor
- Clean-room plan: DESKTOP_REBUILD_PLAN.md
- Qt for Python: https://doc.qt.io/qtforpython-6/
- MySQL Connector/Python: https://dev.mysql.com/doc/connector-python/en/
