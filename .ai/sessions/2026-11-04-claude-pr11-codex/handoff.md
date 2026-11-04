# Handoff: PR #11's Codex review fixes (`agent/pr11-codex`)

Worker: Ledger (Claude Code, Opus 5.5), 2026-11-04. Base `ded2f3b` (brief `2c7625f`). Commits, one per finding,
each with the test that fails without it:

| Finding | Verdict | Commit |
|---|---|---|
| C-1 (P1) a view's shots vs. its layer entries | **confirmed** | `0d2b9c7` |
| C-2 (P1) TXY sources mixed when marking layers seen | **confirmed** | `49726d1` |
| C-3 (P2) completion check before converting cached raw pulses | **confirmed** | `eafc3fc` |

No schema change (no `store_v4.migrate` addition), no version bump. Paths beyond the brief's: `helab/io_ops/loading.py`
and `helab/io_ops/save_held.py`, one call each (`mark_seen`), with CoCo's OK for that call only.

## C-1: confirmed

**Cause.** A view item was `[shot, size, mtime_ns, "txy", layer]`: the TXY file the view's composition chose, and
the layer, but not *which entry* of the layer it saved. `Access._read_data` read `read_txy_shots(path, layer, shots)`,
by shot number alone. Two views share a layer (External-only and the priority modes both use `matlab`), and a save
through one replaces the shared entry (`_apply_txy_unit`, a later job wins). The other view then served the new
arrays under its old fingerprint. Loads were mostly safe (a changed TXY fingerprint drops the shot by `baseline`), but
`read_cached` sends the view's fingerprint and signature as they are, so result reuse keys could match other data.
`cache-store.md` already said "a view whose layer entry is gone or doesn't match is incomplete"; the code didn't check.

