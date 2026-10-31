# Handoff: plot identity, the area review's plots fixes (`agent/plot-identity`, Claude Opus 5.5, 2026-10-31)

Brief: [brief.md](brief.md). Findings fixed: the area review's `plots.md` (`573361f`), plots-1, plots-3,
plots-4 and both nits. plots-2 is out of scope (Q39.1, A39.3). Base `0571ff2`; no signature code changed
(`io_ops/loading.py`, `helab_txy.py` untouched).

## What was built (one commit each)

1. **plots-1 (`49b7a9c`): each view chain has its own identity.**
   - `ViewIdentity.chain`: a token `build_view` makes (`uuid4().hex`), kept by `with_shots`; "" for
     `presets`' placeholder views. A dataset `revise` refuses (another folder, shots gone, another TXY
     choice or profile) and every fresh load (`view_of` of a new `Dataset`) is another identity, so
     `follow.newer` offers it whatever its revision, `Follow.due` runs it once whatever "every N", and
     `ViewKey`s no longer collide. The reuse key (`AnalysisResult.reuse_key`) lists its fields by name and
     is unchanged; `result_codec` decodes by field name, so records saved before (no `chain`) still read.
   - The dock's source line (`PlotWorkspace._update_plot_source_label`): "Data source" when the tab shows
     the same data as the plot's view, else "Showing previously loaded data". Compared with
     `DatasetView.held` / `held_of(dataset)` (`Held`: SHA-256 of the shot numbers and of each shot's
     fingerprint and origin; per `Dataset` cached in a `WeakKeyDictionary`, memory only), not the
     signature. A plot with its own TXY choice (`not on_tab_choice()`) compares shot numbers only
     (`Held.own`), since the tab reads other files. The dock property `dataSourceSignature` is now
     `dataSourceHeld` (a `Held`, or None for an outdated saved result, which no tab shows).
     `set_plot_result` and `AnalysisInstance._show_content` take the run's view.
   - `shot_trends.newer_than_drawn`: unchanged code; with the chain in the identity a new chain notifies
     from its second revision (comment updated).
   - Tests: `test_live_plots.py`'s and `test_shot_trends.py`'s fakes give every dataset one signature
     (`sha256("[]")`, as a raw-only folder), not `sig-<n>`/`sig-again`/`sig-changed`; new:
     `test_each_load_of_a_raw_only_folder_is_another_chain` (a fresh load and another profile offered,
     and their next revisions), `test_the_feed_offers_a_new_chain_after_live_starts_again` (GUI, the
     review's scenario A), `test_the_source_label_compares_the_data_shown_not_the_signature` (5 vs 50
     shots, a changed file, another profile, own choice), `test_a_new_chain_notifies_from_its_second_revision`.
     The two follow tests fail with the chain token blanked (checked).
2. **plots-3 (`a15d940`): Live-kept steps keyed by the data.** `DatasetView.chain_key` = [identity
   source, TXY choice, chain, sorted profile hashes of its HeLab shots]. In
   `velocity_distributions.kept_key` and Correlations' `box_key` and `detection_key`. Tests: another
   profile's and a fresh load's next Live run detects again (velocity), another load's Live run keeps no
   box (correlations); both fail without `chain_key` (checked). The existing velocity kept test built its
   "later" view as another load; it now uses `revise` (a real revision).
