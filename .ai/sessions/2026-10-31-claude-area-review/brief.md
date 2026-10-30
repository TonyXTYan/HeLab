# Brief: area review of HeLab 0.0.7a1 (`agent/area-review`)

Coordinator: CoCo, 2026-10-31. Tony (Chat): "do area review, and ok to hybrid". HeLab 0.0.7a1 is released
(`main` `e03c32a`, PR #10); `dev/v0.0.8` starts at `c3a503f` (this floor's base: the same tree plus one
handoff note). Codex's PR review found 9 real bugs in six rounds (all fixed; `.ai/sessions/2026-10-31-claude-quick-fixes-7/`),
mostly where one area's state crosses into another (held shots and TXY kinds, remembered convert lists across
profiles, the cached quick check across HeLab instances). This review looks for the rest **by area**, each
Reviewer against its area's invariants, before v0.0.8 builds on it (caching v2 / store-v4 is next).

**Read-only.** Never edit code, tests or the shared docs. Each Reviewer writes only its own file:
`.ai/sessions/2026-10-31-claude-area-review/<area>.md` (area keys below). Commit it on this floor's branch
(`git add` that one file; the Coordinator pushes the branch). No fixes, no PR, no push.

## The areas

| Key | Reviewer | Area and main files | Architecture file(s) |
|---|---|---|---|
| `io` | Reviewer 1 | I/O helpers and the queue, Live: `helab/io_helper.py`, `helab/io_ops/` (not `convert.py`, `helab_txy.py`, `stores.py`, `admin.py`), `helab/utils/io_service.py`, `helab/utils/folder_cache.py` (jobs, lanes, Live, RAM budget), `helab/views/explorer_live.py` | io-and-browsing, live |
| `cache` | Reviewer 2 | The disk cache and data roots: `helab/utils/cache_store.py`, `cache_paths.py`, `data_roots.py`, `cache_move.py`, `cache_setting.py`, `helab/io_ops/stores.py`, `admin.py`, `markers.py`, results/presets storage, `folder_cache.py`'s store identity and save guards | cache-store, data-roots |
| `convert` | Reviewer 3 | The TXY converter: `helab/convert/`, `helab/convert_cli.py`, `helab/io_ops/convert.py`, `helab/io_ops/helab_txy.py`, `helab/utils/txy_sources.py`, `file_kinds.py`, `native/` | converter |
| `plots` | Reviewer 4 | Analysis, plots, scripts: `helab/analysis/`, `helab/scripts/`, `helab/views/plots/`, `helab/utils/dash_server.py` | plots-and-scripts, dld-analyses |
| `app` | Reviewer 5 | App runtime, UI, settings, release: `helab/main.py`, `helab/views/` (not `plots/`, not `explorer_live.py`), `helab/models/`, `helab/utils/settings_*`, `settings_defaults.py`, `app_log.py`, `gui_watchdog.py`, `accessible.py`, `helab/release*.py`, `build_info.py`, `.github/workflows/`, `HeLab.spec` | app-runtime-and-ui, settings, release-and-ci, testing |

Read where your area touches another (the boundary is where Codex's bugs were), but report only what lives in,
or is caused by, your area's code; name the other area when it's a boundary finding.

## What to look for, in order

1. **Each AGENTS.md invariant and each rule in your architecture file(s)**: is it actually true in the code? A rule
   the code breaks is a finding; a rule the docs state that isn't true any more is a doc finding.
2. **State that outlives its context**: remembered lists, caches, held data, flags or settings kept across a profile,
   source mode, folder, cache-folder move, Work Offline, restart or a second HeLab instance, and reused without
   checking it still applies (the class of Codex's 9).
3. **Error and race paths**: what happens on a failed or partial write, a helper dying, a file changing while read,
   a cancel, quit mid-operation; anything that can lose or overwrite the user's data or block the GUI thread.
4. **Tests**: important behaviour of your area with no test, or a test that can pass without checking what its
   name says. Flaky-test causes you can see in the code (the known-issues entries for your area).
5. Lower priority: dead code, duplicated logic, unclear names. One line each, at the end.

## How to report (your `<area>.md`)

- Each finding: **ID** (`io-1`, …), **severity** (High: data loss, corruption, wrong results, crash, GUI freeze; Medium:
  wrong behaviour a user can hit; Low: edge case, misleading UI or docs; Nit), `file:line`, what's wrong, a
  **concrete scenario** (inputs or steps → what happens), and how you verified it (read the code path; a test or a
  scratch script under `.ai/temp/` you ran: say which). **Only report what you've verified**; mark anything you
  couldn't confirm "Unverified" with what would confirm it. No speculative findings dressed as certain.
- A short "Checked and fine" list: the invariants and paths you checked that hold (so the next review knows).
- A proposed fix direction per finding (one or two lines), not a patch.
- Keep it to what matters: 5 real findings beat 30 guesses.

## Running things

Shell: `cd "$(git rev-parse --show-toplevel)"` then `source venv/bin/activate` if the floor has one, else
`source /Users/tonyyan/GitHub-Local/HeLab/venv/bin/activate` (pytest's `pythonpath = .` tests this floor's checkout).
Tests you run: `pytest <files> -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-<area>`; report any
RERUN. Tests never touch real data; never read `~/HeLab-samples` beyond what a test does; never the X share. No
GUI launch. Scratch scripts only under `.ai/temp/`.

When done: commit your file, then report back with
`maestri ask "CoCo" "<area> review done: N findings (H/M/L counts), committed <hash>"`.
