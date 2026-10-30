# Area review: `convert` (Reviewer 3, Carver), HeLab 0.0.7a1

Floor `agent/area-review` at `c3a503f`. Read-only. Scope: `helab/convert/`, `helab/convert_cli.py`,
`helab/io_ops/convert.py`, `helab/io_ops/helab_txy.py`, `helab/utils/txy_sources.py`, `file_kinds.py`,
`native/` (build scripts only), against AGENTS.md and `.ai/architecture/converter.md`. The boundary read:
`FolderCache.convert`/`_remember_convert` (`folder_cache.py:1219-1266`), Live's auto-convert
(`explorer_live.py:751-830`) and `cache_move.move`.

**Checks run.** `pytest tests/test_convert_*.py tests/test_live_convert.py tests/test_txy_files.py
tests/test_txy_sources.py tests/test_txy_last_used_quit.py tests/test_converter_tab.py -n 4 --reruns 5
--reruns-delay 1 --basetemp=.ai/temp/pytest-convert`: **3742 passed, 669 skipped, no RERUN** (the skips are
the unbuilt optional backends; log `.ai/temp/convert-review-tests.log`). One scratch test,
`.ai/temp/convert-review/test_again_watch.py` (run with `pytest -p tests.conftest …`), for convert-1.
Not rerun: the full suite and the type checks (no code changed on this floor, five reviewers share it,
and the brief asks for the area's tests); `0.0.7a1` passed them in CI.

**Summary: 6 findings: 0 High, 3 Medium (convert-3 is behaviour as designed, flagged for v0.0.8),
3 Low (one of them unverified), plus 3 Nits.** No data loss
and no wrong TXY found: the byte-for-byte path, the atomic write, the row-before-rename rule, the
no-replace beside write and the settle/damaged rules all hold.

## Findings

### convert-1 (Medium): `helab convert --watch F --again` never converts anything again

`helab/convert_cli.py:263` and `:317`. `--again` sets `redo = "always"` for the first pass only, and the
loop resets it to `"stale"` after every pass. But `--watch`'s first pass sends `seen = []`, so it only
records: every shot not already current waits as `changed` (`io_ops/convert.py:607-610`), and shots that
*are* current are skipped from `current` only because `redo == "always"`, then also wait. From the second
pass `redo` is `"stale"`, so every shot with a current TXY is `current` again (`convert.py:591`) and none
is converted. `--again` works only with `--once` (seen None, no first-pass wait).

Scenario: a folder already converted (shot 1 current in the temp folder); `helab convert --watch F
--again --output temp`: 4 passes, `convert_plan.todo` = `[0, 0, 0, 0]`, 0 `shot_converted`; pass 1 sends
`shot_waiting` `changed`. The same with `--once --again`: 1 converted.

Verified: scratch test `.ai/temp/convert-review/test_again_watch.py` (drives `convert_cli.main` with
`time.sleep` patched to stop after N passes; output above). No test covers `--again` (grep of
`tests/test_convert_helab.py`).

Fix direction: keep `redo = "always"` until the pass that actually converted (e.g. reset it only once a
pass ran with a non-empty `seen`), or treat `--again` as "convert each shot once more this run"
(remember the shots done this run); add a `--watch --again` test.

### convert-2 (Medium): "Path too long… choose a shorter cache or temp folder" can't be acted on this session

`helab/io_ops/convert.py:567-569`, `:693-696`, with the caller `helab/utils/folder_cache.py:1238-1243`.
A shot whose TXY path is too long is refused as `failed` with a message telling the user to choose a
shorter cache or temp folder (Settings) or switch where TXY go. The shot then sits in the folder's
`unconvertible` list, which `FolderCache.convert` sends back as `skip` whenever the **profile** is
unchanged. Nothing else resets `convert_lists`: not a cache-folder move, a temp-folder change, the
TXY output setting (cache/temp), the backend setting, nor auto-convert off and on (`_convert_off` only
cancels; `convert_lists` is written only by `_remember_convert`). So after following the advice, the
shot is still skipped (`skip.get(name) == stat` comes before any look at the new destination) until
HeLab restarts or the raw file changes. The same applies to a shot that `failed` under one backend
(e.g. a compiled kernel's error) after switching back to `numpy`.

Scenario (Windows, long paths off): a user profile (33-character tag), cache folder deep enough that
`…\converted-txy\<24 hex>\d_txy_helab_u<32 hex>_123.txt` passes 259 characters. Live shows
"1 unconvertible" with the message; the user switches Settings → TXY converter output to temp (or moves
the cache to `C:\HC`); every later Live conversion still lists the shot as unconvertible.

Verified by reading the code path (the lists are keyed by folder path and compared only on
`lists["profile"] == profile`). The architecture file states "the shot isn't tried again while its raw
file is unchanged, this session" (Q23.6), so the rule is documented; the advice in the same message
contradicts it.

Fix direction: key the remembered lists (at least `unconvertible`/`skip`) by what made them, i.e. profile,
backend, destination, and the cache and temp folders, as the profile already is; or drop `failed` entries
from `skip` when any of those changed. A one-line test: a `failed` shot converts after the destination
changes.

### convert-3 (Medium, forward compatibility; behaviour as designed): 0.0.7a1 sets aside a newer HeLab's live index on every conversion

`helab/convert/provenance.py:434-450` (`open_index(write=True)`: `version > SCHEMA` → `reason = "newer"` →
`set_aside`). The released 0.0.7a1 renames a newer HeLab's `converted-txy/index.sqlite` (with its
`-wal`/`-shm`) to `index-newer-<UTC>-<8 hex>.sqlite` and starts a schema-1 index, whenever it converts
a shot into that base. Two HeLabs sharing a cache folder (Tony's machine running a dev build and the
release; a lab PC upgraded while `helab convert --watch` from the old build still runs) then
ping-pong: each conversion by the old one drops all of the new one's rows (all shots convert again under
the new one) and leaves another `index-newer-…` file that, by design, no Clear ever removes, so they
accumulate. `index_schema`'s own docstring (`provenance.py:475`) says a newer index is "never ours to
change", and Clear honours that, but the writer path does change it.

