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

## Building the TXY converter (block 9)

- [x] **A9.1 Remove unused converter backends from the build** (done in `134e2ec`: numpy, cython and the reference ship) (Q9.2): every backend ships while the
  converter is tested; once the default and the optional fast ones are settled, drop the rest
  from `requirements.txt`, the lock and `HeLab.spec`, and note the size saved. Input: the stage 2
  results (`sessions/2026-10-29-claude-txy-bench/results.md`) and Q11.2. Packaging's sizes (macOS app):
  mlx +234 MB (78 zipped), numba+llvmlite +127 (40), rust +0.48, cython +0.27. Dropping numba means
  removing it from the lock (or adding it to `excludes`): once it is in the lock, pandas' and scipy's
  optional imports pack it even without the spec.

## Converter stage 1 (block 10)

From the `agent/txy-reference` handoffs ([builder](sessions/2026-10-29-claude-txy-reference/handoff.md),
[cross-checker](sessions/2026-10-29-claude-txy-reference/crosscheck/handoff.md)); detail in
[converter.md](architecture/converter.md).

- [x] **A10.1 Settle checks, with the evidence** (done in stage 4 core, `5cf4652`, landed `775fb1d`;
  converter.md's settle rules) (stage 4, `agent/txy-helab-core`): 2019-halos d3667
  shows MATLAB converting a raw file 0.25 s after its last write and losing the end of the shot.
  Test the settle check with a synthetic half-written file.
- [x] **A10.2 Backend constraints** (done in the stage 2 landings `d522691`, `32158c2`, `7031bea`,
  `aecbe68`, `ed35099`) (stage 2, every backend floor): all 39 cases and every sample shot,
  including the phantom row, `NoRowsError` and stable NaN-last sorts (`kind="stable"`). A split of
  one shot keeps the global `t_zero`, the first-row skip (first piece only), the whole-file
  `floor(N/4)` preallocation, the 2023 cuts (only at gaps over 20,000 bins, or before splitting)
  and one final stable sort by T; test that a split equals the whole on the `phantom_*` and
  `dead_time_x1` cases.
- [x] **A10.3 Built-in profiles as JSON files** in the package (stage 4, Q6.11), each tested to load
  equal to the Python definitions. Done in `475c6a6` (`agent/txy-ui`).
- [x] **A10.4 Durable HeLab TXY writes** (done in `5cf4652`, landed `775fb1d`; `io_ops/convert.py`)
  (stage 4): use `txy.write_atomic` (new file with mode
  `0o666` under the umask, fsync, rename, folder fsync) for `d_txy_helab_<N>.txy`, which matters
  once they go beside raw files on a share (Q9.7).
- [x] **A10.5 A conversion with no hits writes an empty HeLab TXY** (stage 4; Q10.3, confirmed by
  Tony 2026-10-29). Done in `5cf4652` (converter.md, `pipeline`).

## Converter stage 2 (block 11)

From the backend floors' and the bench's handoffs (`sessions/2026-10-29-claude-txy-*/handoff.md`).

- [x] **A11.1 Packaging the backends** (done in `7cb168e`; since `134e2ec` only numpy, cython and the
  reference ship, Q11.2) (stage 4, `agent/txy-packaging`): build cython and rust in CI on
  all three OSes (MSVC from VS 2022 17.0+, never `/arch:AVX2` with an older toolset; GCC/clang with
  `-ffp-contract=off`; maturin abi3-py311, no `target-cpu=native` for the Sandy Bridge lab PC), make
  their tests required there (a missing extension fails, not skips) and check each built kernel
  equals the reference on `tests/data/convert/`; numba (with llvmlite) in the lock if it ships;
  mlx's GPU tests only where Metal exists (print `mx.metal.is_available()` first); `hiddenimports`
  for every `_MODULES` backend and mlx's `collect_*`.
- [x] **A11.2 In the helper** (done in `5cf4652`, landed `775fb1d`; numba's folder is now under the
  temp folder, Q18.1, `874fd2b`) (stage 4, `agent/txy-helab-core`): `numba_backend.set_cache_folder(<cache_dir()>/numba)`
  before first use, and after a cache-folder move restart helpers that loaded the kernels (or accept
  a stray old folder); a lock in `reconstruct._load`; convert across shots in long-lived processes,
  no within-shot splitting for the fast backends.
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
- [x] **A12.3 Live sends the summary back** (done in `573c86b`, landed `6454b4a`; `folder_cache.py`'s
  `convert` payload) (`agent/txy-live`): every `convert_summary`'s lists as
  `seen`/`done`/`kept`/`skip`, so done shots aren't checked again and unfinished ones aren't read again
  (`seen` is required).
- [x] **A12.4 JSON leftovers in `converted-txy/`** (done in Quick Fixes 5, `2b9435a`): conversions remove their own leftover temporary TXY
  there (over 1 h), but a kill can also leave `.d_txy_helab_<N>.json.<16 hex>.partial` (the record)
  and `.folder.json.<16 hex>.partial`, which stay for good. Harmless and small; widen the own-folder
  pattern to HeLab's own JSON names (Gannet, fix round).

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

## Converter stage 4, packaging (block 16)

- [x] **A16.1 Rust build cache in CI** (moot: rust left CI, A9.1, `134e2ec`): every build job compiles the rust crate from cold (LTO fat,
  `codegen-units = 1`); if CI time matters, `Swatinem/rust-cache@v2` with `workspaces: native/rust`.
- [x] **A16.2 The compatibility jobs** (moot: numba left CI, `134e2ec`) (3.11, 3.12, 3.14, unpinned; PR-only, experimental) also build and
  require cython, rust and numba: watch the first PR run, and make numba conditional there if a
  Python has no wheel.
- [x] **A16.3 `native/build.py`'s `--out`/`--prebuilt`** (dropped in `134e2ec`) are no longer used by any workflow (Puffin): drop
  them, or fix the module docstring that says the test job takes a build job's `--out`.

## Tony's answers on the converter (block 17)

- [x] **A17.1 Warn about raw files with no hits** (Q10.3; done in `62d156e`): the HeLab GUI shows a
  warning for shots whose conversion found no hits (Folder details and the Live line), with the
  shot numbers.
- [x] **A17.2 Two pytest groups per OS in CI** (Q16.2 b; done in `874fd2b`, `ci-test.yml`'s
  `--test-group`): split the test job into two shards on every OS, keeping the typing-tests-first
  ordering (Quick Fixes 6); no limit raised.

## Converter follow-ups (block 18)

- [x] **A18.1 Folder status and HeLab's TXY** (Q14.4): merged into A23.1; the question is Q14.4.

## Caching after the converter (block 19)

**On hold: Tony's go (block 19).** Tony, 2026-10-29: no cache coding until his explicit go, "A19.1
and A19.2 included"; don't start these without it.

- [x] **A19.1 Settings › Cache shows and clears HeLab's TXY in the temp folder too** (audit I4, I6;
  in Q26.2's floor, Q27.5, Tony 2026-10-29): `converted_usage` and `clear_converted` over both places.
  Done on `agent/txy-index` (landed `460360b`).
- **A19.2 Clear converted TXY vs a running conversion** (audit K4; on hold): `clear_converted` takes
  a fence a conversion checks before each write, or the docs say a running conversion may write
  after it.

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

## Byte units by OS (block 26)

- [x] **A26.1 OS-aware byte units** (Q26.1, decided; done on `agent/byte-units`, landed `8bf810f`): `number_format.byte_size(n, kind="disk" |
  "ram")` and `time_format.byte_rate` SI on macOS/Linux, powers of 1024 labelled KiB/MiB/GiB on
  Windows; RAM in GiB everywhere; budget defaults and minimums follow (8 GB / 8 GiB disk, 1 GB /
  1 GiB, RAM 1 GiB); the ~67 calls sorted into disk and RAM; tests for both platforms; AGENTS.md's
  units rule, `cache-store.md` and `settings.md` updated. Not cache code; a floor now, in v0.0.7
  (Tony, 2026-10-29: "do now").

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
- **A30.4 Write skipped `last_used` marks in the background every ~10 min** (Q30.3 (c)): the marks
  `FolderCache` keeps (`txy_unmarked`) go out in one `cache_admin` `mark_used` request about every
  10 minutes while any are owed, respecting Work Offline, lane pausing, quit (the quit flush stays)
  and the cache being off. A short follow-up after `460360b`.
- **A30.5 Settings refuses a temp folder on a network drive or in a synced folder** (Q30.5): the
  cache folder's check (`cache_location.cache_location_problem`) and wording for Settings › General's
  temp folder; an existing such setting kept but warned about once.

## Byte units floor (block 32)

- **A32.1 `result_cache.LARGE_RESULT_BYTES` by OS** (optional): the 50 MB threshold could follow the
  disk unit like the log thresholds, if Tony wants every threshold by OS
  ([handoff](sessions/2026-10-29-claude-byte-units/handoff.md)).

## Provisional UI pass (block 33)

From the [findings](sessions/2026-10-30-claude-ui-provisional-0.0.7/findings.md); in the UI polish
floor (Q33.6).

- [ ] **A33.1** Tab out of a plot setting opens the next row's editor (an empty wide box until the
  next click); Tab should commit and stop, like Return after Smoke ready.
- [ ] **A33.2** Offline, Folder details says "Loaded from cache · not checked yet" beside "checked,
  unchanged"; make the two agree with the summary's "not checked (offline)".
- [ ] **A33.3** Settings › General labels the temp folder "DIR_TEMPS:" (the constant's name); word it
  like the cache folder's row.
- [ ] **A33.4** After a plot floats, the settings panel's Float button floats whichever plot the panel
  names, not the one just floated; make it act on (or show) the right plot.

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

## Not AI work (stays in MANUAL_TODO)

These need a real share, lab hardware or a person in the lab:
- remounts, and two mounts of one folder;
- read-only shares, and mapped-drive spellings on Windows;
- the converter and the lab's MATLAB scripts ignoring `.helab-root`;
- the physics checks on real data: temperatures, condensate fits, g², release time, the QE
  calibration;
- release recovery in a disposable release;
- the self-update questions for ANU IT.