**Fix.** Each view item records the layer entry key it was saved with: `[shot, size, mtime_ns, "txy", layer,
[entry size, entry mtime_ns, entry kind]]` (`Access.write`, from the save's `keys`). `read_txy_shots(…, keys=)`
leaves out a shot whose entry now has another key, checked on the same layer row its segments are read from (no
race with a save between the view read and the data read). Such a shot is unavailable: `read_cached` counts it as
failed, and a load reads it again ("Some cached shots are gone") and saves the view with the current key.
`confirm` keeps each item as stored, so `confirm_view`'s equality check still holds.
A view an earlier build saved (five items, `txy_cache.saved_key`): a MATLAB shot's key is its own TXY fingerprint
(Q45.3: MATLAB entries are always keyed by their TXY file), so it is still served; a HeLab shot's key is unknown, so
it is read again once (from the raw layer or its text) and the next save writes the key. That costs one re-read per
HeLab view saved by a pre-fix v0.0.8 dev build; no shipped release has store-v4 on. In detail (the landing review's
PR-1, accepted as is by CoCo): until that load, such a view serves no cached read (a HeLab-only view's raises "No
cached data for this folder"; a priority view's HeLab shots count as failed). Its first load reads its HeLab shots
again under **"Cached dataset invalid"** (not "Some cached shots are gone": `loading`'s `elif unpacked:` takes the
empty data as falsy; no change to `loading.py`), from the share where no raw layer is filled. After that save the view
has keys and the next load is `cached`, reading nothing.

**Tests** (`tests/test_txy_loading.py`):
- `test_a_view_leaves_out_a_shot_another_views_save_replaced_in_the_layer`: External-only view saved; shot 2's
  MATLAB TXY rewritten; the priority view's load saves it into the shared layer; `read_cached` of the External-only
  view. Before the fix it sent shot 2 (5 rows) under the old fingerprint; now only shot 1, `failed_files == 1`.
- `test_a_view_saved_before_entry_keys_serves_its_matlab_shots`: five-item view items still serve MATLAB shots, the
  quick path still reads nothing, and the next save writes six-item items.
- `test_old_helab_view_is_read_again_once_then_keyed` (PR-1's regression test, Probe2's scratch test, `f90217c`): a
  five-item HeLab-only view: `read_cached` raises "No cached data for this folder"; the next load is not cached,
  reads both shots under "Cached dataset invalid" and saves six-item items; the load after it is cached, reading
  nothing.

## C-2: confirmed

**Cause.** `Access.mark_seen(path, raw, [*matlab, *helab_found], listed_at)` sent one combined `"txy"` set, and
`mark_txy_seen` checked every TXY-keyed entry against `present[entry.kind]`. With a MATLAB TXY deleted and HeLab's TXY
of the same shot still there, a HeLab load's listing found the shot in the combined set and marked the `matlab` layer
seen (`gone_at` cleared). `purge_cached` and `clear_folder_data` (`gone_at IS NULL`) could then take the only copy, and
Make room put it in group 3 (seen) instead of 5 (only copies, named).

**Fix.** `mark_txy_seen`'s `present` is keyed by `"raw"` and by **layer name** (`"matlab"`, `"helab:<hash>"`). A
raw-keyed entry is checked against the raw files (unchanged), a TXY-keyed one against its own layer's TXY only. A
layer the listing names no TXY for has none, so it becomes an only copy. That is the conservative direction: a
false "gone" keeps data from ordinary removal; it never makes data removable. `Access.mark_seen(path, raw_shots,
matlab_shots, helab_shots: {shot: profile_hash}, listed_at)` builds it.

`mark_seen` callers (grep; calls go through `access.`): `helab/io_ops/loading.py:489` (load) and
`helab/io_ops/save_held.py:277` (Live's save). Both now pass MATLAB's shots and HeLab's found shots, with profile
hashes, separately. `mark_txy_seen` has no other caller in `helab/`. The tests that called it with `{"txy": …}`
(`tests/test_txy_layers_store.py` ×11, `tests/test_txy_fixes.py` ×2) all mark MATLAB layers and now say `"matlab"`.

Edge left as it is: a HeLab layer's **TXY-keyed** entries (HeLab shots saved while their raw file wasn't listed, a
rare race, since a current HeLab TXY needs its raw file) are seen only when this listing found that profile's TXY of
the shot. A listing that didn't look (another source, or a list stage an earlier stage covered) marks that layer an
only copy until a listing of its profile sees it again. That is conservative: it never allows removal.

**Tests:**
- `tests/test_txy_loading.py::test_helabs_txy_doesnt_make_a_gone_matlab_txys_layer_recoverable`: conversion into
  the cache folder, External-only load (MATLAB layer), MATLAB TXY of shot 1 deleted, HeLab-only load. Before the fix
  `gone_at` was None; now set, the HeLab layer (raw-keyed, raw files there) stays seen, and `purge_cached(…, ("txy",))`
  leaves the MATLAB layer.
- `tests/test_txy_layers_store.py::test_a_layers_txy_entries_count_only_their_own_layers_txy`: both directions
  (HeLab's TXY doesn't cover `matlab`, MATLAB's doesn't cover a TXY-keyed HeLab layer), and raw-keyed entries go by
  the raw files.

## C-3: confirmed

**Cause.** `raw_fill` caches a raw file whose first line isn't on a trigger channel (`_unfinished`: only the checks
that need no profile). `Access.from_raw` then reconstructed the pulses without `raw_layer.not_done(layer.facts,
profile.channel_trigger)`, so the same file that `convert_raw_file` rejects (late or damaged) became a valid-looking
shot, with the wrong first row as time zero, and was saved in a HeLab layer.

**Fix.** `from_raw` runs `raw_layer.not_done` on the layer's facts with the profile's trigger channel first. If that
check fails it returns None, and the load takes its normal path for that file: convert on read
(`convert_raw_file`'s late/damaged judgement, which depends on the file's age) or the TXY text. `from_raw` is the only
place cached raw pulses are converted (grep `raw_layer.decode`; `convert/check.py` is the developer harness, which
encodes the bytes it checks).

**Test** (`tests/test_txy_loading.py::test_a_raw_layer_not_starting_on_the_trigger_is_rejected_as_its_file_is`): the
same folder loaded from its raw files and, separately, after `raw_fill` cached both shots. Before the fix the
raw-layer load kept shot 2 in the HeLab layer; now both loads give `problematic == [2]`, the same `files`, and only
shot 1 in the layer.

## Checks

- Full suite on the floor at `eafc3fc`, macOS: `pytest -n 4 --reruns 5 --reruns-delay 1
  --basetemp=.ai/temp/pytest -rR` gave **9289 passed, 673 skipped, 2 warnings in 189.42 s; no RERUN** (no
  "rerun" anywhere in the output). The 2 warnings are pyqtgraph's NumPy 2.5 `arr.shape` deprecation in
  `test_t_spectrum.py`, unrelated.
- Type checks, all clean: `mypy helab/ --strict` (207 files), `mypy tests --strict` (210), `pyright helab tests`
  (0 errors), `mypy helab/ --strict --platform win32` (207), `pyright --pythonplatform Windows helab tests` (0 errors).
- After the landing review (PR-1's test `f90217c`, handoff `c609506`): full suite **9290 passed, 673 skipped, 2
  warnings in 141.04 s, no RERUN**; the five type checks clean again.
- Each new test was run before its fix and failed as described above.
- CI: run **41651767280** on `7238242` (push to `agent/pr11-codex`): **success**, every job green on macOS,
  Ubuntu and Windows (Build, Tests 1/3, 2/3, 3/3, Converter backends, each per OS; Docs; the 3.11/3.12/3.14 compat
  jobs are skipped, since they run on PRs only). Every Tests and Converter backends job's log was downloaded
  (`gh api …/actions/jobs/<id>/logs`, each 80 kB–1.4 MB) and read: **no RERUN in any of them**. Summaries: macOS
  3151/3075/3063 passed (Tests 1/2/3), 869 (Converter); Ubuntu 3150/3073/3063, 869; Windows 3143/3058/3051, 867.

## Proposed doc changes (Coordinator applies)

`.ai/architecture/cache-store.md`, store-v4 section:
- `txy_views` bullet: after "each shot's layer and fingerprint," add: "and the layer entry key it was saved with
  (`[…, layer, [size, mtime_ns, kind]]`; C-1, `0d2b9c7`). A view whose layer entry is gone or has another key
  (another view's save replaced it) is incomplete for that shot: a cached read leaves it out, and a load reads it
  again (`read_txy_shots(keys=)`). A view saved before the key (five items) derives a MATLAB shot's from its TXY
  fingerprint; its HeLab shots are read again once."
- `txy_layers` bullet, after the `gone_at` / `seen_at` sentence: "A listing checks a raw-keyed entry against the raw
  files and a TXY-keyed one against its own layer's TXY only (`mark_txy_seen`'s `present` by layer name; C-2,
  `49726d1`): HeLab's TXY of a shot never makes a MATLAB layer recoverable, nor the reverse."
- Stage 3 paragraph ("The order per shot is its TXY layer, the raw layer, …"): add "A raw layer is used only if
  `raw_layer.not_done` passes for the profile's trigger channel (`raw_fill` can't check it); otherwise the file is
  judged as `convert_raw_file` judges it (C-3, `eafc3fc`)."

From the landing review's PR-4 (Probe2, `review.md`):
- `.ai/architecture/io-and-browsing.md`, "Loads with TXY layers": in loading-order step (1) "its layer, with the
  current fingerprint (Q45.3's kind included)", add "and the entry key the view saved (C-1)"; change "Every v4 listing
  marks its sources seen (`mark_txy_seen`)" to "… each layer against its own source (C-2)"; add to step (2): "only if
  `raw_layer.not_done` passes for the profile (C-3)".
- `.ai/architecture/cache-store.md`, the `raw_fill` paragraph ("`raw.not_done`'s checks that need no profile;
  C3-2"): add "the trigger check runs when a load converts from the layer (C-3)".
- `.ai/architecture/cache-store.md`, the `txy_views` bullet (PR-1 accepted): add "a five-item view's HeLab shots
  serve no cached read and are read again once by its next load ("Cached dataset invalid"), which saves the keys".

`roadmaps/known-issues.md`: nothing new (no RERUN locally or in CI).

## The landing review (Probe2, `review.md`, `e25426b`)

No blocker; one Low, three Info:
- **PR-1 (Low)**, an old five-item HeLab view: accepted as is (CoCo); its regression test is `f90217c`, and the
  C-1 note above says what the user sees.
- **PR-2 (Info)**, `_view_row`'s `rows` / `ram_bytes` count a replaced entry's rows rather than the view's: accepted,
  no change. It is cosmetic (`_too_large` estimates from the fingerprint, and data is never served by it).
- **PR-3 (Info)**, C-2's safe side: a HeLab layer's TXY-keyed entries (rare) become an only copy under any listing
  that didn't find that profile's TXY, so it survives `purge_cached` and a folder's Clear, and Make room names it in
  group 5. Accepted, no change; it is the conservative direction (C-2 note above). MATLAB presence by shot number,
  not (size, mtime_ns), predates the fix (A~1 below).
- **PR-4 (Info)**, doc proposals: added under "Proposed doc changes" above.

## Replies CoCo can post to the Codex comments

- **C-1:** "Confirmed and fixed in `0d2b9c7`. Each view item now records the layer entry key it was saved with, and
  `read_txy_shots(keys=)` leaves out any shot whose entry has since been replaced by another view's save, checked on
  the same row its segments are read from. A cached read counts such a shot as failed, and a load reads it again.
  Older five-item views: MATLAB shots derive the key from their own TXY fingerprint; HeLab shots are re-read once.
  Test: `test_a_view_leaves_out_a_shot_another_views_save_replaced_in_the_layer`."
- **C-2:** "Confirmed and fixed in `49726d1`. `mark_txy_seen` now takes presence per layer (`raw`, `matlab`,
  `helab:<hash>`): a TXY-keyed entry is checked only against its own layer's TXY, so another profile's TXY can no
  longer make an only copy look recoverable. Both callers (load, Live's save) pass MATLAB's and HeLab's shots
  separately. Tests: `test_helabs_txy_doesnt_make_a_gone_matlab_txys_layer_recoverable`,
  `test_a_layers_txy_entries_count_only_their_own_layers_txy`."
- **C-3:** "Confirmed and fixed in `eafc3fc`. `from_raw` now applies `raw_layer.not_done(layer.facts,
  profile.channel_trigger)` before reconstructing; when it fails, the file takes the normal path and is rejected as
  late or damaged, as without a raw-cache hit. Test: `test_a_raw_layer_not_starting_on_the_trigger_is_rejected_as_its_file_is`."

## Follow-ups (provisional)

- A~1: none needed for these fixes. Optional: `mark_txy_seen` could use the sizes and mtimes it is passed (always
  `(0, 0)` today) to tell a replaced TXY from the one a layer holds; not needed for C-2.

## Round 2 (C-4): confirmed (`brief-c4.md`, base `2557480`)

**C-4 (P1), `script_tree.py`: no recheck of in-flight runs after the asynchronous script probe.** Confirmed by a
test before the fix. `_try_reload` checks `_busy` only before the round of test imports. The round's answer
(`_probe_then`'s `answered` → `_finish_reload` → `_load_folder`) then imports at once. A plot opened from the folder
during "Reload (checking)" (`run_analysis`, `reopen_plot`) computed on the old code while `load_directory` replaced its
helper modules. In the test, the real import saw **1** run of the folder's scripts in flight.

**Fix, `bac9ddf`: both of Codex's options.** Each covers what the other can't:
- **Held from its start** (`_hold_if_reloading`, called in `run_analysis` and `reopen_plot` before `start`). A plot
  is held this way when its folder is in the running round (`_round`) or waits to reload (`_pending`, also
  "Reload (waiting)" with the probe off). It computes nothing on code about to be replaced, and doesn't delay the
  reload. It takes the new code with the folder's other plots (`_adopt`), or keeps its code and says why
  (`keep_script`, for a folder that failed its test import), as plots held by Reload do. A reopened plot keeps
  waiting for its data (`adopt_script`'s rule).
- **The backstop** (`_end_round`). When the round answers, the answers are kept (`_answered`) and the import
  (`then`) runs only once no run of the round's still-listed folders' scripts is queued or computing, on any runner
  (`_busy`). Until then:
  - those folders' plots are held, so a plot opened any other way submits no more;
  - the reload waits on each runner's `finished`, reading "Reload (waiting)". The wait is `_wait_for_runs`, now
    shared with `_try_reload`, and the GUI thread never waits.

  `_probing` stays set while the reload waits, so a reload asked meanwhile still waits in `_pending` and follows in
  its own round. That round's plots are held again first, since this round's `_adopt` let them run. Removing a
  folder while an answered round waits for it lets the round go on (`remove_folder` calls `_end_round`, as L2
  does for "Reload (waiting)").
- **The start's restore** (`restore_folders` → `_restored`) goes through the same `_end_round`. Its window is empty:
  its folders' scripts aren't loaded until `_restored` imports them, so no plot or run of theirs can exist. The
  recheck covers it all the same.

**Tests** (`tests/test_live_scripts.py`, probes faked with `fake_probes`; `imports_seen` records `_busy` at each
real import; all three failed before the fix):
- `test_a_plot_opened_while_its_folder_is_tested_waits_for_the_reload`: the import sees 0 runs in flight (1 before
  the fix). The plot never computes the old code and opens on the new code. One round only.
- `test_the_import_waits_for_a_run_that_started_while_its_folder_was_tested`: a run queued during the round, still
  computing at the answer. The reload reads "Reload (waiting)" and the old class stays loaded. It imports once the
  run ends, with no second test-import round. A reload asked meanwhile follows in round 2.
- `test_removing_the_folder_a_tested_reload_waits_for_lets_it_go_on`: the round ends without importing.

Not tested on its own: `reopen_plot`'s hold (the same `_hold_if_reloading` line as `run_analysis`; the backstop
test covers a run from any path).

**Proposed doc change, `plots-and-scripts.md`, the try-import paragraph's "Rounds:".** After "a reload asked meanwhile
waits in `_pending` for its own round", add:

> When a round answers, its import waits (`_end_round`, the answers kept) until no run of its folders' scripts is
> queued or computing, on any runner, reading "Reload (waiting)"; those plots are held meanwhile. A plot opened while
> its folder is in a round or waits to reload is held from its start (`_hold_if_reloading`, in `run_analysis` and
> `reopen_plot`), and takes the new code with the others (`_adopt`). A reload asked meanwhile holds its plots again
> before its own round (C-4, PR #11).

**Reply text for the Codex comment (C-4):** "Confirmed and fixed in `bac9ddf`, with both options. A plot opened
while its folder is being test-imported, or waits to reload, is now held from its start
(`_hold_if_reloading` in `run_analysis` and `reopen_plot`). It runs no old code and takes the new code with the
folder's other plots. Separately, the round's answer no longer imports at once: `_end_round` keeps the answers and
waits on each runner's `finished` ("Reload (waiting)") until no run of those folders' scripts is queued or computing,
with no second probe round and no wait on the GUI thread. Tests:
`test_a_plot_opened_while_its_folder_is_tested_waits_for_the_reload`,
`test_the_import_waits_for_a_run_that_started_while_its_folder_was_tested`,
`test_removing_the_folder_a_tested_reload_waits_for_lets_it_go_on`."

**Checks (at `bac9ddf`):** the full suite, `pytest -n 12 --reruns 5 --reruns-delay 1`: **9293 passed, 673 skipped**,
no RERUN (output: `.ai/temp/suite-c4.txt`). The five type checks pass: `mypy helab/ --strict` (207 files),
`mypy tests --strict` (210), `pyright helab tests` (0 errors), `mypy helab/ --strict --platform win32` (207),
`pyright --pythonplatform Windows helab tests` (0 errors). CI: see the report to CoCo.

**Follow-ups:** none.

### Round 2's review (Probe2, `review.md`, `d91c3d3`): C4-1 and C4-2 fixed

- **C4-1 (Medium): confirmed, fixed in `b19a07e`** (`instance.py`, which the brief allows for holding a plot). A
  plot held from its start whose folder then kept its code never ran. That happens when the folder's test import
  failed, its class or action is gone, or it was removed meanwhile. `keep_script` only called `_follow_next`, and
  nothing waited. It now runs the plot (`run()`) when the plot has no result yet and neither has a run in flight
  nor waits for its data or its own TXY choice; otherwise it calls `_follow_next` as before. The kept code is the
  code that stays loaded, and no import of that folder follows in the round. This also covers a plot whose first
  run a reload cancelled.

  Test: `test_a_plot_held_from_its_start_whose_folder_keeps_its_code_runs_it`, over a failed test import and the
  folder removed. Both cases timed out before the fix and draw "old" now.
- **C4-2 (Low): confirmed, fixed in `364ee45`.** A run ending between `_busy`'s count and the `finished` connection
  went unseen, and the reload stayed "Reload (waiting)". In the answered wait a click on Reload couldn't recover
  it. The fix has two parts:
  - `_listen` connects every runner before each count, in both `_end_round` and `_try_reload` (L2's wait), and
    `_stop_waiting` still disconnects;
  - `_try_reload`, while an answered round waits, calls `_end_round` to count again.

  Test: `test_a_run_ending_as_the_reload_counts_it_doesnt_leave_the_reload_waiting`. A `_busy` wrapper lets the
  counted run end, its `finished` emitted (seen through a direct connection), before the count returns. Before
  the fix the reload stayed waiting; now it imports, in one round.

**Doc proposal, added to round 2's (`plots-and-scripts.md`):** "a plot held from its start that keeps its code runs
it then (`keep_script`); the runners' `finished` is connected before runs are counted (`_listen`), and Reload during
the answered wait counts them again".

**Reply text, if CoCo mentions the review on the PR:** "Follow-up from our own review: a plot held from its start
whose folder kept its old code now runs it (`b19a07e`), and the reload listens for runs ending before it counts
them (`364ee45`)."

**Checks (at `364ee45`):**
- The full suite, `pytest -n 12 --reruns 5 --reruns-delay 1`: **9296 passed, 673 skipped**, no RERUN (output:
  `.ai/temp/suite-c4b.txt`).
- The five type checks pass: `mypy helab/ --strict` (207 files), `mypy tests --strict` (210), `pyright helab tests`
  (0 errors), `mypy helab/ --strict --platform win32` (207), `pyright --pythonplatform Windows helab tests`
  (0 errors).
- CI: see the report to CoCo.
