# AI to-do

This is the ongoing list of work agents may do without asking Tony: docs upkeep, release
preparation, repo hygiene, verification jobs and small fixes already agreed. Any agent may
raise an item. It is one of three living lists shared by every agent:

- [DECISIONS_TODO](DECISIONS_TODO.md): decisions for Tony, `Q` IDs;
- [MANUAL_TODO](MANUAL_TODO.md): checks that need Tony at a screen or the lab, `M` IDs;
- this file: work agents do, `A` IDs.

**IDs** are `<letter><block>.<item>[.<sub>]`. Blocks are listed in [ID_BLOCKS](ID_BLOCKS.md),
and the ID rules are in [DECISIONS_TODO](DECISIONS_TODO.md). Floors and cloud agents propose
`A~1`, `A~2`… in their handoff, and the Coordinator or the Assistant gives them final IDs when
merging.

How to use this list:

- Each item says where it runs (Ground, a floor or CI) and links to its evidence.
- An item that needs a decision first goes to DECISIONS_TODO, and comes back here once Tony has
  answered.
- Features stay in `roadmaps/_readme.md` and bugs in `roadmaps/known-issues.md`; an item here may
  point to them.
- Tick a done item with its commit, and drop ticked items at each release's tidy-up.

The usual rules still apply:

- ask before committing on Ground;
- floors work on their own branches;
- **tests never touch real data**: real-share items only prepare tools and fixtures, and running
  them on the share stays with Tony.

## Carried over from v0.0.6 (block 1)

- **A1.1 Tidy MANUAL_TODO** (Ground, docs only). Tick or merge the items later work replaced:
  the store-v2 / account-independent SMB-key instructions (now Q1.5), and duplicates between the
  v0.0.5a lists and the later ones. Link the smoke pass from each item it covers. Group what's
  left by where it's checked: Mac, lab PC, lab share, real-data physics. Give the older items
  M IDs as they're touched.
- **A1.2 Build the macOS app locally** (Ground). On the release commit, run
  `pyinstaller HeLab.spec --clean -y`, then check:
  - the zip is ~300 MB and holds only `HeLab.app`;
  - launched from outside the checkout, Help › About matches the version, commit and build stamp;
  - helpers run in the packaged app;
  - the SVG triangle and Qt's SVG icon plugin render.

  This is the macOS half of MANUAL_TODO's "native UI and packaged application" and "release
  evidence". The Windows build is checked on the lab PC with the smoke pass.

  Partly done: the smoke pass built the app at `41a6a7d` and its helpers ran
  ([results](sessions/2026-10-28-claude-smoke-mac/results.md)); About showed `0.0.5a1` there,
  before the bump, so the About check on a release commit is left.
- **A1.3 A picture sheet of every plot** (Ground or a floor). Render each Basic plots v1 and DLD
  port plot natively on macOS (not offscreen) in a 560 px dock, from a synthetic dataset in
  Tony's units, into one sheet that Tony can check in one look. It covers how "ms/mm
  everywhere", "titles wrap" and "the ħ glyph" look; behaviour stays in the smoke pass.
- **A1.4 Edge cases with disposable fixtures** (a floor). Under pytest with the real window
  (`HELAB_SHOW_GUI=1` where it helps), check each case and add a test where none exists:
  - a TXY file written halfway, then finished or repaired;
  - tabs switched and closed during shared listings and loads;
  - cancel and retry during I/O, never beside a helper that is still stopping;
  - a source folder removed mid-load.

  Most of these already have offscreen tests, so first list which ones.
- **A1.6 Hover-menu timing tests** (CI watch). Read each release CI run's logs for hover-menu
  reruns (≈200 ms slack). One that reproduces goes to known-issues with its logs.

### After the smoke pass

