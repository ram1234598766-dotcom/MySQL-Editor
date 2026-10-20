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

The repository is already a native PySide6 application with horizontal workspace navigation, query tabs, a SQL editor, results grid, schema/history/snippet panels, background database worker, connection profiles, a local master-password gate, Windows Credential Manager storage, CSV/JSON/NDJSON export, a guided tour, and Windows installer/portable packaging.

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
- The SQL script splitter supports standalone MySQL-client DELIMITER changes and compound stored-program statement boundaries; it is not a full MySQL grammar or semantic validator.
- Query results initially load up to 2,000 rows; additional pages are read from the local result spool on demand. Table preview remains capped at 1,000 rows. CSV, JSON, and NDJSON export read the full fetched result spool in server-fetch order; the visible grid sort/filter does not reduce exported rows.
- Query cancellation is best-effort and depends on server permissions/state.
- Some MySQL DDL implicitly commits.
- Risk detection and history redaction are heuristic; neither is a complete parser or security boundary.
- Automatic TLS negotiates encryption where supported but does not verify server identity; strict mode does.
- The current dark styling is spread through UI code and should be consolidated into reusable design tokens before substantial visual changes.
- Automated/offscreen tests cannot prove the visual result on every real display configuration.
- Preview Windows executables remain unsigned by policy. Stable version-tag builds require a configured code-signing PFX and successful final signature verification; the default self-signed mode does not make recipient PCs trust the publisher certificate.

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
8. Keep statement boundaries consistent with the script parser; malformed DELIMITER directives must fail closed instead of silently splitting stored-program bodies.

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
- Add a read-only Schema Object Inspector for tables and views, showing MySQL-generated DDL plus independently recoverable columns, indexes, constraints/foreign keys, and object properties; use worker-thread metadata queries, quoted identifiers, bound values, and explicit permission warnings.
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
- [x] Keep the quick filter case-insensitive and document that it filters the visible preview while CSV, JSON, and NDJSON exports include the full fetched result set.
- Add clear “no rows”, “no result set”, “filter has no matches”, “query failed”, and “connection lost” states.
- Add column-width behavior that balances readable values and speed; do not auto-size thousands of cells on every load.
- Add a cell detail view for wide/long values, plus copy cell/row/selected cells/headers. Respect NULL versus empty text in copy/export documentation.
- [x] Add guarded single-cell editing for verified Schema Explorer base-table previews: exclude primary keys/generated and unsupported types; require a transactional engine; parameterize writes; re-read and lock the row to reject stale changes; do not auto-commit; restore edited rows in the local cache after full rollback.
- [x] Invalidate cached table previews after `ROLLBACK TO SAVEPOINT`, since we do not keep per-savepoint snapshots; block further edit, paging, and result export of invalidated previews until re-preview.
- Ensure result sorting does not reorder the underlying result spool. CSV, JSON, and NDJSON exports preserve server-fetch order rather than the current sorted-grid order, and quick filtering never reduces the exported row set.
- [x] Add JSON-array and NDJSON export alongside CSV without adding a runtime dependency; tests cover type preservation, duplicate column labels, fetch order, and atomic-failure cleanup.
- Keep XLSX export deferred until a streaming writer is evaluated for Python/Qt/PyInstaller compatibility, dependency size, licence, and large-file behavior.
- [x] Replace the raw `EXPLAIN` grid action with `EXPLAIN FORMAT=JSON`, a structured expandable plan tree, an optimizer-estimate summary, and a copyable raw JSON tab. Invalid/unsupported responses are surfaced without running the original SELECT.
- Continue atomic file replacement and temp-file cleanup. For long exports, show true progress or an honest indeterminate state and keep the window responsive.

Exit gate:
- Export after sorting/filtering has defined and tested semantics.
- Large results do not cause UI freezes or unbounded memory use.
- Failures preserve previously saved export files.
- Row counts and completion states agree with the worker's result data.
- [x] Table-edit tests cover eligibility, non-transactional engine rejection, parameterized update and no implicit commit, stale same-cell and other-column conflict detection, session invalidation, full rollback restoration, savepoint rollback invalidation, and UI consistency.
- [x] Explain-plan tests cover JSON row extraction, malformed/empty/error responses, nested plan rendering, raw JSON copy, asynchronous request dispatch, and graceful unsupported-server failures.
- [x] Bound remote EXPLAIN JSON to 2 MiB, reject malformed/excessively nested JSON, limit the visual tree to 3,000 nodes and 32 levels, and cap the summary traversal; the raw JSON remains available when visual details are truncated.

### Phase 6 — Professional polish, accessibility and preferences

**Goal:** Deliver the finish quality expected from a mature desktop application.

Tasks:
- Add a small Settings surface that groups Appearance, Editor, Results, Query History and Connections (only settings that exist and work should be shown).
- Add dark/light/system theme selection after dark-theme parity is proven.
- Add Reduce Motion, editor font, tab width, and appropriate result-grid display preferences.
- Confirm keyboard traversal order and visible focus for all forms, navigation, tree controls, menus, result actions, popups, and dialogs.
- Check keyboard-only use for connect/test, editor completion, query execution, stop/cancel, results switching, export, and close-with-unsaved-changes.
- Check screen-reader accessible names for icon-only controls, busy state and error messages.
- [x] Add automated WCAG AA contrast regression checks for normal, hover, selected, disabled, error, warning, success, menu/table selection, primary-button hover, and focus-boundary states in both dark/light palettes. Physical Windows high-DPI and display-scaling validation remains part of Phase 8 manual acceptance.
- Use UI copy that is precise: distinguish “request sent” from “cancelled,” “saved locally” from “encrypted,” and “connected” from “connection settings saved.”
- Review installer welcome, progress, finish, shortcut and uninstaller screens for branding consistency, legible copy and fast completion—without inserting fake progress or long animations.

