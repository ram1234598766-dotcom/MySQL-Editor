# MySQL Editor — Windows Release Candidate Checklist

Use this checklist on the exact candidate commit shown in `RELEASE-MANIFEST.json`. Automated CI status and hands-on Windows acceptance are separate gates. Do not mark an item complete unless it was actually checked, and do not call an unsigned preview publisher-verified.

## Automated release gates

The Windows packaging workflow must pass all of the following for the candidate commit:

- [x] Lint, Python compilation, and full unit/UI test suite on Python 3.12, 3.13, and 3.14.
- [x] Disposable MySQL 8.4 integration tests.
- [x] Declared-runtime and installed build-environment dependency audits.
- [x] Windows Qt startup/preferences/file-recovery smoke tests.
- [x] Onedir executable and portable executable builds.
- [x] Inno Setup installer build, silent installation, desktop shortcut check, silent uninstall, and shortcut cleanup.
- [x] Launch smoke test for both packaged executables.
- [x] Release manifest, CycloneDX SBOM, third-party license inventory, and SHA-256 checksums.

### Verified automated gate record — 18 October 2026

The automated items above passed on the exact product source commit `b37e1e146d3526b298b31fe3c13205ae4323dbdc`. The later documentation-only merge `6bba4814e9138670ed9df3813df45f9dda16aed8` did not change application code. Re-run the automated gates for any future code-changing candidate.

- [Desktop CI](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39118312368) — **PASS**: lint, compilation, Python 3.12/3.13/3.14 tests, Windows Qt UI smoke, and MySQL 8.4 integration.
- [Dependency security audit](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39118312479) — **PASS**.
- [Windows package workflow](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39118312396) — **PASS**: onedir application, portable EXE, installer build, install/uninstall and shortcut-cleanup smoke, app launch, output verification, release manifest, SBOM, license inventory, SHA-256 checksums, and artifact upload.

These are CI results and an Actions artifact, not a stable GitHub Release or trusted-publisher signature. All hands-on Windows acceptance items below intentionally remain unchecked.

## Hands-on acceptance — Windows 10/11 x64

Record the tested machine, Windows version/build, monitor scaling configuration, MySQL server version, and date before checking items.

- [ ] Install from `MySQLEditor-Setup.exe`; confirm the app icon, installer branding, Start Menu shortcut, desktop shortcut, and uninstaller are correct.
- [ ] Launch the installed app and `MySQLEditor-Portable.exe`; confirm neither immediately exits or opens a blank window.
- [ ] Check 100%, 125%, 150%, and 200% scaling on the real target display(s); verify readable text, crisp logo rendering, and no clipped or overlapping controls.
- [ ] Complete SQL editing, Find/Replace, completion, schema navigation, result sorting/filtering, cell copy, and CSV export using keyboard-only navigation.
- [ ] Use Narrator or another screen reader to inspect connection, SQL, results, error, and confirmation flows.
- [ ] Verify the local master-password unlock flow and that remembered MySQL passwords are stored only through Windows Credential Manager, not plaintext application files.
- [ ] Test connection success and recoverable failure against a non-production MySQL server, including the intended TLS policy and certificate configuration.
- [ ] Run a read-only query, a multi-statement script, a query failure, and a cancellation attempt; verify each status is truthful and SQL text is preserved.
- [ ] Change theme, editor preferences, and result-grid settings; restart and confirm preferences persist without losing unsaved SQL during a live theme change.
- [ ] Export a filtered/sorted result; verify CSV includes all fetched rows in original fetch order and preserves SQL NULL versus empty text.
- [ ] Uninstall; confirm the desktop/Start Menu shortcuts are removed and the installer reports no runtime error.

## Manual test record

- Candidate commit SHA:
- Release/tag URL:
- Tester:
- Test date:
- Windows edition/version/build:
- Display(s) and scaling:
- MySQL server/version/TLS mode:
- Outcome: **Pending**
- Failures, screenshots, or notes:

Do not promote a preview to a stable release until failed items have been addressed and this record is complete. Current preview builds are unsigned; hashes help detect file mismatches but do not prove software safety.
