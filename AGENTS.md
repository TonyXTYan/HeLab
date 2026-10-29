# HeLab Agent Notes

HeLab (Helium Experiment Lab Analysis Board) is a PyQt6 desktop app for real-time analysis of
the ANU Helium BEC lab's delay-line-detector data. It browses the lab's data folders, loads and
caches TXY files, follows new shots live and runs pluggable analysis scripts as interactive plots.

`TonyXTYan/HeLab` (this repo) is where HeLab is developed and released; `HeBECANU/HeLab` is the
lab's stable copy.

**This file holds the rules every task follows, plus a map.** The detail of each area is in
[`.ai/architecture/`](.ai/architecture/README.md). Keep this file under 30 KB: Codex reads only
its first 32 KiB. A new feature adds at most a line here (an invariant, or a pointer); its
mechanics go in its architecture file.

## Working with Tony

- Address the user as "🎓Tony" when answering him directly (a Chat answer, a reply in the
  terminal). Progress lines and messages between agents don't need it.
- **Commits.** Always ask Tony before `git commit` in his checkout or on his branches. Staging,
  diffing and reviewing are fine without asking. An agent in its own worktree, Maestri floor or
  cloud environment, on a new branch from the commit Tony or the Coordinator chose, commits there
  freely. It pushes that branch only at checkpoints, never with every commit (each push runs the
  full CI): when its work is done, after review fixes, or when a CI run on all three OSes is
  worth it (Tony, 2026-10-29). Merging into Tony's branches, landing a floor and opening a PR
  need his approval.
- **Commit messages:** a concise subject and a body that says what changed, why, and how it was
  checked, separated by a blank line.
- **Branches are kept.** Never delete an agent branch, locally or on GitHub; push finished
  branches to `TonyXTYan/HeLab` for the record.
- **Don't guess Tony's decision.** When a choice is his (behaviour users see, wording, scope,
  anything hard to undo), add it to [`.ai/DECISIONS_TODO.md`](.ai/DECISIONS_TODO.md) with
  options and a proposed answer, and carry on with what doesn't depend on it.
- **Offer, don't start:** at a natural pause, offer roadmap or known-issues items that fit,
  saying why. Start one only after Tony agrees. Items in [`.ai/AI_TODO.md`](.ai/AI_TODO.md) may
  be done without asking.
- **Floors** (Maestri; [workflow](roadmaps/agent-workflow.md), [setup](.ai/maestri-setup.md)):
  workers and reviewers never edit `AGENTS.md`, `.ai/architecture/`, `roadmaps/`,
  `.ai/MANUAL_TODO.md`, `.ai/DECISIONS_TODO.md`, `.ai/AI_TODO.md` or `.ai/memory/`. They write
  only their own `.ai/sessions/<date>-<tool>-<task>/` and propose doc changes in its handoff,
  which the Coordinator applies when landing.