Exit gate:
- Preferences persist predictably and survive invalid/missing settings.
- Theme changes preserve current work and do not reset pane/tab/cursor state.
- Essential operations are available without a mouse.
- Reduce Motion disables optional motion without disabling feedback.


**Contrast hardening follow-up — 19 October 2026:** The light-theme selected navigation text was measured at 3.69:1 against its selected background. It now uses the darker `#056C78` foreground, giving 4.71:1 against `#D6E3F2`. Regression tests exercise hover, selected, disabled, connection success/lost, warning, menu/result selections, primary-button hover, and focus boundaries. Hosted tests validate computed color pairs; high-DPI rendering still requires physical-Windows acceptance.
### Phase 7 — Reliability, security and performance hardening

**Goal:** Catch failures before release rather than hide them behind a polished interface.

Tasks:
- Expand tests around database-worker shutdown, interrupted connection attempts, simultaneous UI actions, server disconnect during fetch, cancellation failure and spool cleanup.
- Inspect races in query completion/status updates so an older background event cannot overwrite the status of a newer task.
- Ensure every worker task has consistent start/completion/failure handling and the UI always leaves busy state on all expected error paths.
- Test credential save/read/delete errors and missing or invalid Windows Credential Manager backend behavior.
- [x] Extend the SQL risk advisory to inspect MySQL `/*! ... */` and MariaDB `/*M! ... */` executable comments, while ignoring comment-like markers inside quoted strings, line comments, and ordinary block comments; add regression tests for hidden high-impact DML.
- Continue exercising remaining SQL literal/comment edge cases, CTE-wrapped DML, nested WHERE clauses, multi-statement risk review, and history redaction. Keep heuristic caveats in UI/docs.
- Test result spool cleanup on normal shutdown and exceptional shutdown; keep fetched rows and CSV files treated as sensitive.
- [x] Implemented the opt-in stable-release update checker in PR #61 and its non-blocking shutdown follow-up in PR #62. Startup checks remain disabled by default; one-time manual checks do not enable the startup preference.
- [x] Centralize user-visible error sanitization across the database worker and UI error surfaces. Redact MySQL `IDENTIFIED BY`/`SET PASSWORD` echoes and key/value secrets, remove control characters, bound displayed text, and use safe fallbacks for missing errors; regressions cover query-failure status/message and CSV export feedback.
- Run \`pip-audit\`, review dependency licence inventory, keep a deliberate version support matrix and update dependencies in small, tested batches.
- Avoid broad “upgrade everything to latest” changes without checking Python/Qt/connector/PyInstaller/Inno Setup compatibility.
- Add time-bounded test scenarios for startup, typing latency, schema fetch, query display and export using representative data.
- [x] Reviewed GitHub Actions permissions and third-party actions on 19 October 2026. Every workflow action reference is pinned to an immutable commit SHA; desktop CI, dependency audit and build jobs use `contents: read`; only the guarded publish job requests `contents: write`. Dependabot checks both Python dependencies and GitHub Actions weekly.

Exit gate:
- No known blocking regression remains in the release-candidate test suite.
- Dependency audit result is reviewed; failures are resolved or explicitly documented before release.
- Tests prove cleanup/recovery behaviour; visual finish does not substitute for reliability.
- [x] Update-check tests prove automatic startup checks stay off by default, non-stable/unsafe metadata is rejected, time/response size are bounded, release URLs are restricted to this repository, manual checks work without opting into future startup checks, and close never blocks on the update thread.

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

### Implementation progress — 17 October 2026

The following editor/UX items have now been implemented on `main` with regression coverage:
- Shared dark-theme tokens and a persistent Reduce Motion preference, with subtle inspector navigation transitions.
- Inline Find/Replace with match counts, case-sensitive search, wrap-around previous/next navigation, Replace, Replace all, and keyboard dismissal.
- Live editor line/column and selection-length status in the bottom status strip.

This was the initial implementation checkpoint, before the later Appearance preference, schema-scoped completion refinements, and Phase 6 accessibility work recorded below. CI results and package verification for a specific current commit must still be inspected before describing that commit as release-ready. High-DPI/manual visual QA on a physical Windows machine remains a separate requirement.


### Preference work — 17 October 2026

The Settings menu now groups Appearance, Editor, Results, and Query History. Editor tab width (2/4/8 spaces) and result-grid row height (24/28/36 px) are validated, persisted, applied to current and new editor tabs, and covered by unit/UI-smoke tests.


### Query lifecycle feedback — 17 October 2026

The worker now emits running/fetch and export progress; the UI distinguishes a cancellation request from a confirmed MySQL interruption, recognizes partial script failure, and keeps earlier result sets available. A pure outcome classifier and database interruption tests cover completion, cancellation, interruption, partial failure, and ordinary failures.


### Appearance preference work — 17 October 2026

System/Light/Dark theme selection is now implemented in the desktop Settings menu. The selected preference is stored in QSettings, applied during startup, and can be changed immediately without rebuilding the main window or clearing editor/result state. Windows System mode reads the Windows app-colour preference; other platforms fall back to the Qt application palette. Regression tests cover invalid stored values, System resolution, and important light-theme widget states. High-DPI contrast and visual consistency still require manual review on real Windows displays before a release claim.


### SQL completion refinement — 17 October 2026

Contextual column completion now remains scoped to the relevant schema tables after commas in common `SELECT`, `GROUP BY`, `ORDER BY`, and `UPDATE ... SET` lists. Regression coverage verifies that unrelated table columns are not introduced and SQL text is not changed while suggestions are computed. This remains a bounded heuristic rather than a complete MySQL grammar parser.


### Full-value clipboard action — 17 October 2026

The cell-details dialog now offers an explicit **Copy full value** action for long or wide cells. The clipboard receives the original cell text rather than the dialog's explanatory NULL label; SQL NULL uses the app's established `NULL` clipboard marker and empty text remains an empty clipboard string. Tests cover the dialog action and scalar formatting.


### Fail-closed handling for malformed DELIMITER scripts — 18 October 2026

Phase 1 now recognizes standalone MySQL-client `DELIMITER` changes only when the preceding script buffer contains no executable statement. The active separator is applied outside strings, quoted identifiers, and comments; directive lines are removed from statements while source offsets are preserved. Malformed directives return a source-line-aware error before the UI queues SQL or the worker opens a cursor. Regression and MySQL 8.4 integration tests cover compound stored-program execution, delimiter changes, false positives in comments/literals, and rejection without partial submission.


### Automated theme and SQL syntax contrast gates — 17 October 2026

Added WCAG AA (4.5:1) regression thresholds for selected normal, muted, disabled, status, selection, and SQL syntax text states in both themes. Focus boundaries use a 3:1 non-text threshold. The checks cover the custom syntax highlighter and line-number gutter as well as shared application chrome. These are targeted palette regression tests, not a claim that every widget/state or every Windows display has completed a full accessibility audit.


### Performance regression budgets — 17 October 2026

Added generous CI time budgets for main-window construction, editing a 1,500-line SQL buffer, loading a 2,000-row/16-column result preview, processing 10,001 schema-column records (while enforcing the 10,000-column cap), and exporting 25,000 disk-spooled rows. These smoke budgets detect severe regressions without presenting CI timings as production benchmarks. Real-server network latency and cold Windows launch time still need measurement in the target environment.

### Backtick-quoted completion — 17 October 2026

Contextual completion is now available while typing a partial MySQL backtick-quoted identifier, including table names after `FROM` and columns after a known table alias. The completion scanner treats backticks as identifier delimiters only in the completion path; ordinary string/comment suppression and the stricter bracket auto-pair path remain unchanged. Regression coverage verifies that suggestions preserve SQL text, quoted table names remain scoped during unqualified completion, and accepting a suggestion changes only the intended identifier token. This remains a bounded editing heuristic, not a complete MySQL grammar parser.

### Schema-scoped completion — 17 October 2026

Completion now keeps table/view and column metadata associated with each schema as lazy-loaded schema nodes are expanded. `schema.table.column` and aliases of schema-qualified tables resolve against that schema's cached columns; `schema.` offers only the loaded table/view names for that schema. When a schema has not been loaded or its column metadata is unavailable, completion returns no scoped object suggestions rather than leaking similarly named columns from the active schema. Refresh clears these caches before new metadata arrives.

### Completion edge-case hardening — 17 October 2026

Completion metadata now fails closed when optional maps are malformed, and a string passed as an identifier collection is treated as one identifier rather than a sequence of characters. Regression tests cover escaped and doubled quotes, multiline line/block comments, empty and large multi-statement buffers, colliding aliases, unsafe or incorrectly shaped schema metadata, and verbatim multiline SQL paste. These tests keep completion scoped without mutating SQL while suggestions are calculated.


### SQL editor preference completion — 17 October 2026

The Settings > Editor tab-width preference now affects actual Tab insertion and automatic indentation after common SQL block openers, not only the visual tab stop. Added persisted toggles for line-number visibility and current-line highlighting; changes apply to open tabs and new tabs. Bracket-matching feedback remains available when current-line highlighting is disabled. Regression checks cover invalid stored boolean values, all supported indentation widths, and the independent gutter/highlight controls. Automated Windows packaging does not replace manual high-DPI visual review on a physical PC.


### Dependency audit scope — 17 October 2026

Expanded the dependency security gate beyond `requirements.txt`: CI installs the declared project/test extras plus PyInstaller and the license inventory tool, audits the compatible runtime requirement set, then audits the actually installed test and packaging environment. The Windows packaging workflow performs the same installed-environment audit before packaging begins. The release CycloneDX SBOM stays deliberately runtime-focused; the separate audit gates catch known advisories in test/build tooling too. The desktop CI and dependency-security workflows passed on code commit `53218aed6b218925aec450bcb44796e462a9bcd6`, and the Windows package workflow also completed successfully for that code commit. The release-marker commit documented below triggers a fresh set of checks and builds the distributables from the exact release commit.


### Active schema session correctness — 17 October 2026

The Phase 4 schema-selection flow now switches the live MySQL session via a worker-thread `USE` operation with safely quoted identifiers. Workspace and saved-profile context are updated only after the server accepts the switch. A rejected switch preserves the previous UI/profile context, and schema switches are refused while a query is running. Regression coverage checks quoted schema names, worker connection-context updates, failed switches, and the UI's context-preservation path. CI and Windows package validation are required before calling this fix complete; physical Windows visual QA remains separate.


### Phase 5 export sort/filter acceptance — 17 October 2026

Added `tests/test_export_sort_filter_semantics.py` to exercise the actual numeric-aware result proxy and the SQLite-backed CSV export together. The test sorts the visible preview, applies the app's case-insensitive filter, confirms the source model remains in fetch order, and verifies that CSV still contains every fetched row in that original order. This closes the remaining combined regression gap in the Phase 5 exit criteria.

Related existing coverage includes bounded result-preview rendering, 25,000-row spool export timing, atomic replacement and preservation of an existing destination on failure, temporary-file cleanup, SQL NULL versus empty text, result row counts, per-statement metadata, cancellation/interruption distinctions, partial-script failure, and persistent export feedback. This records automated regression coverage; it does not replace real Windows display-scale QA.



### Phase 6 — Preferences, accessibility and visual QA — 17 October 2026

**Implementation status:** automated gates passed for code commit `53218aed6b218925aec450bcb44796e462a9bcd6`. The release-marker commit repeats these gates and rebuilds the packages from the exact published commit.

Implemented and regression-tested:
- Explicit screen-reader names/descriptions and concise tooltips for the connection form, local master-password setup/unlock dialog, primary SQL actions, results controls, schema/history/snippet views, connection status, and guided-tour controls. The tour's final action changes its accessible name to “Finish guided tour”.
- Predictable keyboard traversal in the connection and unlock forms; regression tests traverse the controls using Qt keyboard events.
- Dark/light theme-switch regression coverage that preserves the active SQL tab, SQL buffer, cursor and selection, result filter and fetched rows, connection context, and splitter state.
- Correct disabled-primary-button styling in both themes, including the disabled-hover state. The tested foreground/background contrast ratios are approximately 5.94:1 in dark mode and 5.78:1 in light mode.
- [x] Correct generic disabled-control text contrast in the light theme from 4.35:1 to approximately 4.98:1 by using `#5D6B7B` on `#F2F5F9`. The regression test now asserts the actual `QPushButton:disabled` stylesheet rule; selected navigation remains at the already-verified `#056C78` and approximately 4.71:1 contrast.
- The visual-QA fixture now resolves its synthetic initial schema refresh instead of leaving a stale loading message. The screenshot states it is an offline preview using synthetic rows and does not suggest an active MySQL connection.
- The native Windows Qt runner generates eight screenshots: dark and light themes at simulated 100%, 125%, 150%, and 200% display scales. The manifest records theme, requested scale, image dimensions, and file size.

