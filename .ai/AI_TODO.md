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

## Quick Fixes 7 (block 38)

From Quick Fixes 7's [handoff](sessions/2026-10-31-claude-quick-fixes-7/handoff.md) (Rivet on Ground, Codex's
review of PR #10, six rounds).

- **A38.1** Audit `helab/io_ops/live.py`'s matching paths for the two gaps Codex found in `save_held`: no
  test for a held HeLab shot whose TXY has gone, nor for a shadowed MATLAB TXY that has settled. Its
  `file_names`/signature shapes are the same, so the same two holes may be there.
- **A38.2** (display only) `AutoConvert.damaged` in `helab/views/explorer_live.py` keeps a file counted
  "damaged" while it stays unconvertible, even when a later profile fails it for another reason; on a new
  summary it could keep only names whose current message starts with `DAMAGED_TEXT`.

## Plot identity (block 41)

From the Plot Identity floor's [handoff](sessions/2026-10-31-claude-plot-identity/handoff.md) (Prism; landed
`e3f94d9`).

- **A41.1 An outdated saved result has no view**: `AnalysisInstance._cached_found` shows it without one.
  If Release or the TXY row ever needs that result's own data, build a hollow view from the saved record
  (coverage and origins). Not needed now: open until Release or the TXY row needs it (Quick Fixes 9
  found no defect, 2026-11-02).

## Quick Fixes 9 (block 46)

- **A46.2 A runtime check for a nameless `QApplication`** (Quick Fixes 9's A~6, optional; after the Plotly worker
  deaths, `b0eb914`): a conftest check that fails a test whose worker's `QApplication` was made with an empty
  argument list (`QCoreApplication.arguments()` empty at the first `qapp`), for code `tests/test_qt_application.py`'s
  AST guard can't see. The guard covers the code today.

## Converter UX (block 48)

From the Converter UX floor's [handoff](sessions/2026-11-02-claude-converter-ux/handoff.md) (Ember; Strata's
[review](sessions/2026-11-02-claude-converter-ux/review.md); landed `ed7bcf9`). A37.1, A39.5 and Q38.1's build
are done.

- **A48.1 Live's test loads without `txy`**: `tests/test_live.py`'s `run_helper` passes a load no `txy` (nor
  `memory_origins`), so its loads never find HeLab's TXY. Give it the fields `io_helper` passes (as
  `test_live_convert.check` does for Live checks) and drop `test_explorer_convert.load_as_the_helper_does`.
- **A48.2 The converter's questions in the accessible-names walk**: add `convert_offer`, `live_share`,
  `beside_refused` and `share_beside_confirm` to `test_accessible_names.ASKS` or `INLINE_SKIPPED` (their IDs
  are checked in `test_explorer_convert.py` only).
- **A48.3 Keep a read stopped early**: the stop is kept only in Live's session and the logs. Record it in the
  provenance row (a column within schema 1), so Folder details can name it for a folder loaded later; the
  same row could tell `ExplorerConverter.offered` that HeLab's TXY already exist in the cache or temp folder
  for a folder not loaded (Strata's info note).
- **A48.4 The output setting's tooltip**: Settings › TXY converter's output tooltip (`ConverterTab.py`) could
  say that a folder on a share asks before writing beside.

## Live Scripts (block 49)

From the Live Scripts floor's [handoff](sessions/2026-11-02-claude-live-scripts/handoff.md) (Lumen; design
[note](sessions/2026-11-02-claude-live-scripts/design.md); Prismo's [review](sessions/2026-11-02-claude-live-scripts/review.md);
landed `971f4af`). A47.5 is done.

- **A49.1 A TXY choice in the Presets row's changes**: the row's dots and "Save N changes" don't count a TXY
  choice changed from the applied preset.
- **A49.2 Same-named helpers in two script folders** share the first one imported (Python's one module
  namespace): detect it and name it in the Scripts panel's error list.
- **A49.3 The presets inspector and TXY profiles**: `PresetsInspector` calls `check_plot` without `profiles`,
  so it doesn't name a preset's unknown TXY profile; pass `{name: file_tag(p)}` from
  `txy_source.known_profiles()`.
