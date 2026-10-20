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
- [Results and data export](#results-and-data-export)
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
- SQL syntax highlighting, configurable line numbers and current-line highlighting, tab-width-aware indentation, bracket matching, and a monospace font.
- A live editor position indicator shows line/column and selected character count; the active connection and unsaved-tab state remain visible.
- The SQL editor supports MySQL-aware line comments with **Ctrl+/** on the current line or selected lines, preserving indentation and grouping the toggle as one undo action. MySQL keyword/function completion includes context-aware schema columns and tables, including comma-separated `SELECT`, `GROUP BY`, `ORDER BY`, and `UPDATE ... SET` lists. Use **Ctrl+Space** to open completion on demand; completion remains a lightweight aid rather than a full MySQL parser.
- SQL formatting, an inline Find/Replace bar with match counts and case-sensitive search, SQL-file open/save, and saved query snippets.
- Resizable editor/results and workspace/inspector panes. Window geometry, pane sizes, inspector tab, editor font family/size, tab width, line-number visibility, and current-line highlight preference are stored locally.
- Five-step guided tour with a short, interruptible content transition that respects Reduce Motion; it can insert a sample SELECT into the editor.

### Database work
- Execute the statement under the cursor, highlighted SQL, or the whole script.
- Dedicated database worker thread keeps SQL execution and schema reads off the Qt UI event loop.
- Configurable connection TLS policy and finite connection/read/write timeouts.
- **Explain SELECT** requests `EXPLAIN FORMAT=JSON` for the statement under the cursor and opens an expandable operation tree plus the original JSON. Optimizer costs/row counts are estimates; this does not execute the SELECT. If the server doesn't support JSON EXPLAIN or the request fails, the workspace reports the issue without running the original query.
- Schema tree for databases, tables, and views; double-click a table for a limited preview.
- Commit and Rollback controls, query history that is opt-in, and high-impact SQL confirmation prompts.

### Results and release engineering
- Switch between results returned by different statements in a script.
- Sortable result grid, numeric-aware sorting, NULL display, and clipboard actions for selected cells/rows, headers, and the full untruncated cell value.
- Case-insensitive quick filter for visible rows. It changes the grid view only; it does not exclude rows from CSV, JSON, or NDJSON export.
- Each query initially loads up to 2,000 rows into the grid. Scrolling to the end requests the next page from the local SQLite result spool asynchronously; scrolling to the top loads earlier rows. The active grid model retains at most 5,000 rows, tracks absolute row numbers, and preserves fetch-order offsets when the window advances in either direction. A first-page restore snapshot may also be retained while paging. **Fetch +1,000** / Fetch Earlier buttons remain available where automatic scrolling is not practical. Paging never reruns or modifies SQL. For ordinary row results, quick filtering searches the full local SQLite spool and displays a bounded window of matches with original source-row labels. Sorting across all fetched rows builds a disk-backed view and pages through a bounded, numeric-aware sorted window; SQL NULL remains last in either direction, and displayed row labels point back to their original source rows. CSV, JSON and NDJSON exports use every row in fetch order, regardless of the view.
- Atomic CSV, JSON-array, and NDJSON export to help preserve an existing destination when a write fails, with persistent non-modal status feedback that keeps the saved path or redacted error visible without interrupting SQL work.
- Windows application-folder build, portable EXE, Inno Setup installer, generated icons/setup branding, and desktop shortcut support.
- Release gating includes lint, compilation and unit/UI tests across Python 3.12–3.14, disposable MySQL integration, dependency audits, Windows UI/launch checks, silent install/uninstall verification, a per-artifact provenance manifest, SBOM/license records, and SHA-256 checksums.
- Release workflow can include SHA-256 checksums, CycloneDX SBOM, third-party license inventory, release notes, and an explicit Windows signing-status note.
- Automatic stable-release checks at startup are disabled by default. The Settings → Updates toggle enables future startup checks; Help → Check for updates performs a one-time check even while automatic startup checks are off. The app never downloads or installs updates automatically.

## UX and upgrade roadmap

The implementation history and remaining phases are documented in **[UPGRADE_ROADMAP.md](UPGRADE_ROADMAP.md)**. Completed work spans the shared design system, Reduce Motion, Find/Replace, contextual SQL completion, persisted editor/result preferences, connection/schema recovery, result-export semantics, Phase 6 accessibility and visual-QA improvements, Phase 7 reliability/security hardening, and Phase 8 release provenance and gated Windows packaging.

The intended visual direction remains a calm, modern database workspace: crisp logo rendering, consistent surfaces and spacing, one primary accent colour, readable SQL syntax colours, restrained gradients, and transitions that never block work.

**Roadmap status:** The current main source commit [`044aeefdcf14527736d4116b42a62a56f6293ee7`](https://github.com/ram1234598766-dotcom/MySQL-Editor/commit/044aeefdcf14527736d4116b42a62a56f6293ee7) passed [desktop CI #444](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39294312768), [dependency security #513](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39294312819), and [Windows packages #325](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39294312718). The main preview-publish lane creates an **unsigned prerelease** and attaches the installer, portable EXE, application-folder ZIP, SHA-256 checksums, release manifest, and SBOM. Browse the [GitHub Releases page](https://github.com/ram1234598766-dotcom/MySQL-Editor/releases) and choose the latest **MySQL Editor Windows Preview** for current download assets. A stable version-tag push now creates signed candidate artifacts for inspection but does not publish a stable GitHub Release automatically. Publication requires reviewing the candidate manifest/checksums, completing physical-Windows acceptance—including real-monitor scaling, keyboard-only workflows, screen-reader use, and the target PC's MySQL/TLS/Credential Manager setup—and manually dispatching the Windows packages workflow on the same tag with `publish_release=true`. Keep the app Windows-desktop-only; Android, cloud relay, cross-device sync, ads, and telemetry remain out of scope.

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
| **RELEASE-MANIFEST.json** | Exact source commit, build metadata, signing disclosure, and per-package SHA-256/size. |
| **sbom.cdx.json** | Software dependency inventory in CycloneDX format, when published |
| **THIRD_PARTY_LICENSES.md** | Third-party license inventory, when published |
| **WINDOWS_SIGNING.md** | Explicit signing status for that release |

### Brand assets and logo rendering

The tracked master logo is `assets/mysql-editor-logo.webp`. Run `python tools/build_brand_assets.py` to regenerate the transparent PNG derivative, `assets/mysql-editor.ico` with 16, 24, 32, 48, 64, 128, and 256 px icon frames, and the two Inno Setup wizard images. The asset pipeline removes the light matte connected to the outer background, reduces pale edge fringes, preserves the artwork's proportions, and keeps white details enclosed within the logo badge. The tracked source image is left unchanged.

The Windows workflow regenerates the crisp app icon and installer branding before packaging. The main-branch preview publishing lane is triggered by a dedicated `[publish-windows-preview]` commit marker; it publishes the validated onedir package, portable executable, installer, `SHA256SUMS`, `RELEASE-MANIFEST.json`, SBOM, release notes, signing guide, and third-party license inventory as a GitHub prerelease. Open the [Releases page](https://github.com/ram1234598766-dotcom/MySQL-Editor/releases) and choose the newest **MySQL Editor Windows Preview** to download `MySQLEditor-Setup.exe`, `MySQLEditor-Portable.exe`, or `MySQLEditor-Folder.zip`. These preview binaries are intentionally unsigned. The configured self-signed PFX is reserved for the stable-tag signing path and was tested against a disposable EXE only; it is not used to sign distributed preview assets. Physical-monitor visual QA remains outstanding.

### About Windows warnings

Unsigned preview builds can show an unknown-publisher or SmartScreen warning. Do not assume an artifact is trustworthy only because it is hosted on GitHub. Confirm the repository and release, review its notes, and check a published SHA-256 hash when available. A matching hash detects a file mismatch; it does not prove that software is safe.

A successful CI build does not mean the executable has been Authenticode signed. Stable releases require final Authenticode verification. The selected default is a self-signed code-signing certificate: its signature can be checked, but Windows does not trust that certificate on recipient PCs by default, and SmartScreen or unknown-publisher warnings may still appear. See [WINDOWS_SIGNING.md](WINDOWS_SIGNING.md).

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
- **Explain SELECT** opens the visual JSON execution plan for the SELECT under the cursor. The app submits `EXPLAIN FORMAT=JSON`, displays a tree and raw JSON tab, and does not run the SELECT itself. Plan costs and row estimates are optimizer estimates, not actual runtime measurements.

Before running a mutation, verify the active server and schema. High-impact statements may trigger a confirmation prompt. That prompt cannot guarantee that a query is safe: even a syntactically ordinary statement can lock a table, consume significant resources, expose sensitive data, or affect many rows.

### Transactions and cancellation
Commit and Rollback act on the active connection. Some MySQL statements, particularly many DDL operations, implicitly commit regardless of the application's transaction controls. Do not assume every operation can be undone with Rollback. Use backups and server-side privileges for important safety controls.

**Stop** sends a best-effort KILL QUERY request through a separate control connection. Permissions, network conditions, and server state affect whether it succeeds promptly. A request to cancel is not proof that the server stopped immediately; check the final state before retrying a mutation. The status strip separates queued/running/fetching states from completion. The UI reports “cancelled” only when MySQL returns an explicit interruption signal after a cancellation request. If a multi-statement script completes earlier statements before a later one fails, it is marked as a partial failure and retains the earlier result sets.

## Results and data export

A multi-statement script can create several result entries. Use the result picker to switch among them. The grid displays column headers and rows along with row-count and duration information where available.

- **Sorting** changes the order of the visible grid rows. Common numeric values use numeric-aware comparison. All export formats preserve the original server-fetch order, not the grid's current sort order.
- If the database session drops during a query, the connection badge changes to **Connection lost**, includes a reconnect hint, and the worker discards the dead session. Reconnect before sending more SQL; query tabs and buffers remain in place.
- **Quick filter** searches all fetched rows case-insensitively for ordinary query results backed by the local result spool, then shows a bounded matching window with original row numbers. Editable table previews and non-spooled results filter only the loaded window. Clear the filter to return to the original result preview.
- **Copy selected cells** copies a tab-separated rectangular selection; tabs and newlines inside values are quoted so copied data stays parseable.
- **Copy selected rows** copies every column from each selected visible row; **Copy column headers** copies only selected columns' headers, or all headers when nothing is selected.
- **Cell details** opens a read-only view for long values, showing the column, row, and whether the value is SQL NULL, empty text, or non-empty text.
- **Result paging** loads up to 1,000 rows from the local SQLite result spool at a time in both directions. The active grid model is capped at 5,000 rows and vertical row headers retain absolute result row numbers as the window moves. It does not rerun the query or change submitted SQL. Full-result quick filtering and sorting use disk-backed indexes of source-row offsets and page through a bounded result view without loading all fetched rows into memory. Sorting is numeric-aware, keeps SQL NULL at the bottom in both directions, and can be combined with quick filtering. Exports read every original row in MySQL fetch order regardless of visible sorting/filtering.
- **CSV export** uses every row fetched into the current session result spool, not only the rows currently loaded in the grid or matched by the filter. It preserves original server-fetch order even after sorting, filtering, or paging. SQL NULL uses the documented unquoted `\\N` token; empty text remains an empty field, and backslash-leading strings are escaped so they can be distinguished from NULL.
- **JSON export** writes a streaming JSON array of row objects. **NDJSON export** writes one JSON row object per line for line-oriented processing. Both formats export every fetched row directly from the local result spool in original fetch order; grid sorting, filtering, and loaded-page count do not reduce the export. SQL NULL becomes JSON `null`, empty text remains an empty string, and duplicate or blank column names are made unique so no values are overwritten. They use a same-directory temporary file and replace the destination only after a successful export.
- **NULL vs empty text:** the grid displays SQL NULL as **(NULL)**; clipboard copy uses the marker **NULL** while empty text remains blank. CSV writes SQL NULL as the unquoted token `\N` and leaves empty text as an empty field. Text values beginning with a backslash are escaped by adding one leading backslash, so a literal text value `\N` exports as `\\N`. Consumers importing these files should decode this documented convention to restore SQL NULL and the original backslash-leading text.

The local result cache may contain sensitive database contents. Treat it, copied clipboard values, and CSV/JSON/NDJSON exports as sensitive. The temporary spool is intended for the current worker session and is removed during shutdown on a best-effort basis.

## Schema, history, and snippets

### Schema Explorer
Refresh the schema tree to read database names and table/view objects visible to the MySQL account. Double-click or press Enter on a different schema to switch the live MySQL session to that database; the displayed context and saved profile default update only after the server accepts the switch. A rejected switch preserves the previous context. Double-click or press Enter on the currently active schema to refresh it. Double-click or press Enter on a table/view to request a preview capped at 1,000 rows. Right-click a schema to switch/refresh it or copy its name. Right-click a table/view to copy its safely quoted qualified identifier, **inspect DDL and metadata**, open a limited `SELECT * ... LIMIT 1000` in a new unsaved query tab, or request a preview. The inspector shows the MySQL-generated CREATE TABLE or CREATE VIEW definition, columns, indexes, constraints, and server-reported object properties in a read-only dialog. Missing or permission-restricted metadata is explained in the inspector; available sections remain visible. Generated SELECT SQL is not executed automatically. The visible objects depend on the privileges of the connected user.

**Guarded preview-cell editing:** On a verified Schema Explorer preview for a base table using a transactional storage engine, right-click an eligible non-primary-key cell and choose **Edit table preview cell…**. The dialog preserves the distinction between SQL `NULL` and empty text. Before writing, the worker revalidates the active connection/session, table and column metadata, primary key, and the locked current row; it rejects stale values or any other column changes since the preview. Updates use bound values and safely quoted identifiers and are left uncommitted for the existing **Commit**/**Rollback** controls—there is no automatic commit. Views, tables without primary keys, non-transactional engines, key/generated columns, and unsupported binary/spatial types stay read-only. A full rollback restores the cached preview snapshots for inline-edited rows. `ROLLBACK TO SAVEPOINT` invalidates cached table previews because the app does not maintain per-savepoint snapshots; refresh affected tables before editing or exporting again.

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
| **Ctrl+/** | Toggle MySQL line comments on the current line or selected lines in the SQL editor |
| **F1** | Open the guided tour |
| **Alt+F4** | Exit the application |

## Settings and preferences

The **Settings** menu groups working preferences by purpose:

- **Appearance:** choose System, Light, or Dark. Theme changes preserve SQL buffers, cursor/selection, current tabs, result filters, and splitter state. SQL syntax highlighting, line-number gutter, active-line shading, and bracket matching follow the selected palette. Reduce motion disables optional transitions while leaving status feedback intact.
- **Editor → SQL font family:** choose an installed monospace font. The family applies immediately to all open tabs and is remembered for new tabs; font size remains independent.
- **Editor → Tab width:** choose 2, 4, or 8 spaces. This changes the visual tab stop in all open and new query tabs; it does not rewrite existing SQL text.
- **Results → Row height:** choose Compact (24 px), Comfortable (28 px), or Spacious (36 px) for the results grid.
- **Updates:** automatic stable-release checks are off by default. Enabling the toggle authorizes a lightweight public GitHub Releases metadata request at startup. Help → Check for updates performs a one-time check even when automatic startup checks are off; the app never downloads or installs updates.
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
The app connects directly from this computer to the MySQL host and port selected by the user. This desktop implementation has no hosted account system, mandatory relay service, analytics endpoint, advertisements, or usage telemetry. SQL and credentials are sent to the database server subject to the selected protocol and TLS policy. Automatic update checks are off by default; when enabled, they request the public latest stable GitHub Release metadata using the app version in its User-Agent. A one-time check can also be started from Help → Check for updates without enabling startup checks. GitHub receives normal request metadata such as the network IP address. The update request does not include SQL, database connection details, credentials, result rows, or usage history. See PRIVACY_POLICY.md for details.

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

A local package build is not proof that the artifact is ready for distribution. Use the Windows packaging workflow to validate startup, installation/uninstallation, file existence, and checksums. Preview binaries remain unsigned. Stable-tag builds require configured signing secrets and passing signature checks; by default, the manifest discloses a self-signed certificate and its recipient-trust limitations.

## Testing and CI

Install the development and packaging dependencies:

~~~powershell
python -m pip install -e ".[dev]" pyinstaller pip-licenses
~~~

Run the repository checks:

~~~powershell
python -m ruff check src tests tools
python -m compileall -q src tests tools
python -m pytest
python -m pip_audit -r requirements.txt
python -m pip_audit
~~~

The requirements-file audit checks the declared runtime dependency constraints. The no-argument audit checks the installed environment, including development, test, and packaging tools. GitHub Actions runs both. The release CycloneDX SBOM intentionally describes runtime dependencies only; packaging tools are covered by the separate installed-environment audit.

GitHub Actions runs lint, compilation, and unit tests across Python 3.12–3.14. A separate integration job starts a disposable MySQL 8.4 service and exercises query execution, schema inspection, transaction rollback, and CSV/JSON/NDJSON export. Windows CI checks Qt imports/UI behavior, builds the application-folder and portable packages plus installer, audits the installed packaging environment, launches the packaged apps, and exercises silent install/uninstall behavior. Consult the Actions page for the exact commit you intend to use.

A successful automated run is evidence only for the checks that actually ran. It does not prove all display scales, upgrade paths, credential-vault states, external server configurations, or end-user PCs were manually tested.

## Architecture

| Path | Responsibility |
|---|---|
| **src/mysql_editor/app.py** | Startup, local master-password unlock/reconnect flow, and shared theme |
| **src/mysql_editor/core.py** | SQL boundaries, risk advisories, formatting integration, and secret-redaction helpers |
| **src/mysql_editor/database.py** | Background MySQL worker, query execution, schema inspection, result spool, cancellation request, and streaming CSV/JSON/NDJSON exports |
| **src/mysql_editor/storage.py** | Local SQLite metadata, history/preferences, Argon2id verifier, Credential Manager adapter |
| **src/mysql_editor/ui/editor.py** | SQL editor, MySQL line-comment toggle, highlighting, line numbers, indentation, and completion |
| **src/mysql_editor/ui/find_replace_bar.py** | Inline literal Find/Replace controls and match counting |
| **src/mysql_editor/ui/connection_dialog.py** | Connection form, profile selection, test/connect actions, first-run lock setup |
| **src/mysql_editor/ui/main_window.py** | Workspace navigation, query tabs, cursor status, result grid, schema/history/snippets, transaction controls and export |
| **src/mysql_editor/update_checker.py** | Optional stable GitHub Release metadata check with a bounded background request and strict release-link validation |
| **src/mysql_editor/ui/tutorial.py** | Animated guided tour |
| **src/mysql_editor/ui/unlock_dialog.py** | Local master-password unlock dialog |
| **src/mysql_editor/ui/explain_plan.py** | Strict MySQL JSON plan extraction, expandable operation tree, estimate summary and copyable raw JSON |
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
The grid initially loads up to 2,000 rows per query result. Scroll to the bottom to request later pages or to the top to return to earlier rows from the local result cache. The active grid model retains at most 5,000 rows, uses absolute row labels, and keeps a first-page restore snapshot while the active result is being paged. The Fetch +1,000 / Fetch Earlier controls provide manual paging when filter results do not allow scrolling. Paging does not rerun SQL. For ordinary row results, the quick filter searches the entire fetched SQLite spool and pages through matches while preserving original row numbers. Sorting also applies across the entire fetched result using a disk-backed order index, with numeric-aware comparison and SQL NULL at the bottom for either direction. A filter and sort can be combined without rerunning SQL. Table preview remains capped at 1,000 rows. CSV, JSON, and NDJSON exports include every row fetched into the result spool in original MySQL fetch order, independent of the loaded window, quick filter, and sort. Ensure the query completed and the correct result entry is selected.

### Stored procedures and DELIMITER
MySQL Editor recognizes standalone MySQL-client `DELIMITER` directives at statement boundaries, uses the active delimiter to keep compound routine bodies together, and removes the client-only directive lines before sending SQL to MySQL. You can switch delimiters (for example, to `//` or `$$`) and restore `;` later in the same script. Malformed delimiter commands fail before the script is queued, so earlier statements are not submitted accidentally. This is a statement-boundary parser, not a full MySQL grammar or semantic validator; the server remains authoritative for SQL validity and permissions.

### Windows flags the installer or executable
Unsigned preview packages can display unknown-publisher warnings. Verify the repository, release notes, and SHA-256 hash when available before deciding whether to run a downloaded artifact. Do not treat a successful build as proof that a file is signed.

### Layout differs on another display
The automated UI check uses Qt's offscreen platform and cannot prove that every Windows scaling factor is visually correct. Record the app version, display resolution/scaling, and steps to reproduce. Do not include passwords, query results, or customer data in a public issue.

## Known limitations

- Script splitting supports standalone MySQL-client DELIMITER changes and compound stored-program boundaries, but it is not a full MySQL grammar or semantic validator. Malformed directives fail closed before submission.
- Table preview is still limited to 1,000 rows; editable previews continue to filter only the loaded window so guarded editing and source-row identity remain predictable. Large query results initially load 2,000 rows and use a bidirectional 1,000-row spool pager with a 5,000-row active grid-window cap. Ordinary row-result quick filtering searches the complete fetched spool, and full-result sorting uses a disk-backed global row order while retaining only the active window in grid memory. Sorting is numeric-aware, keeps SQL NULL last in both directions, and can be composed with filtering. CSV, JSON, and NDJSON exports retain the complete fetched result. Paging for table previews, aggregate-memory behaviour across many result sets, and physical-Windows one-million-row performance measurements remain open.
- Query cancellation is best-effort and server-side completion cannot always be confirmed immediately.
- Some MySQL DDL statements implicitly commit regardless of Commit/Rollback controls.
- SQL risk classification uses SQLGlot's MySQL AST for parseable UPDATE/DELETE outer-WHERE checks and keeps a heuristic fallback for unsupported syntax and executable comments. It can still miss destructive or expensive queries and is not an authorization boundary.
- Query-history redaction is heuristic and cannot guarantee detection of every secret or sensitive literal.
- Automatic TLS does not verify server identity; Disabled TLS does not encrypt the connection.
- Windows Credential Manager behavior, high-DPI appearance, upgrade-in-place, and varied external-server TLS configurations still require real-environment testing.
- Automated logo generation preserves the tracked source and cleans its alpha edges; final rendering still needs visual review on a physical Windows display at the intended DPI scales.
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