Automated evidence for code commit `53218aed6b218925aec450bcb44796e462a9bcd6`:
- [Desktop CI](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39050148985) — passed lint, Python compilation, unit tests, legacy-import guard on Python 3.12/3.13/3.14, MySQL 8.4 integration, and Windows Qt UI smoke.
- [Dependency-security audit](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39050148975) — passed.
- [Windows package build](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39050148964) — passed application-folder build, portable EXE build, installer build, silent install/uninstall and shortcut cleanup, packaged-application startup smoke, output validation, SBOM/license generation, checksums, and artifact upload.
- The generated visual-QA artifact contains the eight dark/light and scale captures. A sample was visually inspected; the disabled SQL primary action now uses a muted disabled state rather than the bright active accent.

**Remaining manual gates (not verified by CI):** physical-monitor Windows DPI behavior across real monitors, full keyboard-only walkthrough of every popup/menu/tree/result operation, a screen-reader spot check (for example, Narrator), and the actual PC's Credential Manager and MySQL/TLS environment. The screenshots use simulated Qt scaling on a native Windows runner and synthetic data; they are not a substitute for a hands-on acceptance pass.

This phase's implementation and automated checks are complete. The manual Windows acceptance items remain part of the release-candidate gate in Phase 8. Preview binaries remain unsigned unless the specific release states otherwise; no Authenticode signing is claimed.

