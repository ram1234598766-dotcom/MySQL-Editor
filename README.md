# MySQL Editor

**A native Windows desktop SQL workspace for MySQL.**

MySQL Editor is a local-first desktop application for connecting to a MySQL server, writing and running SQL, exploring schemas, inspecting results, and exporting data. It is built with Python and PySide6/Qt. Its independent runtime lives under **src/mysql_editor/** and does not import components from the legacy MySQL IDLE application.

> **Project status: pre-release.** Automated tests and packaging checks do not replace testing on the Windows PC, MySQL version, authentication method, and network/TLS configuration you intend to use. Preview Windows packages are unsigned unless their release notes explicitly state otherwise.

## Contents

- [Highlights](#highlights)
- [UX and upgrade roadmap](#ux-and-upgrade-roadmap)
- [Platform and scope](#platform-and-scope)
- [Download a Windows build](#download-a-windows-build)
- [Quick start](#quick-start)
- [Connect to MySQL](#connect-to-mysql)
- [Work with SQL](#work-with-sql)
- [Results and CSV export](#results-and-csv-export)
- [Settings and preferences](#settings-and-preferences)
- [Schema, history, and snippets](#schema-history-and-snippets)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Security and privacy](#security-and-privacy)
- [Run from source](#run-from-source)
- [Build Windows packages](#build-windows-packages)
- [Testing and CI](#testing-and-ci)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)
- [Contributing](#contributing)
- [Project links](#project-links)

## Highlights

### Editing and navigation
- Horizontal workspace navigation for SQL Editor, Connections, Schema Explorer, Query History, and Saved Queries.
- Multiple SQL tabs with unsaved-change markers and a confirmation before discarding modified tabs.
- SQL syntax highlighting, line numbers, current-line highlighting, indentation, and a monospace font.
- A live editor position indicator shows line/column and selected character count; the active connection and unsaved-tab state remain visible.
- MySQL keyword/function completion plus suitable identifiers learned from the current schema and result-column names. Use **Ctrl+Space** to open completion on demand.
- SQL formatting, an inline Find/Replace bar with match counts and case-sensitive search, SQL-file open/save, and saved query snippets.
- Resizable editor/results and workspace/inspector panes. Window geometry, pane sizes, inspector tab, editor font family, and font size are stored locally.
- Animated five-step guided tour that can insert a sample SELECT into the editor.

### Database work
- Execute the statement under the cursor, highlighted SQL, or the whole script.
- Dedicated database worker thread keeps SQL execution and schema reads off the Qt UI event loop.
- Configurable connection TLS policy and finite connection/read/write timeouts.
- Explain SELECT runs an EXPLAIN version of the current SELECT statement.
- Schema tree for databases, tables, and views; double-click a table for a limited preview.
- Commit and Rollback controls, query history that is opt-in, and high-impact SQL confirmation prompts.

### Results and release engineering
- Switch between results returned by different statements in a script.
- Sortable result grid, numeric-aware sorting, NULL display, and copy-selected-cells support.
- Case-insensitive quick filter for visible rows. It changes the grid view only; it does not exclude rows from CSV export.
- Up to 2,000 rows per result are shown in the grid. Fetched result rows are also stored in a temporary local SQLite spool for CSV export.
- Atomic CSV export to help preserve an existing destination when a write fails.
- Windows application-folder build, portable EXE, Inno Setup installer, generated icons/setup branding, and desktop shortcut support.
- CI includes lint, compile checks, unit/integration tests, a Windows UI smoke test, launch tests, installer/uninstaller tests, and dependency auditing.
- Release workflow can include SHA-256 checksums, CycloneDX SBOM, third-party license inventory, release notes, and an explicit Windows signing-status note.

## UX and upgrade roadmap

The next planned quality phase is documented in **[UPGRADE_ROADMAP.md](UPGRADE_ROADMAP.md)**. It covers the visual design system, a restrained colour palette, reusable UI styling, smooth but purposeful animation, a Reduce Motion preference, deeper SQL-editor completion, clearer connection and schema workflows, improved result handling, accessibility, reliability, dependency compatibility, and staged Windows release verification.

The intended visual direction is a calm, modern database workspace: crisp logo rendering, consistent surfaces and spacing, one primary accent colour, readable SQL syntax colours, restrained gradients, and short transitions that never block work. The plan proposes motion tokens and explicit checks for keyboard focus, interrupted animations, high-DPI layouts, and result-grid performance.

**Roadmap status:** implementation is in progress. Shared dark-theme tokens, Reduce Motion controls, the inline Find/Replace bar, and live line/column/selection status are implemented with regression coverage; semantic completion refinements, deeper accessibility, and release verification remain roadmap work. Automated checks do not replace Windows visual QA. Keep the app Windows-desktop-only during this phase; Android, cloud relay, cross-device sync, ads, and telemetry remain out of scope.

## Platform and scope

| Item | Current scope |
|---|---|
| Packaged desktop app | Windows 10/11 x64 |
| Source development | Python 3.12–3.14 |
| Database | MySQL server reachable from this PC |
| UI framework | Python / PySide6 / Qt |
| Saved database passwords | Windows Credential Manager |
| Android APK/AAB | Not part of this desktop phase |
| Cloud account, relay, or cross-device password sync | Not implemented |
| Analytics, ads, or telemetry | Not included |

Python 3.15 is not listed as supported in this release line. A new Python release does not automatically make the complete driver, Qt, and packaging dependency chain compatible. The supported range should expand only after the connector, integration tests, and Windows packaging matrix pass.

## Download a Windows build

Open the [GitHub Releases page](https://github.com/ram1234598766-dotcom/MySQL-Editor/releases), select the specific release you intend to install, and read its release notes.

| File | Purpose |
|---|---|
| **MySQLEditor-Setup.exe** | Standard installer with Windows shortcuts and an uninstaller |
| **MySQLEditor-Portable.exe** | Single-file portable executable |
| **MySQLEditor-Folder.zip** | Application-folder package for advanced users or diagnostics |
| **SHA256SUMS** | SHA-256 hashes for the release files, when published |
| **sbom.cdx.json** | Software dependency inventory in CycloneDX format, when published |
| **THIRD_PARTY_LICENSES.md** | Third-party license inventory, when published |
| **WINDOWS_SIGNING.md** | Explicit signing status for that release |

### About Windows warnings

Unsigned preview builds can show an unknown-publisher or SmartScreen warning. Do not assume an artifact is trustworthy only because it is hosted on GitHub. Confirm the repository and release, review its notes, and check a published SHA-256 hash when available. A matching hash detects a file mismatch; it does not prove that software is safe.

A successful CI build does not mean the executable has been Authenticode signed. Publisher identity can only be established after signing with a trusted code-signing certificate and verifying the final file signature.

## Quick start

1. Download a Windows package from the Releases page and install or launch it.
2. At first launch, create a local master password and type it a second time to confirm. This is separate from the MySQL password.
3. Enter a profile name, host, port, MySQL username, password, and optional default schema.
4. Choose a TLS policy. Read the explanatory hint before connecting.
5. Select whether to remember the connection and save the database password to Windows Credential Manager.
6. Optionally use **Test connection** before connecting.
7. Connect, confirm the active server/schema, then start with a read-only SELECT until you have verified the context.

On later launches, MySQL Editor asks for the local master password. If a saved profile and Windows Credential Manager entry are available, it tries to reconnect. If the server is unreachable, the password is missing, or MySQL rejects it, use the connection dialog to correct the profile or enter the password again.

The master password unlocks this installation only. It is not an online account, it does not synchronize to another device, and it is not the encryption key for Windows Credential Manager.

## Connect to MySQL

The connection form supports a profile selector, profile name, host, port, username, password, default schema, TLS policy, optional CA certificate path, and read/write timeouts.

### Host and port
- Use **127.0.0.1** or **localhost** when a MySQL server is running on the same computer and accepts that connection.
- Use a DNS name or IP address reachable from this PC for a remote server.
- **3306** is the typical MySQL port, but use the port your server actually listens on.
- MySQL Editor is a client; it does not install or automatically start a database server.

### TLS policies

TLS affects transport confidentiality and server identity verification. These are different guarantees.

| Policy | Behavior | When to use it |
|---|---|---|
| **Automatic TLS** | Allows TLS negotiation where supported, but does not verify certificate and hostname identity in this mode. | Compatible development environments where you understand the trust model. |
| **Verify server identity** | Enables certificate and hostname verification. You can supply a CA file for a private certificate authority. | Preferred for remote servers and untrusted networks. |
| **Disabled** | Explicitly disables TLS. Traffic is not encrypted by this connection policy. | Only when you understand and accept the risk in a suitably trusted local/test environment. |

Do not disable certificate validation globally to hide an error. When strict verification fails, check the host name, certificate validity, trust chain, and CA file. A self-signed server certificate needs deliberate trust configuration when strict validation is required.

### Common connection causes
A server that is stopped, incorrect host/port, firewall rules, denied remote access, wrong credentials, missing permissions, an invalid default schema, or mismatched TLS settings can all prevent connection. MySQL Editor can display an error, but it cannot change server configuration or grant privileges.

Prefer a dedicated database account with only the permissions the work requires. Avoid using a root account for routine SQL work.

## Work with SQL

### Edit and organize queries
Use **New query** to create a tab. Open existing SQL files and save your current buffer as a file. Modified tabs show an unsaved marker and prompt before closing with unsaved changes.

Completion covers common MySQL keywords/functions and suitable identifiers discovered in the selected schema and result headers. Completion is an editing aid, not a semantic validator: the server remains authoritative on SQL syntax, objects, data types, and permissions.

### Run the right scope
- **Run statement** executes the statement associated with the editor cursor.
- **Run selection** executes the highlighted SQL.
- **Run script** executes the full editor buffer in order.
- **Format SQL** formats the selection when one exists, otherwise the whole buffer.
- **Explain SELECT** executes EXPLAIN for the SELECT under the cursor.

Before running a mutation, verify the active server and schema. High-impact statements may trigger a confirmation prompt. That prompt cannot guarantee that a query is safe: even a syntactically ordinary statement can lock a table, consume significant resources, expose sensitive data, or affect many rows.

### Transactions and cancellation
Commit and Rollback act on the active connection. Some MySQL statements, particularly many DDL operations, implicitly commit regardless of the application's transaction controls. Do not assume every operation can be undone with Rollback. Use backups and server-side privileges for important safety controls.

**Stop** sends a best-effort KILL QUERY request through a separate control connection. Permissions, network conditions, and server state affect whether it succeeds promptly. A request to cancel is not proof that the server stopped immediately; check the final state before retrying a mutation. The status strip separates queued/running/fetching states from completion. The UI reports “cancelled” only when MySQL returns an explicit interruption signal after a cancellation request. If a multi-statement script completes earlier statements before a later one fails, it is marked as a partial failure and retains the earlier result sets.

## Results and CSV export

A multi-statement script can create several result entries. Use the result picker to switch among them. The grid displays column headers and rows along with row-count and duration information where available.

- **Sorting** changes the order of the visible grid rows. Common numeric values use numeric-aware comparison. CSV export preserves the original server-fetch order, not the grid's current sort order.
- If the database session drops during a query, the connection badge changes to **Connection lost**, includes a reconnect hint, and the worker discards the dead session. Reconnect before sending more SQL; query tabs and buffers remain in place.
- **Quick filter** searches visible row cells case-insensitively. Clear the filter to show all rows in the current preview.
- **Copy selected cells** copies a tab-separated rectangular selection; tabs and newlines inside values are quoted so copied data stays parseable.
- **Copy selected rows** copies every column from each selected visible row; **Copy column headers** copies only selected columns' headers, or all headers when nothing is selected.
- **Cell details** opens a read-only view for long values, showing the column, row, and whether the value is SQL NULL, empty text, or non-empty text.
- **CSV export** uses rows fetched into the current session result spool, not just the visible grid. The 2,000-row display preview and active quick filter do not limit the exported fetched result set. CSV export retains fetch order even after sorting and filtering.
- **NULL** appears as **(NULL)** in the display and copies as the marker **NULL**. CSV follows standard empty-field output here: SQL NULL and an empty string both produce an empty field, so inspect cell details before exporting if this distinction matters to downstream processing.

The local result cache may contain sensitive database contents. Treat it, copied clipboard values, and CSV exports as sensitive. The temporary spool is intended for the current worker session and is removed during shutdown on a best-effort basis.

## Schema, history, and snippets

### Schema Explorer
Refresh the schema tree to read database names and table/view objects visible to the MySQL account. Double-click or press Enter on a schema to select it as the default schema for this workspace. Double-click or press Enter on a table/view to request a preview capped at 1,000 rows. Right-click a schema to refresh/select it or copy its name. Right-click a table/view to copy its safely quoted qualified identifier, open a limited `SELECT * ... LIMIT 1000` in a new unsaved query tab, or request a preview. Generated SQL is not executed automatically. The visible objects depend on the privileges of the connected user.

### Query History
Query history is **off by default**. It can be enabled in Settings. When enabled, SQL text, profile label, result status, duration, and timestamp are stored locally after heuristic redaction of common credential-like syntax. Redaction cannot guarantee that every possible secret or sensitive literal is detected. Avoid putting passwords, tokens, or confidential data directly in SQL text.

Disabling history clears saved query history. Do not enable it on a shared computer unless you are comfortable with the SQL that might remain in the Windows user's local data directory.

### Saved Queries
Save a useful statement as a SQL snippet and reopen it from Saved Queries. Snippets are ordinary local SQL files, not encrypted secret storage. Never put passwords, access tokens, or production secrets inside snippets.

## Keyboard shortcuts

Shortcuts can depend on which widget has focus.

| Shortcut | Action |
|---|---|
| **Ctrl+N** | New query tab |
| **Ctrl+O** | Open SQL file |
| **Ctrl+S** | Save current SQL file |
| **Ctrl+Shift+S** | Save SQL snippet |
| **Ctrl+F** | Open inline Find bar; Enter navigates matches |
| **Ctrl+H** | Open inline Find/Replace bar; Replace and Replace all are available |
| **Ctrl+Enter** | Run current statement |
| **Ctrl+Shift+Enter** | Run selected SQL |
| **Ctrl+Alt+Enter** | Run complete script |
| **Ctrl+Shift+F** | Format SQL |
| **Ctrl+Plus** | Increase editor font size |
| **Ctrl+Minus** | Decrease editor font size |
| **Ctrl+0** | Reset editor font size |
| **F5** | Refresh schema |
| **F1** | Open the guided tour |
| **Alt+F4** | Exit the application |

## Settings and preferences

The **Settings** menu groups working preferences by purpose:

- **Appearance:** choose System, Light, or Dark. Theme changes preserve SQL buffers, cursor/selection, current tabs, result filters, and splitter state. SQL syntax highlighting, line-number gutter, active-line shading, and bracket matching follow the selected palette. Reduce motion disables optional transitions while leaving status feedback intact.
- **Editor → SQL font family:** choose an installed monospace font. The family applies immediately to all open tabs and is remembered for new tabs; font size remains independent.
- **Editor → Tab width:** choose 2, 4, or 8 spaces. This changes the visual tab stop in all open and new query tabs; it does not rewrite existing SQL text.
- **Results → Row height:** choose Compact (24 px), Comfortable (28 px), or Spacious (36 px) for the results grid.
- **Query History:** history is opt-in and stored locally; disabling it clears the saved history. Use Clear query history when needed.

Tab width, font family, and result row height are validated when settings load. Missing or malformed values fall back to 4 spaces, Cascadia Code, and 28 px, respectively. Editor font size remains available under **View** and is persisted separately.

## Security and privacy

The **File → Recent SQL files** menu keeps a bounded list of local file paths to speed up reopening work. It stores path metadata only—not SQL text or query results. **Clear recent list** removes the paths from the menu and does not delete the source files. Missing files are marked and can be retried after restoring them.

### Local data
- Connection profile metadata—including host, port, username, default schema, TLS policy, CA path, and timeouts—is stored in the local settings database.
- The original master passphrase is not stored; only an Argon2id verifier is saved.
- Saved database passwords are sent through **Windows Credential Manager** when saving is enabled. They are not stored in SQLite, ordinary log files, query history, or saved snippets.
- If the Windows credential backend is unavailable, the application does not fall back to a plaintext password file.
- Opt-in query history stores SQL text and execution metadata after heuristic redaction.
- Saved snippets are ordinary local files.
- During query execution, a temporary SQLite spool stores fetched result rows so the app can display a bounded preview and export the fetched set.

### Master password versus database password
The master password is an application-session gate local to this PC. It is not a MySQL password, cloud identity, cross-device key, or encryption key for a Windows Credential Manager entry. Windows protects saved credentials under the Windows user account and operating system. Protect your Windows login and use appropriate device-lock and disk-encryption policies for sensitive databases.

### Network and telemetry
The app connects directly from this computer to the MySQL host and port selected by the user. This desktop implementation has no hosted account system, mandatory relay service, analytics endpoint, advertisements, or usage telemetry. SQL and credentials are sent to the database server subject to the selected protocol and TLS policy.

See **SECURITY.md** and **PRIVACY_POLICY.md** for policy details.

## Run from source

### Requirements
- Windows 10/11 x64 is the main development and packaging target.
- Python 3.12, 3.13, or 3.14.
- A reachable MySQL server for integration testing.
- Windows Credential Manager for persistent database-password saving.
- PowerShell for the commands below.

### Create a virtual environment

Run from the repository root:

~~~powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python tools/build_brand_assets.py
python -m mysql_editor
~~~

The branding script generates a transparent PNG logo and multi-size Windows icon from the tracked source asset. It leaves the original source image unchanged. Run it before launching from source or packaging if the generated assets are not present.

If PowerShell blocks activation, follow your organization's script policy or use the virtual environment's Python executable directly rather than changing machine-wide execution policy.

### Launch and local data
The module entry point is **python -m mysql_editor**. The installed console entry point is **mysql-editor**. Local settings and snippets live under the per-user data directory resolved by platformdirs. Query-result spools are created in the system temporary directory while the database worker runs.

## Build Windows packages

Build on Windows x64. Install Inno Setup separately and ensure its compiler, **iscc**, is available to the shell. Use Python 3.14 for the CI-aligned release build.

~~~powershell
python -m pip install -e ".[dev]" pyinstaller pip-licenses
python tools/build_brand_assets.py

# Windowed application-folder package
python -m PyInstaller --clean --noconfirm pyinstaller/mysql_editor.spec

# Single-file portable executable
python -m PyInstaller --clean --noconfirm --onefile --windowed --name MySQLEditor-Portable --icon assets/mysql-editor.ico --add-data "assets/mysql-editor-logo.webp;assets" --add-data "assets/mysql-editor-logo-transparent.png;assets" --add-data "assets/mysql-editor.ico;assets" --paths src src/mysql_editor/__main__.py

# Setup installer; Inno Setup must already be installed
iscc installer/MySQLEditor.iss
~~~

Expected outputs include:

- **dist/MySQLEditor/** — application-folder build.
- **dist/MySQLEditor-Portable.exe** — portable single-file executable.
- **dist/installer/MySQLEditor-Setup.exe** — installer.
- **dist/MySQLEditor-Folder.zip** — compressed folder package created by the release workflow.
- **dist/SHA256SUMS**, **dist/sbom.cdx.json**, license inventory, release notes, and signing-status note when generated by the release workflow.

A local package build is not proof that the artifact is ready for distribution. Use the Windows packaging workflow to validate startup, installation/uninstallation, file existence, and checksums. Windows binaries are unsigned unless a trusted Authenticode certificate is configured and the final signature is checked.

## Testing and CI

Install the development dependencies:

~~~powershell
python -m pip install -e ".[dev]"
~~~

Run the repository checks:

~~~powershell
python -m ruff check src tests tools
python -m compileall -q src tests tools
python -m pytest
python -m pip_audit -r requirements.txt
~~~

GitHub Actions runs lint, compilation, and unit tests across Python 3.12–3.14. A separate integration job starts a disposable MySQL 8.4 service and exercises query execution, schema inspection, transaction rollback, and CSV export. Windows CI checks Qt imports/UI behavior, builds the application-folder and portable packages plus installer, launches the packaged apps, and exercises silent install/uninstall behavior. Consult the Actions page for the exact commit you intend to use.

A successful automated run is evidence only for the checks that actually ran. It does not prove all display scales, upgrade paths, credential-vault states, external server configurations, or end-user PCs were manually tested.

## Architecture

| Path | Responsibility |
|---|---|
| **src/mysql_editor/app.py** | Startup, local master-password unlock/reconnect flow, and shared theme |
| **src/mysql_editor/core.py** | SQL boundaries, risk advisories, formatting integration, and secret-redaction helpers |
| **src/mysql_editor/database.py** | Background MySQL worker, query execution, schema inspection, result spool, cancellation request, CSV export |
| **src/mysql_editor/storage.py** | Local SQLite metadata, history/preferences, Argon2id verifier, Credential Manager adapter |
| **src/mysql_editor/ui/editor.py** | SQL editor, highlighting, line numbers, indentation, and completion |
| **src/mysql_editor/ui/find_replace_bar.py** | Inline literal Find/Replace controls and match counting |
| **src/mysql_editor/ui/connection_dialog.py** | Connection form, profile selection, test/connect actions, first-run lock setup |
| **src/mysql_editor/ui/main_window.py** | Workspace navigation, query tabs, cursor status, result grid, schema/history/snippets, transaction controls and export |
| **src/mysql_editor/ui/tutorial.py** | Animated guided tour |
| **src/mysql_editor/ui/unlock_dialog.py** | Local master-password unlock dialog |
| **tests/** | Unit, integration, and startup/regression tests |
| **tools/** | Brand-asset generator and Windows UI smoke tests |
| **pyinstaller/** | PyInstaller application-folder specification |
| **installer/** | Inno Setup installer definition |
| **.github/workflows/** | Desktop CI, security audit, and Windows packaging workflows |

Database operations are sent to a worker thread through queued tasks and Qt signals. The UI does not synchronously wait for SQL execution in its event loop. MySQL Editor connects directly to the chosen MySQL server; it does not require a cloud proxy or hosted account.

## Troubleshooting

### The application cannot connect
Confirm that the server is running, the host/port are reachable, and the account is allowed to connect from this computer. Verify the username/password and default schema. Try Test connection to separate network/authentication issues from SQL execution errors.

### Certificate verification fails
If **Verify server identity** is selected, check the hostname, certificate validity, trust chain, and CA configuration. Supply the correct CA file for a private certificate authority. Do not disable TLS on an untrusted network just to hide the error. Automatic TLS does not verify server identity.

### The app does not remember the database password
Confirm that Remember this connection was selected and Windows Credential Manager is available for the current Windows user. If the credential is missing or rejected by MySQL, open the connection form and enter it again. The app intentionally has no plaintext fallback.

### Query results look incomplete
The grid previews up to 2,000 rows per result; table preview is capped at 1,000 rows. CSV export is intended to contain all rows fetched into the current result spool and is not reduced by the quick filter. Ensure the query completed and the correct result entry is selected.

### A procedure script does not run as expected
The statement splitter does not implement MySQL client DELIMITER directives or full compound stored-program parsing. Scripts relying on those directives may need a MySQL client that supports them until this feature is implemented.

### Windows flags the installer or executable
Unsigned preview packages can display unknown-publisher warnings. Verify the repository, release notes, and SHA-256 hash when available before deciding whether to run a downloaded artifact. Do not treat a successful build as proof that a file is signed.

### Layout differs on another display
The automated UI check uses Qt's offscreen platform and cannot prove that every Windows scaling factor is visually correct. Record the app version, display resolution/scaling, and steps to reproduce. Do not include passwords, query results, or customer data in a public issue.

## Known limitations

- MySQL DELIMITER directives and compound stored-program parsing are not implemented in the initial statement splitter.
- Table preview is limited to 1,000 rows; the result grid displays up to 2,000 rows per result.
- Query cancellation is best-effort and server-side completion cannot always be confirmed immediately.
- Some MySQL DDL statements implicitly commit regardless of Commit/Rollback controls.
- SQL risk classification is heuristic. It can miss destructive or expensive queries and is not an authorization boundary.
- Query-history redaction is heuristic and cannot guarantee detection of every secret or sensitive literal.
- Automatic TLS does not verify server identity; Disabled TLS does not encrypt the connection.
- Windows Credential Manager behavior, high-DPI appearance, upgrade-in-place, and varied external-server TLS configurations still require real-environment testing.
- Resizing a logo derivative cannot restore detail that is absent from a low-resolution source image.
- This is a pre-release Windows desktop client. Android, cloud synchronization, collaboration, and cross-device account features are not included.

## Contributing

Issues and pull requests are welcome. Keep changes aligned with the Windows desktop scope.

1. Read **AGENTS.md** and the relevant guide under **.agents/skills/** before changing a subsystem.
2. Reproduce the issue and add or update a regression test.
3. Keep database operations off the UI thread; never add plaintext database-password storage.
4. Run Ruff, compileall, pytest, and the dependency audit where the environment supports them.
5. Check Actions for the exact pull-request commit. Do not call a workflow successful while it is still running or has failed.
6. Update this README and, when appropriate, RELEASE-NOTES.md, SECURITY.md, or PRIVACY_POLICY.md for user-visible behavior changes.
7. Do not claim signing or manual QA unless the relevant evidence exists.

SQL snippets, query results, credentials, production connection strings, and screenshots containing database information may be sensitive. Do not put them in public issues or pull requests.

## Project links

- [Repository](https://github.com/ram1234598766-dotcom/MySQL-Editor)
- [Releases](https://github.com/ram1234598766-dotcom/MySQL-Editor/releases)
- [GitHub Actions](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions)
- [Security policy](SECURITY.md)
- [Privacy policy](PRIVACY_POLICY.md)
- [Windows signing guide](WINDOWS_SIGNING.md)
- [Desktop implementation plan](DESKTOP_REBUILD_PLAN.md)
- [Advanced UX, motion, and engineering upgrade roadmap](UPGRADE_ROADMAP.md)
- [Qt for Python / PySide6](https://doc.qt.io/qtforpython-6/)
- [PySide6 deployment with PyInstaller](https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html)
- [MySQL Connector/Python documentation](https://dev.mysql.com/doc/connector-python/en/)
- [Connector/Python compatibility reference](https://dev.mysql.com/doc/connector-python/en/connector-python-versions.html)

---

**Use a least-privilege MySQL account, verify the active server and schema before running mutations, and keep appropriate backups for important data.**