3. **plots-4 (`a293214`; Windows `65de6d4`; `b1f6280`): Dash port.** `DashServer._listened_on_all(port)`: before
   binding the preferred port, a wildcard bind as HeLab binds its own (`SO_REUSEADDR` off Windows);
   refused only by a socket holding the port on all addresses (IPv4, or dual-stack IPv6), not by
   connections in TIME_WAIT, so `test_stop_frees_the_port` still gets the same port back. Windows has the
   same hijack without `SO_REUSEADDR` (CI run 41158691080 failed the new test there on every try), so
   the probe runs on every OS since `65de6d4` (CI then passed the IPv4 case on Windows). **Not handled:
   Windows beside a dual-stack `[::]` listener**: HeLab's 127.0.0.1 bind and an IPv4 wildcard probe both
   succeed there, and so did a `[::]` probe with `IPV6_V6ONLY` (`fd069e2`, CI 41161383176); which socket
   then gets 127.0.0.1's connections is unverified. `b1f6280` reverts that probe (it fixed nothing, and on
   macOS the IPv4 probe already finds dual-stack listeners) and skips the test's ipv6 case on Windows, with
   the reason; a known-issues entry is proposed below. Nothing is sent to the other program.
   Measured on this Mac first (scratch probe): IPv4 and dual-stack `[::]` listeners found, TIME_WAIT
   not, our own bind not. Test parametrised ipv4/ipv6, fails without the probe (checked). Dropping
   `SO_REUSEADDR` on macOS (the review's first option) would have broken that same-port restart.
4. **Nits (`3afe2fe`).** `reuse_on`'s docstring: off by default (Q27.1). A failed rerun beside an
   outdated saved result: the amber note drops ": rerunning" (`RERUNNING` in `instance.py`), keeping the
   reasons; test added (fails without). The nit's other half (`_shown_view` not set for the outdated
   saved result) is left on purpose: that result's data isn't the run's view, and with plots-1 its
   source line already says "Showing previously loaded data" (`dataSourceHeld` None).

## Review (Optic, [review.md](review.md), `0d00b13`): 5 Low findings, all fixed

- **R-1** (`a76ba3c`): the velocity test's fresh-load leg passed with the chain token blanked; it now runs
  right after the kept rerun on a load of the same choice, so only the chain tells them apart.
- **R-2** (`a76ba3c`): `test_correlations_plot.py::test_another_load_keeps_no_detection`: Correlations'
  kept t_r detection ("detected, kept") isn't kept for another load.
- **R-3** (`a76ba3c`): a cancelled rerun, or one not shown because Follow Live went off, kept ": rerunning"
  beside an outdated saved result; `_finished` now drops it once for every run that ends (test: failed
  and cancelled).
- **R-4**: the known-issues rewording below (lines 61-66).
- **R-5** (`a76ba3c`): `shot_trends`' 143-character comment line wrapped.

Each changed test was run with its fix taken out and failed (the chain token blanked; `chain_key` out of
`detection_key`; the `_finished` line removed).

## Files

| File | Change |
|---|---|
| `helab/analysis/dataset_view.py` | `ViewIdentity.chain`, `DatasetView.held` / `chain_key`, `Held`, `held_of` |
| `helab/analysis/follow.py` | `newer`'s docstring |
| `helab/views/plots/workspace.py` | source line by `Held`; `set_plot_result(view, own_choice)` |
| `helab/views/plots/instance.py` | passes the run's view; `RERUNNING`; the failed-rerun note |
| `helab/views/plots/cached_results.py` | docstring |
| `helab/scripts/dld/velocity_distributions.py`, `correlations_plot.py` | keys with `chain_key` |
| `helab/scripts/dld/shot_trends.py` | comment |
| `helab/utils/dash_server.py` | `_listened_on_all` |
| `tests/test_live_plots.py`, `test_shot_trends.py`, `test_velocity_distributions.py`, `test_correlations_plot.py`, `test_dash_server.py`, `test_result_cache_plots.py` | as above |

## Checks

Logs kept whole in `.ai/temp/plot-identity/` (gitignored): `suite.log`, `suite2.log`, `types.log`.