Verified by reading; `tests/test_convert_helab.py:1489` (`problem="newer"`) asserts this set-aside
behaviour, so it is intended. It matters now because 0.0.7a1 is released and can't change: **v0.0.8
(caching v2 / store-v4) must not raise `user_version` in `converted-txy/index.sqlite` in place**.
Moving provenance into the store's `txy_layers` (as planned), or a new file name, avoids it.

Fix direction: record this constraint in the caching-v2 plan (Coordinator); in a later build, treat a
newer index like a newer store (convert to the temp base or fail the conversion) rather than setting it
aside. Possibly a decision for Tony (Q~1 below).

### convert-4 (Low): a large shot whose worker dies is "unconvertible" for the session; in the pool path the same crash is retried

`helab/io_ops/convert.py:743-759` vs `:857-858`. With one shot of ≥ 20 MB (`SPLIT_BYTES`) and workers > 1,
`convert_shot(..., executor=pool.executor)` runs its pieces in the pool (`split.reconstruct_split`,
`executor.map`); a worker killed (out of memory, a native crash) raises `BrokenProcessPool`, which the
`except Exception` at `:757` turns into `refuse(shot, "failed", …)`; the shot is then skipped while
unchanged (convert-2's lists). In `_convert_in_pool` the same `BrokenExecutor` is re-raised as "not the
shot's fault: the conversion fails, and is tried again". The in-process path likewise makes a
`MemoryError` permanent for the session.

Scenario: Live on a dense 25 MB shot (the architecture's "Live's worst case"), the OS kills a worker
under memory pressure: the shot shows as unconvertible ("Conversion failed: BrokenProcessPool: …") until
restart, while a 15 MB shot under the same pressure would have been retried.

Verified by reading (`split.py:104`: `executor.map`, no handling). Not reproduced.

Fix direction: re-raise `concurrent.futures.BrokenExecutor` (and probably `MemoryError`) at `:757` as
the pool path does.

### convert-5 (Low): `done`/`kept` lists carried across a destination or beside change are trusted by file presence alone

`helab/io_ops/convert.py:530`, `:570-575`. A shot in the previous `done` (or `kept`) list with the same
raw stat is taken as current (or kept) if *a* TXY of the tag exists in the **current** destination
(`_txy_shots` lists names only), without the provenance check (`stale`) that a shot not in the lists
gets. The lists survive a change of destination (Don't cache toggled, output setting, beside flag on or
off, or a one-off flag read failure that turns beside off for one conversion). So (a) a shot `kept`
beside is reported `kept` in cache/temp mode if any TXY of its tag is in HeLab's folder there, though
`kept` means "a TXY in a source folder we don't stand behind"; (b) a shot `done` in one destination whose
TXY in the other has no row (index set aside as damaged) stays `current` for the session, while loads
(`helab_txy.find`) reject that TXY, so `helab-only` shows nothing for it.

Verified by reading. Both need an unusual sequence; no data is lost or overwritten.

Fix direction: send `there` only for the destination the lists were made for (store the summary's
`output`/`folder` with the lists and drop `done`/`kept` when they differ), or keep `kept_before` only
when beside.

### convert-6 (Low, Unverified): TXY copied to a coarser-timestamp disk by a cache move all look changed

`helab/convert/provenance.py:158` (`stale`: the TXY's `(size, mtime_ns)` must equal the row's exactly,
Q30.1) with `helab/utils/cache_move.py:399` (`shutil.copy2`). A copy move to a file system with coarser
mtimes (HFS+ 1 s, exFAT 10 ms, some shares) would round every TXY's mtime, so every HeLab TXY under the
moved cache is "changed" and converted again (written over, not lost). Unverified: confirm by copying a
TXY with `copy2` to an HFS+ or exFAT volume and comparing `st_mtime_ns`. If confirmed, compare mtimes at
the destination's resolution, or rewrite the rows' `txy_mtime_ns` after the copy (boundary with
`cache`).

## Nits

- `helab/convert_cli.py:55-58`: `--profile` and `--backend` default to `matlab-2019`/`numpy`, not
  Settings → TXY converter's profile and backend, while `--output` defaults to the setting. Someone
  whose app converts with `plates-2025` gets `m19v1` TXY from the command line, which the app's
  `helab-priority` loads then ignore. And it uses the default settle time, not Settings → General's
  (`fingerprints.py:29-31` says `helab convert` "reads no settings"; it does read `converted_txy_output`).
  Either make all three follow the settings or say in `--help` which do (Q~2).
- `helab/utils/file_kinds.py:27-28` (and `TXY`): `\d` without `re.ASCII` takes leading zeros and
  non-ASCII digits: `d01.txt`, `d1.txt` and `d١.txt` are all shot 1 (checked in Python). The converter
  then writes both raw files to one `d_txy_helab_<tag>_1.txt` (the later replaces the earlier, and the
  two alternate across sessions). The TDC never writes such names; `0|[1-9][0-9]*` with `re.ASCII`, as
  `HELAB_TXY` has, would make it impossible.
- `helab/io_ops/convert.py:773-825`: `_remove_partial` and `_remove_own_partials` repeat the same age and
  regular-file rules; the second neither traces nor logs its unlinks (HeLab's own folder, so allowed, but
  `partial_removed` is its only record).

## Checked and fine

- **Byte for byte**: backends are tested on every case in `tests/data/convert/` (the backend tests ran);
  `format_txy` refuses anything but 2-D float64; the CI "Converter backends" file list covers every test
  that runs a backend (`test_convert_reference` uses the reference only).
- **`PURE`** lists every `helab/convert` module except `backends.numba_kernels`, as documented.
- **Atomic writes** (`txy.write_atomic`): `O_EXCL` 0o666 temporary, fsync, `before_rename` with the
  temporary's stat, `os.replace` or the no-replace rename (hard link, `renamex_np`/`renameat2`, Windows
  `os.rename`, else ENOTSUP, never check-then-rename), temporary removed on any failure, folder fsync.
- **Row before rename** (`convert.py:675-705`): the pinned row names the temporary's size and mtime; a
  failed write `forget`s it only if still its own (SHA-256 and mtime); two writers side by side end
  consistent or stale, never wrong (worked through all four interleavings).
- **Source folders**: only beside writes, only with the store's flag or `beside_confirmed`, `_guard`ed and
  traced, never replacing; leftovers removed only by `partial()`'s exact pattern, `lstat`, regular,
  1 h old. Raw files are opened read-only.
- **Settle and damaged rules** (A10.1, Q18.5, Q23.7): age, two looks via `seen`, fstat before and after the
  read, future dates, `first_seen` carried and reset when the stat changes, `--once` at 60 s; the
  profile-change path in `FolderCache.convert` drops reasons but keeps first-seen times.
- **Index**: WAL or DELETE by `journal_for`; `_patient` retries; readers never create or set aside;
  `IndexUnavailable` fails the conversion before the rename; Clear never removes the live or a newer index.
- **Remembered lists across profiles** (the QF7 fix): `FolderCache.convert` compares the whole profile
  dict, so a trigger-channel-only change (same hash and tag) also resets the reasons.
- **`helab_txy.find`**: beside TXY by tag and date, HeLab's folders by row (`stale` with the wanted hash),
  held shots trusted only for the same origin and stat, newest `converted_at` wins across the three folders.
- **Workers**: compute only; exit on the parent's pipe EOF; heartbeats stop after `compute_budget`.
- **CLI**: registers as a running HeLab, asks only on a terminal for a Don't cache folder, exits 1 only
  for a failed `--once`.

## Proposed for the Coordinator

- known-issues: convert-1, convert-2, convert-4, convert-5 (and convert-6 if confirmed).
- `roadmaps/caching-v2` (or the converter roadmap): convert-3's constraint ("0.0.7a1 sets aside a newer
  `converted-txy/index.sqlite`: don't bump its `user_version` in place").
- `converter.md`, "`helab convert --watch`": `--again` works with `--once` only (until convert-1 is
  fixed); the CLI's profile, backend and settle time are the defaults, not the settings.
- Q~1 (Tony): should an older HeLab set aside a newer HeLab's TXY index (today) or leave it and write to
  the temp base / fail the conversion? Proposed: leave it, like a newer store.
- Q~2 (Tony): should `helab convert` default to the app's conversion profile, backend and settle time?
  Proposed: yes, all three, with the defaults named in `--help`.
