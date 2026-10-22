# Review findings (Lens, Claude Fable 5.1)

Branch `agent/codebase-review` at `fc0f50d`; brief: [brief.md](brief.md). Each finding: ID,
severity (blocker / high / medium / low / quality), file:line at `fc0f50d`, what goes wrong and
when, suggested fix. "Unsure" marks what I couldn't confirm by reading or a probe. Mend records
outcomes in `notes.md`; I review each fix commit before the batch counts as done.

Baseline at `fc0f50d` (floor venv, `source .ai/local/floor-env.sh`):
`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: 2378 passed, 2 skipped,
2 xfailed, **no reruns**, 86 s. `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`:
clean.

## Area 1: `helab/io_ops/`, `io_helper.py`, `io_service.py`, `cache_store.py`, `folder_cache.py`, roots

No blocker or high finding. Already known and not repeated: `roots_verify` missing from
`io_helper.CACHE_ONLY`; helper folders in the system temp dir.

### R-1 · medium · the quick check compares the share's clock with this computer's

`helab/io_ops/loading.py:131` (`_unchanged_since_cache`: `modified > as_of`) and `:174`
(`_unchanged_since_memory`: `modified > listed_at`); the recorded side is `snapshot_at` /
`listed_at` = `time.time()` on the client (`loading.py:287`, `:631`; `cache_store.confirm_dataset`
keeps it client time too).

The folder's mtime is set by the file server (SMB) in the server's clock; `snapshot_at` is this
computer's clock. With the lab server's clock behind the client's, a new shot written after the
cached listing gives a folder mtime *earlier* than `snapshot_at`, the sample stats see only cached
files, and the check answers `unchanged`: the new shot isn't shown until something forces a full
listing (Retry / Refresh, or a later change that overtakes the skew). Confirmed by a probe
(`tests/test_cache_first.py` helpers; removed after running): cache 2 shots, add shot 3, set the
file's and folder's mtime 30 s back → `loaded` with `unchanged: True`, `files: 2`. A server
clock *ahead* only costs an unnecessary full check. Live's own check is immune (it compares
`since == folder.st_mtime_ns`, `live.py:92`), which is the model to follow; Live's `racy` test
(`live.py:73`, `abs(time.time() - st_mtime)`) has the same class of exposure but only widens or
narrows a 2 s window.

Fix: compare mtimes with mtimes, never with the client clock. Stat the folder *before* the
listing (as `live_check` does; `_summary` stats it after, which would miss a file added during
the listing) and save its `st_mtime_ns` in the dataset's `info` (e.g. `folder_mtime_ns`, written
by `_write_dataset` and refreshed by `confirm_dataset` from the confirming load's pre-listing
stat); the quick check then requires `folder.st_mtime_ns == info["folder_mtime_ns"]`, and falls
back to today's `modified > as_of` rule only for caches saved without the field. For
`memory_check`, carry the same pre-listing mtime in the `loaded` event (the dataset's metadata)
and compare equality in `_unchanged_since_memory`. Keep the sample stats as they are. Test: the
probe above (both paths), plus "server ahead" still answers unchanged. Note for the handoff: a
new optional key in `info` (compatible with older stores and HeLabs; nothing to migrate).

### R-2 · medium (unsure of real sizes) · a Live save's data dump runs under the no-progress timer

`helab/utils/io_service.py:728-736` (`_run` writes every held array with `np.save` before the
helper process starts) with `:423-424` (`last_activity = started` at dispatch) and `:924-927`
(`_tick` retires a request with no event for `timeout` seconds).

A Live save (`FolderCache.save` → `submit` with `arrays=dict(base.data)`, `folder_cache.py:1376-1384`)
first copies the whole dataset held in RAM to the helper's private folder, on the daemon thread,
with no event sent. The 60 s no-progress timer runs from dispatch, so a dataset whose dump takes
longer than 60 s (several GB on a lab PC's HDD, or with an antivirus scanning each `.npy`) is
retired as "Timed out after 60 s without progress", before the helper even starts; `retries()` is
False (no `current_file`), so the save fails, Live says "Save failed: Timed out…", the data stays
unsaved, and the next autosave repeats it. On quit the quit window's save fails the same way.
Note also that every autosave (every 10 shots) and Live off rewrites the *entire* dataset to temp
and the helper reads it all back: by design per AGENTS.md, but worth a line in the handoff.

Fix: count the dump as progress. Simplest: `_put(request, {"kind": "heartbeat", "phase": "saving
held data", "entries": n})` every N arrays (any helper event resets `last_activity`,
`io_service.py:890-892`; a Live save is a `load` with no `current_file`), or set
`request.last_activity = time.monotonic()` just before `Popen`. Test: a fake slow `np.save` (or a
tiny `NO_PROGRESS_TIMEOUT`) with a few arrays must not time out; cancellation during the dump
still returns at once (`:733-734`).

### R-3 · low (unsure) · frozen build: the response reader can miss the helper's last lines

`helab/utils/io_service.py:824-834` (`_file_lines`), used only when `sys.frozen` (the packaged
app the lab runs, `main.py:3-11`).

The loop calls `readline()`, gets `""` (nothing new yet), then `process.poll()`; if the helper
wrote its final lines (`done`) and exited between those two calls, the reader breaks without
reading them, and `_run` reports "I/O helper exited unexpectedly" (`:777-778`) for an operation
that completed. The window is small (the helper flushes `done`, then `_end_trace` and interpreter
exit, a few ms) but the reader thread can lose the GIL for 5 ms between the two calls, so it is
possible under load. Not covered by tests (the frozen path has no reader test).

Fix: when `poll()` says the process has exited, read the file to EOF once more (loop `readline()`
until it returns `""`, yielding complete lines) before breaking. Test: a fake process whose
`poll()` turns non-None after the file gains its last line, read with `_file_lines`, yields it.

### R-4 · low · two roots-table reads raise raw `sqlite3.Error` and fail the listing

`helab/utils/cache_store.py:478-486` (`root_at`, `other_root_locations` don't wrap `sqlite3.Error`
in `StoreError`, unlike every other read); callers `helab/io_ops/browse.py:110` (outside any try)
and `helab/io_ops/markers.py:34, 54` (inside `_discover_root`, which catches `StoreError` only).

A transient database error there (a busy store past `BUSY_TIMEOUT`, Windows' "disk I/O error"
while another helper closes the WAL, `cache_store.py:34-37`) propagates out of `list_folder`
after the entries were sent: the listing ends with `error`, and since a listing error records a
scan failure (`FolderCache._record_scan_outcome` for `kind == "error"` with the default
`scan_mode`, `folder_cache.py:2557-2558`), the folder is `blocked` for automatic status checks
until a manual one. `stores._data_root` already catches `sqlite3.Error` for the same reason
(`stores.py:44`).

Fix: raise `StoreError("Data roots could not be read: …")` from both methods, as
`root_locations` does (`cache_store.py:457-464`); `_discover_root` then sends its
`cache_warning` and the listing completes. Test: `root_at` raising → `list_folder` still sends
`status` and `done`, with a `cache_warning`.

### R-5 · low · every store-open failure is reported as "Mount information is unavailable"

`helab/io_ops/stores.py:144-147`: the `except Exception` around `_cache_store`'s body wraps the
store's own `StoreError` (from `CacheStore(...)`, `cache_store.py:387`) and an `OSError` from
`os.makedirs` (`cache_store.py:416`) as `StoreError("Mount information is unavailable: …")`. Then
`_store_or_off` (`stores.py:88`) sees a message not starting with `OPEN_FAILED` and prefixes it
again: the user reads "Disk cache could not be opened: Mount information is unavailable: Disk
cache could not be opened: unable to open database file". `tests/test_cache_store_open.py:124-125`
encodes this double text. (The "warning said it twice" fix in known-issues, `95f2309`, removed a
different duplication.)

Fix: narrow the wrapping to the mount and resolver steps (`_mounts`, `CachePaths`,
`current_local_volumes`, `DataRoots`); let `StoreError` pass unchanged and wrap `OSError` from the
store as `OPEN_FAILED`. Update that test's expectation.

### R-6 · low · a pending root stays pending after its duplicate is gone

`helab/io_ops/markers.py:55-58`: `decision` is "pending" whenever the location's row is already
pending with the same UUID, before looking at `duplicates`. When the other location has since been
forgotten or its marker deleted (`forget_root`, `forget_root_tree`, `cache_admin forget_root`),
the next listing of the pending folder sends `root_duplicate` with `other_locations: []` and
`others: []`: the folder stays RAM only, the Review window asks "same folder or a copy?" with
nothing to compare against, and only Same folder (or placing a new marker) ends it.

Fix: evaluate `duplicates` first: with none, record the location confirmed (`root_found`), since a
pending decision only exists because another confirmed location had the UUID. Test: confirmed A,
B found pending, A forgotten, B listed again → B confirmed, no `root_duplicate`.

### R-7 · low (unsure of frequency) · a scan's new signature cancels the folder's running jobs

`helab/utils/folder_cache.py:2523-2526` (a completed scan whose signature differs from the
snapshot's calls `_invalidate_data`), `:1616-1627` (which bumps the epoch, **cancels** the
folder's running `load`, `live` and `cached` jobs and drops its datasets), and `:2621-2628` (a
`loaded` arriving for a job of an older epoch is cancelled too).

`_invalidate_data` was written for Clear data cache, where cancelling is right. On a signature
change it means: a `details` scan or a manual Check folder status of a folder being acquired,
completing while a Live check reads a new shot, or while a plain load of that folder runs (two
tabs, Queue mode), ends that job with `cancelled`; `LiveController._live_event` then halts Live
("Cancelled", Retry; `explorer_live.py:399-420`), and a tab's load shows "Cancelled — Retry". The
`loaded` event's own check (`:2621-2623`, signature ≠ the snapshot's) already discards a stale
result without cancelling. Unsure how often the window is hit in the lab (the details scan is
skipped while the selected load of a leaf folder runs, and Live locks the tab), so first a test
that shows it: a running `live` job (or a load) of a folder, a `details` scan's `done` with a new
signature, assert the live/load job survives and the next `loaded` is kept.

