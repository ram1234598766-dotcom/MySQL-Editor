# MySQL Editor — Windows Preview Release Notes

**Application version:** 0.1.0  
**Channel:** Preview — this is an unsigned preview build, not a stable release.  
**Platform:** Windows 10/11 x64  
**Source and verification:** See `RELEASE-MANIFEST.json` for the exact source commit, package hashes, build metadata, and signing state.

## What's new in this preview

- **Visual JSON execution plans:** Explain SELECT uses `EXPLAIN FORMAT=JSON` and opens an expandable plan tree with a raw JSON tab and Copy JSON action. It does not execute the original SELECT. Row counts and optimizer costs are estimates.
- **Guarded table-preview editing:** Schema Explorer supports single-cell updates only on verified transactional base-table previews and eligible non-primary-key columns. Changes remain subject to the existing manual Commit/Rollback workflow. Full rollback restores edited preview snapshots; rollback to a savepoint marks affected cached previews stale until refresh.
- **Optional stable-release update checking:** Automatic startup checks are disabled by default. A one-time Help → Check for updates action does not enable future startup requests. The app validates release tags and canonical GitHub release URLs, does all network work off the UI thread, and never downloads or installs updates automatically.
- **Accessibility contrast improvements:** The light theme's selected navigation and generic disabled-control text colors have regression checks. Generic disabled text now uses `#5D6B7B` on `#F2F5F9` (approximately 4.98:1 contrast); the selected-navigation color remains `#056C78` on `#D6E3F2` (approximately 4.71:1).
- **SQL risk advisory hardening:** Executable SQL comments are inspected by the risk advisory so comments cannot trivially hide potentially destructive SQL from the user.
- **SQL analysis and formatting:** Parseable MySQL `UPDATE`/`DELETE` statements use the SQLGlot AST to distinguish an outer `WHERE` predicate from predicates inside CTEs and subqueries. The heuristic fallback remains for unsupported syntax; this advisory is not an authorization boundary. SQL formatting now preserves multiple parsed statements and refuses scripts using MySQL-client `DELIMITER` directives rather than risking changes to stored-program boundaries.
- **Result paging:** The result grid requests the next local SQLite spool page when you scroll to its end; **Fetch +1,000** remains a manual fallback. Page requests run through the database worker and do not rerun the SQL. Loaded rows accumulate during browsing, so a bounded cache-eviction strategy for million-row views remains future work.
- **Release engineering:** The Windows workflow builds the application-folder distribution, portable EXE, and installer; validates install/uninstall and packaged launch; generates SBOM, third-party license inventory, release manifest, and checksums.

## Downloadable Windows packages

The GitHub Release for this preview contains the following artifacts when the Windows package workflow completes successfully:

- **`MySQLEditor-Setup.exe`** — standard installer with Windows shortcuts and uninstaller.
- **`MySQLEditor-Portable.exe`** — portable single-file executable.
- **`MySQLEditor-Folder.zip`** — application-folder distribution.
- **`SHA256SUMS`** — SHA-256 hashes for the released packages and supporting documents.
- **`RELEASE-MANIFEST.json`** — source commit, project version, Windows build metadata, signing disclosure, and each package's relative path, byte size, and SHA-256 hash.
- **`sbom.cdx.json`** — CycloneDX dependency inventory.
- **`THIRD_PARTY_LICENSES.md`** — third-party license inventory.
- **`WINDOWS_SIGNING.md`** — signing behavior and limitations.

The workflow builds the manifest from the final files and the exact `GITHUB_SHA`; `SHA256SUMS` includes a hash of the manifest itself. These files provide provenance and integrity checks, not a safety guarantee.

## Signing status and Windows warnings

**Preview binaries are intentionally unsigned.** The configured self-signed certificate was verified by signing a disposable executable on a trusted `main` run; it was not used to sign distributed preview artifacts. The stable-tag workflow is a separate path and fails closed unless signing configuration and artifact verification succeed.

Windows may show SmartScreen or unknown-publisher warnings for these unsigned preview files. Do not bypass a warning solely because a file is hosted on GitHub. A matching SHA-256 hash detects file mismatches but does not prove software safety. A future stable build signed with the selected self-signed certificate will still not establish publisher trust on recipient PCs by default.

## Validation and known limits

The current main commit passed desktop CI, dependency-security audit, and the complete Windows packaging workflow. Automated validation covers Python 3.12/3.13/3.14 tests, disposable MySQL 8.4 integration, Windows Qt startup/preferences and recovery smoke tests, application-folder and portable EXE builds, installer install/uninstall, packaged application launch, manifest/SBOM/checksum creation, and artifact upload.

**Manual acceptance on a physical target Windows PC remains outstanding.** Runner screenshots use simulated display scaling and synthetic data. They cannot certify the actual display, screen-reader operation, Windows Credential Manager state, or the user's MySQL/TLS environment.

## Scope

This is a Windows desktop MySQL client. Android APK/AAB, SSH tunneling, cloud relay, cross-device synchronization, analytics, ads, and telemetry are not part of this preview. The app does not install or start the MySQL server.