### Phase 7 verification record — 17 October 2026

**Automated status:** PASS for code commit `cc14e703fc815153a2add8f05f6dff7828df6125`. The implementation, tests, and packaged Windows build ran against this same source commit.

Completed and regression-tested:
- Guarded query cancellation with task, connection ID, and statement-generation checks before and immediately before dispatching `KILL QUERY`.
- Moved network control-connection setup outside the worker-state lock while keeping the final statement check and cancellation dispatch serialized. A regression test simulates a statement transition while the control connection is opening.
- Removed nested temporary result-cache artifacts during worker cleanup.
- Expanded redaction for common MySQL account/password syntax in surfaced database errors.
- Audited declared runtime dependencies and the installed test/build environment.
- Separated read-only Windows build permissions from release publication permissions; pinned GitHub Actions to immutable SHAs and checked Dependabot's weekly updates.
- Kept performance smoke budgets for startup, large SQL buffers, result previews, schema-column handling and disk-spooled export.

Automated evidence for code commit `cc14e703fc815153a2add8f05f6dff7828df6125`:
- [Desktop CI](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39053534568) — **PASS**: lint, Python compilation, unit tests on Python 3.12/3.13/3.14, legacy-import guard, MySQL 8.4 integration and Windows Qt UI smoke.
- [Dependency-security audit](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39053534463) — **PASS**.
- [Windows package build](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39053534529) — **PASS**: application-folder package, portable EXE, Inno Setup installer, silent install/uninstall and shortcut cleanup, packaged application startup checks, output verification, CycloneDX SBOM, third-party license inventory, SHA-256 manifest and successful `MySQLEditor-Windows` Actions artifact upload (about 220 MB).

**Not claimed as complete:** the generated Windows build is unsigned. Physical-PC validation is still required for real multi-monitor/high-DPI rendering, a full keyboard-only walkthrough, a Narrator/screen-reader spot check, actual Windows Credential Manager behavior, and external MySQL/TLS configurations. Simulated scaling captures and hosted-runner smoke tests do not replace these checks.

The automated Phase 7 exit gate is complete. Phase 8 remains a separate release-candidate/manual-Windows-acceptance phase; do not describe the product as publisher-verified or fully release-certified until those checks are recorded.



### Phase 8 implementation — release provenance and fail-closed publication — 17 October 2026

The Windows release workflow now runs a release-specific test matrix on Python 3.12, 3.13, and 3.14, plus disposable MySQL 8.4 integration, before building packages. These gates are in the same workflow dependency graph as publication, so a skipped or failed preflight prevents release assets from being published. The Windows workflow also runs for pull requests to validate candidate changes before merge.