Fix, if confirmed unwanted: on a signature change drop the unpinned datasets and the snapshot's
freshness, but don't cancel running jobs or bump the epoch (keep `_invalidate_data` for the
explicit clear); the `loaded` signature check decides the result's fate as now.

### R-8 · low · a crashing helper leaves no cause in the log

`helab/utils/io_service.py:749-751`: helpers start with `stderr=subprocess.DEVNULL`. A helper that
dies before sending `error` (an import that fails on a lab PC, a segfault in blosc/numpy/pandas,
an OOM kill) is reported only as "I/O helper exited unexpectedly" (`:777-778`), with nothing to
chase in the log (`:879-882` logs that message).

Fix: send stderr to a file in the helper's private folder (`request.output`, created at `:723`),
and on an incomplete exit append its last lines (bounded, e.g. 2 KB) to the error message and the
warning; `release` removes the folder as now. Test: a helper command that writes to stderr and
exits 1 → the error event carries that text.

### R-9 · low (efficiency) · the details scan stats each subfolder a second time

`helab/io_ops/scanning.py:184`: `_stat(entry.path, "subfolder date", follow_symlinks=False)` is a
separate `lstat` per subfolder. `entry.stat(follow_symlinks=False)` gives the same without a
system call on Windows (the lab PCs; the listing already has it) and the same single call
elsewhere; `_entry_stat` (`infra.py:219-233`) exists for that but follows symlinks. On a share's
top folder with hundreds of date folders this is hundreds of round trips per details scan.

