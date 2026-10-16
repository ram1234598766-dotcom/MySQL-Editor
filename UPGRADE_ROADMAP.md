# MySQL Editor — Advanced UX, Motion, and Engineering Upgrade Roadmap

**Document status:** Proposed implementation plan  
**Prepared:** 16 October 2026  
**Product target:** Clean-room, native Windows desktop IDE for MySQL  
**Primary stack:** Python, PySide6 / Qt, MySQL Connector/Python  
**Current implementation:** \`src/mysql_editor/\` on \`main\`  
**Design reference:** [MySQL Editor Figma workspace](https://www.figma.com/design/EFFQpRTE8pKybt1lQR0eQH)

This plan describes the next quality phase: make MySQL Editor feel exceptionally polished, responsive, cohesive, and dependable. The visual direction is a calm, dark database workspace with restrained colour, crisp typography, deliberate spacing, subtle motion, and no distracting effects. The work should improve real interaction quality—not add animation merely for decoration.

> **Important:** This is a roadmap, not a claim that every item is already implemented. Every phase requires small pull requests, regression tests, visual verification, and a release decision based on evidence. Never describe the product as error-free or production-certified simply because CI passed.

---

## 1. Product direction

### North-star experience

MySQL Editor should open quickly into a clear connection flow, then provide a stable workbench where the user always understands:

- **Where they are connected:** server, port, user, selected schema, and TLS policy.
- **What will run:** current statement, selection, or entire script.
- **What is happening:** connecting, executing, fetching, cancelling, exporting, or complete.
- **What the app changed:** visible confirmation after a successful action and a recoverable explanation after failure.
- **What is safe to assume:** local confirmations are guidance, MySQL permissions are the enforcement boundary, and cancellation may be best-effort.

The interface should feel considered and quick on an ordinary Windows laptop as well as on a high-resolution external display. It should not emulate a browser dashboard, a terminal transcript, or a mobile UI stretched across a desktop.

### Product boundaries

- Windows desktop is the current product phase; use the dedicated Android/mobile workstream only when that phase is explicitly reopened.
- Continue the clean-room implementation under \`src/mysql_editor/\`. Do not import, rename, or port application components from the legacy MySQL IDLE project.
- Connect directly from the user's PC to the configured MySQL server.
- Do not add a cloud relay, forced account, analytics, ads, or telemetry.
- Keep database secrets out of SQLite, ordinary logs, query history, snippets, screenshots, test logs, and repository files. Saved passwords must use Windows Credential Manager without a plaintext fallback.
- SQL risk warnings are advisory. Least-privilege MySQL accounts and server-side privileges remain the real access controls.
- Keep database I/O and large result processing off the Qt UI thread.
- Avoid unsafe dependency upgrades that break supported Python, Qt, MySQL driver, or Windows packaging combinations.

---

## 2. Current baseline and recent work

The repository is already a native PySide6 application with horizontal workspace navigation, query tabs, a SQL editor, results grid, schema/history/snippet panels, background database worker, connection profiles, a local master-password gate, Windows Credential Manager storage, CSV export, a guided tour, and Windows installer/portable packaging.

The recent advanced-workbench change adds:

- MySQL keyword/function completion with Ctrl+Space and inline suggestions.
- Suitable schema/database identifiers and result-column names in the completion dictionary.
- Improved syntax highlighting for block comments across lines.
- Case-insensitive result-grid quick filtering without dropping rows from CSV export.
- Numeric-aware result sorting.
- Safer heuristic risk advisory logic that masks literals/comments, inspects top-level WHERE clauses, and identifies common CTE-wrapped mutation patterns.
- Regression coverage for these behaviors.
- Updated PySide6 and development-tool minimums and refreshed GitHub Actions majors.

The associated pull request is [PR #7](https://github.com/ram1234598766-dotcom/MySQL-Editor/pull/7). Its Python 3.12, 3.13 and 3.14 unit-test jobs, MySQL 8.4 integration job, Windows Qt UI smoke test, and dependency-security audit passed for the verified PR head. That is evidence for those automated checks; it is not a substitute for hands-on visual QA on different Windows display scales, real Credential Manager states, and external MySQL/TLS setups.

### Current product limitations that should inform the plan

- SQL completion is an editing aid, not a full semantic engine. It does not yet reliably resolve every table alias, join scope, column type, or nested query context.
- The SQL statement splitter does not fully implement MySQL client DELIMITER directives or compound stored-program bodies.
- Result display is capped at 2,000 rows per query result; table preview is capped at 1,000 rows. CSV export is based on the fetched result spool.
- Query cancellation is best-effort and depends on server permissions/state.
- Some MySQL DDL implicitly commits.
- Risk detection and history redaction are heuristic; neither is a complete parser or security boundary.
- Automatic TLS negotiates encryption where supported but does not verify server identity; strict mode does.
- The current dark styling is spread through UI code and should be consolidated into reusable design tokens before substantial visual changes.
- Automated/offscreen tests cannot prove the visual result on every real display configuration.
- The Windows executable remains unsigned unless a trusted Authenticode signing certificate is configured and the final signature is verified.

---

## 3. Visual design system

Implement the visual foundation before adding many animated components. The app should derive its surfaces, typography, spacing, borders, and interaction states from named tokens rather than scattering colour literals and one-off styles through widgets.

### 3.1 Proposed dark theme palette

Use these values as a starting point, not a mandate. Validate final contrast with automated checks and visual review before freezing the palette.

| Token | Initial value | Intended use |
|---|---|---|
| \`window.bg\` | \`#0B111B\` | Main window background |
| \`surface.base\` | \`#101927\` | Editor and primary content surface |
| \`surface.raised\` | \`#162235\` | Cards, popups, menus, raised panels |
| \`surface.hover\` | \`#1B2B42\` | Hovered rows and secondary controls |
| \`surface.selected\` | \`#203650\` | Selected navigation, tree rows, tabs |
| \`border.subtle\` | \`#26364B\` | Dividers and panel boundaries |
| \`text.primary\` | \`#E7EEF8\` | Main labels, SQL text, grid text |
| \`text.secondary\` | \`#A6B6CB\` | Supporting text and metadata |
| \`text.muted\` | \`#8093AC\` | Low-priority metadata; not essential instructions |
| \`accent.primary\` | \`#37C7D8\` | Main action, keyboard focus and restrained highlights |
| \`accent.secondary\` | \`#8D91FF\` | Secondary accent, selected non-critical decorations |
| \`status.success\` | \`#4CC7A3\` | Successful operation |
| \`status.warning\` | \`#F2BE6B\` | Attention, long-running operation, caution |
| \`status.danger\` | \`#F07886\` | Errors and high-impact action warnings |
| \`editor.line.active\` | \`#14263A\` | Current SQL line |
| \`editor.comment\` | \`#8297B2\` | SQL comments |
| \`editor.keyword\` | \`#41D4E7\` | SQL keywords |
| \`editor.string\` | \`#F3C878\` | String literals |
| \`editor.function\` | \`#78B9FF\` | Built-in function names |
| \`editor.number\` | \`#C5A5FF\` | Numeric literals |

**Rules:**

1. Use a single primary action accent. Do not turn every button, border, icon, and card into a bright accent.
2. Keep the app background and editor surfaces stable. Use gradients sparingly—only in limited brand regions such as a header edge, a first-run welcome surface, or a subtle progress strip.
3. Avoid bright neon glows, blurred logo artwork, rainbow effects, glass effects behind dense text, and gradients underneath query results.
4. Colour is never the only state indicator. Combine colour with text, an icon, shape, or accessible name.
5. Maintain clear focus rings, readable disabled states, visible selection, and adequate contrast for essential content. Measure actual rendered contrast rather than assuming these sample colours pass.
6. Keep SQL syntax colours distinct from state/error colours so a keyword cannot look like an error.
7. Respect the provided logo and its transparent derivative. Do not redraw or distort the authoritative mark. Preserve aspect ratio and sharp edges.

### 3.2 Later light theme and theme settings

After the dark theme is stable, add an optional light theme and a System/Light/Dark preference. Do not simultaneously redesign both themes in the first pass.

- Introduce semantic theme tokens before styling each widget.
- Keep identical semantic meanings across themes: primary action, selected row, destructive state, disabled state, and focus indicator.
- Persist the selected theme locally in QSettings.
- Change themes without losing editor contents, cursor position, selection, active connection, result filters, splitter sizes, or current tab.
- Test light and dark modes across every primary surface before announcing light-mode support.
- Consider a high-contrast mode if standard themes cannot meet the accessibility needs of the target environment.

### 3.3 Spacing, type and component rules

- Use a consistent spacing scale, for example 4, 8, 12, 16, 20, 24, and 32 px.
- Keep text roles distinct: page title, section heading, normal control text, help text, status text, and code text.
- Prefer a clear system UI font for app chrome; keep a configurable monospace font for SQL.
- Keep click targets comfortably sized and tab/focus indicators explicit.
- Prefer consistent button heights, input spacing, corner radii, and separators over one-off widget effects.
- Do not rely on emoji as core navigation icons; replace them with a consistent, redistributable icon set or carefully authored Qt vector artwork.
- Maintain readable spacing around editor tabs, result toolbar, splitters, connection badge, and status bar at 100%, 125%, 150%, and 200% display scaling.

---

## 4. Motion and animation system

Animations must communicate state changes and make the interface feel deliberate. They must not delay work, conceal a failure, obstruct keyboard navigation, or turn the editor into a constantly moving display.

### 4.1 Motion principles

- **Purposeful:** animate entry, selection, disclosure, progress and completion—not every static label.
- **Short:** micro-feedback 100–150 ms; standard transitions 160–220 ms; tutorial transitions up to 280 ms.
- **Subtle:** small opacity or position changes, restrained colour changes, and limited progress indicators. Avoid large scaling, spring/bounce motion, overshoot, persistent shimmer, or full-window animated gradients.
- **Interruptible:** a second click, keyboard input, cancellation, or closing the dialog should stop or complete the existing animation without leaving widgets transparent or stuck.
- **Non-blocking:** no sleep loops, busy-waiting or synchronous animations that freeze the UI thread.
- **Accessible:** add a Reduce Motion preference; when enabled, replace movement/fades with immediate state changes while preserving focus and status communication.
- **Performance-aware:** avoid applying graphics effects to the entire main window or repainting large result grids on each animation frame.
- **Deterministic in tests:** animation should be disabled or time-controlled in most tests, with a small separate test for correct completion/cleanup.

### 4.2 Proposed motion tokens

| Token | Duration | Curve | Usage |
|---|---:|---|---|
| \`motion.micro\` | 120 ms | OutCubic | Button feedback, subtle disclosure |
| \`motion.standard\` | 180 ms | OutCubic | Navigation/page selection and small panels |
| \`motion.dialog\` | 200 ms | OutCubic | Dialog entrance/exit where native window behavior permits |
| \`motion.panel\` | 220 ms | InOutCubic | Compact inspector or collapsible panel |
| \`motion.tour\` | 260 ms | OutCubic | Guided-tour step changes |
| \`motion.progress\` | State-based | Linear only where necessary | Progress indicator—not decorative looping |

Use Qt's native animation facilities, such as QPropertyAnimation and QParallelAnimationGroup, only for widgets/properties that can be safely animated. Avoid assumptions about native OS window opacity on systems where it behaves inconsistently. Prefer predictable widget-level transitions.

### 4.3 Animation inventory

| Area | Intended motion | Guardrails |
|---|---|---|
| Workspace navigation | A quick colour/underline/indicator transition and instant focus transfer | Do not animate the entire editor or change focus unexpectedly |
| Inspector tabs | Subtle selection feedback; optional short fade when content truly changes | No animation during heavy schema population |
| Guided tour | Fade between steps; animate progress indicator | Back/Next must remain responsive; Skip/Finish must always work |
| Connection attempt | Indeterminate progress with clear text; button state changes | Must show failure and restore controls; no fake progress percentage |
| Query execution | Clear running state and optional small activity indicator | No blocking overlay across the editor/results; Stop remains available |
| Results loaded | One calm completion acknowledgement; optionally fade in the empty-state-to-grid transition | Never fade thousands of individual cells |
| Schema expand/collapse | Native tree disclosure animation only if it is stable and cheap | Keep double-click preview and keyboard expansion predictable |
| Status/toast messages | Fade in/out for short-lived non-critical notices | Important errors persist until dismissed or replaced |
| Dropdowns/popovers | Prefer native Qt menu behavior; subtle custom transition only when accessible | No custom animation that breaks keyboard navigation |
| Theme change | Short cross-fade only if it avoids flashing and doesn't disturb focus | Immediate update under Reduce Motion; preserve content and scroll |
| Installer | Keep platform-native steps fast and legible; improve progress/state copy | Do not add decorative installation animations that imply fake progress |
| Startup/unlock | Short, restrained transition only after the app is ready | No splash-screen delay; unlock and connection progress remain distinct |

### 4.4 Motion implementation architecture

Create one small UI module—proposed path \`src/mysql_editor/ui/animations.py\`—with named durations, easing choices, cancellable helpers, and an immediate-mode path for Reduce Motion. Add a settings preference stored through QSettings. Do not duplicate animation duration literals across feature widgets.

Add reusable helpers only after a specific animation has an acceptance test. Avoid a generalized animation framework that has more states than the UI needs.

**Animation acceptance criteria**

- No visible flicker, black frames, stale opacity effects, or widgets left hidden after interruption.
- Focus, selected row, current editor and keyboard shortcuts continue to work during transitions.
- Query execution, connection attempts, cancellation and file operations remain asynchronous where they already are.
- Reduce Motion causes a predictable immediate transition with no lost information.
- No recurring animation consumes CPU while the user is editing SQL or reading results.
- Repeatedly opening and closing panels/dialogs does not increase memory usage or leave timers/effects attached to deleted widgets.
- Offscreen tests verify final state and interruption; human visual QA verifies visual quality.

---

## 5. Upgrade phases

Work in focused pull requests. Each phase should have a defined scope, tests, screenshots or other evidence, and rollback-friendly changes. Avoid merging a giant UI rewrite and dependency overhaul as one unit.

### Phase 0 — Establish a reliable baseline

**Goal:** Know exactly what works before altering visuals.

Tasks:
- Record the default-branch commit and verify the CI/security/Windows-package runs for that exact commit.
- Capture baseline screenshots at 100%, 125%, 150%, and 200% scaling on supported Windows systems.
- Exercise first-run master-password creation, subsequent unlock, reconnect, missing/stale saved credentials, changing profile, and TLS modes.
- Check new/open/save/close tabs, unsaved-change prompts, formatting, completion, running a statement/selection/script, cancellation, history settings, schema preview, filtering, copy, CSV export, commit and rollback.
- Record known issues with reproducible steps, expected result, actual result, app version, and sanitized logs.
- Establish the current performance baseline for startup, editor typing, schema fetch, result preview, and export on a representative dataset.

Exit gate:
- Baseline is documented.
- Existing tests pass on the exact baseline commit.
- No unrelated behavior changes are included in the next visual-system PR.

### Phase 1 — Centralize visual tokens and component styling

**Goal:** Replace inconsistent styling with a cohesive design system before adding animation.

Tasks:
- Create a small theme module, proposed \`src/mysql_editor/ui/theme.py\`, to define semantic colour tokens, spacing, typography, border radii, component dimensions and stylesheet generation.
- Remove duplicated, conflicting and widget-local style rules from the current window/dialog/theme code as each component migrates.
- Standardize app header, brand block, connection badge, workspace navigation, primary/secondary/destructive buttons, forms, tabs, splitters, tables, tree views, menus, status surfaces and dialogs.
- Build one representative screen first and compare it against the Figma design reference; only then migrate remaining surfaces.
- Preserve selected, hover, pressed, disabled, keyboard-focus, error, warning and success states.
- Check logo alpha, rendering sharpness, icon scaling and layout clipping at different DPI settings.
- Add theme/token tests where useful; do not snapshot every single stylesheet string.

Deliverables:
- Central dark-theme tokens.
- Consistent shared component styles.
- Screen captures at the baseline display sizes.
- No visible white patches, blurry logo scaling, inconsistent bright borders, or unreadable disabled controls.

Exit gate:
- Header, navigation, editor, result grid, schema inspector, connection dialog and guided tour use the same semantic tokens.
- Contrast/focus checks are documented.
- Existing functional UI smoke tests continue to pass.

### Phase 2 — Add measured micro-animations

**Goal:** Make navigation and state changes smoother without making the app flashy.

Tasks:
- Add the shared animation helper module and a persistent Reduce Motion preference.
- Implement navigation feedback and one or two small transitions first.
- Refine guided-tour transitions and add correct interruption/close cleanup.
- Improve connection/query progress states with explicit copy and deterministic button enablement.
- Add non-intrusive success/error feedback for save, export, connect, disconnect, query completion and schema refresh.
- Prefer immediate/native transitions for menus and frequently repeated editor interactions.
- Avoid a global animated background or blanket graphics opacity effect on large containers.

Deliverables:
- A documented motion token table in code and documentation.
- A working Reduce Motion preference.
- Unit/UI checks for transition completion, cancellation and repeated open/close cycles.

Exit gate:
- Motion never blocks user input.
- No stale overlays, stuck opacity or permanent busy state.
- Users can disable non-essential motion.
- Visual review confirms movement is subtle and consistent.

### Phase 3 — Refine the SQL editor

**Goal:** Make editing efficient for real daily SQL work.

Tasks, in priority order:
1. Improve completion using current schema metadata: databases, tables, views and columns where the schema service can fetch them safely. Separate keywords/functions from context-specific objects.
2. Extend completion gradually to common contexts—qualified names, aliases, table names after FROM/JOIN, and column names after a known table—without pretending to parse every MySQL grammar case.
3. Add clear keyboard-first completion behavior: Ctrl+Space opens it; Up/Down choose; Enter/Tab accept according to the documented rule; Esc dismisses; focus remains in the editor.
4. Support bracket/parenthesis matching, smarter indentation and safe auto-pairing only if it can be regression-tested without disrupting strings/comments or pasted blocks.
5. Replace simplistic Find/Replace prompts with a compact, keyboard-accessible find bar, match count, next/previous and case-sensitivity controls.
6. Improve the editor status surface with line/column, current selection length, file dirty state and a clear active-connection indicator.
7. Add configurable editor font, tab width, line numbers and current-line highlight; consider minimap only if it can be built without harming performance.
8. Keep statement boundaries consistent with the parser/splitter, and document unsupported DELIMITER/stored-program syntax rather than silently splitting it incorrectly.

Tests:
- Multiline comments, escaped quotes, Unicode, punctuation, alias collisions, large buffers, empty buffers, pasted multiline SQL, completion popup focus, keyboard-only completion, and invalid schema metadata.
- Verify completing a token never alters unrelated text.
- Verify completion does not block typing while schema metadata is loading.

Exit gate:
- Completion remains helpful in normal query contexts and gracefully degrades when metadata is unavailable.
- SQL text is preserved on popup dismissal and any completion error.

### Phase 4 — Refine schema, query tabs and connection workflow

**Goal:** Make context switching obvious and reduce accidental actions.

Tasks:
- Introduce a clearer connection-management view with create/edit/duplicate/delete profile actions and explicit current/last profile state. Confirm before deleting saved metadata or a stored credential.
- Keep connection status visible and unambiguous; consider a configurable, semantic connection colour marker, never colour alone.
- Make schema navigation refresh, error, empty and loading states explicit.
- Fetch schema metadata on the worker thread; use lazy expansion where appropriate so large schemas do not freeze the UI.
- Add schema-tree context actions in an incremental release: copy qualified identifier, generate a SELECT preview, refresh schema, and show object type.
- Make query tabs easier to manage: new tab, close tab, close others, save all, reopen recent files if privacy-safe, and clear dirty-state logic.
- Clarify whether a query tab follows the current connection or is associated with a specific profile; do not silently execute on an unexpected server after switching connections.
- Warn before a connection switch if it changes the context for a running query or pending transaction.
- Keep startup/master-password unlock, saved-credential recovery and server reconnection as separate, correctly labelled states.

Exit gate:
- The active profile/server/schema is visible before query execution.
- Switching/refresh failures keep enough context to recover.
- Credential storage never gains a plaintext fallback.
- Tabs and schema browsing work at keyboard-only and common display scales.

### Phase 5 — Upgrade the results and query feedback experience

**Goal:** Help users understand query outcomes and large result sets.

Tasks:
- Refine query lifecycle: queued, running, fetching rows, complete, cancelled, partial failure, export in progress, and failed.
- Disable only actions that conflict with the actual current operation; preserve navigation and SQL editing when safe.
- Improve result metadata: row count, visible preview count, elapsed duration, affected rows, warnings, and which script statement produced each result.
- Keep the quick filter case-insensitive and document that it filters the visible preview while CSV exports the fetched result set.
- Add clear “no rows”, “no result set”, “filter has no matches”, “query failed”, and “connection lost” states.
- Add column-width behavior that balances readable values and speed; do not auto-size thousands of cells on every load.
- Add a cell detail view for wide/long values, plus copy cell/row/selected cells/headers. Respect NULL versus empty text in copy/export documentation.
- Ensure result sorting does not reorder the underlying result spool or corrupt CSV order unexpectedly. Define whether export preserves server fetch order or current sorted-grid order and communicate that clearly.
- Add export options deliberately (CSV first; JSON or XLSX only after dependency/licence/large-file/performance review).
- Continue atomic file replacement and temp-file cleanup. For long exports, show true progress or an honest indeterminate state and keep the window responsive.

Exit gate:
- Export after sorting/filtering has defined and tested semantics.
- Large results do not cause UI freezes or unbounded memory use.
- Failures preserve previously saved export files.
- Row counts and completion states agree with the worker's result data.

### Phase 6 — Professional polish, accessibility and preferences

**Goal:** Deliver the finish quality expected from a mature desktop application.

Tasks:
- Add a small Settings surface that groups Appearance, Editor, Results, Query History and Connections (only settings that exist and work should be shown).
- Add dark/light/system theme selection after dark-theme parity is proven.
- Add Reduce Motion, editor font, tab width, and appropriate result-grid display preferences.
- Confirm keyboard traversal order and visible focus for all forms, navigation, tree controls, menus, result actions, popups, and dialogs.
- Check keyboard-only use for connect/test, editor completion, query execution, stop/cancel, results switching, export, and close-with-unsaved-changes.
- Check screen-reader accessible names for icon-only controls, busy state and error messages.
- Validate text contrast in normal, hover, selected, disabled, error, warning and high-DPI states.
- Use UI copy that is precise: distinguish “request sent” from “cancelled,” “saved locally” from “encrypted,” and “connected” from “connection settings saved.”
- Review installer welcome, progress, finish, shortcut and uninstaller screens for branding consistency, legible copy and fast completion—without inserting fake progress or long animations.

Exit gate:
- Preferences persist predictably and survive invalid/missing settings.
- Theme changes preserve current work and do not reset pane/tab/cursor state.
- Essential operations are available without a mouse.
- Reduce Motion disables optional motion without disabling feedback.

### Phase 7 — Reliability, security and performance hardening

**Goal:** Catch failures before release rather than hide them behind a polished interface.

Tasks:
- Expand tests around database-worker shutdown, interrupted connection attempts, simultaneous UI actions, server disconnect during fetch, cancellation failure and spool cleanup.
- Inspect races in query completion/status updates so an older background event cannot overwrite the status of a newer task.
- Ensure every worker task has consistent start/completion/failure handling and the UI always leaves busy state on all expected error paths.
- Test credential save/read/delete errors and missing or invalid Windows Credential Manager backend behavior.
- Exercise SQL literal/comment edge cases, CTE-wrapped DML, nested WHERE clauses, multi-statement risk review, and history redaction. Keep heuristic caveats in UI/docs.
- Test result spool cleanup on normal shutdown and exceptional shutdown; keep fetched rows and CSV files treated as sensitive.
- Audit all user-visible database errors for useful context and secret redaction without exposing raw credentials.
- Run \`pip-audit\`, review dependency licence inventory, keep a deliberate version support matrix and update dependencies in small, tested batches.
- Avoid broad “upgrade everything to latest” changes without checking Python/Qt/connector/PyInstaller/Inno Setup compatibility.
- Add time-bounded test scenarios for startup, typing latency, schema fetch, query display and export using representative data.
- Review GitHub Actions permissions and third-party actions, and pin actions by immutable SHA when the release security policy is ready for that maintenance overhead.

Exit gate:
- No known blocking regression remains in the release-candidate test suite.
- Dependency audit result is reviewed; failures are resolved or explicitly documented before release.
- Tests prove cleanup/recovery behaviour; visual finish does not substitute for reliability.

### Phase 8 — Release candidate and real Windows QA

**Goal:** Package the exact tested source state and verify the installed product, not just the source.

Required sequence:
1. Run Ruff, compileall, unit tests on Python 3.12, 3.13, 3.14, MySQL 8.4 integration tests, and dependency audit.
2. Run Windows startup/import smoke tests.
3. Build onedir, portable EXE and installer from the same commit.
4. Launch both packaged application variants and confirm startup survives.
5. Install silently into a clean path, verify executable and desktop shortcut, uninstall, verify shortcut/file cleanup.
6. Manually test first launch, master-password setup, unlock, saved credential reconnect, missing/rejected password, profile switch, TLS, query execution, result filtering/export, and close with unsaved edits on a Windows PC.
7. Review screenshots at 100%, 125%, 150%, and 200% scaling and check window resize/restoration across monitors.
8. Confirm logo rendering and setup wizard at native scale; confirm no blurred or stretched assets.
9. If publisher trust is required, sign the final binaries with a trusted Authenticode certificate, verify the signature and timestamp, and check that the published hashes match the signed artifacts.
10. Generate release notes, SHA-256 manifest, SBOM, third-party license inventory and explicit signing-status note.
11. Publish only if all required gates have passed. Keep an unsigned preview clearly labelled as such; do not promise the absence of Windows SmartScreen warnings unless signing/reputation evidence supports it.

Exit gate:
- Each item is marked PASS/FAIL/NOT TESTED with evidence.
- The exact commit SHA and artifact hashes are written to the release record.
- Manual QA gaps are disclosed plainly.

---

## 6. Proposed code organization

Keep modules small and aligned with their responsibility. The paths below are proposals; keep an existing path if the responsibility already lives there and moving it would add churn.

| Module | Responsibility |
|---|---|
| \`src/mysql_editor/ui/theme.py\` | Semantic colour tokens, palette selection, shared stylesheet construction and spacing/type constants |
| \`src/mysql_editor/ui/animations.py\` | Motion tokens, reusable cancellable transitions, Reduce Motion checks |
| \`src/mysql_editor/ui/editor.py\` | Editor, syntax highlighter, completion interaction, indentation and editor-level behaviour |
| \`src/mysql_editor/ui/main_window.py\` | Workspace composition and connection-aware command routing; delegate detailed behavior to smaller widgets as they grow |
| \`src/mysql_editor/ui/connection_dialog.py\` | Connection fields, profile selection and explicit status feedback |
| \`src/mysql_editor/ui/tutorial.py\` | Guided-tour copy, accessible step flow, motion-aware transitions |
| \`src/mysql_editor/database.py\` | Worker-side MySQL tasks, cancellation request, schema metadata and result spool |
| \`src/mysql_editor/core.py\` | SQL boundaries, risk advisories and redaction helpers, with clear heuristic limits |
| \`src/mysql_editor/storage.py\` | Versioned local metadata, preferences, password verifier and Credential Manager adapter |
| \`tests/\` | Unit/integration/regression coverage and behavior-level UI smoke |
| \`tools/smoke_test_ui.py\` | Cross-platform offscreen UI smoke where supported |
| \`.github/workflows/\` | Required checks, security audit, Windows packages and release evidence |

Do not create a module merely to match the table. Split a widget/module when it has multiple independently testable responsibilities or when its size is preventing focused work.

---

## 7. Testing strategy and acceptance matrix

| Area | Automated check | Manual visual/behavior check |
|---|---|---|
| Theme tokens | Token/palette tests and lint | Contrast, logo edges, state consistency |
| Motion | Completion/interruption tests; Reduce Motion path | Flicker, timing, focus and repeated interactions |
| SQL editor | Splitter, highlighter, completion, shortcuts and buffer regression tests | Long SQL, keyboard navigation, high DPI |
| Connection UX | Profile/credential/TLS unit tests and MySQL integration tests | Actual Windows Credential Manager and external TLS setups |
| SQL execution | MySQL 8.4 integration and failure-path tests | Cancel timing, reconnect and transaction semantics |
| Results | Proxy filter/sort tests, spool/export tests, failure cleanup | Large result responsiveness and clarity of row counts |
| Tabs/files | Dirty-state, open/save recovery tests | Multi-tab flow, external file edits, file-dialog usability |
| Schema | Worker/query tests, metadata-failure tests | Large schemas, permissions, refresh, keyboard expansion |
| Packaging | Windows executable launch and installer/uninstaller tests | Install/upgrade/uninstall on a clean PC |
| Accessibility | Accessible-name/focus checks where feasible | Keyboard-only and screen-reader spot checks |
| Dependencies | pip-audit, supported Python matrix, licences/SBOM | Verify release toolchain and signed artifacts |

### Minimum regression checklist

- Strings and comments containing words such as WHERE, DROP, UPDATE and DELETE do not fool simple advisory checks.
- DML with a WHERE only inside a nested subquery is still flagged for review when the outer mutation has no WHERE.
- Selecting a completion changes only the intended token; pressing Escape preserves the SQL buffer.
- Result filtering is case-insensitive, clearing a filter restores rows, and a filter never silently reduces a CSV export.
- Numeric sort handles values such as 2 and 10 intuitively; NULL ordering is explicitly defined.
- A schema refresh failure does not leave stale completion identifiers presented as current.
- Failed export preserves the prior file and removes the temporary export file.
- Missing/rejected credentials return the user to a correction flow without plaintext persistence.
- Closing a running query or switching connection results in a truthful status and does not claim cancellation before it is confirmed.
- Every connection/query/export failure restores the appropriate controls and avoids leaving the app stuck in a busy state.
- Reduced Motion changes only non-essential visual movement, not the meaning or availability of functionality.
- Theme change and window restore keep editor buffer, cursor, active tab and split sizes.
- Install/uninstall leaves no app shortcut behind after a successful uninstallation.

---

## 8. Colour and animation design review checklist

Before approving any screen, ask:

**Colour**
- Is the main hierarchy clear with one primary accent?
- Are body, metadata, selected, disabled and error states readable?
- Does the UI remain attractive without glow, blur, oversized gradients or excessive colour?
- Does the brand mark remain crisp and correctly proportioned?
- Is colour backed by text/icon/shape for state communication?
- Is SQL syntax highlighting distinct from success/warning/danger states?

**Motion**
- Does each animation communicate something?
- Is it short, interruptible and non-blocking?
- Can all essential functions be completed with Reduce Motion enabled?
- Can a keyboard user finish, dismiss or interrupt the animated component?
- Does it avoid repainting large grids or consuming CPU in idle?
- Does it preserve focus and make the final state explicit?

**Workflow**
- Is the active database context always visible?
- Are loading, empty, error, success, cancelled and partial-result states distinguished?
- Is every destructive confirmation specific about what will happen?
- Can a failed action recover without losing SQL text or overwriting a previous export?
- Are UI changes covered by regression tests and tested on Windows?

Reject visual embellishments that make the screen less legible, slower, or less predictable. “Premium” means consistency and control, not a maximum number of effects.

---

## 9. Suggested delivery sequence

1. **PR A — Theme foundation:** shared tokens and migrate the top bar, navigation, editor/result surfaces and connection dialog. No broad behavior changes.
2. **PR B — Motion primitives:** animation helpers, Reduce Motion setting, navigation/tour feedback and interruption tests.
3. **PR C — Editor polish:** completion reliability, find bar, current cursor/file state, safe indentation and targeted tests.
4. **PR D — Result UX:** filtering/sorting semantics, column display, cell detail/copy options, progress and export feedback.
5. **PR E — Connection/schema UX:** explicit profile management, schema refresh/empty/failure/loading states, no-context-switch surprises.
6. **PR F — Preferences/accessibility:** theme selection, font/tab width, keyboard/focus and high-DPI verification.
7. **PR G — Reliability:** worker races, cancellation/spool cleanup, query safety/redaction edge cases, dependency/licence audit.
8. **PR H — Release candidate:** full CI, Windows package/install/uninstall tests, manual QA report, release manifest and signing status.

Keep pull requests reviewable. One cohesive behavior or visual subsystem per PR is preferable to one giant “upgrade everything” commit.

---

## 10. Definition of done

The next major quality release is ready only when all of these conditions are true:

- The core layout uses a consistent semantic design system and the user-supplied logo is sharp and undistorted.
- Animation is subtle, consistent, interruptible, non-blocking, and optional through Reduce Motion.
- Editor, connection flow, schema explorer and results remain fully usable with keyboard navigation.
- Query status, active database context, errors and export behavior are honest and clear.
- No database-password plaintext fallback or telemetry has been introduced.
- The app remains responsive during connection attempts, query execution and large exports.
- Lint, compilation, unit tests, MySQL integration, Windows UI smoke, packaged-launch tests, installer/uninstaller tests, and dependency review all pass for the candidate commit.
- Visual/manual checks are recorded for the supported Windows display environment.
- Any untested condition, unsigned state, or known limitation is disclosed in the release notes.

No software process can guarantee “zero errors.” The engineering target is to reduce defects, detect regressions early, make failures recoverable, and publish with evidence.

---

## 11. Links and working rules

- [Main repository](https://github.com/ram1234598766-dotcom/MySQL-Editor)
- [Pull requests](https://github.com/ram1234598766-dotcom/MySQL-Editor/pulls)
- [GitHub Actions](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions)
- [Figma design reference](https://www.figma.com/design/EFFQpRTE8pKybt1lQR0eQH)
- [README](README.md)
- [Clean-room desktop rebuild plan](DESKTOP_REBUILD_PLAN.md)
- [Security policy](SECURITY.md)
- [Privacy policy](PRIVACY_POLICY.md)
- [Windows signing status and instructions](WINDOWS_SIGNING.md)

For implementation, read \`AGENTS.md\` and the relevant skills under \`.agents/skills/\`. Before changing code, read the current implementation, state acceptance criteria, add or update a regression test, run the narrow test first, and then run the relevant full checks. Never treat a source commit as a release, never say CI is green while it is running, and never claim visual QA or signing without evidence.
