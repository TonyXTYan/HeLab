# Review: Plot RAM budget

Reviewer: a fresh Claude (Opus 5.5), read-only. Reviewed `git diff 531ec41...ebf674d` against
the brief and Tony's decisions, not the handoff's account of it.

## Verdict

**Changes requested before landing.** Nothing breaks the I/O rules: a reload never touches the
source folder, rendering never measures RAM, and no plot is ever closed. But two bugs go against
Tony's decisions, and a reviewer probe confirms both (#1, #2). Both fixes are small. #3–#5 are
design points that need a decision or a small change.

## Checks (rerun from the floor root, with venv and floor-env)

- `pytest -n 6 --reruns 5 --reruns-delay 1 -rR --basetemp=.ai/temp/pytest-review`: 1272 passed,
  2 skipped, 2 xfailed, **no RERUN** (72 s).
- `mypy --strict helab/` and `mypy --strict tests`, each also with `--platform win32`: no issues.
- `pyright helab tests` and `pyright --pythonplatform Windows helab tests`: 0 errors.
- `git diff --check 531ec41..HEAD`: clean.
- Probe tests (untracked, gitignored): `.ai/temp/review-probe/test_review_probe.py`. Run them
  with `PYTHONPATH=tests pytest .ai/temp/review-probe/test_review_probe.py -p conftest --rootdir=. -s`.
  Both fail on this branch, which confirms #1 and #2.

## Findings, most severe first

1. **"Datasets first" breaks after the first plot is released.** `helab/analysis/budget.py:300-311`.
   `check()` calls `evict_to(limit)` once, before the release loop. Take a plot of a held,
   unshown dataset. While the plot holds that dataset's arrays, eviction keeps the dataset
   ("frees nothing"). Releasing the plot then makes the dataset freeable, but the loop never
   evicts again, so it releases the next plot instead. Nothing later evicts the dataset either,
   because usage is then under 80 %.
   Probe: dataset A (4 units, unshown) with plot P_A on it, plot P_B with its own data, and
   plot P_C shown. Total 14 units, limit 9. Result: P_A and P_B are both released and A stays.
   Expected: P_A released, then A dropped, then P_B kept.
   Fix: after each successful `release()`, call `self.cache.evict_to(limit)` again and re-measure
   before the next candidate. `datasets = held_buffers()` must then be recomputed too. Add this
   scenario as a test.

2. **A reload whose run fails (or is cancelled) leaves the plot released but holding its
   restored arrays, and it can never be released again.** `helab/models/ScriptTreeSelector.py:619`
   (`follow.start(view)` makes the restored view `follow.ran`), `:624-665` (`_finished` keeps it
   on failure or cancel) and `:855` (`releasable` needs `released is None`).
   Probe: release, then reload with a script that raises. The plot is still released, but
   `ram_buffers()` = 3 shots and `releasable()` = False, so `plot_bytes` counts memory the
   budget can never free.
   Fix: when a run ends without drawing while `self.released is not None`, put
   `follow.ran = hollow(follow.ran)` back (likewise `_job_view` is already None). Or let a
   released plot that still holds buffers be hollowed again by the budget.

3. **A release can cost more RAM than it frees, and pictures are not counted.**
   `ScriptTreeSelector.py:872` (`snapshot`) and `budget.py:307`.
   - The picture is a full-size `QPixmap` of the plot area: on Retina, ×4 for the device pixel
     ratio, so about 8–25 MB per released plot. It stays until the plot reloads and is never
     counted in `Usage`.
   - Take a plot whose folder is still held, e.g. a histogram. Its only own buffers are its
     result arrays, often a few kB. `any(key not in datasets …)` still passes, so releasing it
     *adds* RAM. Many released plots add up.
   - Suggestions: keep the picture as PNG bytes (`QPixmap.save` into a `QBuffer`; plots compress
     to around 100 kB) and decode it in `paintEvent`. Skip candidates whose own bytes are below
     the picture's cost, or count released pictures in `plots`.