Fix: give `_entry_stat` a `follow_symlinks` parameter (traced as `lstat` when False) and use it
here. Test: the trace of a details scan on Windows shows `syscall: False` for subfolder dates
(or simply no `stat` lines for them).

### R-10 · quality · two functions too long to follow

`helab/utils/folder_cache.py:2193-2701` (`_on_event`, ~510 lines: root events, verification owners,
admin, subtree and history writers, finishing loads, then scans, loads, icons, invalidate, resolve)
and `helab/io_ops/loading.py:252-618` (`_load`, ~370 lines). Every finding above in these files
took a second reading to place. Suggest, without behaviour change and only if Mend agrees it
helps: split `_on_event` into `_on_root_event`, `_on_finishing_event`, `_on_scan_event`,
`_on_load_event` (each already a contiguous block with its own `return`s), and lift `_load`'s
cache-read block (`loading.py:385-452`) into `_cached_shots(...)` returning
`(data, cached, reused, problematic, baseline, cache_info, had_dataset, cache_reason, saved_raw)`.
The existing tests cover both thoroughly; no new tests needed beyond passing them.

### Area 1 summary

Counts: blocker 0 · high 0 · medium 2 (R-1, R-2) · low 7 (R-3 to R-9) · quality 1 (R-10).
Order for Mend: R-1, R-2, R-4, R-6, R-5, R-3, R-8, R-9, R-7 (test first), R-10 (optional).
Needs Tony (handoff): R-1 adds an optional `info` key to cached datasets; R-2's note on the
cost of each Live autosave.

