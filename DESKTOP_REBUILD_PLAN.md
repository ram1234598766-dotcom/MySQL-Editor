# MySQL Editor — Clean-Room Desktop Rebuild Plan

**Status:** Clean-room implementation is committed on `desktop-rebuild` and reviewed via [draft PR #3](https://github.com/ram1234598766-dotcom/MySQL-Editor/pull/3). The branch contains the new Windows desktop application, source tests, disposable-MySQL integration tests, installer and release pipelines, and rewritten product documentation.  
**Target:** Windows desktop application first. Android is explicitly deferred to a later, separate project phase.  
**Design reference:** [MySQL Editor Figma workspace](https://www.figma.com/design/EFFQpRTE8pKybt1lQR0eQH)  
**Rule:** No application code, UI component, business-logic module, or test implementation may be copied, imported, renamed, or ported from MySQL IDLE. The existing repository is a source of requirements and lessons learned only. The user-supplied MySQL Editor logo is a brand asset, not reusable application code.

---

## Current implementation and cutover status

The clean-room application is implemented under `src/mysql_editor/`. The branch has previously passed:

- Lint, compile and unit-test jobs on Python 3.12, 3.13 and 3.14.
- End-to-end tests against a disposable MySQL 8.4 service covering login, multi-statement execution, schema inspection, Unicode/NULL rows, CSV export, transaction rollback and rejected credentials.
- A dependency audit.
- A Windows workflow that built the onedir package, portable executable and Inno Setup installer; it completed install/uninstall, EXE-launch, manifest and artifact-upload steps successfully on the previous code commit.

The current branch additionally uses a bounded `--smoke-test` startup path and packages the supplied logo in the setup wizard artwork, with the desktop shortcut checked by default. These latest packaging edits must pass their own current-head workflow before merging. Manual QA is still needed for high-DPI rendering, upgrade-in-place behavior, real Windows Credential Manager interactions, and connections to external MySQL server/TLS configurations. The executable is unsigned until a trusted code-signing certificate is configured; do not claim publisher verification or promise no SmartScreen warning.

The Windows build workflow uploads an artifact named `MySQLEditor-Windows` containing the application folder, portable EXE, setup installer, folder archive, SHA-256 checksums, CycloneDX SBOM, third-party license inventory, release notes and signing-status note. It can publish a GitHub pre-release on a version tag after the full job passes. The default branch remains protected from the clean-room cutover until PR #3 is merged.

---

## 1. Product goal

Build a polished, reliable Windows SQL IDE for MySQL from a clean codebase. It should feel like a purpose-built database product—not a terminal wrapper, not a command transcript, and not a reskinned MySQL IDLE.

The initial release is a local desktop application that connects directly to MySQL servers. It does not require an account, cloud relay, local web server, mobile pairing service, or Android installation.

### Non-negotiable principles

1. **Clean room:** Build the new application under a new `src/mysql_editor/` package with newly authored modules and tests. Do not reuse the old `mysql_idle.py`, `sql_toolbox.py`, `feature_governor.py`, `password_auth.py`, `mobile_companion.py`, or their tests.
2. **Desktop only:** Do not build, test, package, sign, or release APK/AAB files in this phase. No Android folder or mobile companion should ship in the desktop distribution.
3. **Professional interface:** A real SQL editor, navigable schema tree, query tabs, result grid, and connection manager. No `mysql>` prompt or terminal transcript in the main editor surface.
4. **Secrets stay secret:** No database passwords in source code, configuration files, query history, logs, screenshots, crash reports, or GitHub Actions logs.
5. **Database work stays responsive:** SQL execution, schema loading, exports, and connection attempts run outside the UI thread.
6. **Quality before packaging:** Do not publish a build simply because an executable was generated. The exact packaged build must pass its test suite and launch/uninstall checks.

## 2. Current-repository assessment

The current `main` tree is mixed: a large `mysql_idle.py` desktop entry point, `mobile_companion.py`, an Android Gradle/Kotlin project, shared helpers and tests, Windows PyInstaller specs, and a combined Windows/Android workflow. This structure does not satisfy the clean-room or desktop-only target.

The redesign is not another refactor of that application. The clean-room implementation exists on `desktop-rebuild`; the legacy baseline on `main` is preserved until the exact replacement commit passes the cutover gate. Merge PR #3 only after current-head unit, integration, security, Windows packaging, app-startup and install/uninstall checks complete successfully.

### Destination for current files

| Existing area | Final desktop-only disposition |
|---|---|
| `mysql_idle.py`, `mysql_idle.spec`, `mysql_idle_portable.spec` | Retire from the new product tree; replace with newly authored entry point and specs. |
| `mobile_companion.py`, `android-app/`, mobile tests and Android signing steps | Remove from the desktop product branch. Android is a future, separately planned project. |
| `feature_governor.py`, `sql_toolbox.py`, `password_auth.py` and their tests | Do not import, copy, or rename. Re-implement only approved product requirements as new domain/service modules with new tests. |
| `MySQLIDLE.iss`, `build_windows.ps1`, combined build workflow | Replace with product-named Windows installer/build scripts and separate desktop CI/release workflows. |
| `README.md`, `PRIVACY_POLICY.md`, `SECURITY.md`, `SIGNING.md` | Rewrite for the actual desktop product. Remove claims about Android, mobile pairing, and unsupported features. |
| `assets/mysqlidle-logo.png` and old generated icon files | Retire. Do not use as alternate product branding. |
| User-supplied MySQL Editor logo | Retain the exact artwork as the only shared brand source. Prepare clean, square, high-resolution masters and derive all output sizes from that master. |

The Git history may remain for traceability, but legacy application source must not be imported at runtime, included in the installer, or used as the implementation base.

## 3. Technology baseline

Use technologies suited to a native-feeling Windows desktop product and validate their compatibility together in CI before pinning releases.

| Layer | Planned choice | Reason |
|---|---|---|
| Language/runtime | Python 3.14 baseline for initial production builds | Conservative supported baseline across the planned UI and database-driver stack. Evaluate newer runtimes only after the complete dependency and installer matrix passes. |
| Desktop UI | PySide6 / Qt 6 Widgets | Native desktop window management, accessible controls, docking/splitters, high-DPI scaling, model/view tables, keyboard handling, animations and custom painting. |
| SQL editor | Qt `QPlainTextEdit` plus a new `QSyntaxHighlighter`, line-number gutter and editor controls | Avoids importing an editor component from MySQL IDLE and avoids an extra editor-binding dependency. Adds room for completion, line markers, selection execution and keyboard shortcuts. |
| MySQL protocol | Official `mysql-connector-python` driver, version pinned after compatibility tests | Explicit MySQL-focused protocol layer with connect/read/write timeouts and transaction support. MySQL's official compatibility table currently lists Python 3.14 for the current GA series; do not assume every newest package works with every newest runtime. |
| SQL parsing | `sqlglot` with the MySQL dialect, pinned and regression-tested | Parsing and statement classification can inform formatting and destructive-query warnings. This is not a replacement for server permissions or a security boundary. |
| Local metadata | Standard-library SQLite behind a repository interface | Stores non-secret preferences, connection metadata and opt-in query history in a versioned local schema. |
| Secret storage | Windows Credential Manager through a vetted `keyring` integration | The database contains secret references, not database passwords. Validate the installed backend before storing secrets; fail closed rather than silently falling back to plaintext. |
| Local app lock | Newly implemented Argon2id password verifier with random per-install salt | The first-run passphrase can unlock local app features without storing a recoverable password. This local lock is separate from each server credential and does not imply future Android identity or synchronization. |
| Packaging | PyInstaller directory build plus portable executable, Inno Setup installer | Bundles the runtime and Qt libraries; end users should not need Python or a separately installed MySQL client. |
| Dev quality | `pyproject.toml`, locked dependencies, Ruff, type checking, pytest/pytest-qt and integration tests | Reproducible builds and independently tested modules. |

Official technology references: [Qt for Python / PySide6](https://doc.qt.io/qtforpython-6/), [PySide6 deployment with PyInstaller](https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html), and [MySQL Connector/Python version compatibility](https://dev.mysql.com/doc/connector-python/en/connector-python-versions.html). Dependency versions must be checked and locked when implementation begins, rather than blindly changing to the highest version number.

## 4. Target user experience

### First launch and connection

1. A branded setup dialog asks the user to create a local master passphrase and confirm it in a second field. The verifier is stored; the password itself is not.
2. On subsequent launches, open a compact, well-spaced **Connect to MySQL** window—not the full editor or a console transcript.
3. The connection form includes a saved-profile selector, host, port, user, password, default schema, TLS policy, **Test Connection**, **Connect**, and a clear error area.
4. Successful connection opens the main workspace. A failed connection must preserve entered non-secret fields and offer a useful, copyable diagnostic with secrets removed.
5. The master passphrase is a local-desktop feature for this phase. Do not build cross-device password synchronization or treat it as a future Android identity system.

### Main workspace

Use the provided Figma design as the visual direction. Deliver a production-quality screen with the following hierarchy:

- **Top application bar:** crisp logo, active connection, server/schema context, connection state, new query tab, settings and account-free app menu.
- **Left navigation rail/sidebar:** Connections, Schemas, Tables, Views, Routines and Saved Queries. Schema loading is lazy and shows loading/empty/error states.
- **Central editor area:** multiple query tabs, visible line numbers, syntax coloring, matching brackets, indentation, search/replace, current-line/selection highlighting, unsaved-state marker and sensible default font size.
- **Editor toolbar:** Run, Run Selection, Stop, Explain, Format SQL, Save Query and transaction controls where supported. Every control has a real operation and a keyboard shortcut.
- **Bottom/right results area:** result tabs, a sortable/filterable grid, row count, execution duration, null values displayed distinctly, copy selected cells/rows, and CSV export. Large results must be fetched in pages or batches rather than rendered all at once.
- **Output/diagnostics panel:** query duration, affected rows, server errors and warnings. This is structured output—not a fake command prompt.
- **Status bar:** active server, selected schema, connection/transaction state, cursor line and column, editor encoding and progress state.

### Visual and accessibility system

Define the design tokens before building screens: dark navy canvas, elevated panels, high-contrast text, restrained cyan/blue accents, semantic success/warning/error colors, consistent spacing, border radius, control heights, typography and focus indicators. Provide a light theme only after the dark theme is coherent.

Use vector icons where practical and the exact supplied logo artwork for brand placement. Avoid scaling the logo repeatedly, converting it through multiple lossy formats, or using CSS-like blur/glow as a substitute for sharp edges. Test screenshots at 100%, 125%, 150% and 200% Windows display scaling. The UI must remain readable, aligned and resizable at common laptop and desktop resolutions.

## 5. New architecture and repository layout

The intended layout is illustrative but should be the boundary between product layers:

```text
MySQL-Editor/
  src/mysql_editor/
    __main__.py
    app.py
    domain/
      connection_profile.py
      query_document.py
      query_result.py
      statement_policy.py
    services/
      connections/
        mysql_connector.py
        connection_manager.py
        schema_browser.py
      queries/
        query_executor.py
        query_classifier.py
        sql_formatter.py
        result_stream.py
      security/
        credential_store.py
        master_lock.py
        secret_redaction.py
    persistence/
      settings_repository.py
      history_repository.py
      migrations/
    ui/
      main_window.py
      connection_dialog.py
      connection_sidebar.py
      schema_tree.py
      query_tabs.py
      sql_editor.py
      results_grid.py
      output_panel.py
      dialogs/
      theme/
    resources/
      icons/
      styles/
  assets/
    mysql-editor-logo-master.png or lossless WebP source
    mysql-editor.ico (generated)
    installer artwork (generated)
  tests/
    unit/
    integration/
    ui/
    packaging/
  .github/workflows/
    desktop-ci.yml
    windows-release.yml
  pyproject.toml
  uv.lock
  README.md
  SECURITY.md
  PRIVACY_POLICY.md
  WINDOWS_SIGNING.md
  LICENSES.md
  pyinstaller/
  installer/
```

**Dependency rule:** UI modules call services; services use domain types and repositories; domain code does not import Qt widgets or access the network. Database-driver exceptions are translated into safe product error types at the service boundary. No module should be named after MySQL IDLE or depend on its files.

## 6. Functional requirements

### Connection manager

- Create, edit, duplicate, rename, test, connect and delete saved profiles.
- Store host, port, username, default database, connection options and a reference to a credential in Windows Credential Manager. Never store the password directly in SQLite or JSON.
- Support DNS names, IPv4/IPv6, non-default ports, local and remote instances, UTF-8 data and long-running connections.
- Apply finite connection/read/write timeouts. Keep UI responsive while connecting. Surface auth, DNS, timeout, server version, permission and TLS errors distinctly.
- Do not require a user-supplied certificate file merely to open a normal connection. Offer explicit TLS policies: automatic/preferred TLS when supported and a stricter verify-CA/identity mode. Explain certificate-validation failures without silently downgrading a strict policy. Any setting that accepts an unverified server certificate must be explicit and visibly marked.
- Include a **Test Connection** command that never executes user SQL.

### SQL editor and execution

- Multiple documents/tabs, new/open/save SQL files, dirty-state prompts, encoding-safe UTF-8, find/replace, select-all, undo/redo and configurable shortcuts.
- Execute current statement, selected SQL or whole script. Correctly handle semicolons inside quoted strings and comments; never split scripts with a naive semicolon-only regex.
- Run work on background workers. Provide progress, cancellation, stale-connection handling and clean worker shutdown.
- Support query parameters only through driver parameter binding when values are separate from SQL; do not implement string interpolation for values.
- Explain/format commands should report parse failures without rewriting or running the query.
- Result grids must support paging/batched fetch, sort/filter where feasible, null display, copy, CSV export, column-width management and useful empty/error states.

### Query safety and transactions

- Clearly warn before potentially destructive or large-impact statements such as `DROP`, `TRUNCATE`, broad `DELETE`/`UPDATE`, privilege changes and schema-altering actions. Warnings are configurable, auditable locally and explain what will run.
- Offer an optional read-only connection profile and a conservative mode that refuses known mutating statements at the UI layer. Server-side MySQL grants remain the real permission boundary; the UI policy must never be marketed as a replacement for database permissions.
- Expose transaction state and clear Commit/Rollback actions when the driver/session is in manual-transaction mode. Do not silently auto-commit a user’s work because a UI tab closed.
- A query timeout or cancellation must not leave the app believing a query stopped when the server is still processing it. Show cancellation status only when confirmed or clearly label it as best-effort.

### Local settings and history

- Version local settings with migrations. Support theme, editor font/size, tab preferences, default fetch limit, query timeout, CSV options and confirmation preferences.
- Keep query history local, disabled or opt-in by default, with configurable retention and delete/clear controls. Do not log SQL literals or returned data to ordinary application logs.
- Redact passwords, tokens, connection strings and query values in logs and error-report copy actions.

## 7. Logo and visual quality pipeline

The logo must be treated as a master artwork, not as a tiny image to enlarge:

1. Retain the uploaded artwork exactly. Create a square, lossless master at the best native resolution available from the original upload (prefer the original/high-resolution master over the current 256px derivative if that source is available).
2. Inspect crop, edge detail, alpha/background, and at 100% zoom before generating any size. Do not draw a replacement, apply an unapproved filter, or upscale a small derivative and call it high-resolution.
3. Derive the Windows ICO frames (16, 24, 32, 48, 64, 128 and 256 px) independently from the master with high-quality downsampling. Apply at most one restrained edge-sharpening step after downsampling, then visually inspect tiny sizes; do not over-sharpen the dolphin or text.
4. Use the correct high-resolution artwork for the main-window brand and installer wizard; use the ICO for window/taskbar/desktop shortcut icons. Confirm shortcut and uninstaller icons match.
5. Use a pre-rendered 256px launcher variant only if/when a future Android project begins. Android is not part of this desktop build.
6. Add image-quality tests for source dimensions, output sizes, ICO frame inventory, exact source selection and stale legacy-logo detection. Add a human visual-review checklist because byte/dimension tests cannot prove that a logo looks sharp.

## 8. Security, privacy and reliability

- No telemetry or cloud dependency in MVP. The app connects directly from the user's PC to the selected MySQL server.
- Master passphrase storage: Argon2id verifier with a random salt and documented parameters; no reversible master-password storage. Do not reuse the master passphrase as a database password.
- Database secrets: Windows Credential Manager only. On unavailable or unhealthy credential backends, ask again rather than falling back to plaintext files.
- TLS: clear mode, verification status and warnings in the connection details. Do not turn off certificate validation globally to hide a server-specific error.
- Validate file paths on open/save/export. Do not auto-execute SQL on opening a file or reconnecting.
- Avoid logging query results, credential-bearing DSNs, environment secrets or raw driver exception strings without redaction.
- Keep third-party dependencies pinned and reviewed; generate an SBOM for release candidates and run dependency/security scanning in CI.
- Document the local files created, what each contains, how to clear history and where the Windows credential entries can be removed.
- Add license notices for Qt/PySide6 and all bundled dependencies. Check the applicable Qt license and redistribution requirements before distributing the executable.

## 9. Build, CI and release engineering

The Windows release pipeline must be independent of Android and contain no Android SDK, Gradle, APK, AAB, mobile signing, mobile web-server or pairing steps.

### Continuous integration

On every push and pull request:

1. Set up the pinned Python version and install from the lock file in a clean virtual environment.
2. Run formatting/linting, type checks and unit tests.
3. Run connection/parser/security unit tests without requiring production credentials.
4. Start disposable MySQL service instances for integration tests; cover the supported MySQL versions and authentication/TLS configurations.
5. Run GUI tests under a headless Qt platform where possible, plus a Windows GUI smoke test.
6. Run dependency audit, secret scan, license/SBOM generation, and verify that no Android paths or legacy module imports enter the desktop package.
7. Build the application folder and portable EXE on Windows. Treat warnings/errors from missing Qt plugins or resources as failures.

### Release output

- `MySQLEditor-Setup.exe`: Inno Setup installer with modern wizard pages, correct application name/icon, Start Menu shortcut and optional desktop shortcut, clean install/upgrade behavior, clear uninstall, and no leftover runtime errors.
- `MySQLEditor-Portable.exe`: portable build with no console window, resources embedded or colocated correctly, and no writes into protected install directories.
- `MySQLEditor-Folder.zip`: optional directory build for diagnostics or advanced users.
- `SHA256SUMS`, `RELEASE-NOTES.md`, SBOM and an explicit Windows-signing-status note.
- Authenticode signing when a valid certificate is configured. Never claim a preview build is signed if it is not. Do not publish release assets unless the files exist, the checksum manifest validates, and the packaged-app smoke test passes.
- Publish a GitHub pre-release first. Promote it only after manual QA and the release checklist are complete. No APK/AAB assets in this phase.

## 10. Test strategy and acceptance gates

### Unit tests

Newly written tests for profile validation, credential-store failure behavior, password verifier logic, settings migrations, SQL splitting with strings/comments, SQL classification, statement warnings, formatter errors, connection-error translation, result paging, export encoding, log redaction and cancellation states.

### Integration tests

Against disposable MySQL instances: success/failure login, wrong port, unreachable host, permissions, empty databases, Unicode, NULL values, big result sets, DDL/DML, transactions/rollback, timeouts, reconnects, server-side errors and TLS policies. No production database or production secret may be used in CI.

### UI and packaged-app tests

- Open app and first-run wizard on a clean Windows account.
- Create and confirm master passphrase; verify confirmation failure and wrong-password failure.
- Restart and confirm startup opens the compact connection window.
- Connect/disconnect, open query tabs, run a SELECT, inspect results, export CSV and recover from a bad query.
- Resize the window and change Windows display scaling. Verify keyboard navigation, focus states, minimum size and no overlapping controls.
- Install, launch from Start Menu and desktop shortcut, upgrade in place, launch portable build, uninstall, reinstall, and verify no “could not call proc” or other uninstall runtime error.
- Test on a clean Windows VM that has no Python or MySQL client installed.
- Confirm exact logo appears in the window, taskbar, shortcut, installer and uninstaller without a fuzzy 256px-to-large resize.

### Release acceptance criteria

A release candidate is accepted only when **all** are true:

- [ ] The product source tree is a clean new implementation and has no runtime imports from MySQL IDLE or its modules.
- [ ] No Android app, APK/AAB output, mobile companion, or mobile setup is part of the desktop branch or release workflow.
- [ ] New tests are independent; the old test suite has not simply been renamed.
- [ ] CI passes on the exact commit used for the release.
- [ ] The packaged app works on a clean Windows VM without Python or MySQL client prerequisites.
- [ ] The connection, editor, result grid, transaction controls, history and CSV export behave as specified.
- [ ] Secret storage and logs pass security review; TLS behavior is explicit and tested.
- [ ] The Figma-inspired interface passes visual review at common window sizes and display scales.
- [ ] The logo's master source and generated icon assets pass both automated checks and human sharpness review.
- [ ] Installer, portable executable, checksums, notes and signing status correspond to the same commit and exact artifacts.
- [ ] README, privacy policy, security guide and support instructions describe only features that actually ship.

## 11. Implementation sequence

| Phase | Outcome | Exit gate |
|---|---|---|
| 0 — Product contract and clean branch | Confirm features, keyboard map, supported server/runtime matrix, design tokens and file disposition. Create a clean rebuild branch. | Approved scope; original source tree is left intact until cutover. |
| 1 — Independent foundation | New package, dependency lock, app startup, structured logging, configuration migration layer, CI and blank testable shell. | Clean install runs; no legacy module imports; lint/type/unit gates pass. |
| 2 — High-fidelity UI shell | Theme system, main window, top bar, sidebar, tabs, editor pane, results pane, dialogs and accessibility states. Use logo master properly. | Reviewed screenshots at 100–200% scaling; no dummy terminal UI or inert controls. |
| 3 — Connection and security | Profile manager, credential store, local master lock, connection testing, TLS modes and safe errors. | Integration tests for success/failure, secret handling and TLS policy pass. |
| 4 — Editor and results engine | SQL editing, parsing, selected-statement execution, worker pool, result streaming/grid, exports and transaction workflow. | Integration tests pass against disposable MySQL; UI remains responsive on slow queries. |
| 5 — Product-grade behavior | Schema navigation, saved queries, history policy, preferences, keyboard shortcuts, robust error and empty states. | Feature acceptance tests and usability review pass. |
| 6 — Windows packaging | Portable EXE, app folder, setup wizard, shortcuts, uninstall/upgrade flow, generated icons and checksums. | Clean Windows VM install/launch/uninstall/upgrade passes. |
| 7 — Release candidate | Security/license/SBOM review, docs, release notes, manual QA and pre-release build. | Every acceptance checkbox is signed off; publish only this verified commit. |
| 8 — Cutover and cleanup | Make the clean-room desktop tree the main product; remove Android and legacy source/tests/workflows/docs from the product branch. | Final tree and release contents contain only the new desktop product and its required shared assets. |

## 12. Explicitly deferred

No Android app, APK/AAB, mobile companion web UI, cross-device master-password synchronization, phone pairing, cloud accounts, hosted database proxy, team workspace or background telemetry. These require a separate threat model, architecture and plan later and must not complicate the first desktop release.

## Definition of success

A user downloads the Windows installer, sees a sharp MySQL Editor logo, completes the first-run passphrase setup, enters a small connection dialog, connects directly to MySQL, writes SQL in a genuine editor, executes it without freezing the interface, inspects and exports results, and can cleanly upgrade or uninstall the app. Every piece of that experience comes from the newly built desktop codebase—not a component inherited from MySQL IDLE.
