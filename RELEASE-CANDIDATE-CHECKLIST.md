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
- [x] Candidate manifest accurately discloses the unsigned preview state; stable tags fail closed without verified Authenticode signing.

### Verified automated gate record — 19 October 2026

**Verified source commit:** `73e8c2687635a85d0151cbd040d1f65749479332`  
**PR:** [#54 — optional verified Windows Authenticode signing](https://github.com/ram1234598766-dotcom/MySQL-Editor/pull/54), merged to `main`.

The automated release gates passed on this exact `main` commit:

- [Desktop CI](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39216104552) — **PASS**: lint, compilation, Python 3.12/3.13/3.14 test jobs, Windows Qt UI smoke, and MySQL 8.4 integration.
- [Dependency security audit](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39216104455) — **PASS**.
- [Windows package workflow](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39216104411) — **PASS**: release test matrix, MySQL 8.4 integration, dependency audit, signing-helper syntax validation, app-folder and portable EXE builds, installer build, silent install/uninstall and shortcut cleanup, packaged-app launch, output validation, SBOM, provenance manifest, checksums, and artifact upload.

The Windows workflow produced a `MySQLEditor-Windows` Actions artifact (about 220.7 MB; SHA-256 of the Actions artifact archive: `55b0cb75edb51538bf1b191562737ca174cfd2d68ea6818f6e789622375f1a4d`, artifact ID `12170265978`). Download it from the [Windows workflow run](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39216104411); the artifact expires on 17 January 2027. The separate `MySQLEditor-UI-Visual-QA` artifact contains simulated-scale captures and expires on 2 November 2026.

**Signing status for this candidate: UNSIGNED.** No signing secrets were configured for this candidate, the SignTool release steps were skipped, and the manifest explicitly reports the unsigned state. Stable version tags fail closed unless `WINDOWS_SIGNING_CERTIFICATE_BASE64` and `WINDOWS_SIGNING_CERTIFICATE_PASSWORD` are configured and every published executable passes SignTool signature verification. The selected default is self-signed; the manifest must disclose that recipient PCs do not trust the certificate by default. See [`WINDOWS_SIGNING.md`](WINDOWS_SIGNING.md). A signature does not guarantee SmartScreen or antivirus will never warn.

These results are hosted-CI evidence, not physical-PC acceptance. All hands-on Windows items below remain unchecked. Do not promote a stable release until both the manual acceptance record and the signing gate are complete. A self-signed certificate can be used for signature verification but does not establish publisher trust on recipient PCs.

## Signing gate — stable releases

- [ ] Configure a self-signed Code Signing PFX using the two repository Actions secrets documented in `WINDOWS_SIGNING.md` (or choose a trusted CA certificate by setting the repository variable `WINDOWS_SIGNING_CERTIFICATE_TYPE=trusted`). A self-signed certificate is not trusted by recipient PCs by default.
- [ ] Build a version tag through the release workflow and confirm the application-folder executable, portable EXE, and installer each pass SignTool verification with a timestamp.
- [ ] Inspect `RELEASE-MANIFEST.json` and confirm `signing.status` is `signed`, `authenticode_verified` is `true`, `certificate_type` is `self-signed`, and `recipient_trust` is `not-trusted-by-default` for the selected mode; verify downloaded files against `SHA256SUMS`.

Preview builds may remain unsigned, but their release notes and manifest must state that clearly. Never infer publisher identity from CI success or hashes alone.

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
