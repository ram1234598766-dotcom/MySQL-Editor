---
name: qt-desktop-quality
description: "Use when editing the PySide6 UI, dialog flows, keyboard shortcuts, window state, startup, file operations, or interaction feedback."
---

# Qt Desktop Quality

## Interaction rules

- Keep database queries, schema discovery, and large exports in the worker thread, not the Qt event loop.
- Use the correct Qt module for each type; most widgets belong to `PySide6.QtWidgets`, graphical primitives to `QtGui`, and signals, timers, and settings to `QtCore`.
- Use non-destructive confirmations for destructive SQL and unsaved edits. A failed file write must not clear the editor's modified flag.
- Catch expected `OSError` and decoding errors at file-operation boundaries and show a recoverable dialog with redacted details.
- Avoid silent no-op failures. Keep the status bar specific about what happened and what the user can do next.
- Keyboard actions must have predictable shortcuts, focus must remain visible, and touch/target sizes and color contrast should remain readable.
- Persist only useful local UI preferences, tolerate invalid/missing settings, and keep startup safe when no settings exist.
- Respect splitter behavior, high-DPI scaling, and windows that may be resized or restored to smaller/larger monitors.

## Verification

- Add a regression test for the behavior changed.
- Run Ruff, compileall, and pytest.
- The Windows workflow must successfully import `mysql_editor.app`, package the app, launch both packaged variants, and pass silent install/uninstall smoke tests.
- Do not claim visual QA was performed on a physical Windows display unless it actually was.