## Area 2: `helab/models/`, `helab/views/` (explorer, Live, tabs, dialogs)

Checked and found fine: rendering reads memory only (the only filesystem calls in `models/` and
`views/` are on local paths: the temp folder, the icon file, a user-chosen folder in
`ManualMarkerDialog`); `SnapshotFileSystemModel.changed` → `activityChanged` → the tab's summary
rebuild costs 0.08 ms and a replay of a 2,000-subfolder listing 0.17 s (probe, removed); Live's
identity, save and halt paths; the quit flow; CacheDialogs' one-question-at-a-time rule. Area 1's
R-7 is confirmed on this side: `LiveController._live_event` turns a `cancelled` check into
`_live_halt` ("Live stopped: Cancelled", Retry), `explorer_live.py:399-420`.

### R-11 · low (rare, but it ends HeLab) · no `sys.excepthook`, and two unguarded timestamp conversions

No `sys.excepthook` is installed anywhere in `helab/`, so PyQt6's default applies: an unhandled
Python exception in a slot or a model virtual (`data()`) calls `qFatal()` and HeLab aborts, with
the traceback on stderr only, which the packaged (windowed) app doesn't have. Two call sites
format a *source folder's* timestamp without a guard: `helab/models/SnapshotFileSystemModel.py:357-358`
(the Modified column: `datetime.fromtimestamp(node.modified)`; `_stamp` at `:30-38` guards the same
value for tooltips, the column doesn't) and `helab/views/explorer_live.py:343` (`when()` in the
re-read warning, a TXY file's old and new mtime). `metadata_date` admits anything up to year 9999,
but Windows' `localtime` (the lab PCs) refuses timestamps past about year 3000: a folder or file
with a corrupt far-future mtime on the share (NTFS allows them) then crashes HeLab the moment its
row renders. The other `fromtimestamp` sites format app-written times and are safe.

Fix: format the Modified column through `_stamp`'s guard (or a small `_date_text` helper used by
both), guard `when()`; and install an excepthook in `main.py` (area 5, but one place) that logs
the exception with its traceback through `logging` before the app ends, so a crash leaves a trace
in the frozen build. Test: a node with `modified = 1e11` renders "date not recorded" (or "") instead
of raising; the excepthook logs.

### R-12 · low · the window icon is looked up relative to the launch directory

