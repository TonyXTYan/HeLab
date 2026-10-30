# Brief: UI polish, settle time as a setting, 32-hex user tags (`agent/ui-polish`)

Coordinator: CoCo, 2026-10-30. Tony's GO (Chat, via Side, Q33.6) for v0.0.7, after Smoke ready landed
(`4ad8ac5`): block 33 (Q33.1–Q33.5, A33.1–A33.4) from the provisional UI pass, plus Q33.7 (the settle
time as a setting) and Q23.6 (custom profile tags `u` + 32 hex). The decisions, Tony's wording and
the proposed details are in `.ai/DECISIONS_TODO.md` (Recently decided, blocks 33 and Q23.6) and
`.ai/AI_TODO.md` (A33.1–A33.4); the evidence in
`.ai/sessions/2026-10-30-claude-ui-provisional-0.0.7/findings.md`. One Worker, then a Reviewer. Not
caching v2: no store or `store-v3` change.

## Read first

`AGENTS.md` (all of it: UI rules, including the new accessible-name rule and the Qt-made-sender lambda
rule; I/O rules: files still being written, `SETTLE_SECONDS`; settings rows; the converter's names);
`.ai/architecture/{app-runtime-and-ui,plots-and-scripts,settings,io-and-browsing,converter,testing}.md`;
the findings above; Smoke ready's handoff (`.ai/sessions/2026-10-30-claude-smoke-ready/handoff.md`:
accessible names and IDs, `tests/test_accessible_names.py`, the Debug menu, `--geometry`, Return/Escape
in plot settings).

## Base and branch

Base `43cb202` (`dev/v0.0.7`). Branch `agent/ui-polish`. Two floors may land before you: Runner Tools
(milestone log lines; `dev/dev_app.py`) and the TXY Index follow-up (A30.4 background `last_used`
writes in `folder_cache.py`; Q23.7 in `io_ops/convert.py`): merge `dev/v0.0.7` when CoCo says, before
your final push.

## Objective (in this order; commit each separately)

1. **UI (block 33)**:
   - Q33.1 double-click on a folder with no subfolders selects it (and so loads it) instead of making it
     the tree's top; a typed path to such a folder opens its parent and selects its row; a folder with
     subfolders, or not listed yet, as today. Memory only (the snapshot model knows `has_dirs`).
   - Q33.2 default split: folders ~380 px, settings ~320 px, plots the rest; the user's drags kept
     across restarts (a settings row; say how it fits `--geometry`, which is for one run); the folder
     panel no longer collapses by itself when a plot opens (only Live collapses it, Q18.3).
   - Q33.3 a newly floated plot opens offset ~40 px from the last one at ~800×600, kept on screen; a
     restart restores where the user left them (say what the arrangement record already keeps).
   - Q33.4 a floating plot window gets a **Dock** button (named, with an ID).
   - Q33.5 remove the Debug menu's three placeholders ("Debug - 6", "Draw a line in debug console",
     "Debug - validate tab status"); keep Smoke ready's runner items.
   - A33.1 Tab out of a plot setting commits and stops (no next row's editor), like Return.
   - A33.2 offline, Folder details agrees with the summary's "not checked (offline)".
   - A33.3 Settings › General's temp folder row worded like the cache folder's, not "DIR_TEMPS:".
   - A33.4 after a plot floats, the settings panel's Float acts on (or shows) the right plot.
2. **Q33.7 the settle time as a setting**: Settings › General beside Live's interval; defaults 3 s
   interval and 5 s settle; settle 2–60 s (below 2 s HeLab can't tell a file still being written,
   `RACY_SECONDS`). Helpers read `fingerprints.SETTLE_SECONDS`, so the app passes the value with each
   request, as `store_options()` is passed (say exactly which requests and how a helper falls back
   when it's absent, e.g. `helab convert` and old payloads); `HELAB_SETTLE_SECONDS` keeps working for
   tests. It applies to every read (browse, load, Live, cache checks, convert), and its help text says
   so. A settings row in `settings_defaults.py`. Tests that the value reaches each helper operation.
3. **Q23.6 user tags `u` + 32 hex** (`USER_TAG_DIGITS` 8 → 32; built-in tags unchanged and pinned):
   `file_kinds.HELAB_TXY`'s tag pattern, `partial()`/`own_partial()` and every name pattern take 33
   characters; existing `u`+8 TXY from tonight's builds: say how they're treated (proposed: like any
   other profile's TXY under a different tag: ignored for the new profile, converted again, never
   deleted). Windows' 260-character path: a test with a deep path on Windows CI, and a clear message
   when a path is too long (where it's raised and what the user sees).
4. **Docs proposals** in the handoff: `app-runtime-and-ui.md`, `plots-and-scripts.md`, `settings.md`
   (the new rows), `io-and-browsing.md` and AGENTS.md (the settle line: "5 s" becomes "the setting,
   default 5 s"), `converter.md` (tags), `testing.md`; provisional `Q~`/`A~`/`M~`.

## Rules

Owned paths: `helab/views/**` (and `helab/views/plots/**`), `helab/analysis/parameter_tree.py`,
`helab/utils/settings_defaults.py` (the new rows), the settle-time plumbing (`helab/io_ops/fingerprints.py`,
the request payloads in `folder_cache.py`/`io_service.py` and the helper side that reads them: the
smallest change), the tag code (`helab/convert/profile.py` or wherever `USER_TAG_DIGITS` lives,
`helab/utils/file_kinds.py`, `io_ops/convert.py`'s name patterns), their tests. Ask CoCo before any
other file. Every control you add has an accessible name and ID (`identify`); the names test must stay
green. Strict typing (incl. `--platform win32`, `pyright --pythonplatform Windows`); tests never touch
real data; window tests that don't check caching use RAM-only folders; the full suite inside and once
outside the checkout basetemp, every RERUN reported; GUI checks only with `floor-env.sh` sourced on
synthetic folders. Docs only in `.ai/sessions/2026-10-30-claude-ui-polish/`. Push at checkpoints only;
the landing needs a Reviewer with no open findings and CI green on 3 OSes by run ID. No version bump,
release, tag or PR.
