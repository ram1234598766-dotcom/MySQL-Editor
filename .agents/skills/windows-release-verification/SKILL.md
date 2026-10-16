---
name: windows-release-verification
description: "Use when building, packaging, testing, or publishing MySQL Editor Windows releases."
---

# Windows Release Verification

## Before packaging

- Run lint, bytecode compilation, and unit tests across supported Python 3.12–3.14.
- Run the disposable MySQL 8.4 integration suite.
- Run dependency auditing from the locked/reviewed project requirement files.
- Import `mysql_editor.app` in the actual Windows packaging environment before PyInstaller. Import failures must fail the workflow.

## Packaged validation

- Build both onedir and portable executables, plus the Inno Setup installer.
- Run `tools/smoke_test_ui.py` on Windows with `QT_QPA_PLATFORM=offscreen` to verify UI preferences restore and file read/write failures preserve the user's buffer.
- Smoke-launch both packaged executables and fail if either exits during startup.
- Perform silent install/uninstall; verify the executable and uninstaller exist, the desktop shortcut appears, and uninstall removes it.
- Verify output sizes and generate the SBOM, third-party license inventory, release notes, and SHA-256 manifest.
- Publish only when all preceding checks pass.

## Release reporting

- Give the exact tag and download links. Never re-use an older release path for a new build.
- State whether the build is a preview or a stable release.
- Do not describe an unsigned app as publisher-verified. Code-signing must use a trusted certificate and the final signature must be checked.
- CI does not substitute for manual QA on physical Windows systems, high-DPI displays, installer upgrades, and diverse MySQL/TLS setups.
