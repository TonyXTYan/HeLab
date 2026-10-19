# Handoff: dataset view + first plots

Branch `agent/dataset-view-plots` (base `376c7dd`). Notes and the auto-crop
investigation: [notes.md](notes.md). Screenshots: `screenshots/`.

## What changed

- **`helab/analysis/`** (new):
  - `dataset_view.py`: `DatasetView`, `ViewIdentity`, `ViewKey`, `Provenance`,
    `DataRootRef`, `build_view`, `view_of`.
  - `stats.py`: auto-crop, display sample, counts per shot, histograms.
  - `parameters.py`: `ParameterSpec`, `effective`, `describe`.
  - `identity.py`: `AnalysisIdentity`, `file_hash`.
  - `results.py`: `AnalysisContext`, `AnalysisResult`, `RamResults`.
  - `runner.py`: `AnalysisRunner`, a single worker thread with a FIFO queue.
  - `panes.py`: `PlotlyPane`, a web view with **Open in browser**.
- **Script context**:
  - `helab/scripts/base.py`: `ScriptMetadata` gains `analysis_id`, `version`
    and `file_hash`, plus `identity()`. New `DatasetAnalysis` base: it declares
    `parameters`, `compute(action, context)` runs in the worker without Qt, and
    `render(result)` runs on the GUI thread.
  - Old `HelabAnalysisScript` subclasses still get `execute_action(name)`,
    unchanged.
  - `ScriptsManager` hashes each file before running it, and has
    `load_module()` for imported modules.
- **Bundled analyses** (`helab/scripts/standard/`, group "Plots"; imported so
  that packaged builds include them):
  - `scatter_3d.py`, `helab.scatter_3d` v1: Plotly via the Dash server.
    One parameter, Auto-crop keep % (default 99, range 50–100; 100 = no crop).
    The axis ranges are the crop box, and the bounds are given on the figure.
    A fixed-seed random display sample is capped at 100,000 events, labelled on
    the figure and in a one-line note (details in its tooltip); the sample
    never becomes the analysed data. **Open in browser** is included. This
    replaces `helab/scripts/plotly_3d_sactter.py` (deleted, along with its
    `print`s and the silent 10k cut).
  - `basic_plots.py`, `helab.counts_per_shot` v1 and `helab.txy_histograms`
    v1, with PyQtGraph:
    - Histograms have Range keep % (default 99, shortest range per axis) and
      Bins (0 = automatic, Freedman–Diaconis, clamped to 1–2000).
    - Each histogram title gives the bin count, how it was chosen, and the
      events outside the range.
- **Scripts panel** (`helab/models/ScriptTreeSelector.py`):
  - The loaded groups stay listed: "Plots" first, then the examples, then the
    placeholder groups.
  - A dataset analysis's button runs on the current tab's shown dataset
    (`HelabMainWindow.current_dataset_view()`). The dock opens at once with
    "Running…", and new docks are tabbed with the open ones.
  - A parameter tab shows the input line, the parameter tree and **Rerun with
    these settings**, which reruns on the *same* view.
  - Closing the dock cancels the job, unpins its result and removes the
    parameter tab. This also fixes the tab removal: it used a stale index after
    other tabs closed.
  - Docks close on `closeEvent` (`AnalysisDock`), not `visibilityChanged`,
    because a plot hidden behind a tabbed dock was being closed.
  - Without data the panel shows the status notice "<name>: load a folder's
    data first".
- **Plot dock** (`HelabMainWindow`):
  - `set_plot_result` sets the source line, for example `Data source: run_042 ·
    rev 1 · helab.scatter_3d v1 · Auto-crop: keep 99 %`. The tooltip holds the
    full record: analysis ID, version, file name and hash, input path and
    revision, root key, signature, parameters, job, state, time, and "kept in
    RAM only".
  - The existing "Showing previously loaded data" prefix still applies.
    `_set_plot_source` behaves as before, with the label code shared
    (`_wrap_plot`).
- **Dash server**: the debug `print` is gone. `remove_plot()` runs when a
  `PlotlyPane` is destroyed, so closed plots free their figures, and the graph
  fills the browser page.

## The view's contract (for Live L3)

- `view_of(dataset, root=None)` gives one `DatasetView` per `Dataset` object
  (a weak-key memo). `root` is `FolderCache.root_of(path)`, used when the load
  didn't report `data_root`. It reads only `Dataset.path`, `.signature`,
  `.data` and `.metadata` (`fingerprint`, `source`, `loaded_at`, `checked_at`,
  `verified`, `unsettled_files`, `failed_files`, `problematic`,
  `cache_reason`, `data_root`). **No browser changes and no new fields were
  needed.**
- **Identity**: `ViewIdentity(source_path, root_key, signature)`.
  - `root_key` is `root://<uuid>/<relative>`, or "" when no data root is known.
  - `signature` is the loaded dataset's own signature.
- **Revision**: 1 when built. `view.with_shots(added, fingerprints)` returns
  the next revision:
  - same identity, `revision + 1`, `added_shots` set;
  - added shots replace any shots with the same number;
  - the original view is unchanged.

  Live should call it for each batch of new shots; results bind to `ViewKey`
  (identity + revision).