- **A1.7 Summarise Tony's I/O trace**, if he recorded one. Run
  `.ai/sessions/2026-10-19-claude-smb-io-audit/trace_summary.py <folder> --under <share> --minutes`.
  Expect:
  - no `roots_verify` bursts;
  - about 0 ops/min while idle;
  - one `load: shot time` per raw file of an uncached load, and none on a cached reload.

  Compare it with the 2026-10-19 audit (`compare_traces.py`). This covers MANUAL_TODO's trace
  items (Live, the DLD port's D7).
- **A1.8 Carry the results into the docs.**
  - Tick the MANUAL_TODO items the [smoke pass](MANUAL_TODO.md#release-smoke-pass) covered.
  - Move the problems it found to known-issues.
  - Move Tony's decisions into the roadmap and `.ai/memory/results/`.

  Partly done: the problems are in known-issues. Left: ticking or marking Mac-passed the
  MANUAL_TODO items the pass overlaps (Presets, Work Offline, Saved results).

## From the audit (block 2)

Finding numbers (#N) refer to the [audit](sessions/2026-10-28-claude-v0.0.6-checks/audit.md).

- **A2.1 Docs refresh** (Ground, docs only, one commit). Bring the docs up to date with what has
  landed, and in line with Tony's decisions where they contradict them:
  - the roadmap and plans' status lines (#8);
  - documents that contradict his decisions (#9, #10);
  - stale memory (#11), known-issues (#12), MANUAL_TODO (#13) and the README (#14);
  - handoff follow-ups that were never carried over, into known-issues, `refactoring.md` and the
    DLD plan (#16);
  - the Maestri note's decisions into `_readme.md`, and the "v0.0.6 changes" note (#7).
- **A2.2 Small app fixes** (a Quick Fixes floor, now that v0.0.6a1 is out):
  - set werkzeug's logger to WARNING (#20);
  - write the watchdog's stall stacks into the log (#19);
  - name the cause in "Disk cache unavailable" (#21);
  - retire the old `diskcache.*` settings keys (#22);
  - lower the back button's log line to DEBUG (#22).
- **A2.3 Idle CPU** (with A2.2): find what repaints at ~35 % CPU in an idle window (#18).
- **A2.4 Unclosed SQLite connections in tests** (with A2.2): run with `-W error::ResourceWarning`
  and tracemalloc to find what opens them (#23). They may explain the Windows file-lock
  failures.

## From the planning-docs audit (block 7)

Finding numbers refer to the [planning-docs audit](sessions/2026-10-28-claude-docs-audit/planning.md).

- **A7.1 Check Dependabot's graph run** (CI watch, from Q6.4). Once v0.0.7 is on `main`, check
  that Dependabot's dependency-graph run passes (no "not our ref" on the submodules) and that
  `dependency-graph.yml`'s snapshot of `requirements.lock` shows in the graph (#7).
- **A7.2 Refresh the lock with `--upgrade`** (a floor or Ground, its own CI run; Q1.9 item 6,
  #8). It brings python-dateutil 3.0 (the lock pins 2.9.0.post0); follow the README's
  "Updating dependencies", then the full suite and the three type checks.

## From the docs and Maestri audit (block 8)

- **A8.1 Call `folder_cache.store_options()` in `HelabMainWindow`** (architecture audit #6).
  `helab/views/HelabMainWindow.py` imports `store_options` by value and
  `tests/test_helabMainWindow.py` patches only `helab.utils.folder_cache.store_options`; once it
  is called as `folder_cache.store_options()`, drop the exception from `io-and-browsing.md`.

## Converter stage 2 (block 11)

From the backend floors' and the bench's handoffs (`sessions/2026-10-29-claude-txy-*/handoff.md`).

- **A11.3 A conftest-wide numba cache fixture**: a session-scoped autouse fixture calling
  `numba_backend.set_cache_folder(<session temp>/numba-cache)`, replacing the numba tests' own (which
  would raise if another file's in-process numba test loaded the kernels first on a worker).
- **A11.4 Faster text I/O** (optional, after stage 4): reading (~560 MB/s) and writing (~340 MB/s)
  are 80-83 % of a compiled conversion and hold the GIL. The rust floor's `parse_strict` (1,910 MB/s)
  and `format_txy` (596 MB/s) are byte-identical on all samples (report only today); wired in behind
  the same checks they'd take rust to ~300 MB/s per core and let threads scale. A vectorised exact
  `%.8g` in NumPy was ~1.5x slower per value than `%` (not worth it while conversions run in processes).

## Converter stage 4, HeLab core (block 12)

- **A12.1 Workers in a frozen app** (`agent/txy-packaging`): run a `convert` with `workers` 2 (spawned
  through `freeze_support`) in the built app on all three OSes; if it works, make `DEFAULT_WORKERS`
  the same as from source (1 frozen today).
- **A12.2 `HeLab.exe convert` on Windows** (`agent/txy-packaging`): the windowed exe has no console;
  check where its output goes, and consider a console launcher (`HeLab-convert.exe`) if the
  acquisition PC needs one.

## Quick Fixes 4 (block 13)

- **A13.1 Helpers start with an explicit working folder** (or, under `SOURCE_GUARD`, the working
  folder leaves the guard's denied list), so a test that `chdir`s can't make a helper's source access
  fail (known-issues, Tests and CI). From Quick Fixes 4's A~2 and Plover's review.

## Converter stage 4, UI and Live (blocks 14, 15)

- **A14.1 An end-to-end GUI test of a plot switching TXY sources** on a folder with real helpers
  (convert, load, Live): the plot's TXY row is checked by unit tests and offscreen rendering only.
- **A14.2 A pending Reload's flag on a source change** (Egret, round 3): `instance.py`'s
  `_reload_from_source` isn't cleared when `set_txy_source` changes the source while a Reload's load
  is pending, so the released picture can stay "loading its TXY source…" until the next run. Reset
  the flag (and the released state) in `set_txy_source`.
- **A15.1 Pace conversions on large shares**: each conversion lists the folder and stats its raw
  files every `live_interval` while auto-convert is on; if M15.1 shows it costs, convert only after a
  Live listing found new names.
- **A15.2 `PresetFolder` and empty folders**: check whether `PresetFolder.check` starts Live twice on
  a folder with no shots yet, as `LaunchFolder` did; same fix if so.
- **A15.3 `test_live.run_helper` sends every field `io_helper` does** (`txy`, `memory_origins`,
  `helab_since`, `listed_mtime`, `seen_names`, `identity_root`), so Live tests elsewhere exercise
  what the helper runs (`test_live_convert.py` already does).

## Caching after the converter (block 19)

Tony's go came on 2026-10-31 (Q28.1), on the Caching v2 floor.

- [x] **A19.2 Clear converted TXY vs a running conversion** (audit K4; done in `ce8eae7` and S0-1's fix,
  Caching v2 stage 0, landed `ad86bd3`): `clear_converted` takes a fence a conversion checks before each
  write, or the docs say a running conversion may write after it.

## Quick Fixes 6 (block 20)

- **A20.1 Correct the slow-first hook's comment** (`tests/conftest.py` ~205-209, and the floor's notes):
  workers never see the command line's `--dist` (xdist sets `dist = 'no'` on every worker), so the
  `spread` check is always true under xdist; drop it and fix the comment. Harmless today (Tern).

## TXY ship (block 21)

- **A21.1 Two stale backend strings** (not the ship floor's paths): `helab/convert/backends/numba_backend.py`'s
  docstring says the helper passes a cache folder under `cache_dir()` (now the temp folder, Q18.1);
  `helab/convert/backends/rust.py` (~:7, :80) says "build it with `maturin develop --release`", now
  `python native/build.py --only rust`.
- **A21.2 Developer venvs keep the unshipped packages**: `uv pip install -r requirements.lock` never
  removes numba, llvmlite, mlx, mlx-metal or maturin from Ground's or floors' venvs (harmless: builds
  exclude them, tests run where installed); `uv pip sync requirements.lock` then `uv pip install -e .`
  gives the shipped set. Say so in the README's "updating dependencies" if worth it.

## Store-v4 planning (block 22)

- **A22.1 Shot axes when numbers skip** (Q22.5): the TDC may skip shot numbers on pause/resume.
  Shot trends already plots against shot number or shot time (`shot_trends.py` `X_AXIS`); add a
  "shot index" (consecutive, gaps removed) and offer the same three axes in every per-shot plot.

## Converter follow-ups (block 23)

- **A23.1 Count HeLab's TXY of the tab's tag in folder status** (also A18.1). Waits for Q14.4.
- **A23.2 Colour only the no-hit part of the Live line** if `ElidedLabel` learns rich text (Q23.5).
- **A23.3 Remove the `live_launch_folders` row and its migration** a release or two after v0.0.7.

## Docs audit 2 (block 24)

- **A24.1 Enforce `helab/convert/` as Qt-free** (architecture audit 2, #6): extend
  `tests/test_headless_imports.py` to walk `helab.convert` (`pkgutil.walk_packages`) with
  `backends.numba_kernels` as optional only, so a converter module that imports Qt or
  `helab.utils.constants` fails CI; then `converter.md` and AGENTS.md can say it is enforced.

## Converted-TXY index (block 30)

From the TXY Index floor's [handoff](sessions/2026-10-29-claude-txy-index/handoff.md) (landed `460360b`).

- **A30.1 `events.ShotKeptEvent`'s docstring** still says "no local provenance record": reword to "a
  beside TXY that isn't current (older than its raw file) or written by another conversion meanwhile".
- **A30.2 `helab_txy.converted_usage` at scale**: it still lists each hash folder (names only; `stat`
  only for files the index doesn't know). If `converted-txy/` grows to tens of thousands of TXY,
  measure by the index alone and list folders only on Clear.
- **A30.3 One index connection per `helab convert` run** (not urgent; no starvation seen outside the
  test): `--watch` reopens the index each pass and the app's helper once per request. Keeping
  `helab convert`'s connection for its whole run (reopening after `IndexUnavailable` or a set-aside)
  stops the `-wal` being rebuilt between them; it doesn't make SQLite's lock fair. Cost (Tern): on
  Windows a long-held connection blocks the app helper's set-aside of a damaged index, so the app's
  conversions fail until `helab convert` reopens.
- **A30.5 Settings refuses a temp folder on a network drive or in a synced folder** (Q30.5): the
  cache folder's check (`cache_location.cache_location_problem`) and wording for Settings › General's
  temp folder; an existing such setting kept but warned about once.

## Byte units floor (block 32)

- **A32.1 `result_cache.LARGE_RESULT_BYTES` by OS** (optional): the 50 MB threshold could follow the
  disk unit like the log thresholds, if Tony wants every threshold by OS
  ([handoff](sessions/2026-10-29-claude-byte-units/handoff.md)).

## Smoke ready (block 34)

From the Smoke ready floor's [handoff](sessions/2026-10-30-claude-smoke-ready/handoff.md) (landed `4ad8ac5`).

- **A34.1 Screenshots of QtWebEngine panes on the lab PCs** paint black on screen and so in the grab
  ([memory](memory/results/lab-pc-qtwebengine-black-render.md)); the plot's HTML export covers them.
  No workaround built; the 3D scatter's OpenGL fallback view wasn't grabbed (M34.2).
- **A34.2 A test guard for Qt-made senders**: fail on `X.<signal>.connect(lambda …)` whose lambda
  refers to `X` where `X` comes from `findChildren`/`findChild`/`tabBar()`/`widgetForAction` (Wren's
  AST scan finds 14 such connections, all safe today). It backs AGENTS.md's rule; a sender reached
  through another name would escape it.

## Runner tools (block 35)

From the Runner Tools floor's [handoff](sessions/2026-10-30-claude-runner-tools/handoff.md) (landed `0316bae`).

- **A35.1 A `dev/` wait helper for runners** (`wait_milestone.py EVENT [key=value …] --log <file>
  --timeout S`, built on `app_log.parse_milestone`), if the runbook's waits want more than `grep`.
- **A35.2 `--geometry` through the dev stub**: `open …/HeLab-dev.app --args --geometry …` (Smoke ready
  has landed it); check once.

## UI polish (block 36)

From the UI polish floor's [handoff](sessions/2026-10-30-claude-ui-polish/handoff.md) and Ibis's
[review](sessions/2026-10-30-claude-ui-polish/review.md) (landed `c104502`). Its A~1, the Plotly SIGSEGV fix,
was done on the floor.

- **A36.1** `read_settle_seconds` could move from `SettingsDialog.py` to `constants.py`, beside
  `read_live_interval`.
- **A36.2** `events.ShotUnconvertibleEvent`'s docstring could name the path-too-long message among the
  "failed" reasons.
- **A36.3** (Ibis R3-1) `helab/analysis/panes.py` `update_figure` after `release_figure()` could put a
  released figure back on the Dash server; nothing calls it so today. A guard (ignore, or log) would close it.
- **A36.4** (Ibis R3-2) `tests/test_main_split.py` would accept a settings panel collapsed to zero width;
  check `0 < right` too.

## Live tests on the test data (block 37)

From the Assistant's Live tests on HeLab's test data (`tests/test_live_testdata.py`, 2026-10-31).

- **A37.1** (Q37.1; v0.0.8, Tony 2026-10-31) Say when a raw file's reading stops early: the parser (`helab/convert/raw.py`, both
  `fastio.parse_strict` and `_parse_textscan`) reports the line where an unreadable token ended it, the
  conversion keeps MATLAB's TXY byte for byte and adds the stop to its event (a `shot_converted` field, or
  a warning kind in `helab/io_ops/events.py`), and the Live line, Folder details and `helab convert` name
  it ("read stopped at line N"). `test_damaged_files_during_live_are_said_once_and_the_run_goes_on` then
  checks the flag.

## Quick Fixes 7 (block 38)

From Quick Fixes 7's [handoff](sessions/2026-10-31-claude-quick-fixes-7/handoff.md) (Rivet on Ground, Codex's
review of PR #10, six rounds).

- **A38.1** Audit `helab/io_ops/live.py`'s matching paths for the two gaps Codex found in `save_held`: no
  test for a held HeLab shot whose TXY has gone, nor for a shadowed MATLAB TXY that has settled. Its
  `file_names`/signature shapes are the same, so the same two holes may be there.
- **A38.2** (display only) `AutoConvert.damaged` in `helab/views/explorer_live.py` keeps a file counted
  "damaged" while it stays unconvertible, even when a later profile fails it for another reason; on a new
  summary it could keep only names whose current message starts with `DAMAGED_TEXT`.

## The release check and Tony's answers (block 39)

- [x] **A39.1 Check release archives on PR builds** (done in `c201c01`, Quick Fixes 8; `release_draft
  --check` on every 3.13 build, passed on all three in its CI runs) (CI; Ground or a floor): `main`'s
  release job is the only place `release_draft --validate-only` runs, so 0.0.7a1's linked macOS build
  stamp showed only after the
  merge (run 41110274554; [known issues](../roadmaps/known-issues.md#fixed)). Run the archive check (the
  stamps, without the tag and the draft) on each PR's three builds against its build commit, so a
  packaging change that breaks it fails the PR.

- [x] **A39.2 Live takes HeLab's TXY for a shot held from MATLAB's** (done in `10a9c3c`, `f945f69`, IO
  Fixes, landed `471966b`) (Q38.2, Tony 2026-10-31; the I/O area):
  under HeLab priority, a HeLab TXY converted during Live replaces the shot held from MATLAB's TXY,
  read again as a changed shot (as a HeLab-held shot converted again is), instead of waiting for the
  folder's next load (`fefe6ab`).

- [x] **A39.3 One running HeLab per computer** (done in `0335768`, `f128623`, Quick Fixes 8; what only
  served several at once is listed in its [handoff](sessions/2026-10-31-claude-quick-fixes-8/handoff.md),
  not removed: A43.2, Q43.4) (Q39.1, Tony 2026-10-31): a second HeLab (source or build)
  started while one runs says so and stops before opening anything; the lock in the app folder, so an
  override (agents, tests) has its own. Then drop what only served several at once where the area
  review names it (`.ai/sessions/2026-10-31-claude-area-review/cache.md`).

- [x] **A39.4 Folder details: TXY left out and TXY per converter** (done in `915aff5`, Quick Fixes 8) (Q38.3, Tony 2026-10-31): the load line says
  "N left out (TXY source)" for shots the folder's TXY source leaves out (a `load_counts` key and
  `FolderExplorer.load_count_details`, `924109a`), keeping "removed" for files really gone; and a line with
  the folder's TXY counts by kind, from the listing's names only (memory, no I/O): MATLAB's
  `d_txy_forc` and each HeLab tag's `d_txy_helab_<tag>_` (e.g. "TXY: 120 MATLAB · 118 p19v1"; detail in
  the tooltip).

- **A39.5 TXY and shares** (Q39.2, Tony 2026-10-31; the converter and I/O areas): writing TXY beside the
  raw files on a share (`helab/utils/cache_location.py` and the data roots' share detection) warns once
  per folder that conversion belongs on the machine that owns the data, the user confirming: the folder's
  beside setting, `helab convert --output beside`, and Live's auto-convert. A share folder with no TXY of
  any kind offers in Folder details to convert into HeLab's cache (recommended) or temp folder, says the
  converter should run on the acquisition PC, and keeps "Convert beside on the share…" behind the warning.

## I/O fixes (block 40)

From the IO Fixes floor's [handoff](sessions/2026-10-31-claude-io-fixes/handoff.md) (Conduit; landed `471966b`).

- **A40.1 A helper still starting when HeLab quits** (no `process` yet in `IOService._run`) is stopped
  only by `_run`'s daemon thread, so it may run until its first stdout write fails. Low risk. Fix: `_run`
  checks `self.closed` right after `Popen` and kills.
- **A40.2 An unreadable new HeLab TXY in `live_check`**: a switched or HeLab-held shot whose new HeLab TXY
  turns out unreadable drops the held data and keeps the shot known-unreadable (as for a HeLab-held shot
  converted again). Unlikely (temporary name and rename); keeping the held data until a readable TXY is
  read would be safer (Probe agrees: a fresh load would take the same file).
- **A40.3 A signature-only change rewrites the whole dataset** (io-5; the cache area, best with caching
  v2's store work): every cached shot is unpacked and packed again, though no TXY is read.
  `CacheStore.confirm_dataset(..., signature=None)` merging a given signature into `info` (JSON, no schema
  change), and a confirm branch in `loading.load` for a cache whole but for the signature, would need
  neither the dataset nor a rewrite.
- **A40.4 Cancel all loads and scans' tip** (Q40.1): set `MissingShotsWindow.CANCEL_TIP` to "Cancel every
  load and scan, running, paused or queued. Browsing, cached data, saves and Live go on; loads already
  saving their cached data finish."

## Plot identity (block 41)

From the Plot Identity floor's [handoff](sessions/2026-10-31-claude-plot-identity/handoff.md) (Prism; landed
`e3f94d9`).

- **A41.1 An outdated saved result has no view**: `AnalysisInstance._cached_found` shows it without one.
  If Release or the TXY row ever needs that result's own data, build a hollow view from the saved record
  (coverage and origins). Not needed now.

## Caching v2 (block 42)

From the Caching v2 floor's [handoff](sessions/2026-10-31-claude-caching-v2/handoff.md) (Vault; stage 0 and
checkpoint 2 landed `ad86bd3`). The floor's own remaining steps (5–7, and what step 5 owes) are in its
handoff and the [plan](../roadmaps/caching-v2.md#stages-each-needs-tonys-go).

- **A42.1 store-v3's saved results under Keep**: copy a v3 result into v4 when it is used (the addendum
  said "by the next save of that folder's results"), or decide read-through is enough while v3 is kept
  (built: read-through only).
- **A42.2 `trim` in Make room's order**: a lowered budget in store-v4 removes datasets only; give it Make
  room's order (datasets, raw layers seen, only copies named).

## Quick Fixes 8 (block 43)

From Quick Fixes 8's [handoff](sessions/2026-10-31-claude-quick-fixes-8/handoff.md) (Rivet on Ground).

- **A43.1 Toolbar icons in every test window**: without `IconsInitUtil.initialise_icons()` the side
  toolbars show their text, so a `HelabMainWindow`'s widths depend on which tests ran earlier on the xdist
  worker (the cause of `test_main_split`'s Windows failures). A conftest autouse fixture would remove it
  everywhere; it must take pytest-qt's `qapp` (icons before a `QApplication` abort the worker, `1f86ca2`).
- **A43.2 "Another HeLab may have changed them"** before `read_presets()` (`PresetsInspector.py:207`,
  `views/plots/presets.py:267`, `:613`): with one app per computer (Q39.1) and `helab convert` writing no
  presets, keep the cheap re-reads and drop that reason from the comments.

## Not AI work (stays in MANUAL_TODO)

These need a real share, lab hardware or a person in the lab:
- remounts, and two mounts of one folder;
- read-only shares, and mapped-drive spellings on Windows;
- the converter and the lab's MATLAB scripts ignoring `.helab-root`;
- the physics checks on real data: temperatures, condensate fits, g², release time, the QE
  calibration;
- release recovery in a disposable release;
- the self-update questions for ANU IT.
