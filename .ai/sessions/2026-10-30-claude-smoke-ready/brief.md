# Brief: smoke ready: accessible controls, runner menu items, window screenshot (`agent/smoke-ready`)

Coordinator: CoCo, 2026-10-30. Tony's GO (Chat, via Side, 2026-10-30) for v0.0.7, before the smoke pass:
[`roadmaps/smoke-automation.md`](../../../roadmaps/smoke-automation.md) items **4, 1 and 2** (Q5.2). Tony
wants it "set up properly": every control named, and a test that keeps it that way. One Worker, then a
Reviewer.

**Not in this floor:** the `--smoke` control channel (item 3) waits for v0.0.8, design first. Item 5's
shape is answered by Tony: the runner's items go in the **existing Debug menu** (Q5.2.5), not a separate
Smoke menu. Nothing about the store, the converter or caching.

## Read first

`AGENTS.md` (UI rules: one-line status rows, details in tooltips; rendering reads memory only; the GUI
never touches source folders or the store; navigation stays available during I/O);
`roadmaps/smoke-automation.md`; the smoke runbook and its evidence
(`.ai/sessions/2026-10-28-claude-smoke-automation/plan.md`,
`.ai/sessions/2026-10-28-claude-smoke-mac/{results,computer-use-notes}.md`: what the runner could not
find or click); `.ai/MANUAL_TODO.md` M1.1–M1.10; `.ai/architecture/{app-runtime-and-ui,plots-and-scripts,testing}.md`.

## Base and branch

Base `9f0b21f` (`dev/v0.0.7`). Branch `agent/smoke-ready`. Two floors land before you (TXY Index:
`CacheTab.py`'s converted row, `convert_cli.py`, the quit path; Byte Units: every `byte_size` call in
`helab/views/`): merge `dev/v0.0.7` into your branch when CoCo says they've landed, before your final
push, and name every new control they add.

## Objective

1. **Accessible names and descriptions (item 4)** on every interactive control in every HeLab window
   and dialog: the main window (path bar, toolbar and icon-only tool buttons, folder tabs, Folder
   details, summary row buttons), the plot workspace (Group combo, each script's Plot button, preset
   buttons, each plot tab's close ×, the settings panel's controls, TXY row), Settings and every tab
   (spin boxes, combos, checkboxes, buttons), and every dialog and tool window in `helab/views/`.
   - The name is what a runner searches for: short, stable, the visible label or the action
     ("Close plot tab: <title>", "Plot <script name>"). A control whose text already gives Qt a name
     needs nothing more; an icon-only or unlabelled one does.
   - The description says what it does, in one line, static. Tooltips that change with state stay as
     they are (memory only); don't move them into the description.
   - Controls created per row or per script (Plot and preset buttons, tab close buttons) get their
     name where they're created, including when a tab or script is renamed.
2. **The test that keeps it set up:** a test that opens each window and dialog (with synthetic data
   where a control only appears with a folder or a plot), walks its interactive widgets
   (`QAbstractButton`, `QComboBox`, `QLineEdit`, `QAbstractSpinBox`, `QAbstractSlider`, tab bars and
   their buttons, item views; say which classes count and why) and fails on any visible, enabled or
   not, whose **effective accessible name** (the one Qt reports, e.g.
   `QAccessible.queryAccessibleInterface(w).text(QAccessible.Text.Name)`) is empty, listing them all.
   Plus a guard so a new window or dialog class in `helab/views/` can't escape it (e.g. the test lists
   every `QDialog`/`QMainWindow`/top-level `QWidget` subclass and fails on one it doesn't open, with an
   explicit, reasoned skip list). No `QWebEngineView` left alive; settings from `app_settings()`; no
   real data.
3. **Menu-bar items for a runner (item 1)**, in the existing **Debug** menu (`HelabMainWindow`): run a
   plot (the current folder tab's scripts), pick the script Group, switch to and close a plot tab, open
   each Settings tab. Submenus filled from memory as they show (`aboutToShow`); each item calls the
   same code path as the button it stands for (no second implementation), disabled with a reason where
   the action isn't available. Navigation and the I/O rules unchanged.
4. **Debug › Save window screenshot… (item 2)**: `QWidget.grab()` of the active HeLab window (say how
   it's chosen when a dialog or floating plot is in front) to a PNG the user picks. Say which plot
   panes come out blank (QtWebEngine, PyQtGraph's GL, if any) and propose any follow-up as `Q~`/`A~`;
   don't build workarounds for them here. If a runner needs a path without a dialog, propose it (`Q~`).
5. **Docs proposals:** an AGENTS.md invariant (Tony's proposal: "every interactive control has an
   accessible name (test-enforced)", one line under UI); `app-runtime-and-ui.md` (names, the Debug
   items, the screenshot); `testing.md` (the test and how to add a window); `smoke-automation.md`
   items 1, 2, 4 done and item 5 answered; the runbook's changes (what a runner now uses instead of
   pixels) as `M~` or proposals.

## Rules

Owned paths: `helab/views/**` and `helab/views/plots/**` (accessible names and descriptions only, plus
the Debug menu and screenshot in `HelabMainWindow.py`), new tests. Change nothing else at a call site.
Ask CoCo before touching any other file. Strict typing (incl. `--platform win32`,
`pyright --pythonplatform Windows`); tests never touch real data; the full suite inside and once
outside the checkout basetemp, every RERUN reported; GUI checks only with `floor-env.sh` sourced on
synthetic folders. Docs only in `.ai/sessions/2026-10-30-claude-smoke-ready/` (notes, handoff with
proposals and provisional `Q~`/`A~`/`M~`). Push at checkpoints only; the landing needs a Reviewer with
no open findings and CI green on 3 OSes by run ID. No version bump, release, tag or PR.
