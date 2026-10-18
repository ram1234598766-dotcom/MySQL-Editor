# Phase 0 — Baseline Audit

**Audit date:** 18 October 2026  
**Repository:** https://github.com/ram1234598766-dotcom/MySQL-Editor  
**Default branch:** `main`  
**Audited commit:** `2226d4084f8f740bb91f95a673477ffdaa3bba24`  
**Scope:** Read-only review of the desktop source architecture, tests, workflows, roadmap, and release metadata. No application logic is changed by this audit.

## Executive result

**Automated baseline: PASS. Manual Windows acceptance: NOT VERIFIED by this audit.**

The latest Windows packaging workflow completed successfully against the exact audited commit. It ran the Python 3.12–3.14 release test matrix, the disposable MySQL 8.4 integration suite, and the Windows package/install/launch/uninstall checks. The current-head Windows artifact and simulated UI visual-QA artifacts were uploaded to GitHub Actions. The latest dependency-security workflow for the exact commit also passed.

This is sufficient evidence for a controlled next feature branch, but it is not proof of a stable, signed release or of hands-on testing on a physical Windows PC.

## 1. Exact baseline and CI evidence

| Check | Evidence | Result |
|---|---|---|
| Audited commit | [`2226d4084f8f740bb91f95a673477ffdaa3bba24`](https://github.com/ram1234598766-dotcom/MySQL-Editor/commit/2226d4084f8f740bb91f95a673477ffdaa3bba24) | Recorded |
| Current-head release test/build workflow | [Run 39058548121](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39058548121) | **PASS** |
| Current-head dependency security | [Run 39058548149](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39058548149) | **PASS** |
| Desktop CI | [Run 39057661944](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39057661944) on commit `6a7a4c0e8ab95d3da8d1e5abb0181494ba3adb9e` | **PASS** |
| Source difference between desktop-CI commit and audited commit | GitHub compare shows `README.md` was the only changed file; no runtime source or test file changed in that interval. | Confirmed |
| Current-head Windows workflow artifacts | The run uploaded `MySQLEditor-Windows` and `MySQLEditor-UI-Visual-QA`. | Present |
| Release publication from current-head workflow | The `Publish Windows preview or release` job was skipped. | **Not published by this run** |

The current-head Windows workflow's release test jobs passed for Python 3.12, 3.13, and 3.14, including the MySQL 8.4 integration job. The Windows build job also passed its import/startup validation, simulated-scale screenshot generation, folder and portable executable builds, Inno Setup installer build, silent installation, desktop shortcut creation/removal, launch smoke tests, package-size checks, manifest generation, SBOM/license generation, and checksum generation.

### Release freshness and signing

The latest listed GitHub Release is [Windows Preview Build 173](https://github.com/ram1234598766-dotcom/MySQL-Editor/releases/tag/windows-preview-39057661925), associated with commit `6a7a4c0e8ab95d3da8d1e5abb0181494ba3adb9e`. The current audited commit differs from that commit only in `README.md`, but its newly built packages are available as Actions artifacts rather than as a newly published Release. The current-head workflow skipped publication because its publish condition requires a tag or a qualifying `[publish-windows-preview]` commit message.

The workflow and `WINDOWS_SIGNING.md` explicitly describe the packages as **unsigned**. Hashes and a release manifest help with artifact integrity and provenance; neither is an Authenticode publisher signature. Do not describe the package as signed or publisher-verified.

## 2. Source architecture

- **Runtime:** Clean-room Windows desktop application under `src/mysql_editor/`, using Python, PySide6, and MySQL Connector/Python. The repository's `AGENTS.md` explicitly rules out migrating legacy MySQL IDLE components or adding Android, cloud-relay, or Base44 application components to this desktop project.
- **SQL core:** `src/mysql_editor/core.py` contains a hand-written state-machine statement splitter that handles ordinary statement separators around strings/comments, a conservative risk advisory, redaction helpers, and SQLGlot-backed formatting. SQLGlot is not currently wired in as a complete SQL-execution parser or a semantic validator.
- **Database work:** `src/mysql_editor/database.py` owns a dedicated `QThread` worker for database operations. Result rows are fetched in batches and retained in a temporary SQLite spool; sensitive row/export data needs to remain treated as local confidential data.
- **Results:** The visible query-result preview is capped at 2,000 rows; table preview is capped at 1,000 rows. CSV export uses the fetched result spool, so sorting/filtering the visible grid does not limit the exported fetched set.
- **Schema Explorer:** Currently discovers visible databases, tables/views, and column names, switches the active schema through the worker, and can preview a table. It does not yet expose a dedicated DDL/index/constraint inspector.
- **Build/release:** GitHub Actions has desktop CI, dependency-security, and Windows package/release workflows. The package workflow creates the app-folder archive, portable EXE, setup installer, release manifest, SBOM, license inventory, release notes, signing disclosure, and SHA-256 checksums.

## 3. Requested feature-gap matrix

| Capability from the advanced upgrade plan | Baseline finding | Implementation status |
|---|---|---|
| MySQL `DELIMITER` and stored-program script support | The app detects a `DELIMITER` directive and fails closed by rejecting the entire script before it is queued. It does **not** parse custom delimiters or compound stored-program bodies yet. | **Open — Phase 1** |
| Fetch-more / result pagination | All rows returned by the query are read into the session spool, but the initial visible preview is bounded at 2,000 rows. No user-facing paging control or spool-page action was identified. | **Open — Phase 2** |
| MySQL-aware parser | SQLGlot is declared as a dependency and used for formatting. Statement splitting and risk advice remain separate hand-written logic; formatting/risk checks are not server-side validation. | **Partial — further parser work needed** |
| Visual execution plan | The existing Explain action prepends plain `EXPLAIN` and sends the result to the ordinary grid. A structured JSON/TREE plan visualizer was not identified. | **Open — Phase 5** |
| DDL/schema inspector | Database/table/view and column-name browsing exist. A dedicated `SHOW CREATE TABLE` viewer and index/constraint/property inspector were not identified. | **Partial — metadata viewer needed** |
| Safe inline result editing | The inspected result model exposes data for display/sort/filter, with no editable-cell/update path identified. | **Open — Phase 6** |
| Windows Authenticode signing | The build explicitly marks packages unsigned; no trusted signing and final signature-verification step is configured in the inspected release workflow. | **Open — Phase 7** |
| GitHub Releases update checker | No update-check implementation was identified in the inspected app, README, or workflows. | **Open — Phase 7** |

Existing functionality should not be rewritten merely to match the new roadmap. In particular, preserve background database execution, fail-closed handling for unsupported scripts until the new parser is ready, the current spool/export semantics, explicit TLS modes, and the existing credential-storage policy.

## 4. Security and product invariants to preserve

- Saved MySQL passwords must use Windows Credential Manager only; never add plaintext fallback or put passwords into SQLite, logs, query history, snippets, or test artifacts.
- The local master-password gate is device-local, not an account or cross-device synchronization feature.
- Query history remains opt-in and heuristically redacted; do not claim redaction catches every possible secret.
- TLS modes must describe encryption separately from server identity verification.
- SQL-risk prompts are advisory; MySQL privileges remain the actual access-control boundary.
- Database I/O, schema reads, and large exports remain off the Qt UI thread.
- Existing result spools and exports remain sensitive; failed exports must not corrupt an existing destination.
- Keep the authoritative logo and Windows packaging/shortcut/uninstall behavior intact.

## 5. Manual Windows acceptance still pending

The project’s `RELEASE-CANDIDATE-CHECKLIST.md` appropriately separates hosted CI from hands-on acceptance. This audit did not perform these physical-device checks, so they remain pending:

- Verify the installed and portable executables on a real Windows 10/11 PC.
- Check 100%, 125%, 150%, and 200% display scaling on actual monitor(s), including crisp logo rendering and unclipped controls.
- Complete keyboard-only navigation and a Narrator/screen-reader spot check.
- Exercise first-run master-password creation, unlock, saved/stale credentials, and the actual Windows Credential Manager backend.
- Test success and recoverable failure against the target non-production MySQL server with the intended TLS/certificate policy.
- Exercise scripts, query failure, cancellation, result sorting/filtering/copy, CSV export, preferences, and installer/uninstaller behavior on the target PC.

The workflow generates simulated display-scale screenshots on a hosted Windows runner, but that is not the same as hands-on physical-monitor validation.

## 6. Audit limitations

A local clone was attempted in the execution environment, but DNS resolution for `github.com` failed (`Could not resolve host: github.com`). Therefore this audit did not independently execute pytest, Ruff, compilation, or the CodeRabbit CLI locally. The automated test/build conclusions above come from the linked GitHub Actions runs, not from local execution. The repository’s `.coderabbit.yaml` has automatic review enabled for non-draft PRs; this report does not claim a CodeRabbit review unless an actual review result is recorded on the audit PR.

The GitHub branch metadata reported `protected: false` for `main`; the branch-protection detail endpoint was not accessible through the connected integration, so enforceable rules could not be fully inspected during this audit.

## 7. Phase 0 decision and Phase 1 gate

**Decision:** The baseline is documented and the exact audited commit has successful automated test/build/security evidence. Phase 0 is ready to close for purposes of beginning a separate implementation branch, with physical Windows acceptance remaining an explicit release-candidate task.

**Phase 1 scope:** Implement a dedicated MySQL-client script parser for `DELIMITER` changes and compound stored-program bodies, preserving source offsets and line numbers. Do not strip/send client-only delimiter directives to MySQL. Keep the existing fail-closed guard until the new parser, regression tests, and integration behavior are verified.

**Phase 1 acceptance criteria:**
1. Regression tests cover custom delimiters, multiple routines, strings, escaped quotes, backticks, line/block comments, whitespace, malformed directives, and ordinary multi-statement SQL.
2. No statement is submitted if parsing fails; successful parsing preserves intended statement order and source-line-aware errors.
3. The existing full test matrix and disposable MySQL 8.4 integration pass.
4. CodeRabbit review is recorded when available; findings are resolved or explicitly justified.
5. The Windows package workflow builds and smoke-tests the resulting EXE/installer from the exact PR head before merge.
6. Only Phase 1 changes are included; no unrelated UI, branding, or release changes are bundled into it.

## References

- [Repository engineering instructions](https://github.com/ram1234598766-dotcom/MySQL-Editor/blob/main/AGENTS.md)
- [Current upgrade roadmap](https://github.com/ram1234598766-dotcom/MySQL-Editor/blob/main/UPGRADE_ROADMAP.md)
- [MySQL 8.4 stored-program delimiter documentation](https://dev.mysql.com/doc/refman/8.4/en/stored-programs-defining.html)
- [SQLGlot API documentation](https://sqlglot.com/sqlglot.html)
- [MySQL EXPLAIN documentation](https://dev.mysql.com/doc/refman/8.4/en/explain.html)