`helab/views/HelabMainWindow.py:92-96`: `os.path.abspath("./helab/resources/ai-icon.icns")` is relative
to the current working directory, so every start that isn't from the repository root (the packaged
app, `python -m helab` from elsewhere) logs `Icon file not found` as an ERROR and shows no icon.
Fix: build the path from the package, as the status-check arrow does at `:830`; keep the check.

### R-13 · low (part needs Tony) · development leftovers in Settings → General

`helab/views/SettingsDialog.py:53-59, 278-279, 311-312`: an "Enable feature X" tick box and an
"Example Text" field are shown to the user and saved to the settings store as `example_checkbox`
and `example_text`; `:331` logs a WARNING ("Settings dialog closed") every time Settings closes;
`:5` `from re import S` and `:4` `time` are unused. Removing the two placeholder controls changes
the dialog (needs Tony's OK; list it in the handoff); the WARNING (make it DEBUG or drop it) and the
imports are Mend's. (The settings *reads* in this file belong to the CI floor: touch only these lines.)

### R-14 · quality · `StatusReport` carries the legacy GUI's fields

`helab/models/StatusReport.py`: `ATTRIBUTES_OPTIONAL`, `payload_progress_ram`, `data_comp_bytes`,
`log_LabviewMatlab_txt`, `log_KeysightMatlab_txt`, `about_txt`, `payload_errors`,
`_reviewed_path_parent_recursively`, `STATUS_MISTERY` and the four ordering operators are read
nowhere in `helab/` (grep); `time_load_ram` is written once (`FolderExplorer.py:1062`) and never
read; `__eq__` compares all of them. `time_last_updated: datetime = datetime.now()` (`:37`) is
evaluated once at import, so the placeholder reports `fetch_status` makes all carry HeLab's start
time. Suggest keeping path, status, count, extra_icons, the two shot lists, `time_last_updated`
(default `None` → `datetime.now()` in the body), `problematic_txy_ns`, `loaded_txy_files_count`,
`loaded_txy_rows_count`, `data_dict_bytes`, and dropping the rest with their `__eq__` lines; check
`tests/` for readers first.

### R-15 · quality · unused imports, star imports and commented-out code in the tab widget and window

`helab/views/FolderTabWidget.py:10` imports `PIL.TiffTags.lookup` (pulls Pillow in at startup, unused),
`:2, :5, :8, :11` (`gc`, `sys`, `Tuple`/`Dict`, `QThreadPool`) unused; lines 54-90, 98-106, 155-171
and 258-277 are commented-out code. `from helab.utils.constants import *` in `FolderTabWidget.py:16`,
`HelabMainWindow.py:29` and `SettingsDialog.py:15` hides what each file uses (and makes pyright's
job harder). Long functions here: `FolderExplorer._update_folder_summary` (`:1601-1778`, ~180 lines)
and `_load_to_ram_cache` (`:752-847`). Only as far as Mend finds it clearly helps the next reader;
no behaviour change.

### R-16 · low (note; wording needs Tony) · the manual marker save writes on the GUI thread

`helab/views/DataRootDialogs.py:167-184`: Save to folder… writes `.helab-root` with `open()` on the GUI
thread into whatever folder the picker returns. The docstring says "a local folder the user chose
(not the source)", but nothing keeps the picker off the share (it only starts at `~`), and the point
of the dialog is a share HeLab couldn't write to: a hung share then blocks the GUI. Documented
behaviour (AGENTS.md), so a note: either say "a local folder" in the dialog's text and the
picker's title (needs Tony), or send the write through a helper.

### Area 2 summary

Counts: blocker 0 · high 0 · medium 0 · low 4 (R-11, R-12, R-13, R-16) · quality 2 (R-14, R-15).
Needs Tony: R-13's placeholder controls, R-16's wording.

## Area 3: `helab/analysis/` core and `helab/views/plots/`

Checked and found fine: views share arrays read-only down the `.base` chain and copy only records
(`dataset_view`); the runner's queue, cancellation, stop/restart and result pinning
(`runner_core`, `results`); Follow's hold-and-coalesce, pin and catch-up (`follow`); the RAM
budget's order, two-pass release and reload from RAM or the disk cache only (`budget`,
`budget_core`, `instance.reload`); the Settings panel's page moves and the dock tab closer; no
in-place writes to shared arrays in `helab/analysis/` (grep of augmented assignments: all on local
accumulators); the Qt-free modules import no Qt (tests check it too).