Added `tools/create_release_manifest.py` with regression tests. It requires the onedir executable, portable executable, installer, folder ZIP, CycloneDX SBOM, release notes, signing disclosure, and third-party license inventory. It records the exact source SHA, project version, platform/toolchain metadata, per-artifact byte sizes and SHA-256 digests, and the current unsigned state. It rejects missing/tiny executables, malformed source SHAs, invalid SBOM metadata, and invalid/incomplete folder archives. `SHA256SUMS` includes the manifest and all final executables. The manifest does not replace a trusted Authenticode signature.

Automated status is determined by the release workflow run on the exact candidate commit. This record does not mark a release ready by itself. **Still pending outside CI:** hands-on Windows display-scale checks, keyboard-only coverage, a Narrator/screen-reader check, real Credential Manager behavior, and connection/TLS validation against the target MySQL environment. See [RELEASE-CANDIDATE-CHECKLIST.md](RELEASE-CANDIDATE-CHECKLIST.md) for the test record to complete before a stable release.


### Advanced capability upgrade — Phase 2: result pagination — 18 October 2026

The result grid now has a **Fetch +1,000** action. It requests the next bounded page from the worker-owned SQLite result spool; it never reruns, rewrites, or appends a LIMIT/OFFSET clause to the user's SQL. The initial preview remains capped at 2,000 rows, and the additional page size is clamped to 1,000 rows. Paging remains available after disconnect while the current worker cache exists, because it is a local cache read rather than a MySQL action.

The result model appends rows incrementally without resetting the model. Sorting remains a proxy-model operation, the active quick filter continues to apply to appended rows, and each result retains its own loaded-page state when switching between statement results. All export formats remain independent of the UI preview and read the complete spooled result in server-fetch order.

Automated acceptance added:
- Worker tests for ordered page boundaries, a clamped page size, invalid/expired results and negative offsets.
- UI tests for the first and final page, preventing duplicate page requests, disallowing paging while a query is active, and retaining the current filter while rows are appended.
- A regression test that verifies appended rows are inserted incrementally while the proxy continues to sort/filter and the source model preserves server-fetch order.
- The complete CSV export assertion remains over every spooled row, regardless of paging.

The phase is complete only when lint/compile, Python 3.12–3.14 tests, MySQL 8.4 integration, Windows Qt smoke, and the Windows installer/EXE packaging workflow all pass on the exact PR head. The resulting build is an Actions artifact until separately published by the release workflow.

### Phase 4–8 automated verification checkpoint — 18 October 2026

**Verified source commit:** `bfa4c9eb0d30d088f5c0388d48b0626dac1a8b4b`

The transaction-safe connection-switch regression tests are merged on `main`. The following GitHub Actions workflows completed successfully for this exact source commit:

- Desktop CI: Python 3.12, 3.13, and 3.14 test jobs; Windows Qt UI smoke; MySQL 8.4 integration.
- Desktop dependency security audit.
- Windows packages: release test matrix, MySQL 8.4 integration, dependency audit, application-folder build, portable executable build, Inno Setup installer build, installer install/uninstall smoke test, packaged-app launch smoke test, expected-output verification, SBOM and release manifest generation, and SHA-256 checksums.

The Windows workflow uploaded the `MySQLEditor-Windows` and `MySQLEditor-UI-Visual-QA` Actions artifacts. These are CI artifacts, not a stable GitHub Release. The successful packaging run does not constitute hands-on acceptance.

**Still not verified on a physical Windows PC:** 100%/125%/150%/200% display scaling and multi-monitor behavior; keyboard-only end-to-end use; Narrator/screen-reader behavior; real Windows Credential Manager behavior; and connection/TLS validation against the intended MySQL environment. Publisher trust is also not established by CI artifacts or SHA-256 hashes; the binaries must be Authenticode-signed and the signature verified if trusted publisher identity is required.

Do not mark Phase 8 fully complete or promote a stable release until the manual checklist above in `RELEASE-CANDIDATE-CHECKLIST.md` has an evidence-backed outcome.

### Phase 6 keyboard-navigation follow-up — 18 October 2026

**Automated status: PASS** for PR #47's tested source commit `8b08fbf96f488fbb2a5b7c57577c12710ef35783`, merged to `main` as `b37e1e146d3526b298b31fe3c13205ae4323dbdc`.

The follow-up exposed and fixed an actual keyboard-accessibility issue: placing workspace navigation buttons in an exclusive `QButtonGroup` removed Tab focus from unchecked navigation destinations. The navigation now retains independent keyboard focus stops while managing the selected appearance explicitly. Regression coverage verifies accessible names, keyboard focus, sequential Tab traversal across workspace destinations, and Tab traversal between SQL toolbar actions.

Evidence on the tested PR head:

- [Desktop CI](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39117894256) — **PASS**: Python 3.12, 3.13 and 3.14 tests, Windows Qt UI smoke, and MySQL 8.4 integration.
- [Dependency-security audit](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39117894250) — **PASS**.
- [Windows package workflow](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39117894252) — **PASS**: application-folder build, portable EXE, installer, automated install/uninstall, packaged-app launch smoke, output validation, CycloneDX SBOM, provenance manifest, SHA-256 checksums, and Windows artifact upload.

The Windows workflow's artifact is a CI download, not a stable GitHub Release. This automated evidence does **not** complete Phase 8 manual acceptance: real-monitor DPI/multi-monitor checks, full keyboard-only operation across menus/popups/trees/results/dialogs, Narrator or another screen-reader check, real Windows Credential Manager behavior, MySQL/TLS validation on the intended machine, and Authenticode signing/verification when publisher trust is required remain outstanding.

### Phase 1 forward-port — shared widget-state color tokens — 18 October 2026

The current-main forward-port replaces recurring hard-coded colors in the shared Qt stylesheet with 61 named `STYLE_COLORS` tokens, resolved by the existing stylesheet token pipeline before Qt applies the style. This is a focused refactor: after token resolution, the dark stylesheet's literal rules are byte-for-byte equivalent to the pre-change template, and the existing dark/light color translation remains in place.