- **A49.4 The reopen setting's description**: `reopen_plots_at_start`'s row could name the TXY rule ("a plot
  with its own TXY choice loads it only once HeLab read its folder this session").
- **A49.5 The loading marker's two loose ends** (Prismo's optional notes, re-check 2): test `deliberate=False`
  end to end through `_check_changes` (today only by calling `reload_scripts(…, deliberate=False)`), and reset
  `_pending_deliberate` in `_stop_waiting` when nothing is pending, so a removed folder's waiting deliberate
  reload doesn't make the next auto-reload clear a marker. Both harmless today.

## Live Scripts' follow-ups (block 52)

From the follow-up sessions on the Live Scripts floor (Lumen; Prismo's reviews): the reload-wait race (the Live
Scripts [handoff](sessions/2026-11-02-claude-live-scripts/handoff.md), landed `f534ede`), the
[plot crash](sessions/2026-11-03-claude-plot-library-crash/handoff.md) (landed `823589a`) and the
[preset hang](sessions/2026-11-03-claude-preset-modal-hang/handoff.md) (landed `566eed6`). All test-side.

- **A52.1 Test-made Scripts panels get a Qt parent** (the plot crash's A~2, Prismo's
  [assessment](sessions/2026-11-03-claude-plot-library-crash/review-crash.md)): about 45 test sites make
  `TreePanelWidget(...)` without one (17 in `test_analysis_gui`, 16 in `test_live_scripts`, 4 in
  `test_constant_layers`, the rest in 6 files); give them `TreePanelWidget(window.plots, window)`, the `plot()`
  helpers that drop the panel first. None crashes under forced collections today ([testing](architecture/testing.md)'s
  rule).
- **A52.2 The plot crash's two optional notes** (Prismo's N1, N2): say in the guard test's docstring and at
  `workspace.py`'s two `setParent(None)` sites that the replaced widget is Python's until the `deleteLater()`
  right after hands it back to Qt, and optionally guard `replace_plot_content` too (the RAM budget's release
  picture); make `test_a_dropped_scripts_panel_survives_a_collection_in_its_first_polish` assert its inner run's
  "3 passed", not only exit 0.
- **A52.3 A shared "wait for owed writes, then restart" test helper** (the preset hang's A~1, Prismo's N3):
  other tests that simulate a restart (shut the helpers down) should wait for owed preset writes as
  `test_presets_plots.stored()` now does. Its private reads (`_presets_again`, `_probe_owner`) could later become a
  public `FolderCache.presets_idle()` (an app change).
- **A52.4 Guard the presets' other modals** (the preset hang's A~2): `presets.ask_name` (`QInputDialog`),
  `presets.replace_or_add` and `presets.confirm` (`QMessageBox`, `exec`) open real dialogs unless a test stubs them
  (per instance today, `presets_for`). Make them fail in conftest as `warning_box` does, after checking every test
  that reaches them stubs them; or, broader, a conftest guard on `QMessageBox.exec` / `QDialog.exec` that fails
  unless a test allows it.

## TXY priority lists (block 55)

From the TXY Priority floor's [handoff](sessions/2026-11-03-claude-txy-priority/handoff.md) (design
[note](sessions/2026-11-03-claude-txy-priority/design.md); [review](sessions/2026-11-03-claude-txy-priority/review.md),
TP-1–TP-11 fixed on the floor; landed `9bf99ff`).

- **A55.1 A widget test of Live's offer**: the Live line's "not read here: convert with m23v1?" and the menu's
  "Convert with m23v1 (this folder reads m23v1 only)" have only FolderCache-level tests
  (`test_a_one_entry_folder_offers_its_profile_to_auto_convert`); add one in `test_live_convert.py`'s style.
- **A55.2 Retire the old composition**: `txy_sources.choose`, `helab_txy.compose` and `could_take` are kept for
  their tests and for MATLAB only (`compose(source, matlab, {})`); they can go once their tests move to
  `compose_list`.
- **A55.3 Time the any-HeLab stage**: the fallback's last stage reads provenance records of every tag in HeLab's
  folders for the shots no earlier stage has, so a large folder converted with several profiles reads more rows
  than before. Time it on a lab folder with M55.4.
- **A55.4 A manual convert beside Live's**: Convert this folder… is disabled while Live's Auto-convert converts
  that folder (TP-5). A manual convert with another profile could queue after Live's conversion instead; that
  needs FolderCache's convert jobs keyed by profile.

## Documentation follow-ups (block 56)