### R-17 · low · a script error in `parameters()`, `backends()` or `live_policy()` ends HeLab

`helab/views/plots/instance.py:194-225` (`start`) and `:244-259` (`run`) call the script's
`parameters`, `backends`, `live_policy`, `minimum_size` and, through `runner.submit`
(`runner_core.py:78-101`), `covered_shots`, `constant_keys` and `run_constants` unguarded; `start`
runs inside the Scripts panel's button slot (`script_tree.py:285-307`) and `run` in Rerun's. The
other hooks go through `_hook` (`instance.py:419-426`), whose docstring says why: an exception in a
Qt slot aborts the app (R-11). `script_tree._load_current_group` (`:264-280`) guards the
constructor and `get_actions()` and shows a red "(Error)" row, but a script loaded with Load
Scripts… whose `parameters()` raises (a typo in a `ParameterSpec`) takes HeLab down on the first
click of its Run button, with nothing in the log of the packaged build.

Fix: wrap `run_analysis` → `instance.start()` (and `run`) so a failure shows in the dock as
"<name> failed: …" (the `_message` label) and is logged, as `_finished` does for a failed compute;
`runner.submit` already logs and falls back for coverage and constants. Test: a script whose
`parameters()` raises opens a dock saying so; HeLab goes on.

### R-18 · quality · leftover state and stale docstrings in the Scripts panel

