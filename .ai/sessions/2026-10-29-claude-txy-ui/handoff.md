# Handoff: TXY converter stage 4, TXY source choice and profile manager (`agent/txy-ui`)

Worker: Facet (Claude Code, Opus 5.5), 2026-10-29. Base `01776d6`; brief in [brief.md](brief.md).

## Summary

Loads, Live checks and Live's saves now read HeLab's own TXY as a **TXY source** asks (Q6.6): by
default MATLAB's `d_txy_forc` with HeLab's current TXY filling the shots MATLAB lacks; per plot also
HeLab's wherever they exist, or both as two datasets (MATLAB's only, HeLab's only). Every dataset,
view, result key and cache records its source and each HeLab shot's profile hash, so caches and
saved results never mix sources; data of MATLAB's TXY alone keeps the identity, signature and saved
results it had. Settings → TXY converter is the profile manager (Q6.11) and picks the profile,
backend and output conversions use. Settings → Cache shows HeLab's converted TXY with a Clear (asked
first, through a helper), and Clear folder preferences names the `write_beside` flag. The plate
built-ins exist (as JSON files too, A10.3), and a plot's settings show the plate profile the swap
dates suggest for its folder (shown, never applied, Q6.10).

**Checks** (at `e4f52e3`): `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`:
**8103 passed, 669 skipped, no RERUN** (the skips are the compiled/MLX backends' tests, as on Ground).
`mypy --strict` helab and tests and `pyright helab tests` clean for darwin and linux; for win32 /
Windows only helab-core's known `helab/io_ops/convert.py:344–346` (Keel is fixing them). GUI:
Settings rendered offscreen with the floor's settings file (`floor-env.sh`), synthetic data only.

## What was built

| Path | What |
|---|---|
| `helab/utils/txy_sources.py` (new, stdlib) | The sources (`matlab` default, `helab`, `matlab-only`, `helab-only`), labels, origins (`""` MATLAB, `helab:<profile hash>`), `choose` (which kind a shot takes; held shots keep theirs), readers of a dataset's `txy` metadata, `describe`. |
| `helab/io_ops/helab_txy.py` (new) | Finding HeLab's TXY where `convert` writes them (`folders`: `folder_for(cache base, root key)`, `folder_for(temps, root key)`, `folder_for(temps, "path:"+abs)`; beside ones from the source listing), **current only** (`provenance.stale` with the raw file's stat and the profile hash asked for; "" any); `compose`, `record`, `matlab_signature`, `folder_state` / `state_unchanged` (HeLab's folders' mtimes for quick checks), `converted_usage` / `clear_converted` (Settings → Cache). HeLab's folders are read with plain `os` calls (not source I/O, not traced). |
| `helab/io_ops/loading.py` | `load(..., txy=, memory_origins=)`: MATLAB's, beside and HeLab's folders composed per source; held, cached and in-RAM shots reused only from the same kind of TXY; HeLab's folders' state joins both quick checks; a 0-byte HeLab TXY (no hits) is an empty shot; `loaded`, `read_cached` and the cache `info` carry the `txy` record; the dataset's `signature` stays **the folder's** (its settled MATLAB TXY, as a scan computes it), whatever the source. HeLab's TXY outside the source folder are named in full in `names` (the quick check's samples join them). |
| `helab/io_ops/live.py` | `live_check(..., txy=, memory_origins=, helab_since=)`: the same composition; held shots keep their kind while that TXY exists (a MATLAB TXY arriving for a HeLab-filled shot doesn't stop Live); HeLab's folders' state (`live_helab`, sent back as `helab_since`) must be unchanged for the one-stat and pending-files shortcuts, so a shot converted since is found; settle rules unchanged. |
| `helab/io_ops/save_held.py` | `save_held(..., txy=, held_txy=)`: held HeLab shots checked against their own TXY; saved with their record. |
| `helab/io_ops/events.py` | `TxyRecord`; `txy` on loaded events; `live_helab` on `LiveState`; `converted_txy` on `AdminResultFields`. |
| `helab/io_helper.py` | Passes the new fields. |
| `helab/io_ops/admin.py` | `inventory` has `converted_txy` {files, bytes, folders}; action `clear_converted_txy` (sends `removed`, kind `converted_txy`). |
| `helab/analysis/dataset_view.py`, `results.py`, `budget_core.py` | `ViewIdentity.source` ("" default), `DatasetView.origins`, `txy_profiles`, `txy_text()`; `Coverage.origins` (in `to_json` only when present); `reuse_key` gets `txy_source` only when not the default; `revise` and `restore` never cross a source or an origin; the result record's tooltip names the TXY source. |
| `helab/utils/folder_cache.py` (load path only) | `with_txy` completes every load's `txy` options (source, `convert_profile()`'s hash, bases, root key); `source_suffix` / `dataset_key`: another source's dataset has its own key and job (`load:<source>`), is never the tab's (`current_dataset`, `latest_dataset`, `_base`, `_drop_superseded` by source); `memory_origins` with the base, `txy` in `memory_check`, `held_txy` with Live's save, `helab_since` from the last Live event; `convert_profile()` / `set_convert_profile()`. No change to convert submission. |
| `helab/views/plots/txy_source.py` (new), `instance.py` | The plot's TXY row (choice; the profile HeLab converts with; the plate suggestion). `AnalysisInstance.set_txy_source`: the default runs on the tab's data; another source loads its own dataset of the folder (RAM only, `no_cache`) and loads again on each Live revision; the source line says `TXY: HeLab only` (or `TXY: 3 shots from HeLab's` on the default). A released plot of another source isn't reloaded from the disk cache (it holds the default's dataset only). |
| `helab/views/ConverterTab.py` (new), `SettingsDialog.py` | Settings → TXY converter: profile / backend / output (saved with Save; FolderCache learns the profile), the profile list (built-ins read-only, plates-2025 uncalibrated, unreadable files named), Duplicate, Edit (`ProfileEditor`: a form over every field, validated, hash shown, a changed output bumps the version), Delete (asked), Import (asks a name when taken), Export, Show folder. Tabs are 125 px so six fit the 800 px dialog. |
| `helab/views/CacheTab.py` | Row "HeLab's converted TXY" (files · size, Clear… asked first, through the helper); Clear folder preferences says and counts `write_beside`. |
| `helab/convert/profile.py`, `builtin_profiles/*.json` (new), `setup.py` | `plates-2017`, `plates-2022`, `plates-2025` (copies of matlab-2019, same hash; `UNCALIBRATED`), `PLATE_SWAPS`, `suggested_plates`, `builtin_files()` (the packaged JSON, tested equal, A10.3); package data. |
| `helab/convert/user_profiles.py` (new, `PURE`) | `ProfileLibrary` (JSON per profile in `<app folder>/profiles`, atomic save, scan with unreadable files, find, delete, import/export, `free_name`), `check_name`, `duplicate`. |
| `helab/utils/settings_defaults.py`, `constants.py` | Rows `convert_profile` (matlab-2019), `convert_backend` (numpy); `profiles_folder()`, **`read_convert_profile(settings)`**, **`read_convert_backend(settings)`**. |
| Tests | New: `tests/test_txy_sources.py` (23), `tests/test_converter_tab.py` (9), `tests/test_profile_library.py`. Updated: `test_convert_profile` (built-ins), `test_headless_imports` (`user_profiles` pure), `test_helper_dispatch` (fields), `test_settings_defaults` (`converted_txy_output` now read by the dialog), `test_settingsDialog` (tabs), `test_folder_flags` (question text). |