4. **A reload doesn't keep exactly the plot's shots when some changed or are missing.**
   `budget.py:150` (`restore`) and `ScriptTreeSelector.py:997` (`_reload_from`).
   - `restore` keeps every shot of the hollow view whose fingerprint matches, not just the
     drawn shots (`shown.coverage.shots`). Shot selections then re-select. For example, a plot
     of the "last 10" with shot 1000 missing redraws 990–999 plus shot 989, which it never drew.
   - Meanwhile the amber line says "without 1 of its 10 shots: shot 1000 missing", which implies
     the other 9.
   - Suggestion: for Reload and auto reload with the drawn settings, restrict the restored view
     to `coverage.shots`. Rerun with new settings can keep the full hollow view's shots. Worth
     Tony's word: "takes exactly the plot's shots".

5. **Unpinned results in `RamResults` aren't small for the 3D scatter.**
   - `ScatterData.points` is a fancy-indexed copy (`scatter_3d.py:141`): 100k × 3 float64 =
     2.4 MB at the default cap, and up to 48 MB at the 2M cap.
   - `RamResults` keeps up to 64 older results, e.g. a Live-following scatter's reruns. That is
     about 150 MB uncounted at the default cap and up to about 3 GB at the maximum.
   - Releasing a plot doesn't free them either.
   - So the handoff's "results are small" holds for histograms and transfer fractions only.
   - Suggestion: count unpinned results' arrays (`arrays_in`) in `plot_bytes`, or cap
     `RamResults` by bytes as well as by count.

6. **Low: a disk read finishing during a Live run is not handled.** `ScriptTreeSelector.py:973`.
   - `_reload_event` → `_reload_from` → `_submit` doesn't check `self.job_id`. If Live started
     on the folder and a revision run is in flight, that run's result is dropped (job id
     mismatch). The plot then draws the older restored revision and waits for the next revision.
   - Fix: at completion, if `self.job_id`, drop the reload, because the run in flight will draw
     the plot.

7. **Low: auto reload runs on every `plotShown`**, which fires on each focus or click of the
   plot (`:904`).
   - A plot whose data is nowhere asks for a new local-lane `cached` read on every click.
   - Suggestion: remember a failed reload until its folder's `datasetChanged` or a manual
     Reload.
   - Also tell Tony: with a budget that fits one plot, switching between two plots reloads one
     and releases the other each time. That is by design, but he will see the reruns.

8. **Low: there is no hysteresis at 75 %.** The window re-opens on every upward crossing, so a
   level hovering near 75 % (a folder dropped and loaded again) re-opens it each time. This
   meets "once per crossing" literally. Suggestion: re-arm only below about 70 %. 80 % is fine:
   a release always lands at or below 80 %.

9. **Low: the 3D scatter picture is unverified.**
   - `test_the_scatter_keeps_a_snapshot_of_its_last_frame` checks only that the pixmap is not
     null, which any offscreen grab satisfies.
   - A scatter that was never on screen (opened behind a tab) has a web view that never painted,
     so its picture will be blank. Keep checklist item 4: macOS and a lab PC.

10. **Low, structure, for landing.**
    - `helab/utils/folder_cache.py:20` now imports `helab.analysis.budget`, so utils depends on
      analysis. The buffer helpers (`Buffers`, `buffer_of`, `dataset_buffers`) could live in
      `helab/utils/`.
    - `budget.fingerprints_of` duplicates `dataset_view._fingerprints`.
    - `PLOT_AUTO_RELOAD_SETTING` sits in `budget.py`, while every other settings key is in
      `helab/utils/constants.py`. The coordinator can move it at landing.

## The brief's checklist

1. **Accounting.**
   - Correct: arrays are counted by buffer, with `.base` chains and memoryview/`frombuffer`
     owners walked, so shared shots count once (tested).
   - `DatasetView` is `eq=False`, so the per-view cache is keyed by object identity and a hollow
     view never takes a full view's cached bytes.
   - `Dataset.data` is never changed in place, so the per-dataset cache keyed by shot count is
     safe.
   - No cost during rendering: measuring runs in a queued `check()`, and the status bar and
     tooltip update only on `changed`.
   - `_evict` now walks each plot's result arrays on every eviction. That is cheap, and not on
     a render path.
