# Quick Fixes 5: notes (Tinker, Claude Code)

## Job 1: `test_disk_cache_summary_tracks_shared_save_completion[cache_saved]` reruns on macOS CI

**Symptom.** `assert 'Cached data loaded · Cached just now · Freshness unknown' == 'Cached data loaded ·
Cached just now'` (`tests/test_folder_summary.py` ~413), macOS CI runs 40279097363, 40679555921 (3×),
40753079487, 40754538456, 40758706117.

**Cause (the test is wrong, not the app).** "Freshness unknown" comes from
`SnapshotFileSystemModel.data_freshness` → `cache_freshness(as_of, node.modified)`: the save date was
there ("Cached just now"), so the second tab's root row had no folder modified time (`node.modified is
None`). The second `FolderExplorer` gets two things on separate zero-timer passes:

1. `open_to_path` (a `QTimer.singleShot(0)` from the constructor) selects the folder, and the test's
   `selectionPathChanged` hook → `load_to_ram_cache` → `_show_cached` → `_display` shows the shared
   dataset from RAM at once. At that moment the row has no `modified` yet.
2. The tab's listing is answered from the shared snapshot by `FolderCache._replay`, which emits its
   `status` (with `modified`) from another `QTimer.singleShot(0, batch)`, i.e. on a later loop pass.

The test waited only for `second.displayed_dataset is not None`. `qtbot.waitUntil` re-checks after each
`qWait`; when one event-loop pass is slow (a loaded macOS runner), `qWait` returns after step 1 and
before step 2, the condition is true, the test emits `cache_saved`, and the label is computed while the
row's date is still missing.

**Evidence.** A probe (not committed) logging `_observe_modified`, `_display` and the wait's polls
showed, in a normal run, `_display second mod=None` followed by the replay's `observe … -> <mtime>`
within the same wait. Adding a 50 ms sleep after `_display` (a slow loop pass) made the poll see
`ds=True mod=None`, and the label became exactly the CI string
`'Cached data loaded · Cached just now · Freshness unknown'`, every time. The same probe showed that
when the replay arrives (one timer later) the label corrects itself to `'Cached data loaded · Cached
just now'` with nothing else happening, so a user sees at most a single-pass transient: no app change.

**Fix.** `tests/test_folder_summary.py`: the wait also requires the second tab's root row to have its
folder date (`second.model.nodes[path].modified is not None`), with a comment saying why.

**Checks.**
- With the 50 ms `_display` slowdown injected (probe fixture, all three params): unfixed test fails
  `[cache_saved]` with the CI assertion; fixed test passes all three.
- Stress loops of the whole module with its neighbours (`tests/test_folder_summary.py -n 6 -p no:randomly`,
  62 tests a run) under busy-loop CPU hogs: 25 runs / 6 hogs gave 24 clean and **one run with one
  failure that I could not identify**: that loop kept only each run's summary line ("1 failed, 61
  passed"), so neither the test nor the reason is known. Two more loops that kept every run's output
  (30 runs / 6 hogs, 40 runs / 10 hogs) were all clean (70 × 62 passed). It may have been this test, a
  neighbour, or load from the type checks I ran beside that first loop; worth watching on CI.
- Full suite, `-n 4 --reruns 5 --reruns-delay 1`: basetemp `.ai/temp/pytest` 8039 passed, 669 skipped,
  no reruns; basetemp outside the checkout (scratchpad) 8039 passed, 669 skipped, no reruns.
- `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`, `mypy --platform win32 --strict`
  (helab/ and tests), `pyright --pythonplatform Windows helab tests`: all clean.

**Proposed known-issues change.** Close the `test_folder_summary.py::…[cache_saved]` entry (Tests and
CI): "Fixed (agent/quick-fixes-5): the test waited only for the second tab's dataset, which shows from
RAM a zero-timer before the shared listing's replay brings the row's folder date; a slow loop pass let
the wait return between them. The test now waits for the date too; the app's label corrects itself one
timer later." In the 2026-10-28 run 40679555921 entry, note that this test's 3 reruns had this cause.
