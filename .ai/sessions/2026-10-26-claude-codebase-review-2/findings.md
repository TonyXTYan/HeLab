# Codebase review 2: findings (Sextant, Claude Fable 5.1)

Branch `agent/codebase-review-2`, reviewed at `3eb0fbf`. Brief: [brief.md](brief.md). Rasp's notes:
[notes.md](notes.md). IDs `C-n`; severity blocker / high / medium / low / quality; each with
file:line (at `3eb0fbf`), the scenario and a suggested fix. "unsure" marks what I couldn't confirm.

Baseline checks at `3eb0fbf` (floor root, `floor-env.sh`): `pytest -n 4 --reruns 5 --reruns-delay 1
--basetemp=.ai/temp/pytest-review`: 4339 passed, 2 skipped, 2 xfailed, **no RERUN** (2:54);
`mypy helab/ --strict` (162 files), `mypy tests --strict` (133 files), `pyright helab tests`: clean.

## Part 1: what landed since `fc0f50d`

### 1. Store identity, presets and saved results in FolderCache / CacheStore / helpers

Read: `FolderCache.store_answer`, `_waits_for_folder`, `_probe`, `_probe_answered`,
`_store_not_confirmed`, `_store_changed`, `_hold_or_submit`, `_drop_held`, the presets section,
`_on_admin_event`, `_on_result_event`, `_note_usage`, `_note_result_counts`,
`_results_store_replaced`; `io_ops/admin.py` (presets, identity, adopt_result), `io_ops/results.py`,
`CacheStore` open / `_migrate` / presets / results / adopt / remove / sweep; the enumeration in
`tests/test_store_identity.py`.

The docstring and the code agree on every transition I traced (first answer names the store; a
second store probes; nothing counts while the probe is out; replay in order; held writes go to the
folder's store; a failed probe leaves the store unknown until a deliberate read or result answer;
a third store seen meanwhile re-probes; shutdown drops held writes before the service cancels the
probe). Cells the two-store enumeration doesn't cover, traced by hand and found sound: a third store
(`_probe_seen` chains one probe at a time); `cancel(owner)` of an owner whose answer already waits
(the replayed event reaches a cancelled owner and is ignored by `CachedRuns`); a held write whose
submit fails after the probe (ended with an `error` through `_on_event`); a probe that ends
`cancelled` (as a failure); an answer naming no store while a probe is out (processed at once unless
its owner already waits, so a job's events stay in order). No finding there.

- **C-4 (low; needs Tony: a documented behaviour)** — `helab/utils/cache_store.py:46`
  (`PENDING_MAX_AGE = 3600.0`), `sweep()` at :2348–2365, startup order
  `helab/utils/folder_cache.py:2422–2425` (the sweep is queued before the inventory). AGENTS.md
  (Saved analysis results) and `roadmaps/result-caching.md:148` say "results still waiting for an
  answer stay for the next session"; the store expires a waiting result an hour after it was held,
  like a waiting dataset save, and the startup sweep runs before the inventory that would ask about
  it. Scenario: a Correlations result doesn't fit; the user quits without answering (the quit window
  says nothing of it: `result_saving` leaves waiting results out, by design); HeLab is started the
  next morning: the result is gone and nothing says so. Fix: either the docs say "for an hour" (as
  the dataset saves, whose rule AGENTS.md states as "they would expire unasked"), or waiting
  results get a longer age (a day?) in `sweep()` and `next_deadline()`. Tony's call.

- **C-5 (quality)** — `helab/utils/cache_store.py:1955–2005`: `remove_results(paths=…,
  _stored_keys=…)` has no caller with `paths` (the three callers in `io_ops/admin.py:94, :191,
  :218` pass `cutoff`, `root` or nothing), so the `paths` branch, its `_stored_keys` flag and the
  `by_path` folder-epoch bookkeeping at :2002–2006 are dead. Fix: drop the parameters, or keep them
  with a test if they are meant for a later per-folder Clear cached analysis.

### 2. Saved results in the plot path

Read: `CachedRuns` (`helab/views/plots/cached_results.py`), `AnalysisInstance._submit`, `run`,
`run_reopened`, `_cached_*`, `_finished`; `result_cache.py`, `result_codec.py`, `result_types.py`;
`AnalysisQueue.prepare` / `enqueue` / `_packed`; `CacheDialogs`; `io_service._run`'s
`result_found` artifact read; the Correlations and Release time hooks.

Sound: lookups keyed on the pre-run key without `found`; the saved record's codec with no pickle
and declared types only; an exact match never re-saved (`_show` pops the lookup before
`_finished`); a run whose lookup fails saves nothing (no guard); Live's reruns and the catch-up run
after Live never look up or save (`_follow_next` isn't `one_off`); `reload` and `run_reopened` are
one-off runs; Make room removes only results and only the ids the question named; a closed plot's
pending save still ends (`_saves` keeps the connection until its event).

- **C-1 (low)** — `helab/views/plots/cached_results.py:247–250` (`_event`, the `error` branch) and
  :285–312 (`_save_event`). A result read or save of a folder on a hinted local volume that this
  session hasn't verified yet fails with `error` + `unverified` (`io_ops/stores.py:142` raises
  `VolumeUnverified`; `io_ops/results.py` has no handler; `io_helper.py:150` flags the event), and
  `CachedRuns` treats it as any error: the plot says "the disk cache couldn't be read (…):
  computing", the run computes, and with `guard` None its result is never saved; nothing retries on
  `volumesVerified`. The cached data read does wait and retry (`FolderExplorer._cached_event`
  :1089–1091 and `arrangement.FolderWait` :192–210), as AGENTS.md's Local lane paragraph says.
  Scenario: data on a second internal disk or a USB disk (`data_roots.fixed_mount` trusts the system
  volume only); the user opens Correlations within the first seconds of a session, before
  `volumes_verify` has answered, or right after plugging the disk in: that run's result is lost to
  the cache, and the note blames the disk cache. Fix: on `unverified`, keep the lookup open and ask
  again once `cache.volumesVerified` fires (as `FolderWait` does); for a save, hold the packed result
  and submit it after verification (or at least say "waiting for the drive's check"). Confirmed by
  reading the path end to end; not reproduced in a test.