`helab/views/plots/script_tree.py`: `group_changed` (`:64, :233`) is emitted and connected nowhere;
`GroupData.tree_item` and `is_loaded` (`:40-41, :263, :283`) and `group_mapping` (`:116, :211,
:257, :262`) are written and never read; `GroupType = Literal["dynamic"]` has one value and the
docstrings describe a type system that is gone ("Type of group (only "dynamic"…)", "Key
concepts…"). `ScriptsManager.get_script_metadata` (`scripts_manager.py:201`) has no caller.
Suggest dropping the unused state and signal, and cutting the docstrings to what the code does.

### Area 3 summary

Counts: blocker 0 · high 0 · medium 0 · low 1 (R-17) · quality 1 (R-18). Nothing needs Tony.

## Area 4: `helab/analysis/` numerics and `helab/scripts/dld/`, `helab/scripts/standard/`

Read in full: `physics`, `stats`, `estimates`, `bootstrap`, `peaks`, `orders`, `fits`,
`correlations`, `bec`, `bec_readout`, `release`, `velocity`, `profiles`, `masks`, `hotspots`,
`spectrum`, `trends`, and every script of both groups. Checked against the physics and by hand:
the Poisson reweighting and bin averaging in `fit_histogram`, the bimodal gating and the R/σ_th
cap, the polylog expansions (series and Wood's near-1 form), the arrival-time Jacobian, Tc and its
two shifts, the Thomas–Fermi μ/R/n0 and their inversion in `radius_check`, the Castin–Dum ODE, the
velocity signs and τ ≤ 0 handling, g²'s ordered-pair totals, the 1D window scaling of the k-d
search, the back-to-back separation's symmetry, the shot-pair matrix resampler and jackknife, the
banded rebuild, the smoothing matrix's mass conservation (symmetric reflection) and the sandwich
covariance, the mask raster against the exact test, the spectrum normalisation (Nyquist halving,
sinc correction), the threshold-edge interpolation and the moving statistics. In the scripts:
each `compute`/`render`/`update`, the per-plot state (`_PlotState`, `KeptRuns`, `trends.CACHE`)
and its thread use (worker writes, GUI reads under `_LOCK` or atomic C-level iteration), the Live
reuse keys (spec `events_key`, `kept_key`, `stable_range`), the newest-shot overlays, the
instance-id reuse guarded by `_CLOSED` (ids are a session counter, never reused). The 2026-10-20
codex review's correlations RAM accounting (`4b779f6`) is not re-reported. No correctness finding
that I would defend; one drifted duplication.

### R-19 · quality · the DLD port's Transfer fractions duplicates the shared order detection

`helab/scripts/dld/transfer_fractions.py:111-330` carries its own copies of what
`helab/analysis/orders.py` and `helab/analysis/peaks.py` now provide for Basic plots v1's
Transfer fractions: `Orders`, `Detection`, `order_label`, `in_box`, `smooth`, `count_orders`,
`unsure`, `chosen_by_search` are byte-identical to `orders.py` (checked by AST); `jump` and
`window_half` differ only in a constant name and the ms formatting; `half_maximum_width` and
`refine` are older copies of `peaks.py`'s; `Fractions` adds `masked`. `detect` has drifted: the
shared one takes a reference spacing and `guided_spacing` (the "bump between orders isn't one"
fix, `orders.py:148`), the DLD one still takes the nearest side peak (`:229`). Two implementations
of one algorithm, one of them behind.

Fix (no behaviour change): import the identical helpers from `orders.py`/`peaks.py`, keep the
DLD `Fractions` as a subclass or add `masked` to the shared one, and keep the DLD `detect` as it is.
Whether the DLD port should also take the Reference spacing (a new setting and a detection change)
is Tony's: handoff.

### Area 4 summary

Counts: blocker 0 · high 0 · medium 0 · low 0 · quality 1 (R-19). Nothing needs Tony beyond the
handoff question in R-19.

## Area 5: `helab/main.py`, `release*.py`, `build_info.py`, `utils/` (Dash, events, watchdog, constants, cache move, small utils), `resources/`

Read in full: `main.py`, `__main__.py`, `_version.py`, `build_info.py`, `release.py`,
`release_draft.py`, `utils/{dash_server, events, gui_watchdog, logging_setup, synchronised_dict,
ram_buffers, cache_freshness, number_format, time_format, colours, cache_move, constants,
lab_parameters, settings_store}.py`, `resources/icons.py`. Checked: the frozen helper entry runs
before any GUI import; the cache-move state machine (every step idempotent, the copy owned by
its marker, recovery per step) against its docstring and the store's columns; the Dash server's
socket hand-over (`fromfd` duplicates, so closing ours is right), snapshot atomicity and the
closed-plot page; the event hub's once-per-key and rate limit; the release/draft manifest
checks. No correctness finding. Note (not a finding): `main._recover_in_helper` waits with
`timeout=math.inf` and no Cancel for a startup recovery helper; a slow delete of a large old
cache keeps the "Finishing an interrupted cache move…" box up with no way out but force quit
(by design, S9).

`helab/utils/constants.py` is partly the CI Robustness floor's (its QSettings reads): R-20 and
R-21 touch other lines of it, so do them only when CoCo confirms that floor isn't editing them,
else leave them for the handoff.

### R-20 · low · `constants.py` imports a private joblib internal it never uses

`helab/utils/constants.py:19`: `from joblib.externals.loky.process_executor import MAX_DEPTH`.
`MAX_DEPTH` is used nowhere in `helab/` or `tests/`; nothing else imports joblib (it is in
`requirements.txt` for this line alone). Every HeLab start imports loky's process executor for
nothing, and a joblib release that moves the vendored module breaks HeLab at import. Fix: delete
the line (and, for the handoff, joblib from `requirements.txt`: `requirements*` is off-limits
here).

### R-21 · quality · dead code and two unused modules

- `helab/utils/constants.py`: `hash_int`, `hash_bit`, `hash_bit_to_int`, `hash_str`,
  `hash_str_to_int`, `base62_encode`, `base62_decode`, `INDICATOR_DOTS`, `INDICATOR_DOTS_ALL`,
  `INDICATOR_DOT_RANDOM`, `OS_DIR_CACHE_TTL`, `MAX_DEPTH_INT`, `TEMPFILE_PREFIX`,
  `DEV_PATH_TO_MATLAB` and the three `DEV_PATH_TO_TDC_*` have no reader outside the module
  (grep over `helab/` and `tests/`); `random` and `hashlib` are imported for them. In
  `DEV_POTENTIAL_DATA_PATHS` (`:478-480`) the comma after `'…/tests_sample_data/bad'` is
  missing, so it and the `''` below it fuse into one entry (harmless today: the `''` was
  meaningless; fix by dropping the `''`). The list's contents are Tony's and stay.
- `helab/utils/synchronised_dict.py`: imported nowhere (and its `__iter__` returns an iterator
  that runs outside the lock).
- `helab/utils/logging_setup.py`: `setup_logging` is called nowhere (`main.py:26-27, 143` have
  it commented out; `main.py:28` installs coloredlogs itself); the rest of the file is
  commented-out Dask filters.
- `helab/main.py:145-150`: six "this is a … message" probe lines at every start, at DEBUG
  through CRITICAL, so every log starts with an ERROR and a CRITICAL that mean nothing; and
  `:47` `from helab.utils.constants import *` (add to R-15's list; `main.py` is not the CI
  floor's). The DEBUG level of `coloredlogs.install` is Tony's.

Fix: delete the dead names and the two modules, drop the probe lines, import `constants` by
name. No behaviour change except a quieter log.

### Area 5 summary

Counts: blocker 0 · high 0 · medium 0 · low 1 (R-20) · quality 1 (R-21). Nothing needs Tony.

## Lens's input to the handoff (draft, to merge into `handoff.md`)

**Needs Tony** (left as they are): R-1 (the quick check's clock comparison; fix proposed by Mend
adds an optional `info["folder_mtime_ns"]` to cached datasets); R-11's `sys.excepthook` (whether
HeLab goes on after an unhandled exception, and where a packaged build would log it: nothing
logs to a file yet); R-13's two placeholder controls in Settings → General; R-16's wording for
the manual marker save; R-19's question (should the DLD port's Transfer fractions take the
Reference spacing as Basic plots v1 does?).

**Proposed doc edits** (not made: `AGENTS.md`, `roadmaps/` and `.ai/memory/` are off-limits here):
- `AGENTS.md`, data roots › Duplicates: after R-6 a pending location whose other locations were
  all forgotten is confirmed by its next listing, with no question asked.
- `AGENTS.md`, Responsive filesystem I/O: after R-8 a helper's stderr goes to `stderr.txt` in its
  private folder, and the last 2 KB are logged at WARNING when it exits without finishing.
- `AGENTS.md`, Caching › "A folder's status … derived": after R-7 a status check's new signature
  drops the folder's RAM datasets but no longer cancels its running load, Live check or cached
  read.
- `roadmaps/known-issues.md`: R-1 (held), R-11's excepthook, R-12 (the packaged app lacks
  `ai-icon.icns`: `HeLab.spec` datas), R-20 (joblib can leave `requirements.txt` once the import
  is gone).
- `.ai/memory/results/folder-io-queue.md`: the R-7 behaviour, if the memory describes the cancel.

**Open risks**: R-2's fix counts the Live save's dump as progress but the dump itself (the whole
held dataset rewritten to temp every autosave) stays, by design; R-3's reader change is only
exercised by the frozen build; the R-6 behaviour change hasn't been tried on a real duplicate root.

**Floors**: `helab/utils/constants.py` (R-20, R-21) and the star imports of `HelabMainWindow.py`
and `SettingsDialog.py` (R-15) wait for the CI Robustness floor if it is editing those files.
