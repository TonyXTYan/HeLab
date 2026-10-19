# Handoff: D7 shot times

Branch `agent/dld-d7` (base 1231025, `agent/dld-front-panel-port`). Not pushed, not merged.
Design, I/O cost, cache format and proposals: [notes.md](notes.md). Brief: [brief.md](brief.md).

## Done

1. **Plumbing** (commit 9690f48). A shot's time is its raw `d<N>.txt` mtime, from the helper's
   own load and Live listings: raw entries are kept and stat'ed only for shots whose time isn't
   known (read now, cached without a time, or re-read for the cache). Times travel as
   `raw_times` (`loaded`) and `raw_mtime` (`shot`), are merged by `FolderCache`
   (`dataset_raw_times`, kept across resumed loads, sent to Live's save), and are saved in a
   new `datasets.raw_times` column of `store-v3`, added to existing stores on open. Old rows
   read as `[]`. `DatasetView.shot_time` / `shot_times` / `fallback_times`: raw time, else the
   TXY fingerprint's mtime, flagged. Fingerprints, signatures and reuse are unchanged.
2. **Plot** (commit 4a0a277). "Shot times" in Basic plots v1
   (`helab/scripts/standard/shot_times.py`): events per shot and gaps between shots against a
   date axis (Show: both / counts / gaps; Log gaps), shared Shots selection, amber triangles
   and "⚠ N TXY times (no raw file)" in the title and dock line, in-place updates for Live,
   tooltip caveat about copied or rewritten files.

## Remaining / not done

- D2's trend plots can use `DatasetView.shot_times()` for a time axis when they are built.
- Old caches gain times only on a listing check of the folder (first full check, Retry /
  Refresh), not on the one-stat quick check (notes, Proposed 3).
- No AGENTS.md change was made (it's not this Worker's file); proposed text is below.

## Checks

- Full suite, `PATH=venv/bin:$PATH python -m pytest -n 2 --reruns 5 --reruns-delay 1
  --basetemp=.ai/temp/pytest -rR` at 4a0a277: **2 failed, 1299 passed, 7 skipped, 2 xfailed,
  10 rerun in 172.42s**. The 2 failures (and all 10 reruns) are the known root-only ones:
  `test_constants.py::test_read_only_saved_folder_is_replaced`,
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`.
- An earlier full run without the venv on `PATH` also failed the 4 `test_typing.py` tests:
  they call bare `mypy`, which found `/root/.local/bin/mypy` without numpy. Environmental:
  they pass with the venv's mypy. That run also needed one RERUN of
  `test_analysis_gui.py::test_scatter_from_the_panel` (a Dash/web view test; passed on retry,
  and on the second full run without a rerun).
- `mypy helab/ --strict`, `mypy tests --strict` (also `--platform win32`), `pyright helab tests`
  (also `--pythonplatform Windows`): clean. `git diff --check`: clean.
- New/changed tests: `tests/test_shot_times.py` (helper raw times, TXY fallback, cache round
  trip without a raw restat, RAM update stats only new shots, deleted raw file keeps the cached
  shot and its time, pre-column cache loads and fills times, Live read and save, FolderCache
  merge through an update, plot compute / gaps / title / dock lines / gap units / empty cases /
  render / in-place update), `tests/test_cache_store.py` (column, pending save, migration),
  `tests/test_io_trace.py` (trace counts gain `load: shot time`), `tests/test_live_plots.py`
  (Live-following update in place; coverage and Live-policy lists), bundled-script lists in
  `test_analysis.py` and `test_script_system.py`.

## For Tony: on-screen checks

1. Load a real run folder with raw files, open Shot times: the times match when shots were taken
   (compare a few `d<N>.txt` mtimes in Finder/Explorer), not the TXY conversion times.
2. A folder whose raw files were deleted or never copied: amber triangles, the count in the
   title and dock line, the tooltip's caveat.
3. Live: new shots join both plots in place; zoom and pan stay.
4. A folder cached before this change: shots show amber until Refresh (or the first full check);
   after Refresh, blue.
5. Show = counts / gaps and Log gaps: one plot; negative gaps (a shot timed before the one before
   it) drop out on the log axis.

## For Tony: real-volume (SMB) checks

1. Record an I/O trace (Help › Record I/O trace) while loading an uncached folder on the share:
   one `entry_stat` with reason `load: shot time` per raw file of a shot read; none when loading
   it again from the cache (`trace_summary.py`).
2. The same during Live: one `live: shot time` per new shot; none on unchanged checks.
3. Load time of a large uncached folder before and after this branch (the raw stat is one extra
   metadata request per shot read).
4. On Windows, the raw stats should be `syscall: false` in the trace (from the listing).

## Proposed AGENTS.md text, for Tony

In **Responsive filesystem I/O**, after the "Files still being written" item:

> - **Shot times** (D7): a shot's time is its raw `d<N>.txt` file's mtime (Tony, 2026-10-20). A
>   load's or Live check's own listing keeps the raw entries and stats one only for a shot whose
>   time isn't known (a shot read now, one cached before shot times, one re-read for the cache;
>   free on Windows): never for shots held in RAM or cached with a time, never in quick checks,
>   cached reads or Live's save (the app sends its times). Raw files never enter fingerprints,
>   signatures or reuse; a deleted raw file keeps the shot and its time. Without a raw time the
>   shot's time is its TXY fingerprint's mtime, flagged (`DatasetView.fallback_times`).

In **Caching**, after the sentence on per-shot fingerprints:

> Shot times are the `datasets.raw_times` column (`[shot, mtime_ns]`, `[]` for rows saved before
> it; added to older store-v3 databases on open, no layout bump), not `info`, which listings read
> per subfolder. `loaded` carries `raw_times` and `shot` events `raw_mtime`; `FolderCache`
> merges them with the base's for held shots (`dataset_raw_times`); `confirm_dataset` fills times
> an older cache lacked.

In **Script system**, the bundled list: add **Shot times** (`shot_times.py`): events per shot and
gaps between shots against shot time, TXY-time shots amber and counted.