- **Shots**: `shots` is a read-only mapping from shot number (ascending) to the
  shared (n, 3) T/X/Y array, handed out as a non-owning read-only view, never
  a copy.
  - Building a view (and `with_shots()`) makes each array and its whole
    `.base` chain read-only, e.g. the buffer `np.load` reads a shot into. So
    neither the view nor the tab's array can be written or made writable again.
  - This guards against accidents, not a security boundary: a deliberate
    `.base.setflags(write=True)` on the owning buffer still gets round it.
    `with_shots()` makes the arrays it is given read-only the same way.
  - `events(shots=None)` concatenates the shots into a new array; that copy is
    the analysis's choice.
  - Malformed arrays give no events.
- `fingerprints`: shot → (shot, size, mtime_ns).
- `provenance` holds `source`, `loaded_at`, `checked_at` (both wall-clock;
  `checked_at` is None if never checked), `verified`, `unsettled_files`,
  `failed_files`, `problematic` and `cache_reason`. All are copied when the
  view is built.
- **Runs**: `AnalysisRunner.submit(script, metadata, action, view, values)`
  validates the values against the declared parameters (unknown keys are
  dropped, values are coerced and clamped), builds an immutable
  `AnalysisContext` and queues it. `finished` emits an `AnalysisResult` with
  state completed, failed or cancelled. A computation can stop early with
  `context.check()` (raises `Cancelled`) or by polling `context.cancelled()`.
  `stop(timeout)` returns True once the worker has exited. Until then it stays
  registered, and `submit` raises `RuntimeError`. Completed results go into `RamResults`
  (limit 64, least recently used dropped first; results that docks show are
  pinned).

## Decisions I made (judgement calls)

