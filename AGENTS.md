# MySQL Editor — Engineering Instructions

This repository is a clean-room **Windows desktop** MySQL editor built with Python and PySide6. It is not a web application, a Base44 app, or an Android project. Do not add unrelated platforms, cloud relays, telemetry, or mobile components as part of desktop work.

## Read the relevant project skill before changing code

- `.agents/skills/karpathy-guidelines/SKILL.md` — surgical, goal-driven changes.
- `.agents/skills/qt-desktop-quality/SKILL.md` — Qt UI behavior, accessibility, preferences, error recovery.
- `.agents/skills/mysql-security-review/SKILL.md` — credentials, TLS, SQL safety, query history, local data.
- `.agents/skills/code-review/SKILL.md` — CodeRabbit review workflow and truthful reporting.
- `.agents/skills/windows-release-verification/SKILL.md` — validation and Windows packaging/release checks.

Apply the skills relevant to the change. Do not force unrelated skills or services into the product.

## Product boundaries

- Keep all runtime source under `src/mysql_editor/`; the app connects directly from the local machine to a configured MySQL server.
- Database work must remain off the Qt UI thread. Do not block the event loop with SQL, schema reads, or full exports.
- No database password may be persisted in SQLite, SQL snippets/history, logs, or plaintext files. Saved passwords must use Windows Credential Manager only.
- Query history remains opt-in and redacted. Treat result spools and CSV exports as sensitive local data.
- TLS modes must remain explicit and accurately described; SQL risk prompts are advisory, not an authorization boundary.
- Never silently discard unsaved SQL edits or a prior export when a write fails.
- Keep the supplied logo as the authoritative brand asset. Preserve high-DPI scaling and keyboard navigation.
- Do not claim a release is signed, secure, or production-certified without the relevant verification evidence.

## Required checks

Run these from the repository root where the dependencies are available:

```powershell
python -m ruff check src tests tools
python -m compileall -q src tests tools
python -m pytest
python -m pip_audit -r requirements.txt
```

The GitHub Actions workflow runs the test matrix on Python 3.12–3.14, plus a real MySQL 8.4 integration service. The Windows release workflow is the source of truth for importing the application in its packaging environment, building PyInstaller and Inno Setup packages, launching packaged executables, and testing installer/uninstaller behavior. A Linux failure to load platform GUI libraries is not evidence that the Windows build is broken; do not remove the Windows startup gate to hide an import failure.

## Change workflow

1. Read the relevant source, tests, and skill guide before editing.
2. Add a regression test for the behavior being corrected.
3. Keep the patch focused; do not rewrite unrelated modules.
4. Run checks and inspect results. Fix failures instead of weakening tests.
5. Use a pull request; do not claim complete validation until checks pass.
6. Update the README/release notes when user-visible behavior or operational procedures change.