From the Docs floor's [handoff](sessions/2026-11-03-claude-docs-manual/handoff.md) (reviews D-1–D-3 and DM-1–DM-4
fixed on the floor; landed `b0e3aac`). Each runs on a floor or Ground; the manual's pages are public text, naming no
person, lab machine or internal ID.

- **A56.2 `dataset_view.py`'s module docstring, public-safe**: it names Q6.6, plots-1 and plots-3, and
  `root_key`'s docstring names a person and a review finding. Then `docs/reference/api/dataset-view.md` may render
  the module instead of naming its classes one by one.
- **A56.3 `docs/.ai-generated/`**: three old planning files in the public `docs/` folder (MkDocs skips dot-folders,
  so the site doesn't show them). Move them to `.ai/sessions/` or delete them. **Stays** (Tony, 2026-11-04, Quick
  Fixes 10's brief: leave `docs/.ai-generated/` where it is).
- [x] **A56.4 The built-in profiles' notes** (done in `0dc4f90`, the five texts approved by Tony 2026-11-04; the
  profiles list's TXY tags in aligned columns, which he asked for then, in `6722408`; Quick Fixes 10, landed
  `20dd672`) shown in Settings › TXY converter carry internal IDs ("stage 3", "Q6.11"): make them user-facing text.
- **A56.5 Stale docs found while writing the manual** (on hold until Tony has tried v0.0.8; Tony, 2026-11-04): `data-roots.md`, `cache-store.md` and `live.md` were
  corrected in the landing's docs pass; left: the comment above `STORE_V4_SETTING` in
  `helab/utils/settings_defaults.py` still says "off until stage 2", while its row is on from v0.0.8.
- **A56.6 Grow `ruff.toml`'s scope** to the rest of what scripts import (`follow.py`, `backends.py`'s panes,
  `stats.py`), each with an API page.
- [x] **A56.7 `helab --help` starts the GUI** (done in `5a4d863`, Quick Fixes 10, landed `20dd672`): `helab/main.py` handles `--version`, `convert` and `cache` before the
  GUI, but not `--help`/`-h`. Print a short usage (the app, `--version`, `--geometry`, `convert`, `cache`, each
  with `--help`) and exit 0, before anything starts.
- **A56.8 The manual's "Which TXY HeLab reads" section** (now a short note): the ordered TXY list (Settings › TXY
  converter › Edit…, a folder's and a plot's own lists, the fallback shots and how a plot's record names them),
  and the External label.

## Test isolation follow-ups (block 57; [handoff](sessions/2026-11-03-claude-fixed-mount-seam/handoff.md))

- [ ] **A57.1 CachedRuns' verification timer outlives a closed plot.** In 41587336570's leaked plots,
  `CachedRuns._verification_due` reached `AnalysisInstance._cached_status` on a deleted QLabel (a plot closed
  while its save waited for the volume check), and `AnalysisInstance.close` raised `'AnalysisRunner' object has
  no attribute 'results'` after its test's runner was released. Both are logged and HeLab goes on. Fix: stop
  `_verify_timer` and drop the plot's callbacks when it closes (or check `sip.isdeleted`), and let `close` skip a
  runner that is gone; a test for each.
- [ ] **A57.2 Windows tests with `--basetemp` on another drive than TEMP's.** conftest's
  `HELAB_TEST_LOCAL_MOUNT` lists only TEMP's drive, so a `--basetemp=.ai/temp/pytest-<name>` on `D:` has no mount
  in the tests' list. Check whether those tests then run as on CI; if not, let it list several drives.
- [ ] **A57.3 An inherited `HELAB_TEST_FIXED_MOUNT`** (Sieve's FM-4, Info): conftest appends to a value set in
  the shell or by a parent process, so that mount stays trusted for the run. Clear it at import before naming
  the temp folder's mount.

## v0.0.8 follow-ups (block 58)

From the Follow-ups floor's [handoff](sessions/2026-11-03-claude-followups/handoff.md) (Mend; Assay's review FU-1,
FU-2 and FU-4 fixed on the floor, FU-3 decided as Q58.3; landed `72ab47a`). Q48.2, Q48.3, Q49.3 (b), Q56.3 and
Q56.1 (b)'s shim are done.