Regression coverage rejects unresolved style tokens and raw hex literals inside the stylesheet template, checks representative token values, and verifies that focus/selection styling still translates into the light palette.

**Automated status: PASS** for implementation commit `39a4fc03bf67a7cc814474d15b3836ac8d3b6790`, merged to `main` as `2e1dfb3393f09c9d217f6512892de815cdfd17f3`.

- [Desktop CI](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39120179594) — **PASS**: lint, compile, tests on Python 3.12/3.13/3.14, Windows Qt UI smoke, and MySQL 8.4 integration.
- [Dependency-security audit](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39120179576) — **PASS**.
- [Windows packages](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39120179535) — **PASS**: onedir application, portable EXE, installer, silent install/uninstall, package launch, expected outputs, CycloneDX SBOM, provenance, checksums, and artifact upload.

This completes the automated stylesheet-token regression gate. It does **not** substitute for human visual review on real Windows displays: physical DPI/high-DPI rendering, contrast and clipping checks remain under Phase 8. CI artifacts are not a stable GitHub Release.

**Workstream numbering note:** `PHASE0_BASELINE_AUDIT.md` uses an earlier “Phase 1” label for MySQL-client script-parser work. That is a separate parser workstream, not the canonical UX roadmap's Phase 1 (shared theme tokens and component styling).

### Phase 8 follow-up — Authenticode release path and current-main verification — 19 October 2026