## Interfaces (for Lantern, packaging and later floors)

- **Conversion settings:** `constants.read_convert_profile(settings) -> DetectorProfile` (a built-in or
  user profile by the `convert_profile` row; missing → matlab-2019) and
  `constants.read_convert_backend(settings) -> str` (a `_MODULES` name, else numpy), beside
  `read_convert_output`. In the app, `FolderCache.convert_profile()` is the same profile and follows
  Settings' Save at once; send `profile.to_dict()` in the convert payload.
- **Loads:** every `load` through `FolderCache.submit` gets `txy` (source default `matlab`); a caller
  wanting another source sends `{"txy": {"source": "<source>"}}` with `no_cache: True`. Dataset
  metadata `txy` = {source, origins {shot: "helab:<hash>"}, profiles {hash: {name, version,
  calibrated}}, profile_hash, folders}.
- **Live after a conversion:** a HeLab TXY is read under the same rules as MATLAB's: settled
  (`SETTLE_SECONDS`, 5 s, by its mtime) and seen unchanged at the previous Live check. So a shot
  converted now reaches the data at the second Live check that is at least 5 s after its write; a
  check requested right after `shot_converted` lists it (HeLab's folder changed) and waits it. If
  Lantern wants it at once, it can request one more check `SETTLE_SECONDS` later.
- **Only HeLab TXY made with the conversion profile's output are loaded** (its content hash): a
  profile change hides HeLab TXY of another output until reconverted (plates-20xx and matlab-2019
  share a hash today, so switching among them hides nothing).

## Decisions made here (technical; say if one is Tony's)

- The dataset `signature` stays the folder's MATLAB-TXY signature for every source: the tab compares
  it with the scan's, and HeLab's TXY in it would make every folder look changed and reload. The
  source enters identity through `ViewIdentity.source`, per-shot origins and the result key instead.
- The tab and Live always load the default source; other sources are per plot, RAM only (no disk
  cache yet), and follow Live by reloading their dataset at each of the tab's Live revisions.
- (c) "both, as two datasets" is offered as two choices, "Both, as two datasets: MATLAB's" and
  "…: HeLab's": one plot on each (Q~1).
- Clearing converted TXY keeps the records of TXY written beside raw files (else those TXY could no
  longer be loaded), never follows a link, removes only HeLab's own names, and isn't fenced against a
  conversion running at that moment (its write then fails and the next check converts again).
- A 0-byte HeLab TXY (no hits, Q10.3) loads as an empty shot, not as unreadable (MATLAB's 0-byte
  files stay "problematic" as before).

## Provisional items

- **Q~1** (Tony): how (c) "both as two datasets" shows in the plot settings. Built: one choice per
  dataset (two plots side by side). Alternative: one plot drawing both (needs scripts that take two
  views), or a button that opens the twin plot on the other dataset.
- **Q~2** (Tony): should a plot's TXY source be saved with presets, arrangements and the plots that
  reopen at start? Not built: a reopened plot uses the default (the record format is
  `analysis/presets.py`'s; adding a field there is a format change).
- **Q~3** (Tony): HeLab TXY of another profile than the one conversions use are not loaded (built).
  Alternative: load any current HeLab TXY whatever its profile (the identity records it per shot).
- **Q~4** (Tony): the folder's status (ok / fixable…) and counts still come from MATLAB's TXY alone;
  a folder with only HeLab's TXY shows its raw files without TXY. Proposed: count current HeLab TXY in
  the status once scans can see HeLab's folders cheaply.
- **Q~5** (Tony): datasets of a non-default source are RAM only. Proposed: keep it so until (b) or
  (c) are used much; caching them needs their own store key (a store change).
- **A~1** (packaging floor): add `helab/convert/builtin_profiles/*.json` to `HeLab.spec` `datas`
  (`builtin_files()` and A10.3's test read them; the app itself uses the definitions, so a build
  without them still converts).
- **A~2**: the plot's TXY row is checked by unit tests and offscreen rendering only; an end-to-end
  GUI test of a plot switching sources on a folder with real helpers (convert, load, Live) would
  catch wiring that the unit tests stub.
- **M~1** (Tony, synthetic or lab copy): open a folder converted by HeLab (Live auto-convert or
  `helab convert --once --output cache`), open a T histogram, switch its TXY between the four
  choices, check the source line and that Live keeps each plot on its own source.
- **M~2** (Tony): Settings → TXY converter: duplicate plates-2022, edit a time sum, set it as the
  conversion profile, Save; convert a folder; check its provenance names the new profile and the
  plots load those TXY (and not the old ones).

## Proposed doc changes (for the Coordinator)

### `.ai/architecture/converter.md`, "In HeLab (stage 4)"

Add a section **TXY sources (Q6.6)**: the four sources and origins (`helab/utils/txy_sources.py`);
`io_ops.helab_txy` finds HeLab's TXY in `folders()` (cache base by root key, temps by root key,
temps by path) and beside, current by provenance for the conversion profile's hash; `load`,
`live_check` and `save_held` take `txy` and the held origins; reuse only from the same kind; HeLab's
folders' mtimes in the quick checks (`txy.folders`) and Live (`live_helab` / `helab_since`); the
dataset signature is the folder's MATLAB one; 0-byte HeLab TXY = empty shot. Add **Profiles in the
app**: the plate built-ins and `PLATE_SWAPS`/`suggested_plates`, `builtin_profiles/*.json`
(`builtin_files`, A10.3), `user_profiles` (`<app folder>/profiles`), the settings rows and readers,
Settings → TXY converter. Module table: `user_profiles`; `profile`'s row: plate built-ins, JSON.

### `.ai/architecture/plots-and-scripts.md`

After the DatasetView sentence: "a view's identity also names its TXY source (`source`, "" for the
default) and each HeLab shot's origin (`origins`); results record their covered shots' origins and,
for another source, `txy_source` in the reuse key. Each plot's settings have a TXY row
(`helab/views/plots/txy_source.py`): the default runs on the tab's data; another source is a dataset
the plot loads itself (RAM only) and reloads at each Live revision."