- **C-2 (low; wording for Tony)** — `helab/views/plots/cached_results.py:189–201`
  (`_pending_answered`): every `resultPendingAnswered(…, saved=False)` shows "not saved in the disk
  cache (discarded)", but the signal is also sent when the waiting result expired (`swept`,
  `folder_cache.py:3057–3060`) and when the store was replaced (`_results_store_replaced`,
  :2690–2701). Scenario: a result waits overnight (C-4) or the store is recreated: the plot says the
  user discarded it. Fix: carry a reason with the signal (expired / store recreated / discarded) and
  word the note by it.

- **C-3 (quality)** — `helab/views/plots/cached_results.py:135–143` (`finished`): a run that ends
  failed or cancelled pops its lookup but, unlike `forget`, doesn't cancel the lookup helper when it
  hasn't answered; the answer (with the result's arrays read off the artifact) is then delivered to
  nobody. Fix: `self.forget(result.job_id)` in that branch.

### 3. Presets and plot reopen

Read: `helab/views/plots/presets.py` (`PresetBar`, `ArrangementPresets`, `PresetFolder`),
`arrangement.py` (`FolderWait`, `capture`, `open_arrangement`, `PlotReopen`), `helab/analysis/presets.py`,
`PresetsInspector.py`, the `AnalysisInstance` hooks they call. A second reader (an Opus subagent)
went through the same files and reproduced C-17, C-18 and C-19 with throwaway pytest probes (in its
scratchpad, not the repo); I re-read each path myself before listing it.

Sound: no disk or store I/O on the GUI thread (RAM reads of `FolderCache`, writes through
`set_presets`/`read_presets`); every apply path goes through `check_plot` (never clamped or
replaced); the inspector's "fits" uses the same `check_plot` and `find_script`; `FolderWait` reads
RAM or one local `cached` read, hears `datasetChanged`, `mismatchesChanged` and `volumesVerified`,
and disconnects in `stop()`; `PresetFolder` starts Live only through `start_live`'s rules; `parse`
rejects newer formats and names unreadable plots; the record is written at quit before the plots
close.

- **C-17 (medium)** — `helab/views/plots/arrangement.py:254` (`capture` renames every dock
  `helab-plot-<index>`) runs in the middle of `open_arrangement` (:297–325): `place_dock` →
  `_add_dock` emits `plotsChanged` (`script_tree.py:327`), `PlotReopen.record` (:425) captures the
  open plots, and only `restore()` sets the `_restoring` guard; `ArrangementPresets.apply`
  (`presets.py:704`) doesn't. So the docks opened so far are renamed by their panel index before
  `restoreState` (:325) looks them up by the names the record gave them (:300). Scenario: a preset
  with plots at Left, Right and Bottom whose first plot's script isn't loaded; after Replace the two
  that open land at Left and Right. Fix: guard `record()` for the whole of `open_arrangement` (a
  flag on `TreePanelWidget` or a context manager `PlotReopen.suspended()`), or better, have
  `capture` name docks only just before `saveState` and restore their names after.
- **C-18 (medium)** — `arrangement.py:254, :265` from `presets.py:657` (saving a folder's
  arrangement): `capture(mine)` renames only this folder's docks 0…k−1, while plots of other folders
  keep the `helab-plot-<n>` names the last `record()` gave them, so `saveState` holds duplicate
  names; Qt's `restoreState` gives each name to the first entry it matches. Scenario: P0 (folder a,
  Left), P1 (b, Right), P2 (a, Bottom); save folder a's preset: names are 0, 1, 1; applying it puts
  P2's replacement at Right. Fix: before `saveState`, clear the object names of docks not captured
  (restore after), or name docks per capture with a unique prefix.
