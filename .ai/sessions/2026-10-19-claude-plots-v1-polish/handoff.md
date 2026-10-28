# Handoff: Plots v1 polish, round 1

Branch `agent/plots-v1-polish`, base `c8e3a2c`. Running list and findings:
[notes.md](notes.md). Renders: `screenshots/`. Not pushed: Maestro decides when
the round is done.

## What changed

| Commit | Change |
|---|---|
| `18c8a27` | Settings for every plot: Shots, View range, scatter points, histogram Log Y. Versions 1 → 2. |
| `29cca7e` | The centre hint hides while any plot dock is open. |
| `08a9927` | Group "Plots" renamed "Basic plots v1", from one constant. |
| `fe13ba9` | The Live pause test is ordered by two named pipes, so it no longer depends on machine speed. |
| `261b7c6` | Polish found in the renders: SI-prefix spin boxes for bounds, decade-only log labels. |

### 1. Script settings

- **Shots** (every plot): all (default), last N (default 50), or a range of
  shot numbers (From shot, To shot with 0 meaning the last). It is applied by
  `helab/analysis/selection.py` (`select_shots`). Plot titles say which shots
  were used, for example "shots 51–60 (10 of 60)".
- **View range** (scatter and histograms): auto-crop with keep % as before, or
  manual T/X/Y min and max. An axis whose min equals its max uses that axis's
  full extent, so you can set only T.
  - Scatter: the manual box sets the axis ranges, and the counts say "Manual
    range keeps …".
  - Histograms: each axis spans its manual bounds. Events outside are counted
    as before.
- **3D scatter**: Points group with point size (default 1.5 px), opacity
  (default 0.5) and display cap (default 100,000, range 1,000 to 2,000,000).
- **Histograms**: Histogram group with Bins (0 = automatic, as before) and Log
  Y. Empty bins are left out of the bars under Log Y.
- **Counts per shot**: Shots only.
- **Versions**: `helab.scatter_3d`, `helab.txy_histograms` and
  `helab.counts_per_shot` all go from 1 to 2.
- **Parameter path** (`helab/analysis/parameters.py`):
  - `ParameterSpec` gains a `choice` kind (a drop-down), a tree `group`, a
    `when` rule and `si`.
  - A parameter with `when` is shown in the tree only under its choice
    (`helab/analysis/parameter_tree.py`).
  - It is also left out of the dock's source line (`describe`).
  - The record in the dock's tooltip lists every parameter
    (`describe(every=True)`). `set_plot_result` gains `record_text` for this.

### 2. Centre hint

The cause was a visibility check: `QMainWindow.addDockWidget` shows a new
dock through a queued event. So the first dock was not visible yet when
`update_placeholder_visibility` ran, and the hint stayed. The hint now shows
exactly while no plot dock is open, whether the docks are visible or tabbed
behind each other.

### 3. Group name

The name is set in `helab/scripts/standard/group.py`, with `VERSION = 1` and
`NAME = f"Basic plots v{VERSION}"`. A later set changes `VERSION`, or adds a
second group module beside this one.

### 4. Live test

`tests/test_live_io.py::test_a_live_check_pauses_background_work_only_while_it_reads`
now uses two named-pipe TXY files, and every wait is bounded:

1. The other tab's load blocks on its pipe, which is shot 41 of 51. It stays
   blocked until the Live check has started reading, so the load is provably
   running and mid-way.
2. The load is then released and pauses at its next file.
3. The check blocks on its own last new file until that `paused` event has
   arrived, so the pause can't be missed.
4. The check is then released and finishes, and the load resumes.

The test is now skipped on Windows, like its stuck-read sibling, because
Windows has no named pipes in the filesystem. `os.mkfifo` stays inside
`if sys.platform != "win32":`.

## Decisions I made

- Shots defaults: last N = 50, and To shot 0 means the last shot.
- In a manual range, an axis with min ≥ max means that axis's full extent. All
  bounds default to 0, so choosing "manual" with no bounds set shows
  everything rather than nothing.
- The display cap is now a parameter. Its previous constant, `DISPLAY_CAP`,
  stays as the default.
- Shot selection is by shot number, not by position. "Last N" means the N
  highest shot numbers loaded, which is what Live's "last N" will want.