### `.ai/architecture/cache-store.md`

Datasets: "a dataset's `info.txy` records its source and HeLab shots' origins; shots are reused only
from the same kind of TXY; data of MATLAB's TXY alone is as before." The converted-TXY sentence:
"Settings → Cache shows their size (`inventory.converted_txy`) and clears them when asked
(`cache_admin clear_converted_txy`, `removed` kind `converted_txy`; records of beside TXY stay)."

### `.ai/architecture/io-and-browsing.md`

"Loads and Live checks also read HeLab's folders under the cache and temp folders (`io_ops.helab_txy`,
plain calls, not source I/O); FolderCache adds `txy` to every load (`with_txy`); another source's load
has its own job key `load:<source>`."

### `.ai/architecture/settings.md`

The rows `convert_profile` and `convert_backend` (Settings → TXY converter) beside
`converted_txy_output`, read by `read_convert_profile` / `read_convert_backend` /
`read_convert_output`; user profiles are files in `<app folder>/profiles`, not settings.

### `AGENTS.md`

- Code map: `helab/convert/user_profiles.py` in the converter row; `helab/views/ConverterTab.py` in
  the views row; `helab/io_ops/helab_txy.py` in the helper row.
- The housekeeping list needs nothing new (the Clear is the user's, asked first, sends `removed`).

### `AI_TODO.md` / `DECISIONS_TODO.md`

A10.3 done. Q6.6 built as decided, with Q~1–Q~5 above. Q6.10's plate suggestion built (shown only).