- **A58.1 Zensical, later** (Q56.1 (b), Tony 2026-11-03). Move the manual from Material for MkDocs to Zensical
  once Zensical's versioning is native or mike's Zensical fork is on PyPI, before Material's end of life
  (2027-05-05). The switch needs:
  1. the version menu: native versioning, or the fork (`git+https://github.com/squidfunk/mike.git`, pinned by
     commit in `requirements-docs.lock`), first proven in a CI dry run; `docs/publish/site_versions.py` only calls
     `mike deploy`, `set-default` and `list`;
  2. `docs/hooks/repo_links.py` doesn't run under Zensical: use its built-in `macros` with `{{ config.repo_url }}`
     in the two pages that use `{repo_url}` (checked: a fork's URL comes out right);
  3. `zensical build` has no `-d`: set `site_dir: !ENV [HELAB_DOCS_SITE_DIR, site]` and the variable in CI; keep
     `mkdocs.yml` (Zensical reads it, and `!ENV` needs YAML);
  4. `ci-build.yml`'s manual step (`mkdocs build --strict -d build/manual`), the Docs job and `docs-site.yml` move
     to `zensical build --strict`;
  5. the vendored search shim: Zensical takes the same `extra.polyfills` entry (checked offline).

  Also: Zensical doesn't warn about pages missing from `nav`. The check is the floor's
  [zensical.md](sessions/2026-11-03-claude-followups/zensical.md).
- [x] **A58.2 Folder details' conversion and a read stopped early** (done in `6b22d8d`, Quick Fixes 10, landed
  `20dd672`; the Convert row's amber is A60.1): `explorer_convert.ExplorerConverter` neither names
  a read stopped early nor notifies; Live's auto-convert does both (Q48.1, Q48.2). Route its `shot_converted`
  through the same stop handling.
- **A58.3 The try-import's cost**: the probe adds about 0.2–1 s per script folder at start and on each reload (two
  at once, `PROBES_AT_ONCE`). If a lab PC's cold frozen start makes it slow, reuse one probe process per round for
  several folders (a protocol change).

## The v0.0.8a1 release (block 59)

From CoCo's check of the v0.0.8a1 release (2026-11-04, Tony in Chat: "ok ya add to todo since i had to manually tag
v0.0.8a1 and v0.0.6a1 just now"). For v0.0.9, before its PR.

- [x] **A59.1 Release notes that link their tags** (done in `ca0bd61`, review fix `be2f0e5`, the previous published
  full release as the compare base, Tony's rule of 2026-11-04, in `9e06bcb`; Quick Fixes 10, landed `20dd672`)
  (`dev-cicd.yml`'s release job, `helab/release_draft.py`). CI's
  draft (`v0.0.8a1`, run 41746737106) had a fixed template. Tony had to link the tags by hand. Make the draft's notes:
  1. name and link their tag;
  2. compare against the previous release tag, a "Full Changelog: <previous>...<tag>" link. The previous tag is the
     newest earlier `v*` tag in the commit's history: v0.0.7a1 has none, its release job having failed (run
     41110274554). Pass it as GitHub's `previous_tag_name`;
  3. add GitHub's generated notes (`generate_release_notes`, or `POST /releases/generate-notes` once and merged
     into the body with the manifest marker kept);
  4. fix "Workflow Run": `github.event.repository.url` is the API URL (`api.github.com/repos/…`). Use
     `${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}`.

  Keep the recovery path (`release_draft` resuming an existing draft) and its tests working. Draft bodies are
  rewritten only while they are drafts, never after publishing.
- [x] **A59.2 GitHub's pre-release flag vs the manual's "stable".** (done (b) in `bfa2b78`, the rule in
  `release-and-ci.md`; Quick Fixes 10, landed `20dd672`) CI made the v0.0.8a1 draft a pre-release
  (`RELEASE_PRERELEASE: true`). Tony published it as a full release on purpose, so GitHub's "Latest" is v0.0.8a1;
  as a pre-release, "Latest" would fall back to v0.0.3b. The manual's site goes by the version number
  (`site_versions.py`, PEP 440), so its front page still says "No stable release yet". Asked in Chat (2026-11-04):
  (a) tick "Set as a pre-release" again; (b) keep the release and reword the no-stable front page; (c) the site
  follows GitHub's flag. **Tony chose (b)** (2026-11-04: "b"). To do:
  1. keep v0.0.8a1 a full release (GitHub's "Latest"); the site still goes by the version number;
  2. reword the no-stable front page (`docs/publish/no-stable.html`, the template `site_versions.py` sets as the
     default) to name the newest pre-release as the latest download, e.g. "Latest: 0.0.8a1 (alpha)", linking to
     `pre-release/`;
  3. record the rule in `release-and-ci.md`'s publishing step (a pre-release version may be published as a full
     GitHub release; the site's `latest` stays the newest stable version, and until there is one the front page
     names the newest pre-release).

