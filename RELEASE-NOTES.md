# MySQL Editor — Windows Preview Release Notes

**Release channel:** Preview / pre-release  
**Platform:** Windows 10/11 x64  
**Signing status:** Unsigned — no trusted Authenticode publisher signature is included.

This is a clean-room Windows desktop SQL editor for MySQL. It is a preview build, not a publisher-signed production release. The Windows build workflow validates expected output files, launches packaged executables, and exercises installation/uninstallation before publishing the preview assets.

## Downloadable Windows packages

The release workflow attaches the following files when the package job succeeds:

- **`MySQLEditor-Setup.exe`** — standard Windows installer, Start Menu/desktop shortcut and uninstaller.
- **`MySQLEditor-Portable.exe`** — portable single-file executable.
- **`MySQLEditor-Folder.zip`** — application-folder distribution for diagnostics or users who prefer the onedir package.
- **`SHA256SUMS`** — SHA-256 hashes for the published packages and supporting release documents.
- **`RELEASE-MANIFEST.json`** — source commit, project version, Windows build metadata, signing disclosure, and each package's relative path, byte size, and SHA-256 hash.
- **`sbom.cdx.json`** — CycloneDX dependency inventory.
- **`THIRD_PARTY_LICENSES.md`** — third-party license inventory.
- **`WINDOWS_SIGNING.md`** — current signing status and instructions.

The workflow writes `RELEASE-MANIFEST.json` from the final package files and the exact `GITHUB_SHA`; its file hashes and byte sizes can be compared against downloaded artifacts. `SHA256SUMS` also hashes the manifest itself. The manifest is provenance evidence, not a publisher signature or a safety guarantee.

The Windows workflow also uploads the complete package folder and a simulated display-scale UI evidence artifact to GitHub Actions. These are useful for diagnostics; artifacts expire, while release assets remain available with the GitHub Release.

## Highlights in this preview

### SQL editor
- Multiple SQL tabs, syntax highlighting, line numbers, current-line highlighting, bracket matching, formatting, SQL-file open/save, and configurable editor font/tab width.
- Inline Find/Replace with match count, case-sensitive search, next/previous navigation, Replace, and Replace all.
- Live line/column and selection-length status.
- Keyboard-first completion for MySQL keywords/functions and schema-scoped table, view and column identifiers, including common qualified, alias and backtick-quoted contexts.
- Completion is a bounded editing aid, not a full MySQL grammar or type-checking engine. It should not change SQL unless a completion item is accepted.

### Connections and schema navigation
- Selecting a different database in Schema Explorer now switches the actual MySQL session on the database worker thread. The active badge, schema metadata, and saved profile default change only after MySQL confirms success; a failed switch keeps the prior context.
- Direct local-to-server MySQL connections, saved profiles, duplicate/delete profile actions, and saved database passwords stored through Windows Credential Manager rather than plaintext application storage.
- Explicit Automatic TLS, Verify server identity, and Disabled TLS policies; strict verification can use a supplied CA file.
- Schema Explorer supports database/table/view navigation, refresh, safe identifier copying, limited table preview, and generating a SELECT in a new tab.
- The active connection and schema context are visible in the workspace. Query execution is blocked when a query is already running or a disconnect is pending.

### Results and query feedback
- Multiple statement results, sortable preview grid, case-insensitive visible-row filter, row/column copy actions, and a cell-details view with **Copy full value**.
- CSV export writes atomically, uses fetched rows rather than only visible filtered rows, and preserves server-fetch order after grid sorting.
- CSV uses an unquoted `\\N` token for SQL NULL; empty text stays an empty field. Backslash-leading text is escaped so it remains distinguishable from NULL.
- Query lifecycle feedback distinguishes execution, fetching, cancellation requests, confirmed interruption, partial script failure, and export progress where the worker can report it.
- Standalone MySQL client `DELIMITER` directives such as `//` and `$$` are handled as client commands, not sent to the server. Compound stored-program bodies stay intact across internal semicolons; malformed directives and routine bodies that would be split under the default delimiter fail closed before any part of the script is submitted.

### Presentation, preferences and reliability
- Shared semantic dark-theme styling, System/Light/Dark appearance selection, editor font and tab-width preferences, result-row sizing, and a persistent Reduce Motion option.
- Contrast regression checks cover selected application states and SQL syntax colours; disabled primary actions use a contrast-tested disabled palette in both dark and light themes.
- Accessibility names/descriptions cover the main SQL, results, schema/history/snippets, connection and unlock controls; keyboard traversal is regression-tested for the connection and unlock forms.
- Theme-switch regression coverage verifies that query tabs, SQL buffer/cursor/selection, result filter/rows, connection context, and splitter state remain intact when changing appearance.
- Windows-runner visual evidence includes dark and light themes at simulated 100%, 125%, 150%, and 200% display scales. Screenshots use synthetic data and explicitly show an offline preview; they are not physical-monitor certification.
- Installer tests confirm the app executable and uninstaller are installed, the desktop shortcut is created, and uninstall removes the shortcut.
- Packaging checks build and launch the onedir and portable EXE variants, build the installer, verify expected files, and generate SHA-256, SBOM, and third-party license records before publication.

## Important limitations and safety notes

- **Unsigned binary:** Windows may show SmartScreen or unknown-publisher warnings. Do not bypass a warning solely because the file is hosted on GitHub. Review the repository and release, and compare a package's SHA-256 hash against `SHA256SUMS`. A matching hash detects file mismatches; it does not prove software safety.
- **Manual Windows QA remains necessary:** automated/offscreen and runner-based tests cannot certify every display scale, hardware configuration, real Windows Credential Manager state, installer-upgrade path, or remote MySQL/TLS environment.
- **MySQL server required:** MySQL Editor is a client and does not install or automatically start the database server.
- **TLS:** Automatic TLS can encrypt traffic without verifying server identity. Prefer Verify server identity for remote or untrusted networks. Disabled TLS should only be used when its lack of transport encryption is understood and accepted.
- **Cancellation:** stopping a query is best-effort and depends on server state, permissions and network conditions.
- **Safety prompts and redaction:** mutation warnings and query-history redaction are heuristic aids, not security boundaries. Use least-privilege database accounts and avoid putting secrets in SQL text.
- **Stored-program parsing scope:** statement splitting recognizes standalone `DELIMITER` changes and protects compound routine bodies, but is not a complete MySQL grammar or semantic validator. The MySQL server remains authoritative for SQL syntax, features, and permissions.
- **Local unlock:** the master password unlocks this installation only. It is not an online account and does not synchronize to another device.
- **Scope:** Android APK/AAB, cloud relay, cross-device synchronization, analytics, ads and telemetry are not included.

## Verification record

The Windows release workflow builds the onedir application, portable EXE, and installer from the exact release commit; checks their output paths and non-trivial size; launches the packaged EXEs; and runs silent install/uninstall smoke checks. The Phase 6 code commit `53218aed6b218925aec450bcb44796e462a9bcd6` passed [desktop CI](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39050148985), the [dependency-security audit](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39050148975), and the [Windows package workflow](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39050148964). The release-marker commit reruns package build and upload for the precise commit attached to the release. Review that final commit's Actions run before using the preview. Manual QA on a physical Windows machine remains **not verified by CI**.