- **Landing** (Coordinator, 2026-10-29; Tony, Q24.4): a floor lands only when its reviewer has no open
  findings, the branch's latest CI run is green on all three OSes (every job, checked by run ID),
  the full suite and type checks pass with their output kept whole, every RERUN is explained or
  in known-issues, and Ground has nothing uncommitted before the merge
  ([setup §6](.ai/maestri-setup.md#6-landing)).
- **CodeGraph**, if the `codegraph_*` tools are available (`.cursor/rules/codegraph.mdc`): it is
  reliable for definitions, signatures and source. Its callers, callees, trace and impact results
  miss calls made through attributes (e.g. `self.model.cache.submit(...)`), so confirm them with
  grep.

## Where things go

| What | Where |
|---|---|
| A feature or priority | [`roadmaps/_readme.md`](roadmaps/_readme.md) (the one priority list), with a plan in `roadmaps/<feature>.md` |
| A bug, gap or flaky test (any RERUN) | [`roadmaps/known-issues.md`](roadmaps/known-issues.md), until its cause is found and fixed |
| A question only Tony can answer | [`.ai/DECISIONS_TODO.md`](.ai/DECISIONS_TODO.md) |
| A settled decision, with its reason and Tony's wording | `.ai/memory/results/<topic>.md`, indexed in [`.ai/memory/MEMORY.md`](.ai/memory/MEMORY.md) |
| A check that needs Tony at a screen, real data or the lab | [`.ai/MANUAL_TODO.md`](.ai/MANUAL_TODO.md) (the release smoke pass first) |
| Work agents may do without asking | [`.ai/AI_TODO.md`](.ai/AI_TODO.md) |
| How an area works (names, mechanics, behaviour) | [`.ai/architecture/<area>.md`](.ai/architecture/README.md) |
| A rule every task must follow | this file |
| Investigations, evidence, briefs, handoffs | `.ai/sessions/YYYY-MM-DD-<tool>-<title>/` (search, don't auto-load; raw transcripts in `.ai/session-export-*/` if present) |
| Scratch | `.ai/temp/`, `.ai/local/` (gitignored) |

**IDs:** items in the three `.ai/*_TODO.md` lists are `Q`/`A`/`M` + `<block>.<item>[.<sub>]` (e.g.
`Q1.2`); refer to them by ID in commits, briefs and Chat. On a floor or in a cloud session, number
proposals provisionally in your handoff (`Q~1`, `A~1`, `M~1`); the Coordinator or the Assistant
merges them under the next block in [`.ai/ID_BLOCKS.md`](.ai/ID_BLOCKS.md), which has the rules.

Read `.ai/memory/MEMORY.md` first (Claude Code loads it by itself; Codex should read it), and
open individual memory files only when relevant. `.ai/coding-workspace.md` holds Tony's
cross-repo conventions; it is a link into his `ai-common` folder and is missing on other machines.

## Setup and commands

Python 3.13 is required (CI gates on it). Use uv, as in the README's "Setup (any machine)":

```bash
uv python install 3.13
uv venv --seed --python 3.13 venv && source venv/bin/activate   # Windows: venv\Scripts\activate
uv pip install -r requirements.lock -e .   # pinned; requirements.txt lists direct deps (README: updating dependencies)
git submodule update --init legacy/tdc_autoconverter   # DLD_front_panel, Momentum_Bells_test: cloned by hand (README)
```

`venv/` may be a symlink to `venv.nosync/` (out of iCloud sync on macOS); both are gitignored.

```bash
helab                          # or: python -m helab   (macOS venv/bin/helab, Windows venv\Scripts\helab.exe)
helab convert --watch FOLDER [--once] [--output temp|cache|beside]   # headless TXY converter
pytest -n 12 --reruns 5 --reruns-delay 1   # full suite; at most the machine's cores (CI: -n 4)
pytest tests/test_foo.py       # one file
mypy helab/ --strict && mypy tests --strict && pyright helab tests
mypy helab/ --strict --platform win32 && pyright --pythonplatform Windows helab tests   # as on Windows
python native/build.py                    # optional: the cython converter backend (C compiler)
pyinstaller HeLab.spec --clean -y          # HeLab.app on macOS (bundle ID au.edu.anu.he-bec-lab)
```

Pass pyright explicit paths: bare `pyright` also scans `dev/`, `dist/` and `side_projects/`.
`helab/scripts/legacy_plotly/` is excluded from type checks. Windows: if pytest crashes in
cleanup with `WinError 5` on `pytest-current`, give each concurrent run its own
`--basetemp=.ai/temp/pytest-<name>`. Logs: `<app folder>/logs/helab-<pid>.log` (macOS
`~/Library/Caches/HeLab/logs/`, Windows `%LOCALAPPDATA%\HeLab\logs\`; Help › Show log folder).

## Tests and typing (rules)

- **Tests never touch real data** (Tony, 2026-10-20). Conftest sets `HELAB_TEST_SOURCE_GUARD`,
  under which helpers refuse any source path on a mount, share, cloud folder or
  `constants.DEV_POTENTIAL_DATA_PATHS` outside the temp folder and this checkout; the refusal
  fails the test. A test of mounts uses paths that don't exist.
- **Never import helab before pytest has loaded `tests/conftest.py`**: `helab.utils.constants`
  reads the cache, temp and app folder overrides (`HELAB_DIR_*_OVERRIDE`,
  `HELAB_APP_DIR_OVERRIDE`) once at import, and conftest refuses to run otherwise. A script
  that imports helab outside pytest sets those three variables first.
- Never run `-n` without `--reruns` and `--reruns-delay`. **Report every test that needed a
  RERUN**, quoting the summary's "rerun reasons", rather than calling the run clean, and list it
  in known-issues until its cause is found.
- Strict typing everywhere. `tests/test_typing.py` runs mypy (strict and not) and pyright inside
  pytest, so a type error fails the suite.
- Tests named `*.disabled` are skipped on purpose; find out why before reviving one.
- Tests must not create native settings stores (conftest gives each test its own ini through
  `app_settings()`), and must not leave a `QWebEngineView` alive.
- **Done means:** the touched tests and the type checks pass for a small change; the full
  parallel suite plus the three type checks pass before a handoff, a landing or a push, with
  any RERUN reported.
- CI runs the suite on each OS as two jobs, "Tests (1/2)" and "Tests (2/2)" (`--test-group`),
  beside a "Converter backends" job (the converter tests with cython built); read every job.
- Seams, fixtures and harness details (read gates, I/O traces, `store_free`, `no_source_io`,
  offline tests, CI timeouts): [testing](.ai/architecture/testing.md).

## Codebase rules (invariants)

Each rule names the area file with the detail.

**I/O and threads** ([io-and-browsing](.ai/architecture/io-and-browsing.md)):
- The GUI process never touches source folders or the disk cache store. Source-folder and store
  work runs in isolated `helab/io_helper.py` processes (operation modules in `helab/io_ops/`),
  started by `IOService` (`helab/utils/io_service.py`), or in the headless `helab convert`
  process. The GUI has no worker pools besides the one analysis worker thread (`AnalysisRunner`,
  no source I/O) and the short startup log tidy.
- HeLab writes nothing into source folders except the user's `.helab-root` markers and, where
  the user turns it on per folder or asks for it on the command line (Q12.4: a typed command overrides the folder's setting), converted
  `d_txy_helab_<tag>_<N>.txt` (`<tag>` the profile's, Q18.4; temporary name, then rename; Q9.7,
  Q18.6). Never modify raw `d*.txt` or an existing TXY.
- Rendering never reads disk or submits I/O: models, badges, tooltips and summaries read memory
  only (`SnapshotFileSystemModel`).
- Never let the GUI thread wait on cancellation, deadlines or a helper. Queues and concurrency
  stay bounded and requests deduplicated.
- A helper holds its slot **until its exit is confirmed** by the reaper's exit flag; never free
  a slot on message delivery. A retry never runs beside the attempt it replaces.
- Timeouts measure time **without progress** (helpers send heartbeats).
- Files still being written (modified within `SETTLE_SECONDS` = 5 s, dated in the future, or
  changing while read) are never read, cached, fingerprinted or counted in signatures.
- Every automatic status scan goes through `FolderCache.submit`, which honours the scan-failure
  flag; only a fresh successful scan clears it.
- `helab/io_ops/` never imports `helab.io_helper` (it runs as `__main__`). A name tests patch is
  called as `module.name` from other modules, never imported by value (list in the area file).
- Helper events are the typed contract in `helab/io_ops/events.py` (standard library only);
  add a kind there, and `tests/test_helper_events.py` checks both sides.
- The frozen helper entry point in `helab/main.py` (after `freeze_support()`, before the `convert`
  dispatch) runs before imports that start GUI services, caches or Dash.

**The disk cache** ([cache-store](.ai/architecture/cache-store.md),
[data-roots](.ai/architecture/data-roots.md)):
- Only helpers (and `helab convert`, a headless process without the GUI) open the store
  (`DIR_CACHES/store-v3`, `CacheStore`); the GUI sends `store_options()` with each request. A
  read answers found / missing / error, and an error is never "nothing saved".
- Disk caching needs a data root (a hidden `.helab-root` at or above the folder; keys
  `root://<uuid>/<relative>`). Without one the folder is RAM only, with no fallback to path keys.
- Every store write checks the save guard its job took when it started (generations, epochs,
  `job_seq`), so a running save can't bring back removed data or overwrite newer data.
- A table or column added within `store-v3` is added to older stores by `cache_store._migrate`
  on every writable open, never only in `SCHEMA`.
- **HeLab never removes the user's data, cached datasets, records, folder flags, constants or
  presets without asking.** Housekeeping is the exception, and only what is listed here:
  - the sweep deletes retired dataset files, and store files no row names once over an hour old;
  - pending saves and results expire after `PENDING_MAX_AGE` (1 h);
  - startup deletes the old diskcache folders and log files beyond the kept count;
  - session-only lists drop their oldest entries;
  - the RAM budget evicts datasets and releases plots (never closes them);
  - a beside conversion deletes its own leftover temporary TXY in that source folder, names
    matching exactly `io_ops.convert.partial()` (`.d_txy_helab_<tag>_<N>.txt.<16 hex>.partial`),
    regular files over an hour old, never through a link (Q12.7, Q18.6);
  - every conversion with shots to convert deletes, by the same rules, its own leftovers in
    HeLab's `converted-txy/` folder (under the cache or temp folder): `io_ops.convert.own_partial()`.

  Any other removal is the user's choice, asked first, and sends `removed` (Q3.3).
- Read the cache folder with `cache_dir()`, never `DIR_CACHES`: it can move while HeLab runs.
- Every byte size shown is SI (kB/MB/GB, powers of 1000) (Tony, 2026-10-26).

**Settings** ([settings](.ai/architecture/settings.md)): open QSettings only through
`app_settings()` (helpers: `cache_setting.open_settings`). Every key HeLab reads is a row in
`helab/utils/settings_defaults.py`, read through `read_setting`. Read numbers untyped (PyQt's
`type=int` is 32-bit).

**Analysis and plots** ([plots-and-scripts](.ai/architecture/plots-and-scripts.md),
[dld-analyses](.ai/architecture/dld-analyses.md)):
- The script contract (`helab/scripts/base.py`) and the Qt-free analysis modules import no Qt,
  plotting library or `helab.utils.constants` (`PURE` in `tests/test_headless_imports.py`; a new
  `helab/analysis` module is listed there as pure or Qt).
- Datasets share read-only NumPy arrays; analysis code that changes an array calls `.copy()`.
- `compute` runs on the worker thread, `render` and `update` on the GUI thread. A hook that
  raises is logged and HeLab goes on.
- Saved results are NumPy arrays plus JSON (`result_codec`), never a pickle.
- Matplotlib uses `matplotlib.figure.Figure`, never `pyplot`. A PyQtGraph log axis takes
  `PlotDataItem`s. Avoid PyVista and VisPy.
- The DLD port shows T in ms and X/Y in mm with "," grouping whatever the locale; Basic plots v1
  keeps s and m with SI prefixes. Never rotate XY.

**The converter** ([converter](.ai/architecture/converter.md)): `helab/convert/` is Qt-free (its
modules are listed by hand in `PURE`; a new one is added there). Every converter backend gives
`reference`'s output byte for byte (the cases in `tests/data/convert/`, and
`dev/txy/check_samples.py` on the sample set). Fixtures compared byte for byte sit under a
`.gitattributes` `* -text`, or Windows CI's autocrlf rewrites them
([testing](.ai/architecture/testing.md)).

**UI** ([app-runtime-and-ui](.ai/architecture/app-runtime-and-ui.md)): keep Qt's normal
main-window resize and repaint handling (no `setUpdatesEnabled(False)` on the window).
Navigation stays available during I/O. No vertical padding around panel blocks; status rows are
one line, with detail in tooltips.

**Versions and releases** ([release-and-ci](.ai/architecture/release-and-ci.md)):
- `helab/_version.py` is the only version source (PEP 440, no `v`).
- Never generate `_build_info.json` in the source package.
- The version bump goes on the PR branch.
- Never modify a published release or move a tag.

## Code map

| Package / module | What | Detail |
|---|---|---|
| `helab/main.py`, `helab/__main__.py` | entry; frozen helper dispatch first | [release-and-ci](.ai/architecture/release-and-ci.md) |
| `helab/io_helper.py`, `helab/io_ops/` | helper process: browse, scanning, loading, save_held, live, convert (`helab_txy`: HeLab's TXY in loads), icons, markers, admin, results, listings, trace_check; `infra`, `stores`, `fingerprints`, `metadata`, `summary`, `identity`, `events` | [io-and-browsing](.ai/architecture/io-and-browsing.md) |
| `helab/convert_cli.py` | `helab convert --watch` (headless converter) | [converter](.ai/architecture/converter.md) |
| `helab/utils/io_service.py` | `IOService`: lanes, slots, pausing, offline gate | [io-and-browsing](.ai/architecture/io-and-browsing.md) |
| `helab/utils/folder_cache.py` | `FolderCache`: session memory, jobs, RAM budget, presets and results state, store identity | [cache-store](.ai/architecture/cache-store.md) |
| `helab/utils/cache_store.py`, `cache_paths.py`, `data_roots.py`, `cache_move.py` | the store, location keys, markers, cache-folder move | [cache-store](.ai/architecture/cache-store.md), [data-roots](.ai/architecture/data-roots.md) |
| `helab/utils/file_kinds.py` | `FILE_KINDS`: raw `d<N>.txt`, TXY `d_txy_forc<N>.txt`, HeLab's `d_txy_helab_<tag>_<N>.txt` (a new format is a new entry) | [cache-store](.ai/architecture/cache-store.md) |
| `helab/models/SnapshotFileSystemModel.py` | the tree model (memory only) | [app-runtime-and-ui](.ai/architecture/app-runtime-and-ui.md) |
| `helab/views/` | main window, `FolderExplorer` and `explorer_live.py` (Live, auto-convert), `live_launch.py` (one launch folder), Folder details, Settings tabs (`ConverterTab.py`: TXY converter), dialogs | [app-runtime-and-ui](.ai/architecture/app-runtime-and-ui.md), [live](.ai/architecture/live.md), [converter](.ai/architecture/converter.md) |
| `helab/views/plots/` | `PlotWorkspace`, docks, settings panel, presets, arrangements, cached results, each plot's TXY row (`txy_source.py`) | [plots-and-scripts](.ai/architecture/plots-and-scripts.md) |
| `helab/analysis/` | analysis core, mostly Qt-free (`QT` in `tests/test_headless_imports.py` lists the rest): `DatasetView`, runner, parameters, selection, fits and other numerics, presets, result cache | [plots-and-scripts](.ai/architecture/plots-and-scripts.md), [dld-analyses](.ai/architecture/dld-analyses.md) |
| `helab/convert/`, `native/` | the TXY converter (Qt-free): `raw`, `profile`, `reconstruct` and `backends/` (numpy the default; cython ships; reference; rust, numba, mlx for developers only, A9.1), `txy`, `fastio`, `split`, `pipeline`, `provenance`, `user_profiles`, built-in profiles as JSON; harness `samples`, `check`, `timing` (scripts in `dev/txy/`); compiled backends' sources in `native/`; TXY sources' four modes `helab/utils/txy_sources.py` | [converter](.ai/architecture/converter.md) |
| `helab/scripts/standard/`, `helab/scripts/dld/` | Basic plots v1; the DLD Front Panel Port | [plots-and-scripts](.ai/architecture/plots-and-scripts.md), [dld-analyses](.ai/architecture/dld-analyses.md) |
| `helab/utils/settings_store.py`, `settings_defaults.py`, `lab_parameters.py` | settings | [settings](.ai/architecture/settings.md) |
| `helab/utils/app_log.py`, `gui_watchdog.py`, `events.py`, `dash_server.py` | logging, stall dumps, notifications, the Plotly server | [app-runtime-and-ui](.ai/architecture/app-runtime-and-ui.md), [plots-and-scripts](.ai/architecture/plots-and-scripts.md) |
| `tests/conftest.py` | isolation: data guard, private store, settings, folders | [testing](.ai/architecture/testing.md) |
| `.github/workflows/` | CI: 3.13 on macOS, Windows, Ubuntu; compat 3.11/3.12/3.14 on PRs | [release-and-ci](.ai/architecture/release-and-ci.md) |
| `legacy/` | MATLAB references: tdc_autoconverter (submodule); Momentum_Bells_test, DLD_front_panel (cloned by hand, README) | [dld-analyses](.ai/architecture/dld-analyses.md) |