PR [#54](https://github.com/ram1234598766-dotcom/MySQL-Editor/pull/54) merged as `73e8c2687635a85d0151cbd040d1f65749479332` and adds an optional, fail-closed Windows Authenticode path:

- Build the app-folder and portable executables, then optionally sign and verify them with SHA-256 Authenticode plus an RFC 3161 timestamp before building the installer. Sign and verify the installer separately after Inno Setup compiles it.
- Keep certificate secrets out of pull-request runs; evaluate signing configuration only on trusted pushes to `main`, version tags, or explicit workflow dispatches for those refs.
- Fail on partial secret configuration, and block stable version-tag publication if a trusted certificate is not configured. Preview builds can remain unsigned, but their manifest must explicitly disclose that state.
- Extend `tools/create_release_manifest.py` so it cannot claim `signed` unless the workflow passes the verified-signature arguments after successful mode-appropriate signature checks: Authenticode integrity and signer-thumbprint checks for self-signed mode, or SignTool policy verification for trusted mode. Add tests for unsigned/signed manifest states and workflow ordering.
- Document the two Actions secrets and the limits of signing/SmartScreen claims in `WINDOWS_SIGNING.md`.

Automated verification for the merged source commit:

- [Desktop CI](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39216104552) — **PASS**.
- [Dependency-security audit](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39216104455) — **PASS**.
- [Windows package workflow](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39216104411) — **PASS**, including executable/installer builds, silent install/uninstall and shortcut cleanup, package-launch smoke tests, SBOM, provenance, checksums, and artifact upload.

The signing-configuration check ran successfully on this main build, but the signing steps were skipped because no certificate secrets were configured; the artifact is unsigned. The signing helper's syntax, manifest guardrails, and the unsigned PR build were tested. Actual signing with a trusted certificate remains unverified until the repository secrets are configured and a tagged workflow confirms successful SignTool verification.

**Phase 8 is not fully closed.** Physical Windows display-scale validation, end-to-end keyboard-only use, Narrator/screen-reader review, real Windows Credential Manager behavior, external MySQL/TLS checks, and the final manual test record are still pending in `RELEASE-CANDIDATE-CHECKLIST.md`. CI screenshots use simulated scaling and synthetic data and are not a substitute for testing on the target PC.

---

## Phase 0 — User decisions and implementation gate

**Recorded:** 19 October 2026  
**Status:** Product decisions recorded and approval gates satisfied. The user approved the baseline audit, PR sequence, and implementation. Phase B's self-signed Windows signing path is merged and the configured PFX has been verified on the trusted `main` workflow. Stable-tag release signing and physical-Windows acceptance remain separate gates.

### Confirmed decisions

1. **SQL parser:** Adopt SQLGlot, with a custom MySQL `DELIMITER` preprocessing/layer. Keep delimiter handling and compound stored-program boundary behavior explicitly tested; do not claim SQLGlot alone provides complete MySQL server-side semantic validation.
2. **SSH tunneling:** Defer to a later phase. Do not include SSH tunneling in the initial Windows desktop scope.
3. **Platform:** Windows 10 and Windows 11 only for this roadmap.
4. **Update checker:** Automatic startup checks are optional and disabled by default. A user-initiated **Help → Check for updates** action may run a one-time check without changing the startup preference. Never fetch update metadata automatically unless the user has opted in.
5. **Windows signing:** Use a **self-signed code-signing certificate** for the planned signing path, rather than assuming a publicly trusted certificate is available. Preview artifacts may remain unsigned until release. Stable-release candidates must disclose the certificate type and pass actual signature verification if signed. A self-signed certificate is not trusted by Windows on other machines by default and does not remove SmartScreen warnings; Microsoft documents self-signed certificates as appropriate for development/testing, not broad public distribution. Do not describe such a build as signed by a publicly trusted publisher or promise warning-free installation. See [Microsoft's SmartScreen guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation) and [code-signing options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options).
6. **Accent palette:** Keep the existing teal-and-indigo direction. Refine contrast, state colors, and consistency without changing the core palette.

### Approval gate — do not bypass

- [x] User explicitly approves the Phase 0 baseline audit.
- [x] User explicitly approves the proposed PR sequence.
- [x] Phase B implementation proceeded after both approvals.
- [x] Implementation used focused branches/PRs, regression tests, CI evidence, and honest validation reporting.
- [x] This decision record is no longer an approval blocker for the self-signed signing-path implementation.

## Phase B — self-signed Windows signing path

**Status: IMPLEMENTATION COMPLETE; CONFIGURED PFX VERIFIED ON MAIN.** PR #57 adds the signing path, PR #58 improves certificate-mismatch diagnostics, and PR #59 pins the workflow to the certificate already configured in Actions. All three are merged. The latest main Windows package workflow passed. Existing theme-token, motion, delimiter parsing, result paging, and other previously merged roadmap work must not be reimplemented merely to replay the older sequence.

### Scope completed

- [x] Keep pull-request builds, main-branch previews, and preview tags unsigned by policy.
- [x] Require signing configuration for stable version tags and fail closed when the certificate or password is missing.
- [x] Support self-signed code-signing without modifying the hosted runner's trust store; accept only the expected untrusted-root Authenticode status when the signer thumbprint matches, and disclose that recipient PCs do not trust the certificate by default.
- [x] Record certificate type and verification trust scope in the release manifest; do not claim recipient trust for self-signed signatures.
- [x] Add a Windows smoke test that generates a short-lived self-signed test certificate and signs a disposable copy of a compiled EXE. It does not mutate or publish that preview artifact.
- [x] Update the signing guide, README signing disclosure, workflow assertions, and release checklist.

### Verification and merge record

- [PR #57](https://github.com/ram1234598766-dotcom/MySQL-Editor/pull/57) — implementation of the signing helper, fail-closed stable-tag path, and signature-integrity validation without trust-store writes; merged as `f4f3fabc132aa30293559a0067f1f12290a2c2e3`.
- [PR #58](https://github.com/ram1234598766-dotcom/MySQL-Editor/pull/58) — diagnostics for mismatched configured and approved certificate thumbprints; merged as `b9216a5c6a93479458c1136e1a0caf5269d0e225`.
- [PR #59](https://github.com/ram1234598766-dotcom/MySQL-Editor/pull/59) — pins the workflow to the public thumbprint of the existing configured certificate, updates the regression assertion, and documents the identity; merged as `9f5ed33f946e08ffaf7cf3bf922422e4dd1641b6`.

The [current-main Windows package workflow](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39253548129) completed **PASS**. The configured PFX loaded with its private key, the signer matched the pinned thumbprint, and the workflow successfully signed and checked a disposable executable. The same commit passed desktop CI and the dependency-security audit. The Windows build generated the application-folder EXE, portable EXE, and installer; passed install/uninstall and packaged-launch smoke tests; generated the SBOM, provenance manifest, and SHA-256 checksums; and uploaded the `MySQLEditor-Windows` CI artifact.

### Remaining release gates

- [ ] Build a stable version tag and verify that the application-folder executable, portable EXE, and installer are each timestamp-signed, verified by the selected mode, and correctly represented in the release manifest.
- [ ] Complete the manual Windows acceptance checks in `RELEASE-CANDIDATE-CHECKLIST.md`, including real display scaling, keyboard-only interaction, screen-reader behavior, the target machine's Credential Manager state, and the target MySQL/TLS environment.
- [ ] Review the produced signed release manifest and `SHA256SUMS` for the exact binaries before promoting a stable release.

**Important boundary:** main/preview artifacts remain unsigned by policy. The disposable-EXE smoke test proves the repository's configured PFX is usable and correctly pinned; it is not a signed product release. No stable version-tag release was published by this work.

### Phase 7 follow-up — opt-in stable-release update checker and shutdown reliability — 19 October 2026

**Implementation status: merged.** Automatic stable-release checking is disabled by default, in line with the Phase 0 decision. A one-time Help → Check for updates action does not turn on future startup checks.

- [PR #61](https://github.com/ram1234598766-dotcom/MySQL-Editor/pull/61), merged as `c72d5cfb0ba376faf5cd665674ff579d5a3b3f28`, adds the bounded GitHub Releases check, strict stable-tag and URL validation, a background QThread, an explicit Settings toggle, manual-only release-page navigation, and privacy/test documentation.
- [PR #62](https://github.com/ram1234598766-dotcom/MySQL-Editor/pull/62), merged as `3db5d9f66e1f2edf30c3bf4db42a6cdf700f25d0`, removes the synchronous UI-thread wait during close. If an update check is active, the close event is deferred until the thread finishes; the main window does not block on the network timeout, and update dialogs are suppressed while closing.
- Regression coverage includes stable-version parsing, safe and unsafe links, newer/equal/older version outcomes, missing stable release, malformed and oversized responses, network failures, default-off behavior, one-time manual checks, and non-blocking close behavior.

The required workflows passed on both pull-request heads:
- PR #61: [desktop CI #409](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39260531405), [dependency security #478](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39260531523), [Windows packages #290](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39260531432).
- PR #62: [desktop CI #412](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39263894629), [dependency security #481](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39263894519), [Windows packages #293](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39263894491).

The exact merge commit `3db5d9f66e1f2edf30c3bf4db42a6cdf700f25d0` passed all post-merge workflows on `main`: [desktop CI #413](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39264933212) — PASS; [dependency security #482](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39264933266) — PASS; [Windows packages #294](https://github.com/ram1234598766-dotcom/MySQL-Editor/actions/runs/39264933203) — PASS, including both EXE builds, temporary-certificate signing smoke test, installer compile, install/uninstall, packaged application launch, expected output verification, SBOM/provenance, SHA-256 checksums, and artifact upload. Actual preview artifact signing was skipped as intended by policy; the PFX was not used to sign distributed preview binaries.

**Behavior/security boundary:** the checker requests public GitHub release metadata only when automatic checking is enabled or a user explicitly requests a manual check. It sends no SQL, MySQL connection details, database credentials, query results, device identifier, or usage history. It never downloads or installs an update. Preview Windows artifacts remain unsigned by policy.


### SQL workstream increment — parser-backed mutation risk advisory — 20 October 2026

**Scope:** Use SQLGlot's MySQL AST as the first path for parseable UPDATE and DELETE risk advisories. The advisory checks only the mutation node's own top-level WHERE; a predicate inside a CTE, join condition, or nested subquery cannot make an unbounded outer mutation look bounded. Unsupported syntax and SQLGlot parse errors retain the existing scanner fallback. MySQL/MariaDB executable-comment bodies continue to be inspected separately.

**Related parser integration fix:** the previously used `sqlglot.format` import is not exported by the supported SQLGlot API. That ImportError had disabled the existing optional-import block, leaving the formatter unavailable and preventing AST access. Parser imports are now isolated to supported public APIs; formatting parses and renders each MySQL statement, keeps later statements, and preserves a final semicolon when present. It rejects scripts with active MySQL-client DELIMITER directives before altering text, because those client-side boundaries are not server SQL.

**Regression coverage:** MySQL joined UPDATE, an outer CTE containing an unbounded UPDATE, a CTE-wrapped DELETE with a real outer predicate, a predicate containing a nested subquery, fallback behavior when SQLGlot is unavailable, and multi-statement formatting. The result remains advisory; server-side MySQL privileges remain the actual authorization boundary.

**Not completed by this increment:** full AST-based statement splitting, schema-aware completion, inline diagnostics, a full MySQL grammar, semantic validation, and physical-Windows acceptance. Merge only after the exact PR head passes the full CI and Windows packaging workflow.

### Phase 5 follow-up — scroll-triggered result paging — 20 October 2026

**Status: merged to `main` in PR #79 (commit `5100b428a5b0beced8e53535b5d0aa1caedcb8a8`).** This increment builds on the existing SQLite result spool and preserves the existing **Fetch +1,000** control as a fallback.

- The result table model now exposes Qt's `canFetchMore()`/`fetchMore()` contract and emits a request when the grid reaches the end of its loaded rows.
- The request is routed to the existing database worker's `fetch_result_page` action. It reads the local spool rather than issuing SQL to MySQL; one request can be active at a time, duplicate requests are blocked, and rows are inserted incrementally without resetting the model.
- Result filtering, sorting, CSV fetch-order semantics, row-count summaries, and existing explicit page loading remain in place.
- Regression tests cover one-page-at-a-time behavior, duplicate suppression while a page is pending, incremental row insertion without a model reset, child-index/failure states, proxy-model forwarding, and the scroll-to-end worker-dispatch path.
- README and release notes explain the automatic paging behavior and the existing manual fallback.

**Acceptance still open; do not describe WS4 as complete:**

- Loaded rows are currently retained in the result model as the user browses. The UI does not yet use a bounded LRU/window cache, so intentionally browsing every row in a very large result can still accumulate model memory.
- Schema Explorer table preview remains capped at 1,000 rows. Removing that cap safely requires a separately tested preview paging/data-consistency path that preserves guarded cell-edit semantics and does not fetch an unexpectedly large table into memory.
- Sorting and quick filtering still operate on the loaded preview rather than query the full SQLite spool. Full spool-backed sort/filter belongs to the remaining results workstream.
- The one-million-row responsiveness and bounded-memory target has **not been measured** by this increment. CI model tests and simulated Windows UI checks are not proof of performance on a physical target PC.

Next: continue with the bounded result-window and spool-backed sort/filter work before marking the large-results exit gate closed.

### Phase 5 follow-up — JSON and NDJSON result export — 20 October 2026

**Status: merged to `main` in PR #80 (commit `c9ab16e6bb6c8a4edfacdfe3aab12740cbd614c1`).** The export dialog can select CSV, JSON array, or newline-delimited JSON without adding a runtime dependency.

- JSON/NDJSON writers stream ordered rows directly from the SQLite result spool on the database worker; they do not rely on the grid's loaded rows, sort order, or quick filter.
- JSON is a conventional array of row objects; NDJSON is one row object per line. SQL NULL maps to JSON `null`; empty text remains an empty string. Duplicate or blank column labels receive stable unique names so duplicate-column values are not overwritten by object-key collisions.
- Both formats use a same-directory temporary file, flush/fsync, and replace the destination only after a successful full export. A malformed spool row or serialization failure leaves an existing destination intact and removes the temporary file.
- UI feedback is persistent, non-modal, format-specific, and redacts credential-like error fragments; tests cover format selection, null/empty/Unicode/duplicate headers, fetch-order semantics, success feedback, failure cleanup, and preservation of pre-existing files.
- README and release notes describe the formats and caveats. CSV behavior and its existing `\\N` convention are retained.

**Acceptance still open:** XLSX remains a separate decision because it needs a streaming writer and dependency/license/packaging evaluation. Bounded model-row retention, spool-backed filtering/sorting, and the Schema Explorer preview cap are still unresolved. Large-result performance and physical-Windows QA have not been measured by this change.

### Phase 3 follow-up — MySQL line-comment toggle — 20 October 2026

**Status: implementation in this PR; CI validation pending.** The SQL editor supports a Ctrl+/ action to toggle MySQL line comments on the current line or selected lines. It preserves leading indentation, cursor/selection positions relative to SQL text, and the surrounding lines. The operation is grouped as one undo action and does not submit or execute SQL.

Regression tests cover current-line comment/uncomment, selected multi-line blocks with mixed indentation and blank lines, pre-existing MySQL line comments, selection/cursor restoration, single-step undo, and accessible keyboard help. The README keyboard-shortcut reference and release notes document the interaction.