2. **Thresholds.**
   - Crossing logic is correct, with the window once per crossing (tested).
   - At 75 % the window can re-open while usage hovers there (#8). At 80 % there is no flapping.
3. **Order and exemptions.**
   - Correct: not-on-screen plots go first, then least recently shown. The shown, running,
     reloading, pending and Live-following plots are exempt, and nothing is closed (tested).
   - No race with runs: everything happens on the GUI thread, and `releasable` needs no job,
     nothing pending and no reload in flight.
   - Live revisions that arrive after a release draw the plot again correctly. The one race is
     a disk reload finishing during a run (#6).
   - Bug: "datasets first" after a release (#1).
4. **Released plots.**
   - The view and result are freed: the weakref test checks the shot arrays, and
     `set_plot_result` keeps only strings on the dock.
   - The Dash figure is freed (`PlotlyPane.destroyed` → `remove_plot`, tested).
   - The hollow view keeps shot numbers and fingerprints (tested).
   - The picture costs RAM (#3), and the scatter picture is unverified (#9).
   - Test gap: a weakref on the result's own data.
5. **Reload.**
   - It reads RAM, or makes a local-lane `cached` read. That is never the source folder:
     `read_cached` opens only the store, and `FolderCache` starts no follow-up check for it.
   - Fingerprint matching works, with an amber line for changed or missing shots and the
     picture kept when nothing is found (tested).
   - Auto reload follows the setting, and Rerun on a released plot works (tested).
   - Cancelling the subscription after `loaded` is safe on the real path: the job is already
     forgotten, so a tab's shared read isn't cancelled. The tests emit `resultReady` directly,
     so they don't exercise that path; I read it.
   - Gaps: exact shots (#4), a failed reload holding RAM (#2), and repeated reads (#7).
6. **Runner fix.** Correct and worthwhile: the loop variables kept the last `(script, context)`
   and its view alive while the worker was idle. `_run`'s frame now ends with each job.
7. **Ownership.**
   - The `SettingsDialog.py` line is needed: without it, Save after Reset all wrote the stale
     checkbox value.
   - The settings key belongs in `constants.py` at landing (#10).
   - No I/O file was changed beyond RAM accounting in `folder_cache.py`. The reload uses the
     existing `submit(..., "cached")` API.

## Views on the worker's open points

- **Datasets dropped below 100 % only when a plot could otherwise be released.** Agree: it keeps
  today's behaviour when no plot is involved. It also needs #1: re-evict after each release,
  otherwise "datasets first" fails exactly in this case.
- **"Least recently viewed" = least recently shown in Settings, plots not on screen first.**
  Agree. It is the best signal available, and it matches what Tony sees.
- **Not counted.**
  - Plot widgets' own copies: acceptable, since a release frees them. The scatter's Dash
    figure, 100k points as JSON lists, is roughly 10 MB and could get a rough estimate later.
  - Unpinned `RamResults`: disagree. They are not small for the scatter (#5).
  - The Live feed: agree. Its views are the pinned Live dataset's arrays, already counted.
- **Add to the list: released plots' pictures (#3).**

## Recheck at e261905

Reviewed `git diff ebf674d..e261905` (10 fix commits), plus new probes in
`.ai/temp/review-probe/test_review_probe.py`.

**Verdict: one blocker, a regression from the #3 fix.** Every other item is fixed as described.

### Blocker: a plot whose data is a loaded folder no tab shows is never released, so the folder is never dropped either

`budget.py` `RamBudget.frees` (used at `check()`: `if frees <= plot.picture_cost(): continue`).
`frees` leaves out every buffer that a held dataset or *any* other plot has. Both of these cases
are common, and in each the plot's own bytes are just its small result:
- **One plot, folder held but unshown** (histograms of a folder you've moved on from). `frees`
  is a few bytes, below the PNG's cost (about 10 kB offscreen, more on screen), so the plot is
  skipped. `_evict` keeps the folder because a plot holds its arrays. Nothing ever goes.
  Probe `test_one_small_plot_of_a_held_unshown_folder`: usage stays at 42 units against a limit
  of 10, with the plot and the folder both kept.
- **Two plots, folder no longer held** (T and X histograms of one folder). Each plot's `frees`
  leaves out the shared shots because the other plot holds them, so both are skipped and the
  shots stay. Probe `test_two_small_plots_of_one_unloaded_folder`: neither is released, and usage
  stays at 42 units against a limit of 10.

At ebf674d the first case at least released the plot. Now nothing is freed, while the status
bar and the 75 % window keep warning. `test_a_release_must_free_more_than_its_picture_costs`
covers only a folder shown in a tab, where skipping is right.

Suggested fix: count as freed what the release makes freeable. That is the plot's buffers held
by neither a dataset shown in a tab (`pins`) nor a plot that won't be released (the shown,
running or Live plot, or one that isn't a candidate). Unshown datasets are then dropped by the
`evict_to` that follows each release, and fellow candidates are released next by the same loop.
Alternatively, judge a group of candidates that share buffers together. Add both probes as tests.

### The items asked about

- **#1 Datasets first:** fixed. `evict_to` runs and `held_buffers` is recomputed after each
  release (`test_datasets_go_first_again_after_each_release`; my probe passes).
- **#2 A failed or cancelled reload:** fixed. `_still_released` hollows `follow.ran` on cancel,
  a pinned Live rerun and failure. My probe now finds only the picture's PNG (5 kB) in
  `ram_buffers`, which is by design.
- **#3 PNG pictures:**
  - Pictures are kept as PNG bytes (`Picture`) and counted in `ram_buffers` and so in
    `plot_bytes` (tested).
  - A release is skipped when it frees no more than the picture costs (`release(frees)`), and
    the cost is remembered, so later checks don't grab again.
  - But see the blocker for how `frees` is computed.
  - Low: `PlotPicture.paintEvent` decodes the PNG on every paint. That is CPU, not RAM, and is
    noticeable only while a window is resized.
- **#4 Exact shots:** fixed. Reload and auto reload restore only `coverage.shots`. Rerun with
  new settings uses the view's shots. `Restored.asked` counts the shots asked for in the amber
  line (`test_a_reload_takes_exactly_the_shots_the_plot_drew`).
- **#5 Results each plot keeps:** fixed. `_runs` follows each run's job id. `ram_buffers`
  counts every completed result still in `RamResults`, and uses `peek` so the result isn't
  touched as recently used. `_forget_runs` discards them on release and on close, keeping the
  job in flight (`test_older_results_count_and_go_with_a_release_or_close`).
- **#6 A disk reload ending during a run:** fixed. The reload is dropped and the run draws
  (`test_a_disk_reload_ending_during_a_live_run_leaves_that_run`).
- **#7 Auto reload:**
  - `plotShown` now fires only when the shown plot changes.
  - After a failed reload, `_nowhere` stops auto reload until `datasetChanged` or
    `diskCacheChanged` fires for the folder (both `pyqtSignal(str)`, compared with
    `FolderCache.key`). Reload always tries, and close disconnects the signals.
  - The grace period: a plot drawn by a reload in the last 10 s is ordered after the others
    (`recently_reloaded`), which stops two plots from releasing and reloading each other.
  - Tested (`test_auto_reload_tries_once_until_the_folder_changes`,
    `test_a_plot_just_reloaded_goes_after_the_others`).
- **#8 Hysteresis:** fixed. The window opens again only after usage drops below 70 %.
- **#9 / #10 Structure:**
  - `helab/utils/` no longer imports `helab.analysis` (only comments name it). The buffer
    counting is in `helab/utils/ram_buffers.py`.
  - `fingerprints_of` is shared from `dataset_view`. The setting and its reader are in
    `constants.py`.
  - Nit: a dead duplicate `PLOT_AUTO_RELOAD_SETTING` is still at `budget.py:47`.

### Checks at e261905

- `pytest -n 6 --reruns 5 --reruns-delay 1 -rR --basetemp=.ai/temp/pytest-review`: 1281
  passed, 2 skipped, 2 xfailed, **no RERUN** (62 s).
- `mypy --strict` on helab/ and tests, each native and with `--platform win32`: no issues.
- `pyright helab tests`, native and `--pythonplatform Windows`: 0 errors.
- `git diff --check 531ec41..HEAD`: clean.

## Recheck at fa75cc9

Reviewed `git diff e261905..fa75cc9` (1f3f340: `frees`; 2ce2e77: decoding the picture), plus
`.ai/temp/review-probe/test_review_probe.py` with one new probe.

**Verdict: the blocker is fixed. No blocker remains. One should-fix: a needless release when
plots share buffers.** Tony or the coordinator can choose to land with it as a known
limitation.

### The blocker: fixed

- `frees(plot, staying)` leaves out only buffers held by a dataset shown in a tab
  (`FolderCache.shown_buffers`, the pins) or by a plot that stays. Those are the
  non-candidates, plus candidates skipped or not released earlier in the same check.
- Both of my probes pass, and they are now tests (`test_one_small_plot_of_a_held_unshown_folder`,
  `test_two_small_plots_of_one_unloaded_folder`).
- The shown-in-tab skip still holds (`test_a_release_must_free_more_than_its_picture_costs`).
- My earlier probes pass too. The failed-reload probe still fails, but only on the released
  picture's PNG in `ram_buffers`, which is by design.

### Should-fix: a release that pays off only if a later candidate goes too

`budget.py` `check()` / `frees`. Candidates later in the order don't count as staying, so the
shots a plot shares with a later candidate count as freed. If the loop gets under 80 % before
that later candidate, the shared shots are never freed, and the first plot was released for
nothing.

Probe `test_no_needless_release_on_a_shared_buffer`:
- P1 and P2 are small plots of one folder no longer held (40 shots). P3 has its own data
  (4 units). P4 is shown. The order is P1, P3, P2, and usage is 3 units over the limit.
- Result: P1 is released, then P3, and P2 stays. Releasing P3 alone was enough.
- P1's release freed 8 bytes and added a ~10 kB PNG. It lost interactivity and will rerun when
  shown.

This is plausible in practice: T and X histograms of a folder you've moved on from,
interleaved with other plots in the order. The cost is mild: one extra plot shows a picture and
reloads when shown, with no data at risk.

Suggested fix, two passes:
1. Release in the LRU order only plots whose release frees more than their picture *with every
   other plot counted as staying*.
2. Only if usage is still over 80 %, use the current rule, which lets candidates that share
   buffers go one after another.

Alternatively, treat candidates that share buffers as one group, released whole or not at all.

### What was asked

- **No new way to free a shown plot's data:** confirmed.
  - `frees` only decides which candidates go.
  - `order()` still leaves out the shown plot, and `releasable()` is unchanged (running,
    reloading, pending and Live plots are exempt).
  - `evict_to` drops only datasets no tab shows, and keeps one whose arrays plots hold.
  - Releasing other plots never touches the shown plot's views.
- **Folders first:** confirmed. `evict_to(limit)` runs before the loop and again after each
  release.
- **Exemptions:** confirmed; `test_release_order_and_exemptions` passes unchanged.
- **Releases more than needed:** one case, the should-fix above.
- **Picture decoding (2ce2e77):** fine. The PNG is decoded once while the picture shows, and the
  decoded pixmap is dropped on `hideEvent` (Qt sends it to visible children when a dock tab is
  hidden), so only the PNG stays behind tabs (tested). While it shows, the decoded pixmap isn't
  counted. That is acceptable, since only plots on screen have one.
- **Nit from the last recheck:** the duplicate `PLOT_AUTO_RELOAD_SETTING` is gone from
  `budget.py`.

### Checks at fa75cc9

- `pytest -n 6 --reruns 5 --reruns-delay 1 -rR --basetemp=.ai/temp/pytest-review`: 1283
  passed, 2 skipped, 2 xfailed, **no RERUN** (58 s).
- `mypy --strict` on helab/ and tests, each native and with `--platform win32`: no issues.
- `pyright helab tests`, native and `--pythonplatform Windows`: 0 errors.
- `git diff --check 531ec41..HEAD`: clean.