- **Full suite, first run** (`3afe2fe`): `1 failed, 8522 passed, 672 skipped, 2 warnings, 5 rerun`:
  `test_txy_sources.py::test_a_revision_or_reload_never_crosses_sources` failed on every try (rerun
  reason each time: `AssertionError … Differing attributes: ['chain']` at line 425). A real failure,
  not a flaky one: the test asserted that a MATLAB priority view and a HeLab priority view of one folder
  have equal identities, the collision plots-1 removes. Fixed in the test (`69b6bca`): it now checks
  what it guarded (both keep the identity's source "", no `txy_source` in the reuse key) and distinct
  chains. Nothing to file in known-issues for it.
- **Full suite, after the fix** (`69b6bca`): `pytest -n 4 --reruns 5 --reruns-delay 1
  --basetemp=.ai/temp/pytest -rR`: **8523 passed, 672 skipped, 2 warnings in 151.83 s; no RERUN** (the
  summary has no "rerun reasons" section). Warnings: pyqtgraph's NumPy 2.5 `arr.shape` deprecation
  (`test_t_spectrum.py`), unrelated. `tests/test_typing.py` (mypy strict and not, pyright) passed inside it.
- **Type checks** (`3afe2fe`, `types.log`): `mypy helab/ --strict` no issues in 195 files; `mypy tests
  --strict` no issues in 175; `pyright helab tests` 0 errors; `mypy helab/ --strict --platform win32` no
  issues; `pyright --pythonplatform Windows helab tests` 0 errors. `69b6bca` changed one test file:
  mypy --strict and pyright on it clean, and test_typing in the second suite run.
- Each new test was run against the code with its fix taken out and failed (plots-1 follow tests,
  plots-3 velocity and correlations, plots-4 both families, the nit).
- **CI run 41158691080** (`08afbb0`): failed. Windows Tests (2/2) (job 124411181934): `2 failed, 4253
  passed, 364 skipped, 34 warnings, 11 rerun`: the new plots-4 test, both families, on every try (rerun
  reason each time `assert <port> != <port>` at `tests/test_dash_server.py:62`: Windows binds beside a
  wildcard listener); fixed in `65de6d4`. The 11th RERUN:
  `test_plot_backends.py::test_2d_plots_draw_with_every_library[values0-Plotly-CountsPerShot]`, reason
  "worker 'gw1' crashed while running" it, passed on retry: **already in known-issues** (Windows CI run
  40803552596); this run is another occurrence to add there. Every other job green with no RERUN (each
  log read): macOS Tests 1/2 4250 passed, 2/2 4273; Ubuntu 1/2 4247, 2/2 4273; Windows 1/2 4233;
  Converter backends macOS 713, Ubuntu 713, Windows 711; Builds green on all three.
- **CI run 41160242383** (`529786e`): failed. Windows Tests (2/2) (job 124416059305): `1 failed, 4254
  passed, 364 skipped, 34 warnings, 5 rerun`: the plots-4 test's ipv6 case on every try (rerun reason each
  time `assert <port> != <port>` at `tests/test_dash_server.py:63`); ipv4 passed. Fixed in `fd069e2`. Every
  other job green with no RERUN (each log read): macOS 4250 / 4273, Ubuntu 4246 / 4273 (one fewer than the
  last run: `test_uncertainty_format.py::test_prefix_matches_pyqtgraph` takes random parameters (its IDs differ
  between the runs), Windows 1/2 4233, Converter backends 713 / 713 / 711, Builds green.
- **CI run 41161383176** (`49dd945`): failed. Windows Tests (2/2) (job 124419526951): `1 failed, 4254
  passed, 364 skipped, 34 warnings, 5 rerun`: the ipv6 case again on every try (the same reason, line 63),
  so the `[::]` probe didn't help; reverted and skipped on Windows in `b1f6280` (above).
- **CI run 41162571197** (`d2d5334`, the branch's code as handed off): **success, every job green on
  macOS, Ubuntu and Windows, no RERUN in any log** (each Tests and Converter backends job's log read):
  macOS Tests 1/2 4250 passed / 2/2 4273; Ubuntu 4247 / 4274; Windows 4233 / 4254 (365 skipped: the ipv6
  case); Converter backends 713 / 713 / 711; Builds green. Since the last local full suite (`69b6bca`) only
  `dash_server.py` and `test_dash_server.py` changed; this run is the full suite on all three OSes.

## Proposed doc changes (for CoCo)

- **`plots-and-scripts.md`, Dataset analyses**, after "identity = source path, `root://` key and
  signature": "and its chain (`ViewIdentity.chain`, `build_view`'s token, kept by `with_shots`: the
  signature is the folder's MATLAB TXY's, the same for every load and TXY choice of it and
  `sha256("[]")` without MATLAB TXY, so a fresh load, another TXY choice or profile is another
  identity, never an earlier revision; plots-1)".
- **`plots-and-scripts.md`, Following Live, coverage and plot display**, after the two source lines
  sentence: "The first line starts "Data source" while the tab shows the data the plot ran on (by shots,
  fingerprints and origins, `DatasetView.held` / `held_of`; by shot numbers for a plot with its own TXY
  choice), else "Showing previously loaded data"; a plot following Live is always the former."
- **`plots-and-scripts.md`, Visualization**, the Dash sentence: "(`127.0.0.1:8050` preferred; another
  free port when it's in use, or held on all addresses by another program, which macOS and Windows would
  otherwise let HeLab share: `DashServer._listened_on_all`, plots-4)".
- **`live.md`, Plots following Live**: after "`revise` makes it the next revision of the folder's view":
  "; a dataset that isn't one (another load, TXY choice or profile, or shots gone) starts another chain
  (`ViewIdentity.chain`), which its plots run on once whatever their revision and Rerun every N".
- **`dld-analyses.md`, Plots of the port** (Velocity distributions; Correlations): "A Live rerun keeps
  the plot's last t_r detection and auto-crop box while the folder's data (`DatasetView.chain_key`:
  TXY source and choice, chain, profile hashes), settings and constants are the same (`KeptRuns`); a
  run the user starts, another plot, load or TXY choice finds its own (plots-3). Correlations' kept box
  and detection use the same key."
- **`roadmaps/known-issues.md`**: plots-1 and plots-3 fixed here, plots-4 for IPv4 wildcard listeners on
  every OS (nothing to file for those); plots-2 stays moot by Q39.1 (A39.3). File:
  - "On Windows the Dash server can bind 127.0.0.1:8050 beside a dual-stack `[::]:8050` listener (an IPv4
    wildcard probe and a `[::]` V6ONLY probe both bind); whether that program then loses its 127.0.0.1
    connections is unverified. `test_dash_server.py`'s ipv6 case is skipped on Windows (CI 41160242383,
    41161383176). Needs a Windows machine: try `SO_EXCLUSIVEADDRUSE` on HeLab's socket, checking it still
    gets its port back after a restart (TIME_WAIT)."
  - Another occurrence of `test_plot_backends.py::test_2d_plots_draw_with_every_library[values0-Plotly-CountsPerShot]`'s
    worker crash: Windows CI run 41158691080, Tests 2/2 (job 124411181934), passed on retry.
  - Reword (Optic's R-4) the item at lines 61-66 ("When a tab's shown data is dropped while it is
    shown…"), whose last sentence describes the label by signature. From "Since plotting," on: "Since
    plotting, a plot whose data differs from the tab's (its shots, their files and origins:
    `DatasetView.held` / `held_of`, plots-1; by shot numbers for a plot with its own TXY choice) says
    "Showing previously loaded data" (`_update_plot_source_label`); not checked: a cache clear (which
    keeps the tab's dataset, so the label stays) and the tab's own arrays (2026-10-28)."

## Provisional items

- **A~1** (may do without asking): `AnalysisInstance._cached_found` shows an outdated saved result
  without a view; if a later change wants Release or the TXY row to know that result's own data, it
  would need a hollow view built from the saved record (coverage and origins). Not needed now.
- **M~1** (Tony, Mac): with another program listening on `0.0.0.0:8050` (e.g. a Dash app run with
  `host="0.0.0.0"`), open a 3D scatter in HeLab: its Open in browser URL is on another port, and the
  other program still answers `http://127.0.0.1:8050`.
- **M~2** (Tony, real data, Live): a raw-only folder with auto-convert, a plot following; switch Settings ›
  TXY converter to another profile: the plot reruns at once on the new profile's data; Velocity
  distributions' title doesn't say "kept from rev N" on that run.