- Settings are grouped in the tree as Shots, View range, then Points or
  Histogram.

## Open questions for Tony

- With a manual range, the source line lists every bound, unset ones included,
  for example "X min 0 m, X max 0 m". A compact form such as "T 3.83–3.87 s, X
  and Y full" would need a per-analysis describe hook. Is it worth doing?
- Should the Live test also run on Windows by another gate, such as a
  progress-event gate without a pipe? It is POSIX-only now; before, it ran on
  Windows too, but with the timing risk.
- The earlier open questions still stand: the crop rule on real data, axes in
  mm, whether open plots count toward the RAM budget, and hashes in packaged
  builds.

## Proposed doc changes (for the coordinator)

- **AGENTS.md › Script system**: after "Dataset analyses subclass
  `DatasetAnalysis`…", add: "Parameters are `ParameterSpec`s
  (`helab/analysis/parameters.py`: float, int, bool or choice, in tree groups,
  optionally shown only under one choice); the plots share Shots and View
  range (`helab/analysis/selection.py`). The bundled plots are the group 'Basic
  plots v1' (`helab/scripts/standard/group.py`)."
- **.ai/memory/results/analysis-plots.md**: add the round-1 settings and their
  defaults, the group name with its version, and analysis versions 2.
- **.ai/MANUAL_TODO.md**: the manual checks below.

## Manual checks (not possible here)

- On Tony's Mac:
  - Change Shots, Range and Points in a plot's settings tab and press **Rerun
    with these settings**. The plot and its source line should follow.
  - The manual bounds' spin boxes should step sensibly when scrolled.
- Open a first plot: the centre hint should disappear at once. Close all plots:
  it should come back.
- Check the 3D scatter's point size and opacity in the dock and via **Open in
  browser**.

## Checks

| Check | Result |
|---|---|
| `pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest` | 965 passed, 2 skipped, 2 xfailed, no RERUNs |
| `mypy helab/ --strict` | clean, 76 files |
| `mypy tests --strict`, also with `--platform win32` | clean, 56 files |
| `pyright helab tests`, and `pyright tests --pythonplatform Windows` | 0 errors |
| `git diff --check c8e3a2c` | clean |
| Live test alone | passed 3 times |
| Live test beside the GUI and lane tests under `-n 6` | passed 8 times |

## Review fixes (round 1)

From Codex's review ([review-codex.md](review-codex.md)), as Maestro asked:

1. **Reversed manual bounds (`acecb0a`).**
   - An axis with min > max still uses its full extent, but the plot now says
     "X: min > max, using full extent" in every place it is read: the scatter
     figure, its note and tooltip, that axis's histogram title, the dock's
     source line, the record ("Warning: …") and the settings tab's status line.
   - `selection.reversed_axes` and `range_warnings` compute it, and
     `DatasetAnalysis.parameter_warnings` passes it to the dock.
   - The tree still accepts the pair. Rejecting it would fight the user
     mid-edit, for example while they type the max before the min. The bound's
     tooltip says what a reversed pair does.
   - Tests: `test_reversed_manual_bounds_use_the_full_extent_and_say_so` and
     the GUI test
     `test_reversed_manual_bounds_are_reported_in_the_dock_and_settings_tab`.
2. **FIFO writer (`b1383c1`).**
   - `release()` opens with `O_WRONLY | O_NONBLOCK`. It retries ENXIO every
     20 ms until a 10 s deadline, then fails the test. A reader that has exited
     can no longer hang it.
   - A direct check: releasing a FIFO that no one opens failed after its 0.5 s
     timeout.
   - Round 2 replaces both FIFO tests with a cross-platform read gate.

Checks after both fixes:

| Check | Result |
|---|---|
| Full suite | 967 passed, 2 skipped, 2 xfailed, no RERUNs |
| `mypy --strict` helab and tests, also `--platform win32` | clean |
| `pyright helab tests`, also tests on Windows | clean |
| `git diff --check c8e3a2c` | clean |

## Round 2

| Commit | Change |
|---|---|
| `8f9060f` | The plot dock's source is two compact lines, through a per-analysis describe hook. |
| `2f61ed6` | Both Live I/O tests run on every platform, using a helper read gate instead of FIFOs. |