## Quick Fixes 10 (block 60)

From Quick Fixes 10's [handoff](sessions/2026-11-04-claude-quick-fixes-10/handoff.md) (Rivet; A59.1, A59.2 (b),
A56.7, A58.2 and A56.4 done; landed `20dd672`, CI 41770471113).

- [ ] **A60.1 Folder details' Convert row amber for a read stopped early** (Quick Fixes 10's A~1;
  `helab/views/FolderDetailsPanel.py`). Live's Auto-convert row turns amber when it names a read stopped early
  (`READ_STOPPED`); the Convert ("offer") row, which names them since A58.2 (`6b22d8d`), doesn't. A two-line change
  beside the `convert` row's style, with a test.
- [ ] **A60.2 Pin `packaging` in the release jobs** (Quick Fixes 10's A~2; `.github/workflows/dev-cicd.yml`).
  get-version and, since A59.1, the release job run `pip install packaging` unpinned; `requirements.lock` has
  `packaging==26.3`. Pin it to the lock's version (or install it from the lock), keeping `--check`'s builds as they
  are.

## UI audit (block 61)

- [ ] **A61.1 Elide the plot's "Data source" line** (the UI audit's leftover, `49a02f1`;
  `.ai/sessions/2026-11-04-claude-ui-audit/README.md`). In an 1100 px window the plot's "Data source: …" line, a plain
  QLabel, is cut off. Elide it in the middle with the whole text in its tooltip, as the Cache tab's path now is. Mind
  `test_main_split`'s 250 px panel check, which has no slack on the preset row.

## Activity window (block 63)

- [ ] **A63.1 A cancelled shared job's history entry keeps its tabs** (the Activity Window floor's A~1;
  `helab/utils/folder_cache.py`, `io_service.py`). FolderCache forgets a job before cancelling its helper, so the
  cancellation's history entry names the producer's owner, not its tabs, and History offers no Show in tab or Retry
  for it. Pass the subscribers to IOService before cancelling (e.g. `owners_of` reading a just-forgotten job).
- [ ] **A63.2 Refresh the Activity window on each tab's own signals** (the floor's A~2; optional,
  `helab/views/ActivityWindow.py`). Live's and conversions' state changes show within the 1 s tick; connect each
  tab's `liveChanged` and `loadStateChanged` too if that delay shows in use.

## Basic plots v2 (block 66)

- [ ] **A66.1 Bin the 2D histograms with `np.bincount`** (the floor's A~1; `helab/analysis/histogram2d.py`): about 17×
  faster than `histogram2d` with the same counts, NumPy only; the last bin's right-edge rule must match. The DLD port's
  Density images could follow on its own floor.
- [ ] **A66.2 Transfer fractions' Y axis in PyQtGraph** (A~2; v2 only): it reads "(x0.001)" with ticks up to 600; set
  the axis's units or turn off its SI prefix scaling.
- [ ] **A66.3 The Presets row at the panel's 250 px minimum** (A~3): "Preset:" is cut and touching (left by the
  2026-11-04 audit) and the TXY row's "HeLab converts with …" elides early; a one-line layout pass.
- [ ] **A66.4 A warning that isn't last takes the parts after it into its tooltip** (Lens's BP-11, Info;
  `helab/views/plots/instance.py:91`): a non-listed warning inside `describe_run`/`describe_result` text that isn't
  the last part shows the following parts in its tooltip line ("⚠ X · bins auto"); the count is right and HeLab's own
  scripts put warnings last, so only a user script shows it.

## Folder info (block 67)