- **C-19 (low)** — `helab/views/plots/instance.py:780–787` (`_revised`) and `_live_ended` (:789)
  have no `waiting()` guard: a reopened plot still waiting (its `follow.ran` is the waiting view,
  empty signature) gets the Live feed's revision, `follow.due` returns it (another identity,
  `finished_at` −inf) and `_follow_next` runs it, outside `run_reopened` ("the one place a reopened
  plot decides to run", AGENTS.md) and past `FolderWait`'s other-data-root rule; `_wait` and the
  waiting message stay set. Scenario: a plot recorded under `root://old`; its folder's tab starts
  Live under another root: the plot runs at once on the first revision. Fix: in `_revised` and
  `_live_ended`, when `self.waiting()`, call `self._wait.look()` (RAM now holds the data) and return.
- **C-20 (low)** — `arrangement.py:393–407` (`_ask`) adds only an AcceptRole and a DestructiveRole
  button, so the "Plots not reopened" box has no escape button: Esc and the title-bar close are
  ignored, and `quit()`'s `self._question.close()` (:448) returns False and leaves it up. Fix:
  `box.setEscapeButton(keep)` (close = Keep, as the comment intends); at quit `done(0)`/`deleteLater()`.
- **C-21 (low)** — `helab/views/plots/presets.py:345` (`PresetBar.refresh`) tests
  `self.note.isVisible()`, which is False for every plot whose page isn't the Settings panel's
  current page (a `QStackedWidget`), so a store problem line replaces a background plot's "Reopened ·
  ⚠ N settings at the script's defaults" note on any `presetsChanged`. Fix: `not isHidden()` /
  `isVisibleTo(self)`. (Plausible from Qt's semantics; not run.)
- **C-22 (low)** — robustness of records read back: `instance.py:220–235` a plot whose
  `_open_settings` raised in `start` is still returned by `reopen_plot`, its `values()` is `{}` and
  the next `record()` saves it with no settings (lost for good); `script_tree.py:283–285`
  `instance_id.isdigit()` accepts "²" and `int()` raises outside the try, aborting the whole
  `restore()`; `arrangement.py:301–302` `settings_width` has no upper bound. Fix: return the error
  from `reopen_plot` (the plot goes to kept), `isdecimal()`, clamp the width.
- **C-23 (quality)** — `PresetsInspector.py:128` `show_summary` connects a closure to the app-wide
  `presetsChanged` per CacheTab built and never disconnects (guarded by `sip.isdeleted`, but they
  pile up per Settings open); `PresetsInspector.rename`/`duplicate` (:311, :321) ignore what
  `set_presets` returns (e.g. QUITTING), unlike `PresetBar`; `helab/analysis/presets.py:28` names
  `reopen.py`, which is `arrangement.py`; three copies of the FolderCache fallback (`presets.py:59`,
  `:575`, `arrangement.py:416`); a script with no parameters has `instance.presets` None, so its
  reopen note (library or Live group not restored) is never shown (`instance.py:265`, `presets.py:712`).

### 4. The quick fixes

Read: `io_service._run` (:721–836: a write to a closed stdin pipe is passed over, the helper's
stderr tail logged with the error), `cache_move.verify` (results' and pending results' files
checked under `results/`), `loading.py` (`file_started` / `file_finished` only for a file read;
`cache_reason` wording; `folder_mtime_ns` carried through the quick checks), the mismatch fence
(`b66bba6`: the epoch bump in `_mismatch`, `_matched` only for an accepted load), and
`tests/conftest.py` (`private_store`, `no_quitting_cache`, `where_qt_raised`, `delete_left_widgets`,
the rerun-reasons summary). I checked that `where_qt_raised`'s hook is the one installed during a
test's call phase (a scratch test printed `sys.excepthook`: it is), so the note reaches pytest-qt's
report. No finding.

- **C-6 (doc)** — `roadmaps/known-issues.md` App list still has "`cache_move.verify` doesn't check
  saved results' files" open; this branch fixed it in `9d90156` (with
  `test_a_copy_with_a_damaged_result_file_fails_verification`). Move it to Fixed in the handoff.

## Part 2: overview pass

Method: my own reading of `folder_cache.py`'s structure and the Part 1 files, plus three
grep-based sweeps (dead names by token count over `helab/` and `tests/`, then a plain grep over
helab, tests, HeLab.spec, setup.py, .github, roadmaps and AGENTS.md; every event kind sent against
`events.KINDS`; the AGENTS.md claims). Every item below I re-checked with my own grep before
listing it.

### Dead code (all confirmed: no reference but the definition, docstrings aside)

- **C-7 (quality)** — unused modules and functions, safe to delete (one commit, with the two
  stale docstrings):
  - `helab/models/data_folder.py` (`DataFolder`, 11 lines): nothing imports it (the `data_folder`
    in tests is a helper of `test_cache_switch.py`).
  - `helab/resources/icons.py:485` `str_to_QIcon` and `:567` `circular_progress_QIcon_cached`
    (`DebugIconsWindow` reads `PercentageIcon.ICONS` directly).
  - `helab/utils/cache_paths.py:183` `current_cache_paths`.
  - `helab/views/FolderTabWidget.py:134` `rescan_current_folder_explorer`.
  - `helab/views/CentralHint.py:81` `set_extra` and `:96` `add_widget`; so its `extra` label
    (:51–57) is never shown, and the class docstring (:43) promises `add_widget`.
  - `helab/analysis/masks.py:373` `apply_mask`: the module docstring (:5) presents it as the entry
    point, but every script uses `mask_from(values).apply(...)`.
  - `helab/utils/synchronised_dict.py` is also unused, but Tony kept it (2026-10-21, R-21): leave
    it; only `roadmaps/cache-storage-and-settings.md:665` ("the Dash server uses it") is stale.
- **C-8 (quality)** — unused constants and fields: `helab/utils/cache_store.py:50`
  `DEFAULT_BUDGET` (a second copy of `settings_defaults.py:64`'s default) and `:72`
  `RESULT_FORMAT` (a copy of `result_codec.FORMAT`, the one written); `helab/utils/io_service.py:152`
  `IOService.LISTINGS`; `helab/views/HelabMainWindow.py:82–84` the three `STATUS_LEFT_*`;
  `helab/analysis/profiles.py:137` `BOSES`; `helab/scripts/dld/release_time.py:87` `FOLDER_KEYS`
  (:303/:305 spell the same keys as literals); `helab/utils/file_kinds.py:23`
  `FileKind.ram_per_byte` (never read: `large_folder.py` says the estimate is unscaled).
- **C-9 (quality)** — signals emitted and never connected (nothing in helab or tests connects
  them): `FolderCache.diskUsageChanged` (`folder_cache.py:192`, emitted :1425, :2757: the Cache
  tab reads usage from inventories), `FolderExplorer.itemExpandedSignal` (:166, emitted :523),
  `AnalysisRunner.started` (`runner.py:28`, emitted :37), `OldLogs.trimmed` (`OldLogs.py:27`,
  emitted :78). Drop them, or connect `diskUsageChanged` where the status bar shows usage.
- **C-10 (low; needs Tony: a menu item)** — View › "Toggle Thread Status Auto Pop-up"
  (`helab/views/HelabMainWindow.py:414–418`, `THREAD_STATUS_SETTING`) reads and writes its setting
  and nothing else reads either, so the item does nothing. Remove the item and retire the key
  (`settings_defaults.RETIRED`), or say what it should do.
- **C-11 (quality)** — helper events the app never handles: `root_rekeyed`
  (`helab/io_ops/markers.py:93`; the app learns of a re-key from the entries sent again with
  `replace`) and `subtree_saved`'s `skipped` paths (`helab/io_ops/scanning.py:117`). Either drop
  the fields/kinds from the contract or handle them; `tests/test_helper_events.py` can't tell (see
  C-13).

### Duplication that has drifted

- **C-12 (low)** — `RACY_SECONDS` is defined twice with different values under the test seam:
  `helab/io_ops/fingerprints.py:31` `min(2.0, SETTLE_SECONDS)` (0 with `HELAB_SETTLE_SECONDS=0`,
  as tests set) and `helab/io_ops/live.py:21` a fixed `2.0`. Equal in production; under tests the
  quick check has no margin while Live keeps 2 s, so a Live test and a cache-first test see
  different rules for "modified within the listing's tick". Fix: one constant (Live imports
  fingerprints' or the reverse), and the AGENTS.md sentence names one. Also
  `FolderExplorer.SETTLE_SECONDS = 0.3` (:179) reuses the name for the selection settle, an
  unrelated rule: rename (e.g. `SELECTION_SETTLE_SECONDS`).
- **C-13 (quality)** — `tests/test_helper_events.py:19–21` lists the GUI files it checks with a
  non-recursive glob of `helab/views/*.py`, so `helab/views/plots/` (which matches `result_*`,
  `loaded`, `too_large`, `error` and `cancelled` kinds in `instance.py`, `arrangement.py`,
  `cached_results.py`) is never checked; nor does the test see fields the app reads, kinds the
  app makes itself, or kinds nothing handles (C-11). Fix: `rglob`, and a list of app-made kinds.
- **C-14 (quality)** — two time formatters: `time_format.duration` (:11) has no hour unit ("75 min
  12 s"), used for retries with no timeout (`FolderExplorer.py:626`) and stopping helpers
  (`io_service.py:572, :592, :667, :684`), which can pass an hour; `span` (:16) and `clock` (:30)
  do. Use one. And `time_format.byte_rate` divides by 1000 while `number_format.byte_size` divides
  by 1024, both labelled kB/MB/GB: say which (SI or binary) and use it in both.
- **C-15 (low, latent)** — two spellings of a folder's `root://` key: the store's is built from the
  percent-quoted location (`helab/utils/data_roots.py:294`, suffix of a `quote`d location,
  `cache_paths.py:118, :168`), the app's `dataset_view.root_key` (:192) from a raw `relpath`. For a
  folder `run 1` the store says `root://u/run%201`, the view `root://u/run 1`. Today each is only
  compared with itself (`arrangement.py` and `presets.py` compare views' keys; result lookups drop
  `root_key`), so nothing breaks; the first code to compare a view's key with a store row's will.
  Fix: one function (quote in `dataset_view.root_key`, or a shared helper), and a test with a space
  in the folder name.
- **C-16 (quality)** — the Live identity of a local folder without a `.helab-root` is its device
  node (`helab/io_ops/identity.py:52`, `f"{mount.fstype}:{mount.source}"`), while data roots
  deliberately use `vol://<volume ID>` so two same-named disks never share a location. A disk
  swapped at the same device node keeps the Live identity; only the held shots' sampled stats can
  catch it. Not a bug today (Live's design accepts it); note it in `roadmaps/live-monitoring.md` or
  use the volume ID when one is known.

### Helper event contract

No mismatch: every kind sent in `helab/io_ops/` and `io_helper.py` is in `KINDS` and sent; every
kind the app matches is in `KINDS` or `GUI_KINDS`; every field the app reads under a kind check is
one the kind's TypedDict declares or one the app adds itself (`arrays`, `tree`, `unreadable`,
`dataset`, `checked_at`, `attempt`, `retry`, `timeout`, `metadata_only`, `scan_skipped`). Gaps in
the test: C-13.

### `helab/utils/folder_cache.py`: size and structure (a proposal for Tony, not a change)

3,749 lines; `FolderCache` is 3,486 of them with 191 methods, 35 signals and 112 attributes set in
`__init__` (:244–495). `_on_event` is 395 lines (:3246–3640), `_on_admin_event` 172 (:2922–3094),
`submit` 141 (:1846–1987). It is six subsystems behind one `QObject`, each already marked by a
section comment and already keeping to its own attributes:

| Section (lines) | Methods | Talks to the rest through |
|---|---|---|
| Data roots, mounts, duplicates (:550–693, :3094–3190) | 22 | `root_of`, `pending_root`, `no_root`, `rootsChanged`, `rootDecided` |
| Folder constants and lab constants (:1011–1223) | 16 | `effective_folder_constants`, `constantsChanged`, the root signals |
| Store identity, presets (:1224–1702) | 27 | `store_answer`, `_hold_or_submit`, `quitSavesChanged`, `presetsChanged` |
| Saved results, usage, budget, pending saves, removals (:2493–2921) | 30 | `store_answer`, `cache_admin`, `pendingSavesChanged`, `cacheRemoved` |
| Jobs: submit, deliver, replay, mismatch, loads, Live saves, quit (:1703–2492, :3191–3640) | 60 | `datasetChanged`, `resultReady`, `_epochs` |
| RAM: datasets, eviction, plot buffers (:789–1010, :1726–1845) | 36 | `holds`, `evict_to`, `pins` |

Proposal, in order of payoff and least risk:
1. **Extract the store identity and presets** into `helab/utils/presets_state.py` (a Qt-free class
   over a small protocol: `cache_admin`, `submit`, `service.resultReady.emit`, two signals). It is
   the newest code, has one rule (the `store_answer` docstring), a 1560-cell test that already
   drives it through `FolderCache`'s public methods, and touches nothing of the job machinery:
   `FolderCache` keeps thin delegating methods so callers and tests don't change.
2. **Extract saved results and disk usage** (`find_result`, `save_result`, `_on_result_event`,
   `_note_result_counts`, `_results_*`, `pending_results`, `_note_usage`, the 80 % pause) the same
   way, as `results_state.py`; it shares `store_answer` with (1) by composition.
3. **Extract data roots and constants** (`roots_state.py`): `_on_root_event`,
   `_on_verification_event`, the duplicate windows' state and the constants' root-move rules.
4. Leave the job machinery (`submit`, `_on_event`, `_on_finishing_event`, mismatch, Live saves,
   quit) in `folder_cache.py`, ~1,500 lines, and split `_on_event` by operation as R-10 started
   (`_on_load_event`, `_on_cached_event`, `_on_scan_event`), each under 100 lines.
Rules to keep it a refactor: the helper contract and every public name on `FolderCache` stay (the
tests call them), each extracted class gets the signals it emits, and the Cache Only floor owns the
file today, so it is for after that lands.

### AGENTS.md rules checked over the whole package

- Source or cache I/O on the GUI thread or during rendering: clean. Every stat/scandir/open/
  sqlite/`CacheStore(` hit in GUI-process code is a helper temp folder, the app or log folder, a
  package resource or a user-chosen script file; `SnapshotFileSystemModel.data()`, `hasChildren`,
  `rowCount` reach memory accessors only; `placement_checks` is lexical plus the in-memory mount
  list.
- Names tests patch imported by value: the io_ops rule holds for every name AGENTS.md lists.
  **C-24 (quality)** — `folder_cache.store_options` is imported by value in nine GUI modules
  (`SnapshotFileSystemModel.py:25`, `CacheTab.py:29`, `CacheDialogs.py:16`, `explorer_live.py:19`,
  `SettingsDialog.py:10`, `DataRootsTab.py:18`, `arrangement.py:25`, `instance.py:36`,
  `FolderExplorer.py:24`), so tests patch it in five places (`test_plot_ram_budget.py`,
  `test_root_gui.py`, `test_root_remove.py`…) and one that patches only `folder_cache.store_options`
  misses the rest. Fix: those modules call `folder_cache.store_options()`, and AGENTS.md's list
  names it. Likewise `cache_move.py:27` imports `cache_location_problem` by value, which
  `test_helabMainWindow.py:378`'s GUI-thread guard can't see.
- Removals without the user asking: C-4 (pending saves and results expire at 1 h, datasets' too,
  which AGENTS.md's "an inventory restores saves still waiting from an earlier session" also
  overstates) and the orphan-file sweep (`cache_store.py:2392`, files no row names, over 1 h old:
  allowed in spirit, undocumented). Everything else is user-driven or documented.
- Tests touching real data: **C-25 (low)** — `tests/test_cache_switch.py:221–255` passes
  `~/Library/CloudStorage/Box-Box/c`, `~/Dropbox/c` and `~/OneDrive - ANU/c` to
  `cache_location_problem`, whose `os.path.realpath` (`cache_location.py:54`) lstats the real home
  path components (inside the guard's denied list on a Mac where they exist). The paths don't
  exist, so nothing is read, but it is real-home I/O outside `tmp_path`: use a fake home under
  `tmp_path` (`monkeypatch.setenv("HOME")`).

### Types weaker than they could be

Strict mypy is clean and `warn_unused_ignores` is on, so none of the 23 `type: ignore`s is stale
(all but two are pyqtgraph/matplotlib/pympler subclassing). `helab/` has ~840 lines with `Any`, 63
`cast`s, 54 `object` annotations; the heaviest files are `folder_cache.py` (76 `Any`),
`cache_store.py` (40, 5 casts), `events.py` (42, by design), `dld/basic_plots.py` (31).
**C-26 (quality)**, the ones worth a pass, each a small change:
1. The app side never imports `HelperEvent`: `IOService._put`/`messages` (`io_service.py:193, :712`),
   `FolderCache._on_result_event`/`_on_admin_event` (:2587, :2922) and the views' handlers take
   `dict[str, Any]`, so field names on the receiving side are unchecked (C-13's gap in another form).
2. `cache_store.py:306, :358` `.event() -> dict[str, Any]` is cast to `ResultCountField`/`UsageFields`
   at `browse.py:50`, `admin.py:212`, `results.py:131`, `stores.py:178`: return the TypedDicts.
3. `cache_move.check_target -> dict[str, Any]` (:241) cast to `MoveCheckFields` (`admin.py:250`);
   `CacheStore.write_presets -> list[dict[str, Any]]` (:995) cast to `PresetRowFields` (`admin.py:166, :171`).
4. `store_options()` (`folder_cache.py:148`) has a fixed shape (`directory`, `budget`, `budget_set_at`):
   a TypedDict; `FolderCache.save_result(record: Any, guard: Any)` (:2569): `ResultGuard`;
   `cache_admin(action: str)` (:2516): a `Literal` of `ADMIN_ACTIONS`.
5. `pending_saves`, `pending_results`, `mismatched`, `root_duplicates` (:361, :389, :455, :458) hold
   event payloads that have TypedDicts; `unpack_dataset -> dict[int, Any]` (`cache_store.py:449`) has
   validated arrays.
6. `main.py:93` `[union-attr]` ignore: an `assert QApplication.instance() is not None` instead.

### Comments and docstrings that no longer match the code (C-27, quality; all verified)

- `helab/analysis/results.py:201`: `reuse_key` "not used yet (R2 and R3 will)": R2 uses it
  (`result_cache.lookup_key`).
- `helab/analysis/bootstrap.py:17`: names `stats.auto_crop`; the function is `stats.crop_box`.
- `helab/analysis/masks.py:5–6`: names `apply_mask` (unused, C-7) and `mask_keeps` (doesn't exist;
  `_keeps` and `masked_counts_per_shot` do).
- `helab/views/HelabMainWindow.py:98`: `named_temp_files` "TODO: dev code, remove": nothing appends
  to it; only iterated at :1489. Dead.
- `helab/utils/events.py:38`: `RATE_SECONDS` "proposed, for Tony", while AGENTS.md states it as settled.
- `helab/scripts/dld/basic_plots.py:151, :193`: `OverlayView` and `overlay_newest` are copies of
  `helab/analysis/overlay.py:14, :57`; the DLD Transfer fractions imports the copy
  (`dld/transfer_fractions.py:63`) while AGENTS.md cites `overlay.py` for both groups. One copy.
- `roadmaps/cache-storage-and-settings.md:665` "the Dash server uses it" (`SynchronisedDict`): it doesn't.

### AGENTS.md statements the code no longer bears out (proposed edits for the handoff)

1. Saved analysis results: "results still waiting for an answer stay for the next session", and
   Caching: "At startup an inventory restores saves still waiting from an earlier session" → both
   last `PENDING_MAX_AGE` = 1 h from when they were held; the startup sweep expires them first
   (C-4: or change the code).
2. Architecture, Package layout: "`helab/models/`, `helab/views/` (…), `helab/workers/`,
   `helab/scripts/`, `helab/utils/`" → `helab/workers/` doesn't exist; add `helab/analysis/` and
   `helab/io_ops/`.
3. Responsive filesystem I/O: "each operation family a module of `helab/io_ops/` (browse, scanning,
   loading, save_held, live, icons, markers, admin, trace_check)" → add `results`.
4. The local lane "runs `cached` reads …, `subtree_save` …, `cache_admin` …, `volumes_verify` …
   and `trace_check`" → also `cache_move`, `result_find` and `result_save` (`IOService.LOCAL_OPERATIONS`).
5. Caching: "Maintenance goes through `FolderCache.cache_admin(action, …)` (`inventory`, `clear`,
   `purge`, `trim`, `adopt`, `discard`, `sweep`, `forget_root`, `root_same`, `clear_root`…)" → also
   `prefs`, `clear_prefs`, `constants`, `presets`, `adopt_result`, `discard_result`,
   `clear_results`, `clear_root_results`, `identity`, `budget` (`admin.ADMIN_ACTIONS`); and the
   folder-flags sentence should mention Settings → Cache's Clear folder preferences (`clear_prefs`).
6. Caching, the sweep: "a `cache_admin sweep` helper … deletes them later …, and at startup also
   deletes the old diskcache folders" → it also expires pending saves and results over an hour old
   and deletes store files no row names once over an hour old (`_sweep_orphans`).
7. Visualization: "`127.0.0.1:8050`" → 8050 is the preferred port; another free one is taken when
   it is in use (`dash_server.py:34`).
8. Threading: "The GUI process has no worker pools, except the single analysis worker thread … and
   the short-lived startup thread that tidies old log files" → also the short daemon threads
   `HeLab-artifact-cleanup` and `HeLab-cancel` (`io_service.py:898, :909`) and `HeLab-shutdown`
   (`HelabMainWindow.py:1495`), besides the readers.
9. Live: "(not within `RACY_SECONDS` = 2 s …)" → Live's own `live.RACY_SECONDS` (C-12: or merge them).
10. Script system: "the plot UI is the `helab/views/plots/` package: `dock`, `pictures`, `instance`
    (`AnalysisInstance`), `script_tree`, `settings_panel`" → also `workspace`, `arrangement`,
    `presets`, `cached_results`.
11. Transfer fractions: "`helab/analysis/overlay.py`" for both groups → the DLD port uses its copy
    in `dld/basic_plots.py` until C-27's merge.
12. Architecture, the patched-names rule: add `folder_cache.store_options` once C-24 is done (or
    list the modules that import it by value).
Everything else I could check by grep (about 120 names, 55 UI strings, every constant, setting
default, env seam and path named in AGENTS.md) matches the code.

- **C-28 (quality, from Rasp's job 1)** — `PresetBar` (`helab/views/plots/presets.py:63, :583`) and
  `PlotReopen._cache` (`arrangement.py:416`) reach the app-wide `FolderCache` through
  `get_folder_cache(get_io_service())`, while `AnalysisInstance` uses its workspace's budget cache
  first (`instance.py:1008`). In the app both are one object; in tests they differ, so preset,
  identity and inventory helpers run on a service the test doesn't own (the cause of the Windows
  rerun Rasp fixed in `5607182`, by waiting for that service too). Fix, when the presets tests
  can take it: hand `PresetBar` and `PlotReopen` the workspace's cache (one injection point, as
  `CachedRuns` has), so a test's traffic stays on its service.

## Review of Rasp's fixes

- **Batch 1** — `5607182` (job 1: `store_free` counts the app-wide service; three store-deleting
  tests wait for it; a regression test fails with the old rule): read in full, sound; the cause is
  C-28. `5d495e4` (C-1, C-3): read in full, accepted. Remarks, no change asked: the per-plot
  `VERIFY_WAIT` timer isn't restarted by a later refusal, so one that arrives after the first waits
  less than 15 s (bounded either way); a refused save keeps its packed bytes in `_unverified_saves`
  for up to 15 s outside the RAM budget's count; a save still waiting there isn't in
  `quit_saves` (quitting makes `save_result` refuse it and the plot's note says so), which matches
  "a plot whose result wasn't saved computes it again". Rasp's "unsure" note on the Windows venv
  redirector and a cache move's rename goes to the handoff's open risks.
- **Batch 2** (`f863c9f`…`7abba35`, notes `1a010ef`): every commit read in full, accepted. C-17/C-18
  (`f863c9f`): `_named_state` names docks only for the `saveState` and restores their names, so
  `open_arrangement`'s names survive `record()` and no recorded name is in a state twice; the
  record's `dock_name` is always `DOCK_NAME.format(index)`. C-19 (`82fc79c`): `_look_again` in
  `_revised` and `_live_ended`. C-20 (`1628c3e`), C-21 (`6fef992`), C-22 (`8651eb4`: `open_error`,
  `isdecimal`, the width clamped to the screen), C-23 part (`fe9a582`: one `PlotWorkspace.folder_cache()`,
  the summary's connection let go with its label), C-7/8/9 part (`7471081`), C-11/C-13 (`197056f`:
  `rglob`, `RECEIPTS`, the unhandled-kinds test), C-25 (`0e44f0d`), C-27 part (`33fbf95`: one
  overlay module with `newest_values` and `update_newest`; both callers switched), C-24 part
  (`e47242b`), C-26 part (`7abba35`). Rasp's decline of C-24 for `arrangement.py` and `instance.py`
  (the by-value import is the presets tests' seam) is reasonable; AGENTS.md's patched-names rule
  should name `folder_cache.store_options` with those two exceptions. The items held for Cache Only
  and the needs-Tony questions are as `notes.md` lists them.
  My rerun at `1a010ef` (floor root, `floor-env.sh`, `--basetemp=.ai/temp/pytest-review`):
  `pytest -n 4 --reruns 5 --reruns-delay 1`: 4354 passed, 2 skipped, 2 xfailed, **no RERUN**
  (1:56); `mypy helab/ --strict` (161 files), `mypy tests --strict` (134 files), `pyright helab
  tests`: clean.

## Follow-up (Tony's answers, 2026-10-26)

- **Batch 3** (`a40ef18`…`3e04f03`, pre-merge): every commit read in full against Tony's answers,
  accepted. Item 8 (`a40ef18`): the per-minute cap, `RATE_SECONDS`, `rate_key` and the held-back
  count are gone; `Event.shown` is "asked for a notification". Item 9 (`33849f4`): `VERIFY_WAIT`
  15 s runs the plot and says `VERIFY_NOTE` in the status bar and status line; the save (or the
  late lookup, asked again for the guard alone) waits to `SAVE_VERIFY_WAIT` 120 s from the refusal
  on one timer (`_schedule`); then, or on a second refusal, `UNCHECKED_NOTE` on the amber line and
  one WARNING; a Clear after the run started fences the late guard (`fenced`). C-12 (`d1aa85b`):
  Live reads `fingerprints.RACY_SECONDS`. C-15 (`898966f`): `dataset_view.root_key` quotes each
  part as `cache_paths` does; the test compares it with the store's `DataRoots.key` for "run 1",
  a dated folder and `a%b/c#d`. C-23 (`3e04f03`): the inspector's note line names a refused or
  RAM-only change with `saved_note`; a parameterless script's reopen note goes on the status line
  (`AnalysisInstance.note_saved`), kept after its runs.
  Remarks, no change required before the merge, Rasp's call whether to fold in with batch 4:
  - `_cache_removed`'s fence takes `entry.late` only; a holds-state script's lookup (`wait` False
    from the start) also runs before its guard when refused, so a Clear between its run's start and
    the guard taken after verification isn't fenced: `not entry.wait and not entry.answered` covers
    both (low: needs an unverified volume, a holds-state plot and a Clear in that window).
  - `_answer` for a late lookup whose second answer is a plain `error` says "…: computing" though
    the run already computed (wording only).
  - AGENTS.md's Live paragraph still says "at most once a minute per kind and folder
    (`RATE_SECONDS`), the held-back ones counted in the next": a doc edit for the handoff.
  Checks: a full run that straddled the `dev/v0.0.6` merge (`c1da54d`) failed one test with a
  mixed tree (`test_helper_events`: `offline` not in `GUI_KINDS` from the pre-merge test file);
  on the merged head it passes (5 passed). Strict mypy (162 + 136 files) and pyright clean. The
  full suite is rerun at the final head below.

- **Batch 4** (`cb6fa23`…`1a15f61`, after the `dev/v0.0.6` merge `c1da54d`): every commit read in
  full, accepted. C-2 (`cb6fa23`): `resultPendingAnswered` carries why (`PENDING_*`), the plot's
  notes read "not saved (expired): it waited over an hour for Make room", "not saved: the disk cache
  was recreated", "not saved: its cached analysis was cleared", Discard keeps "(discarded)".
  Item 9 follow-up (`8026637`): the fence on `not entry.wait`, the "computing" note only for a run
  not yet going, a holds-state fence test. C-10 (`dce92c7`): the menu item gone, its key in
  `RETIRED`. C-12 rename (`d95b18b`). Held cleanups (`fce2de0`: `remove_results` keeps `paths`,
  which is tested, drops `_stored_keys`; `DEFAULT_BUDGET`, `RESULT_FORMAT`, `LISTINGS`,
  `STATUS_LEFT_*`, `diskUsageChanged`, `itemExpandedSignal`, `current_cache_paths`,
  `rescan_current_folder_explorer`, `named_temp_files` with the `HeLab-shutdown` thread that only
  closed them). C-24 rest (`0d7a83c`: the five Cache Only views call `folder_cache.store_options()`;
  `arrangement.py` and `instance.py` stay by value, the presets tests' seam). C-26 part (`1a15f61`:
  `ResultCount.event()`, `Usage.event()`, `write_presets`, `read_presets` typed; four casts gone).
  Rasp's decline of C-28 for `PresetBar` (presets are app-wide by design; `preset_store()` is the
  one place) is reasonable: C-28 stays a note in the handoff.
  My rerun at `1a15f61`: `pytest -n 4 --reruns 5 --reruns-delay 1`: 4451 passed, 2 skipped, 2
  rerun, both `test_typing.py::test_pyright_tests` on 2 pyright errors in `tests/test_zz_seam_probe.py`,
  **my own scratch probe, which sat in `tests/` during the run** (not the branch's: with it removed,
  `test_typing.py` 6 passed); `mypy helab/ --strict` (162 files), `mypy tests --strict` (136
  files), `pyright helab tests`: clean.

## The combined branch: Cache Only (Work Offline) meeting the review fixes

Read: the merge's changes to `io_service.py` (`OFFLINE_OPERATIONS`, `set_offline`,
`finishes_offline`), `folder_cache.py` (`_offline`, `set_offline`, `_offline_submit`,
`store_options`), `io_ops/stores.py` (`_offline_mounts`, `offline` keying), `cache_store.py`
(`listings`, `_migrate`), the explorer, the model, the main window, `io_helper.py`, `listings.py`,
`conftest.py`; Cache Only's own four review rounds (`review-findings.md`) so as not to repeat them.
The seams, each traced and found consistent:
- Saved results (C-1, item 9): `result_find`, `result_save`, `cache_admin` and `volumes_verify` are
  `OFFLINE_OPERATIONS`, so lookups and saves run offline, the identity probe runs, and the 15 s /
  120 s waits can end; `_store_or_off` passes `offline` to `_cache_store`, so a folder on an
  unmounted hinted volume keys through its hint; `set_offline(False)` calls `_verify_roots`, whose
  `volumesVerified` re-asks any waiting lookup or save.
- Reopened plots and presets: `FolderWait`'s `cached` read is allowed offline; `PresetFolder`'s
  deliberate load becomes the explorer's `_show_offline` (RAM, else one cached read); Live is refused
  through `live_unavailable` with `OFFLINE_LIVE`; `set_work_offline(True)` stops Live before the
  switch, and the remembered setting is applied before `PlotReopen.restore`.
- Dock layout (C-17/18): no interplay with offline. The event-contract test (C-13) passes with the
  `offline` kind in `GUI_KINDS`. `store_free` counts `saved_list` helpers (`CACHE_OPERATIONS`).
  Saved listings carry each subfolder's `results` count and `data_root`, so the REPORT badge and
  the root hints hold offline. `KINDS` gained `listings`; `remove_results` and `cache_move.verify`
  are unaffected (listings have no files).
- Probes (in this folder, `review-probe-seam-offline-preset*.py`; run as `tests/test_zz_*.py`
  copies, then removed): an arrangement preset with a plot and Live applied while offline for a
  folder seen online opens the plot, runs it on the folder's RAM data (shots 1–3), refuses Live with
  "Live is off while working offline", and starts only `cache_admin` helpers; for a folder never
  listed online, the plot waits ("Reading run's data from the disk cache…", then waiting) and
  nothing reads the folder. Two findings came out of them, neither a seam defect:

- **C-29 (low)** — `helab/views/plots/presets.py` (`PresetFolder.check`, the
  `selected_path_globally != self.folder` branch): offline, `open_to_path` of a folder with no saved
  listing leaves the selection on its parent (the tab can't list it), so the notice says "Live not
  started: another folder was selected", which isn't what happened. Fix: when
  `cache.offline` and the folder isn't the tab's node, say "can't be opened while working offline
  (not listed while online): its plots wait for its data".
- **C-30 (low, online; from the Presets Reopen floor, not the merge)** — `PresetFolder.check`
  gives up too early on a folder whose data isn't shown yet: in the probe, `apply("on")` (Live, no
  plots) on a folder with three shots, after the tab's startup listing had settled, ended with
  "Live not started: Select a folder with loaded data, or with no shots yet, to watch it for new
  shots" while the folder's load then completed and showed the data (`opened True data True`
  right after). `_busy()` covers `loading`, `load_waiting` and `settling` only; between
  `load_to_ram_cache` returning and the load (or a pending cached read, `_cache_read_path`)
  becoming visible there is a gap in which `live_unavailable` is asked and `finish()` called.
  Applied before the startup resolve answered, it instead ends "another folder was selected" (the
  resolve moves the selection after `open_to_path`). The repo's test uses an empty folder, which has
  no load, so it never sees this. Fix: after `load_asked`, wait for the next `dataLoaded` /
  `loadStateChanged` (or count a pending cached read as busy) before judging Live; and treat the
  startup resolve as the tab settling. Observed twice by the probe; the exact gap is my reading.

- **Batch 5** (`bbed82c`, `28c0dff`, docs `41df9ce`): both code commits read in full, accepted.
  C-14 (`bbed82c`): `byte_size` SI (999.5 / 1000), `app_log.MB`, `MIN_DISK_BUDGET` and
  `MIN_RAM_BUDGET` 10^9, the default budget 8e9, `CacheTab.GB` 10^9, the memory window in SI,
  `duration` = `span` on whole seconds; a saved budget keeps its bytes. C-29/C-30 (`28c0dff`):
  `PresetFolder.data_expected` keeps `_busy()` True from the load it asked until the data shows,
  the load fails or the folder is held as large; offline, a folder never listed online is named as
  such; `tests/test_preset_folder_live.py` from my probes, both failing before.
- **C-31 (quality; C-14 leftover)** — two byte sizes still binary after "SI everywhere":
  `helab/views/HelabMainWindow.py:346–347` (`update_status_bar_right`: RAM shown as "x.x GB" from
  `/ (1024 ** 3)`), and `helab/analysis/result_cache.py:40` (`LARGE_RESULT_BYTES = 50 << 20`,
  whose comment says "50 MB as HeLab shows sizes"). `CacheTab.py:148`'s `1 << 20` is a spin-box
  ceiling in GB (fine); `MAX_MARKER_BYTES`, `_LOCK_OFFSET`, `MAX_BINS` aren't sizes shown. Fix:
  `/ 1e9` and `50 * 10**6`.
- **C-31** (`e35df6f`): read, accepted (the two sizes in SI).

## Sign-off (Sextant, final head `e35df6f`)

Every commit of the follow-up (batches 3, 4 and 5 and C-31) was read in full and accepted, as were
batches 1 and 2 before. The combined branch (Cache Only's Work Offline merged at `c1da54d` plus the
review fixes) was checked where the two meet; no seam defect, and the two probe findings (C-29,
C-30) are fixed with tests. Final checks, run by me at `e35df6f` (floor root, `floor-env.sh`,
`--basetemp=.ai/temp/pytest-review`): `pytest -n 4 --reruns 5 --reruns-delay 1`: 4464 passed, 2
skipped, **no RERUN** (1:47); `mypy helab/ --strict` (162 files), `mypy tests --strict` (137
files), `pyright helab tests`: clean. Nothing blocks landing on my side; the follow-up isn't pushed
yet (CoCo's call), so CI on the final head is still to run.