### 5. Two-line source

The dock now shows:

```
Data source: run_042 · rev 1 · shots 51–60 (10 of 60) · helab.txy_histograms v2
last 10 shots · auto-crop 99 % · bins auto · log Y
```

- **Line 1** keeps the existing "Data source" or "Showing previously loaded
  data" prefix, which flags a stale plot. It adds which shots the run used.
  - Keeping the prefix also leaves `tests/test_folder_summary.py`, which I
    don't own, unchanged.
  - Say if Tony wants the prefix dropped for current data, as in his example.
- **Line 2** gives the settings in short form.
  - A manual range lists only the axes actually set, each with one SI prefix,
    for example "T 3.84–3.87 s, X −2–3.5 mm".
  - Unset and reversed axes are left out. A reversed axis keeps its ⚠ warning
    on this line.
  - "All shots" and "Log Y off" are left out. The scatter shows its display
    cap only when it differs from the default.
  - Counts per shot with all shots is a single line.
- **Tooltip**: the full record, with every parameter.
- **Hook**: `DatasetAnalysis.describe_run(action, values, view)` returns
  `(selection, settings)`. The default keeps the generic "title value" form
  for lab scripts loaded with Load Scripts…. The short forms live in
  `selection.py`.
- **Vertical space**: the label never wraps, and a long line is cut at the
  dock's edge. Its layout has zero vertical margins and spacing, so the label
  is at most two lines. Renders: `screenshots/source_lines_*.png`.

### 6. Live I/O tests on Windows

- **Seam** (`helab/io_helper.py`; nothing else there changed):
  - With `HELAB_TEST_READ_GATE=<dir>`, a TXY read of `<name>` first waits until
    `<dir>/<name>.go` exists, polling every 20 ms. This covers both a load's
    read and a Live check's read.
  - While waiting, the helper sends nothing, like a read still in progress.
    So a gate that is never opened stands in for a stuck read, and the
    parent's per-file timeout stops it.
  - Unset, as in production, each read costs one `is None` check.
- **Tests**: both use a `ReadGate` fixture. The skips, `os.mkfifo`, the FIFO
  writer and its POSIX guards are gone, and every wait is a bounded
  `qtbot.waitUntil`.
  - The pause test holds the background load on one file until the check
    reads, then holds the check on its last file until the load's `paused`
    event arrives.
  - The stuck-read test uses a real file whose gate is never opened.
  - Gates go by file name, so the pause test's folders use different shot
    numbers.
- **Evidence**:

  | Run | Result |
  |---|---|
  | Seam disabled | both tests fail |
  | Beside the Live and GUI tests under `-n 6`, 10 times | 43 passed each time |
  | 3 rounds of 12 copies of each test under `-n 6` | 72 runs, all passed, reruns off |

- **Not yet run on Windows itself.** Maestro will run them on a real Windows
  PC.

### Proposed AGENTS.md wording (Testing)

In the Testing section, replace "Production code reads two test seams:
`HELAB_TEST_LOCAL_MOUNT` (Windows: one local mount) and `HELAB_TEST_VOLUME_ID`
(a fixed volume ID)." with:

> Production code reads three test seams: `HELAB_TEST_LOCAL_MOUNT` (Windows:
> one local mount), `HELAB_TEST_VOLUME_ID` (a fixed volume ID) and
> `HELAB_TEST_READ_GATE=<dir>` (`helab/io_helper.py` only: a TXY read of
> `<name>` waits until `<dir>/<name>.go` exists, sending nothing meanwhile, so
> tests order reads on every platform and a gate never opened is a stuck read;
> `tests/test_live_io.py`).

Also update **AGENTS.md › Script system**, after the round-1 wording: "Each
plot dock's source is two lines, the input and the settings in short form
(`DatasetAnalysis.describe_run`), with the full record in the tooltip."

### Checks after round 2

| Check | Result |
|---|---|
| `pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest` | 968 passed, 2 skipped, 2 xfailed, no RERUNs |
| `mypy --strict` helab and tests, host and `--platform win32` | clean |
| `pyright helab tests`, host and `--pythonplatform Windows` | clean |
| `git diff --check` | clean |