- [ ] **A67.1 Activity's name for the Folder info read** (A~1): give it a label ("Folder info read") and leave successful
  ones out of History (`activity.NOT_KEPT_WHEN_OK`: Live's saves make one each while the window is open).
- [ ] **A67.2 Raw pulses after a Live save** (A~2): `raw_fill` runs after a save, so the window's raw pulses lag one save;
  read again on `raw_fill_done` of the watched folder too (bounded by `Reads`).
- [ ] **A67.3 A read-only store open for `folder_info`** (A~3): the admin opener makes the store folder when it isn't
  there; open read only (as `helab cache --folder` does) so the window never creates a store (`stores._cache_store`).
- [ ] **A67.4 Time `folder_contents` on the largest real folder** (A~4, with M67.1): it parses every TXY layer's
  entries; move the shot range into SQL if it's slow.
- [ ] **A67.5 A per-folder fence for HeLab's converted TXY** (A~5, Tally's FI-6): a per-folder Clear sets the index's one
  fence token, so another folder's conversion into the same base waits for its next check with a wrong "cleared"
  message; a `folder_fences` table (additive within schema 1) read by `fence_of(root, folder)` beside the base's
  (`helab/convert/provenance.py`, `helab/io_ops/convert.py`).
- [ ] **A67.6 Read again after Hide HeLab** (Tally's FI-11, Info, optional): a hide that isn't a minimise (Cmd+H) unhooks
  the window, so it misses Live's saves and doesn't read on reshow ("As of" stays honest); read once on a reshow after a
  spontaneous hide.

## App updates (block 68)

- [ ] **A68.1 The frozen self-update** (A~2; Q65.1 (b)'s later part): `updater` has no frozen path and the update
  window shows Download only; needs the signing / attestation decision in `roadmaps/app-updates.md`'s Open decisions.
- [ ] **A68.2 CI marks for every commit in the update window** (A~3): the commit list shows CI only for the (at most
  5) commits looked at; the rest show none.

## Bug review of f844c0f..0de469b (block 72; [handoff](sessions/2026-11-10-claude-review-0de469b/handoff.md))

- [ ] **A72.1 More memory estimates** (A~1): only the XY, XT, YT histograms declare
  `DatasetAnalysis.estimated_bytes`; other plots with large set grids (the DLD port's density images,
  Correlations, Plane projections) could too.
- [ ] **A72.2 The 2D histograms in the RAM budget before drawing** (A~2): their arrays count toward the budget only
  once drawn (`RamBudget`, plots' buffers); the warning is the only check before.
- [ ] **A72.3 Plotly's copies in the estimate** (A~3, Probe's Info): the estimate assumes PyQtGraph's colouring;
  Plotly base64-encodes `z` and `customdata` and QtWebEngine holds its own copy, several GB more at 20,000²; would
  need the library passed to `estimated_bytes` (Drawing › Library isn't an analysis value).
- [ ] **A72.4 Align `blur_brief`'s and `blur_steps`' default Order** (A~4, Probe's Info; harmless): next time
  `histograms_2d.py` is touched.

## GUI threads audit (block 73; [handoff](sessions/2026-11-10-claude-gui-threads-audit/handoff.md))

- [ ] **A73.1 A script folder's code from memory** (A~1, GT-6 (A)): the probe returns each `.py` file's and helper
  module's bytes (bounded, e.g. 8 MB in all) through a file in its temp folder; during `load_directory` a temporary
  meta-path finder serves the folder's modules from them (`__file__` the real path; linecache gets the source), so
  the GUI thread reads nothing of a share at Reload. Data files a script reads at import still come from disk.
- [ ] **A73.2 Mounts from helpers** (A~2, GT-7 (b)): `share_of`'s mount table (Folder details' refresh, Live's
  convert tick, the share question) is read on the GUI thread every 10 s on Windows. Proposed: helpers report
  mounts (`mounts_seen` in `events.py`), `FolderCache` keeps them; after M73.1 shows whether those calls wait.
  Evidence (block 74, A~1): in 3 of the lab log's GUI stalls of 2026-11-11 the GUI thread was in
  `cache_paths._windows_unc`, from `_convert_tick` → `explorer_convert.share_to_confirm` (beside on).
- [ ] **A73.3 `RamBudget.check` in O(plots × shots)** (A~3, GT-11): each plot's buffers taken once per check, with
  holder counts.
- [ ] **A73.4 Fewer derives and activity updates** (A~4, GT-12): coalesce `activityChanged` with `one_activity()`
  or a dirty flag; running tallies on parents instead of `_derive` over all children per child event; cache
  `txy_sources.empty_helab_shots`/`origins_of` per dataset (11 ms per 100 ms at 100,000 shots); refresh
  only the shown tab's summary. (`low_hits_threshold()` from memory: done in block 74, `871afff`.)
- [ ] **A73.5 Profiles, trace and cache-move clean-ups off the GUI thread** (A~5, GT-13): keep the profile library
  in memory; `delete_io_traces` into `trace_check`'s helper; the cache move's `undo_rename` and
  `cache_move.cleanup` into a helper.
- [ ] **A73.6 `build_info` keeps commit and branch when only `git status` times out** (A~6, GT-15), and logs it
  (today a timeout quietly turns updates off for the session).
- [ ] **A73.7 A suite-wide stall report** (A~7, guard 3): the audit's `stall_probe.py` into conftest, reported like
  RERUNs (over 1 s listed with stacks; fail only over 5 s).
- [ ] **A73.8 The cache move's heartbeats** (A~8, GT-8, Q73.3): progress from the move helper while it copies and
  deletes (through `cache_move.recover`/`cleanup`/`_remove_tree`), then a no-progress timeout for the startup
  recovery.
- [ ] **A73.9 The GUI-thread lint, wider** (A~9, guard 1): the GUI-side `helab/utils` modules (needs per-function
  scoping: IOService and the watchdog wait on their own threads), and `open`/`os.stat` with a longer allow-list.
- [ ] **A73.10 A modal in a delivery, logged in the app** (A~10, GT-1): a warning with its stack when a box opens
  inside a delivery; today only the suite catches it.

## Live stall (block 74; [handoff](sessions/2026-11-12-claude-live-stall/handoff.md))

- [ ] **A74.1 Coalesce `_update_folder_details`** (A~2): `HelabMainWindow._update_folder_details` runs on most
  Live events (each `_update_activity` and `loadStateChanged`), re-rendering Folder details and every plot's
  source line; once per event-loop turn (a 0 ms single-shot) would cut the GUI work per drain (65 of the lab
  log's 217 stalls showed only the event loop).
- [ ] **A74.2 Answers and `done` in different drains** (A~3): F2 covered loads' answers (`ANSWERS`); audit the
  other `has_request` callers (results, admin, icons; Live's conversion ends on `done`, scans replay at `done`)
  for a request joined after its answer.
- [ ] **A74.3 Build info once per app run** (A~4, with A73.6): every process importing `helab.utils.constants`
  (each helper and test worker) runs `get_build_info()`'s four git calls, up to 2 s each. Cache it per app run
  and pass it to helpers (as `settle_seconds` is), or read it lazily where shown (About, the log's header); may
  also explain the lab log's "Commit: unknown".
- [ ] **A74.4 `events.py` docstrings for `read_failed`**: `ShotWaitingEvent`'s "couldn't be read now
  (`read_failed`)" gains "; unconvertible once unchanged and unreadable for 20 s"; `ShotUnconvertibleEvent`'s
  reasons gain `read_failed` (unchanged and unreadable for `DAMAGED_SECONDS`, by its mtime and since first seen).

## Review fixes at 09ca79b (block 75; [handoff](sessions/2026-11-17-claude-review-09ca79b-fixes/handoff.md))

- [ ] **A75.1 Laserlock's auto-lock after a plain sweep** (A~1): `_sweep` with `lock_thz` engages without checking a
  new reading at the target, as N3's hold did; the same fix as the hold of 0 would do.
- [ ] **A75.2 The cloud environment's venv** (A~2): it installs `requirements.txt`, not `requirements.lock` (PyQt6
  6.12.1 for 6.11.0, mypy 2.4.1 for 2.4.0), and then `mypy helab` reports 165 errors. Its setup script should
  install the lock. The PyQt6 6.12.1 ViewBox failure is in known-issues.
- [ ] **A75.3 `test_a_killed_helpers_workers_exit`: count a zombie as exited** (A~3; `psutil.STATUS_ZOMBIE`), the
  second symptom in its known-issues entry. Not reproduced yet, so a fix would be unchecked.

## Not AI work (stays in MANUAL_TODO)

These need a real share, lab hardware or a person in the lab:
- remounts, and two mounts of one folder;
- read-only shares, and mapped-drive spellings on Windows;
- the converter and the lab's MATLAB scripts ignoring `.helab-root`;
- the physics checks on real data: temperatures, condensate fits, g², release time, the QE
  calibration;
- release recovery in a disposable release;
- the self-update questions for ANU IT.