1. **Auto-crop rule: a heuristic box, peeling then narrowing** (see
   [Review fixes](#review-fixes)). Central and common-window rules keep
   one-sided tails; see [notes.md](notes.md#auto-crop-rule-how-it-was-chosen).
   The whole rule is in `stats.crop_box`, behind the keep % parameter, so a
   different rule is a change to that one function.
   - The rule is in the parameter's tooltip and on the figure (bounds and kept
     share).
   - The crop bounds are derived results, not parameters. Keep % is the saved
     parameter.
2. **Plot libraries**:
   - PyQtGraph for counts and histograms: native Qt drawing, fast redraws for
     Live, and it paints on lab PCs that can't paint QtWebEngine.
   - Plotly only for the 3D scatter, as decided.
3. **Display cap is a constant** (100k), not a parameter, so the scatter keeps
   "one parameter". The sample has a fixed seed (0), so redraws are identical.
4. **Execution**: one daemon worker thread in the GUI process, FIFO, with
   cooperative cancellation (`context.cancelled()`). This is new: AGENTS.md
   says "The GUI process has no worker pools". It is one thread, not a pool,
   for computation, kept separate from the source-I/O queue as the job runner
   plan asks. A separate process can come with job runner stage 2 or 3.
5. **Rerun** uses the dock's own input. A run on new data is a new dock (press
   the script's button again). Folder-following views are later work.
6. **File hash** is the script file's SHA-256 at load. It covers only that
   file, not shared helpers like `helab/analysis/stats.py`; the version bump
   covers those by convention. In a PyInstaller build the bundled `.py` files
   aren't on disk, so the hash is "" and the record shows "hash unknown".
7. **Units**: the axes are labelled s and m (as stored), not mm as the legacy
   figures use.
8. Bundled scripts moved to `helab/scripts/standard/`, and the typo filename
   `plotly_3d_sactter.py` is gone.

## Open questions for Tony

- Is the peeling crop right for the lab's data, or should the box be centred
  on the atoms (for example a density peak)? Should the crop be adjustable on
  the plot?
- Axes in mm (like the legacy figures) rather than m?
- A dock's view keeps its dataset's arrays alive after the browser evicts them,
  and that memory isn't counted in the RAM budget. Should open plots count, or
  warn?
- Packaged builds: add `helab/scripts/standard/*.py` to the `HeLab.spec`
  datas so hashes are known? That file isn't owned by this floor.
- Keep the placeholder "Basic Analysis" and "Advanced Analysis" groups and
  `examples/`, or drop them now that real analyses exist?

## Proposed doc changes (for the coordinator)

- **AGENTS.md › Architecture › Script system**: add something like:
  > Dataset analyses subclass `DatasetAnalysis` and get an `AnalysisContext`:
  > an immutable `DatasetView` (`helab/analysis/dataset_view.py`) and the
  > effective parameters, never the tab. `compute` runs in the analysis worker
  > thread (`helab/analysis/runner.py`), `render` on the GUI thread. Each
  > declares `analysis_id` and `version`, and the manager records the file's
  > SHA-256. Results stay in RAM (`RamResults`), and each plot dock's source
  > line and tooltip show the record. Bundled analyses are in
  > `helab/scripts/standard/` (imported); `examples/` is still scanned.
- **AGENTS.md › Threading**: "The GUI process has no worker pools" → add "…
  except the single analysis worker thread (`AnalysisRunner`), which computes
  analyses, never source I/O."
- **AGENTS.md › Visualization**: PyQtGraph for 2D analysis plots (counts,
  histograms); Plotly via the Dash server for the 3D scatter, with Open in
  browser; `DashServer.remove_plot` when a plot closes.
- **roadmaps/analysis-workflow.md**:
  - "Current foundation": replace the `plotly_3d_sactter.py` mentions with
    `helab/scripts/standard/`.
  - First analysis: record the peeling auto-crop rule, the 100k fixed-seed
    sample, crop bounds as derived results (not parameters), and the open
    "adjust crop on plot" question.
  - Standard analyses: counts per shot and T/X/Y histograms done (v1), in s and
    m.
- **roadmaps/refactoring.md**: milestone 1 done. The dataset view contract is
  as above.
- **roadmaps/result-caching.md**: R1 done (RAM-only, bound to `ViewKey`,
  policy recorded as `ram`).
- **roadmaps/analysis-job-runner.md**: stage 1 partly done (in-process request,
  result and identity contract, no adapters). Stage 2: worker, cancellation and
  "selection can't change input" done in-process.
- **roadmaps/build-size.md**: `plotly_3d_sactter` → `helab/analysis/panes.py`
  (`PlotlyPane`).
- **.ai/memory**: a short `results/analysis-plots.md` with Tony's defaults
  (99 %, 100k, Freedman–Diaconis with override), the crop rule and the
  dock-line format.
- **.ai/MANUAL_TODO.md**: the manual checks below.

## Manual checks (not possible here)

- On screen, the real 3D scatter in the dock (QtWebEngine) and via Open in
  browser, on Tony's Mac and on a lab PC (the black QtWebEngine pane: the
  browser path must work).
- Real lab folders: are the crop bounds and histogram ranges sensible? How long
  does a large folder take (several M events, crop about 2 s per 5 M)? Does
  navigation stay responsive while it computes?
- Close and tab docks: the parameter tabs follow, and the Dash page says "Plot
  not found" after closing.

## Review fixes

From Codex's review ([review-codex.md](review-codex.md)), as Maestro asked:

1. **Immutability (finding 1, with Maestro's correction)**:
   - `read_only()` walks the `.base` chain, making each array read-only, then
     hands out `arr.view()`. With no copies, NumPy refuses both
     `setflags(write=True)` and writes, on the view and on the tab's array.
     `with_shots()` does the same.
   - The docstring calls this a guard against accidents, not a security
     boundary (trusted scripts; `.base` still reaches the buffer).
   - Tests:
     - `test_view_guards_the_loaded_shot_path` follows the real path (`np.save`,
       `np.load`, FolderCache-style `setflags(False)`) through `build_view` and
       `with_shots()`, including a writable added shot.
     - The writable-source test now expects the source to become read-only.
   - Only `dataset_view.py` changed (not `folder_cache.py`).
2. **Shortest range (finding 2)**:
   - Histograms use `shortest_range`, the exact shortest sorted sliding window
     (checked against brute force on 50 random cases).
   - `crop_box` now peels, then narrows each axis to the exact shortest window
     over the events inside the other axes, repeating while any axis narrows
     (at most 4 rounds). The `[0,1,2,3,100,101]` keep-4/6 case now gives
     `[0,3]` (tested).
   - It is still a heuristic: the parameter help and the figure say "Auto-crop
     (heuristic box)".
   - 5 M events take 2.75 s (was 1.9 s).
3. **Cancellation (finding 4)**:
   - The scatter checks between phases and passes `context.cancelled` into the
     crop (polled every 4096 peel steps and each narrowing step); the histogram
     checks per axis. `Cancelled` ends a job as `cancelled`.
   - GUI test `test_closing_a_dock_mid_run_delivers_nothing`: a dock closed
     while a blocked computation runs ends `cancelled`, with no render, no
     stored result and nothing delivered to the instance.
4. **Runner stop (finding 5)**:
   - The worker stays registered until it exits (the worker clears it in a
     `finally`), and submissions raise `RuntimeError` while it is stopping.
   - `stop()` returns whether the worker exited.
   - Test `test_stop_keeps_a_blocked_worker_registered`: the join times out,
     submit is refused, then after release one new worker takes work again.
5. **Whitespace (finding 6)**: the blank line at the end of `base.py` is
   removed; `git diff --check 376c7dd` is clean.

The screenshots in `screenshots/` were taken before these fixes. The crop
figure's label now reads "Auto-crop (heuristic box) keeps …", and its bounds
may be slightly narrower after narrowing.

**Finding 3** (what "keep 99 %" means for a cloud on a flat background) is
left as it was for Tony's decision. The rule lives only in `crop_box`, and
histogram ranges in `shortest_range`.

## Checks

- After the review fixes, `pytest -n 6 --reruns 5 --reruns-delay 1
  --basetemp=.ai/temp/pytest`: 920 passed, 2 skipped, 2 xfailed, **no
  RERUNs**. Before them: 914 passed, run twice, no RERUNs.
- `mypy helab/ --strict` (74 files), `mypy tests --strict` (53 files),
  `pyright helab tests`: no issues.
