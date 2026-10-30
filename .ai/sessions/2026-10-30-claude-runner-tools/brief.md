# Brief: runner tools: milestone log lines and a dev bundle for source runs (`agent/runner-tools`)

Coordinator: CoCo, 2026-10-30. Tony's GO (Chat, via Side, 2026-10-30) for two of the computer-use
extras from `.ai/sessions/2026-10-28-claude-smoke-mac/computer-use-notes.md`: **item 2, milestone
log lines** and **item 7, a macOS bundle ID for source runs**. The Smoke ready floor (Beacon,
`agent/smoke-ready`) does the rest of the runner work (accessible names, objectName IDs, the Debug
menu items, Dump state, Quit that confirms, `--geometry`, two plot bugs): stay off `helab/views/`
except the single log line named below. One Worker, then a Reviewer.

## Read first

`AGENTS.md` (I/O rules: the GUI never touches source folders or the store; helpers' events are the
typed contract; logs); `roadmaps/smoke-automation.md`; the computer-use notes above (what a runner
could not do: no bundle ID for `venv/bin/helab`, so `app_*` tools can't target it and its window is
hidden from screenshots); `.ai/architecture/{app-runtime-and-ui,io-and-browsing,converter,release-and-ci}.md`;
`helab/utils/app_log.py`.

## Base and branch

Base `9f0b21f` (`dev/v0.0.7`). Branch `agent/runner-tools`. The TXY Index floor (`agent/txy-index`)
changes `helab/io_ops/convert.py` and `helab/convert_cli.py` and lands before you: do the conversion
line last, after CoCo says TXY Index has landed and you've merged `dev/v0.0.7`.

## Objective

1. **Milestone log lines (item 2)**: one INFO line, in a fixed greppable form, when
   - a folder's load is done (shots, events, seconds, from cache or source): where the GUI learns it
     (`helab/utils/folder_cache.py`);
   - a plot's compute is done (script ID, plot/tab ID, seconds, ok/failed): `helab/analysis/runner.py`
     or where its result reaches the GUI;
   - a conversion finished (folder, shots converted/failed/no-hit, output, seconds): the GUI on the
     helper's `convert_summary` event (`helab/views/explorer_live.py`, that one line) and
     `helab convert` (`convert_cli.py`, after TXY Index lands).

   Propose the form (e.g. `MILESTONE load_done key=value ...`), one helper for writing it so the
   form can't drift, and the log a runner reads (HeLab's log file; Help › Show log folder). No
   source paths beyond what the log already writes (the privacy pass, block 29: check
   `.ai/DECISIONS_TODO.md` block 29 for what the log may contain). Memory only, the GUI thread never
   waits. Tests for each line.
2. **A bundle ID for source runs on macOS (item 7)**: a `dev/` tool that builds a small `.app` stub
   (gitignored output, e.g. `.ai/local/HeLab-dev.app`) whose executable runs this checkout's
   `venv/bin/python -m helab "$@"`, with its own bundle ID (proposed `au.edu.anu.he-bec-lab.dev`, so it
   never answers for the release's `au.edu.anu.he-bec-lab`) and a distinct name ("HeLab dev"). Show it
   works: `open` it, then `lsappinfo` / `osascript` find the process by that bundle ID, and its window
   appears in a screenshot. Say what happens with `--geometry` and other arguments (`open --args`),
   and with two checkouts (the stub names the checkout it runs). No app code changes; a README line
   proposed for the setup section.

## Rules

Owned paths: `dev/` (the new tool), `helab/utils/app_log.py` (the helper), the log lines at the sites
above (one line each, nothing else changed there), new tests. Ask CoCo before any other file. Strict
typing (incl. `--platform win32`, `pyright --pythonplatform Windows`); tests never touch real data;
the full suite inside and once outside the checkout basetemp, every RERUN reported. The test data
set (item 6) is Side's and Tony's, local and outside the repo: don't add a fetch script or CI wiring
for it. Docs only in `.ai/sessions/2026-10-30-claude-runner-tools/` (notes, handoff with proposals:
`app-runtime-and-ui.md` (logs), `testing.md` or README (the dev bundle), the smoke runbook; provisional
`Q~`/`A~`/`M~`). Push at checkpoints only; the landing needs a Reviewer with no open findings and CI
green on 3 OSes by run ID. No version bump, release, tag or PR.
