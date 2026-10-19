# Notes: D7 shot times

## Design

**What a shot time is.** `raw_times`: `[shot, mtime_ns]` of each shot's raw `d<N>.txt`
file (`file_kinds.RAW`, `^d(\d+)\.txt$`, same folder as `d_txy_forc<N>.txt`), where the
helper found one. A shot without an entry has the TXY fingerprint's mtime as its time, flagged
as a fallback. This covers "raw file gone" and "dataset cached before shot times" with one
rule and no extra field: `DatasetView.shot_time(shot)`, `shot_times(shots)`,
`fallback_times(shots)` (`helab/analysis/dataset_view.py`). The view's `raw_times` mapping is
read-only like the rest. Parsing is in one place, `file_kinds.raw_times` (helper-safe, used by
the helper, `FolderCache` and the view).

**Where the time comes from (helper, `helab/io_helper.py`).** The load and Live listings already
scandir the folder and match every name against `FILE_KINDS`; they now keep the RAW entries'
`DirEntry` objects. A raw entry is stat'ed (`_raw_mtime`, `DirEntry.stat()`, trace reason
`load: shot time` / `live: shot time`) only when its shot's time is not already known:

| Path | Raw stats |
|---|---|
| `load`, a shot read from its TXY file (new or changed) | 1 per shot |
| `load`, shot reused from the disk cache with a saved time | 0 |
| `load`, shot reused from a cache saved before shot times | 1, once: the time is saved (merge save or `confirm_dataset`) |
| `load`, shot held in RAM (`memory`, source `updated`) | 0: the app has its time |
| `load` with `cache_base` (the check beside a cached read) | 0, or 1 per shot the cache lacks a time for |
| `load`, held shot read again for the cache save | 1 per such shot (beside a TXY read) |
| quick checks (`_unchanged_since_cache` / `_memory`), `read_cached` | 0 (no listing; times from the cache / app) |
| `live_check`, a new shot read | 1 per new shot; a held shot read again keeps the app's time |
| `save_held` (Live's save) | 0: the app sends its times (`held_raw_times`) |

**I/O cost.** On Windows `DirEntry.stat()` uses the listing's find data: no call. On macOS and
Linux it is one `stat` per raw file, the same as a separate stat; on SMB each is a network
round trip (not measured on a real share here). A load already makes four stats and one read
per TXY file it reads (listing, before, after, verifying), so the raw stat adds a fifth small
metadata request; it only happens alongside a TXY read, a one-off fill-in of an
old cache, or a re-read for the cache. A load of a folder
already cached with times stats no raw file. An "unknown" time is never retried in a loop: a
shot whose raw file is not listed gets no stat at all (the listing's names tell). A raw file
listed but gone by the stat (`OSError`) is a fallback, never an error.

**Carrying times (GUI, `helab/utils/folder_cache.py`).** `shot` events carry `raw_mtime`
(`SharedJob.raw_times` keeps them, so a resumed load keeps completed shots' times:
`_resume_load`); `loaded` carries `raw_times` for what the helper knows. `dataset_raw_times`
builds the dataset's list: the base's times (for shots it held: an update sends none for them),
then the event's, then the shot events'; only shots in the fingerprint. A shot whose TXY file is
read again keeps its time: the raw file is the same shot. Live's save sends the held dataset's
times as `held_raw_times`. `revise` / `with_shots` add new revisions' times to the view.

**Fingerprints unchanged.** Raw files enter no fingerprint, signature, summary signature,
reuse decision, `shots_missing` check or quick-check sample. Deleting a raw file changes only
that a later *new* listing doesn't stat it; the cached time stays (tested).

## Disk cache format change and compatibility

- New column `datasets.raw_times TEXT NOT NULL DEFAULT '[]'` in `store-v3`
  (`helab/utils/cache_store.py`). Not in `info`: `read_dataset_infos` reads `info` for every
  subfolder of a listing, and a per-shot list there would grow every listing's read. Not in the
  fingerprint (semantics) and not in the packed dataset file (a fill-in would mean rewriting it).
- Existing stores gain the column when a helper opens them writable (`_add_raw_times`: checked
  with `PRAGMA table_info`, added under `BEGIN IMMEDIATE`, re-checked inside so concurrent
  helpers don't race). No layout-version bump: older HeLabs name their columns in every
  `SELECT`/`INSERT`, so they keep reading and writing the store (their saves leave `[]`). A
  read-only store without the column (a newer layout opened read-only) selects `'[]'`.
- `DatasetRecord.raw_times` is `NotRequired`; pending saves keep it inside their record JSON, so
  Make room / Save update adopt it with the dataset. `confirm_dataset(..., raw_times)` records
  times an older cache lacked, after a full listing found the cache complete.
- Old datasets: their shots are fallbacks until a listing check of the folder with the cache as
  base (selecting it in a new session runs the cached read and that check beside it, unless the
  quick check answers; Retry / Refresh always lists). The quick check (one folder stat) doesn't
  list, so a static old folder keeps TXY times until Refresh. Proposed, for Tony: acceptable,
  since the plot flags them; a background fill-in is possible but would add raw stats to a check
  that is otherwise one stat.

## The plot

`helab/scripts/standard/shot_times.py`, `ShotTimesPlot` ("Shot times", `helab.shot_times` v1,
Basic plots v1, after "T, X, Y histograms" in the panel). Parameters: the shared Shots, **Show**
(counts and gaps / counts / gaps) and **Log gaps**. Two stacked PyQtGraph plots sharing a
`DateAxisItem` x axis (local time): events per shot, and time since the previous shot (by shot
number; the first has none; negative when a shot's time is before the previous one's). Raw times
are blue circles, TXY times amber triangles (legend entry only when present); gaps from or to a
TXY time are amber too. Title: shots, events, the longest gap (between raw times when any: a
conversion time would make up a stall) and "⚠ N TXY times (no raw file)"; the dock's first line
carries the same count. Tooltip: what the time is and that a copied or rewritten file has a new
mtime. `update` refreshes the points in place (Live keeps zoom and pan) unless Show or Log gaps
changed. Live policy and coverage are the defaults (every shot; the Shots selection).

## Proposed, for Tony

1. **Shots without events are drawn** (at 0 events) rather than "No events in the chosen
   shots": they have times, and a run of empty shots is what a stall or detector fault looks
   like. The counts plot keeps its empty note. (So the plot is not in the shared "no events"
   empty-case parametrisation in `tests/test_live_plots.py`.)
2. **Gap units in the title** adapt (s, min, h, d); the gap axis is in seconds, with Log gaps
   for mixed scales.
3. **Old caches fill in times only on a listing check** (above), not by the quick check.
4. **Times by shot number**: a shot keeps its raw time when its TXY file is rewritten, and after
   its raw file is deleted.
5. **Counts plot against time**: D7 here is a separate plot; D2's trends (per-shot fits, moving
   mean) can take `DatasetView.shot_times()` for a time axis option later.

## Considered and not done

- Statting raw files during the listing pass for every shot (simplest, but on macOS/Linux and
  SMB it is one stat per raw file on every load and Live listing, even when every time is known).
- A separate `shot_times` table: every removal, purge, root clear and re-key would need to
  delete or move its rows too; a column moves with the row.
- A layout bump to `store-v4`: would start an empty cache for an additive change.
