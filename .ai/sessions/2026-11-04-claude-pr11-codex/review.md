# Review: PR #11's Codex review fixes (`agent/pr11-codex`)

Reviewer: Claude Code (Opus 5.5), 2026-11-04, for CoCo's landing review. Diff reviewed: `git diff ded2f3b..2aeba41`
(the code, not the handoff's account of it). Read: the brief, the handoff, AGENTS.md's cache rules,
`.ai/architecture/cache-store.md` (store-v4) and `io-and-browsing.md` ("Loads with TXY layers").

**Verdict: no blocker.** All three fixes close the findings as Codex described them. Each new test fails with its
fix reverted. None of the fixes breaks the identity rule, the save guards, Make room's only-copy rule, store-v4 views
saved before this change, or the store-v3 fallback. Four findings: one Low, three Info.

## Checks rerun

- Full suite on the floor at `2aeba41`, macOS: `pytest -n 4 --reruns 5 --reruns-delay 1
  --basetemp=.ai/temp/pytest-review -rR` gave **9289 passed, 673 skipped, 2 warnings in 174.35 s, no RERUN** ("rerun"
  appears nowhere in the output). The 2 warnings are pyqtgraph's `arr.shape` deprecation, as the handoff says.
- Type checks, all clean: `mypy helab/ --strict` (207 files), `mypy tests --strict` (210), `pyright helab tests`
  (0 errors), `mypy helab/ --strict --platform win32` (207), `pyright --pythonplatform Windows helab tests` (0 errors).
- **Each test fails without its fix.** In a throwaway worktree at `2aeba41`, with only that commit's `helab/` change
  reverted (`git show <fix> -- helab | git apply -R`), and the tests kept:
  - C-1 `0d2b9c7` reverted: `test_a_view_leaves_out_a_shot_another_views_save_replaced_in_the_layer` fails
    (`[1, 2] == [1]`: shot 2 is sent under the old fingerprint); `test_a_view_saved_before_entry_keys_serves_its_matlab_shots`
    fails on the six-item check.
  - C-2 `49726d1` reverted: `test_helabs_txy_doesnt_make_a_gone_matlab_txys_layer_recoverable` fails (`gone_at` is
    None); `test_a_layers_txy_entries_count_only_their_own_layers_txy` fails (`2 == 1` layers marked gone).
  - C-3 `eafc3fc` reverted: `test_a_raw_layer_not_starting_on_the_trigger_is_rejected_as_its_file_is` fails (the
    from-layer load keeps shot 2 in the HeLab layer: `[1, 2] == [1]`).
- CI run 41651767280 ran on `7238242`. Its conclusion is success, and every Build, Tests 1/3 to 3/3 and Converter
  backends job passed on macOS, Ubuntu and Windows (compat jobs skipped, PR only). `2aeba41` differs from `7238242`
  only in `handoff.md`. I didn't re-read the job logs for RERUN; the landing check does that by run ID.

## Per fix

### C-1 `0d2b9c7`: views record their layer entry key

- **It closes the finding.** `Access.write` saves each view item as `[shot, size, mtime_ns, "txy", layer, [entry
  size, entry mtime_ns, entry kind]]` (from the save's `keys`, which cover every shot of the same fingerprint, in
  `loading` and in `save_held`). `_read_data` passes the saved keys to `read_txy_shots(…, keys=)`, which leaves out a
  shot whose entry now has another key. The check runs on the same `txy_layers` row the segments are read from,
  including the compaction retry, so a save landing between the view read and the data read can't slip through. A
  cached read counts the shot as failed. A load either finds its fingerprint changed (the shot is read anyway) or goes
  down "Some cached shots are gone" and reads it again.
- **Identity rule:** kept. The entry key is the Q45.3 identity (size, mtime_ns, kind). For a five-item item,
  `saved_key` derives a MATLAB shot's key from the item's own fingerprint. That is right because `listed_stats` for
  origin `""` is `matlab_stats`, and MATLAB entries are always keyed by their TXY file (`entry_keys`).
- **Save guards:** no new write path. `confirm` now resends each stored item as it was, so `confirm_view`'s
  fingerprint equality still holds for six-item views (it would have failed if confirm had rebuilt them as five
  items) and for five-item ones. The guard and `job_seq` checks are unchanged. Every race between `lacking`/`write`
  and another view's save now goes the safe way: the view names a key, the entry holds another, and the shot is read
  again.
- **Old five-item views:** MATLAB shots are served as before. HeLab shots are left out and read again once (PR-1).
  Pending saves that hold a five-item view in their record apply as they are and go through the same `saved_key`
  path.
- **store-v3:** untouched. Everything new is behind `layered`; `read_txy_shots` answers missing below `LAYOUT`.
- **Other view readers:** `_view_infos` (listings: `entry[1]`, `entry[4]`), `cached_matlab_shots` (`entry[4]`) and
  `confirm_view` read by index or compare the whole item, so six items are fine. `lacking` and `write` check entries
  against the current keys. `compact_txy` reads a whole layer, and needs no view keys. `cache_cli` reads layers and
  segments only, never views. Only `_view_row`'s sizes still count entries without the key (PR-2).

### C-2 `49726d1`: `mark_txy_seen` per raw + layer

- **It closes the finding.** `present` is keyed by `"raw"` and by layer name. A raw-keyed entry is checked against
  the raw files, a TXY-keyed one against its own layer's TXY only. HeLab's TXY of a shot can no longer clear a
  `matlab` layer's `gone_at`, and the reverse holds too.
- **Callers:** `loading.py:489` and `save_held.py:277` pass `raw_entries` (keys), `matlab` and `{shot:
  found.profile_hash}`. `matlab` is filled from the listing whatever the source (`kind.loaded`), so a HeLab-only
  load still sees every MATLAB TXY. No other caller exists (grep, `access.` included).
- **Make room's only-copy rule:** strengthened. `_txy_groups`, `purge_cached` (`gone_at IS NULL`),
  `clear_folder_data` (`cache_store.py:1526`) and `txy_summary` read only `gone_at`, which this fix only ever makes
  more conservative. A store a pre-fix build marked wrongly heals on its next listing: `gone_at` is set because that
  listing is newer than the stale sighting.
- **Other `seen` writers:** `_write_layer_row` gives `seen_at` to a *new* layer only, made from this save's own
  sources. An existing layer keeps its marks, so a save doesn't mix sources either. `mark_raw_seen` is per raw file
  and was never mixed.
- **Save guards, identity, store-v3:** unaffected (`mark_txy_seen` writes only the marks; `_needs_v4`).

### C-3 `eafc3fc`: `not_done` before converting cached raw pulses

- **It closes the finding.** `raw_layer.not_done(facts, profile.channel_trigger)` mirrors `raw.not_done` check for
  check (blank, final newline, first channel). It runs before `decode`/`reconstruct`. On failure `from_raw` returns
  None, and the load takes the shot's normal path: `convert_on_read` → `convert_raw_file` → LATE or DAMAGED by age,
  or its TXY text if one exists. The test shows the same `problematic` and `files` with and without a raw-layer hit,
  and shot 2 kept out of the layer.
- **Other conversions of cached pulses:** none. `store.read_raw` is called only from `Access.from_raw`;
  `raw_layer.decode` is used elsewhere only in `convert/check.py` (developer harness). `helab convert` converts from
  the files it reads.
- **Identity, guards, Make room, old views, store-v3:** unaffected (read-side only, behind `layered`).

## Findings

### PR-1 (Low): an old five-item HeLab view: no cached read until the next load, which reads every HeLab shot again under "Cached dataset invalid"

`helab/io_ops/txy_cache.py:161` (`saved_key` → None for HeLab), `helab/io_ops/txy_cache.py:286` (`_read_data`),
`helab/io_ops/loading.py:609` (`elif unpacked:`).

The handoff says a HeLab shot of a view saved before the key "is read again once". That is right, but nothing tests
it, and the user sees more than that. A scratch test in a throwaway worktree (HeLab-only load converting on read,
then the view's items cut to five) showed:

- `read_cached` of that view raises **"No cached data for this folder"**. All its shots are keyless, so
  `_read_data` returns `{}`. A priority view's HeLab shots would count as failed instead.
- The next cold load gets `{}` from `unpack()`. `elif unpacked:` treats `{}` as falsy, so the load reports
  `cache_reason` **"Cached dataset invalid"** (not "Some cached shots are gone") and reads every HeLab shot again:
  `read: 2, converted: 2`, i.e. raw files over the share when no raw layer is filled.
- After that save the view has six items, and the following load is `cached`, `read: 0`, as the handoff says.

Impact: dev builds only (no published release has store-v4 on), once per such view. Not a blocker. Options for
CoCo: accept as is and say so in the handoff's C-1 note; or add the scratch test (below) as a regression test; or,
with Tony's OK for `loading.py`, change `elif unpacked:` to `elif unpacked is not None:` so the message reads "Some
cached shots are gone". I haven't checked that change against the rest of the suite.

Scratch test (passes at `2aeba41`; not committed):

```python
def test_old_helab_view_is_read_again_once_then_keyed(tmp_path):
    # HeLab-only load (convert on read, profile_def sent) → cut txy_views items to item[:5]
    # → read_cached raises "No cached data for this folder"
    # → load: cached False, read 2, cache_reason "Cached dataset invalid"; view now six items
    # → load: cached True, read 0
```

### PR-2 (Info): `_view_row`'s sizes count layer entries whose key no longer matches

`helab/io_ops/txy_cache.py:255`. `rows` / `ram_bytes` add `held[layer].entries[shot].rows` for each of the view's
shots without the C-1 key check. For a view with a replaced entry, the cache info's sizes count the replacement's
rows, not the view's. This is cosmetic: `_too_large` estimates from the fingerprint, and data is never served this
way. No change needed for landing.

### PR-3 (Info): C-2's safe side, worth one line in the docs

`helab/utils/cache_store.py:3723`. A HeLab layer's TXY-keyed entries (rare: the raw file wasn't listed when saved)
are now marked only copies by any listing that didn't find that profile's TXY: an External-only load, another
profile, or a list stage another stage covered. Such a layer then survives `purge_cached` and a folder's Clear
(`clear_folder_data`, `gone_at IS NULL`), and Make room names it in group 5. That is the safe direction, and the
handoff says so. MATLAB presence is still by shot number, not (size, mtime_ns); that predates this fix (the
handoff's A~1).

### PR-4 (Info): doc proposals to add when landing

Beyond the handoff's three `cache-store.md` items:
- `.ai/architecture/io-and-browsing.md`, "Loads with TXY layers": in loading-order step (1) "its layer, with the
  current fingerprint (Q45.3's kind included)", add "and the entry key the view saved (C-1)". Change "Every v4 listing
  marks its sources seen (`mark_txy_seen`)" to "… each layer against its own source (C-2)". Add to step (2): "only if
  `raw_layer.not_done` passes for the profile (C-3)".
- `.ai/architecture/cache-store.md`, the `raw_fill` paragraph ("`raw.not_done`'s checks that need no profile;
  C3-2"): add "the trigger check runs when a load converts from the layer (C-3)".
- If PR-1 is accepted as is, mention in the `txy_views` bullet that a five-item view's HeLab shots are read again
  once ("Cached dataset invalid"), with no cached read until then.

## Not findings (checked)

- `read_txy_shots(keys=)` leaves out a shot whose key is absent from `keys`. `_read_data` drops keyless shots from
  both `shots` and `keys`, so the two agree.
- `saved_key` on a malformed sixth item falls back to the five-item rule (`len(item[5]) == 3` guard). A non-integer
  value would raise in `_view_row`; only HeLab writes views, so I don't report it.
- `confirm`'s fallback branch (an item whose first three values differ) writes a five-item item, but `confirm_view`
  then refuses on fingerprint inequality, so it never lands.

## Re-check: PR-1's follow-up (`git diff 2aeba41..9b2ec20`)

Reviewer: Probe2, 2026-11-04. The new commits are `f90217c` (PR-1's regression test), `c609506` and `9b2ec20`
(handoff notes); the range also contains this review (`e25426b`). No code change under `helab/`.

- **`f90217c`, `tests/test_txy_loading.py::test_old_helab_view_is_read_again_once_then_keyed`**: this is the scratch
  test, tightened into assertions. Its steps: a HeLab-only load converting on read; view items cut to five; then
  `read_cached` raises "No cached data for this folder". The next load is not cached, reads both shots under "Cached
  dataset invalid" and saves six-item items. The load after it is cached, reading nothing. It names the view by
  `view_key("helab-only", txy)`, which is better than the scratch test's first row.
- **It guards C-1.** In a throwaway worktree at `9b2ec20` with `0d2b9c7`'s `helab/` change reverted, it fails
  (`DID NOT RAISE ValueError`: without the key check the old view serves HeLab shots with no proof they are its own).
- **Checks at `9b2ec20`:** `pytest -n 4 --reruns 5 --reruns-delay 1 tests/test_txy_loading.py` gave 27 passed, no
  RERUN. `mypy tests --strict` (210 files) is clean, and `pyright` and `pyright --pythonplatform Windows` on the file
  give 0 errors. The worker's full suite (9290 passed, 673 skipped, no RERUN) and the five type checks are recorded
  in the handoff; I didn't rerun the full suite for a test-only change.
- **Handoff:** the C-1 note now says what the user sees: no cached read, then one read under "Cached dataset
  invalid", and `loading.py` unchanged. It lists the test, and carries PR-2 and PR-3 as accepted and PR-4's doc
  proposals. All of it matches this review.

**PR-1: closed** (accepted as is, with its regression test). There are no open findings. PR-2 to PR-4 are Info,
accepted. CI hasn't run on `9b2ec20` yet (unpushed); the landing rule's CI run on the latest commit is still to come.

## Round 2: C-4 (`git diff 2557480..5558972`, fix `bac9ddf`)

Reviewer: Probe2, 2026-11-04. Read: `brief-c4.md`, the handoff's "Round 2 (C-4)", the diff of
`helab/views/plots/script_tree.py` and `tests/test_live_scripts.py`. Also read, to follow the paths:
`instance.py` (`hold_for_reload`, `_submit`, `adopt_script`, `keep_script`, `_follow_next`) and `runner.py` /
`runner_core.py` (`cancel`, `in_flight`, the order of the pop and `finished`).

**Verdict: no blocker for the rule Codex cited.** The real import no longer runs while a run of the round's folders'
scripts is queued or computing. Two findings: **C4-1 (Medium)** and **C4-2 (Low)**. Both are in what happens around
the wait, not in the rule itself.

### Checks rerun

- Full suite at `5558972`, macOS: `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review -rR`
  gave **9293 passed, 673 skipped, 2 warnings in 159.50 s, no RERUN** ("rerun" appears nowhere in the output).
- The five type checks are clean: `mypy helab/ --strict` (207), `mypy tests --strict` (210), `pyright helab tests`,
  `mypy helab/ --strict --platform win32` (207), `pyright --pythonplatform Windows helab tests` (0 errors each).
- **The tests fail without the fix.** In a throwaway worktree at `5558972`, with `bac9ddf`'s `helab/` change
  reverted, all three fail: `test_a_plot_opened_while_its_folder_is_tested_waits_for_the_reload` (`[1] == [0]`: one
  run in flight under the import), `test_the_import_waits_for_a_run_that_started_while_its_folder_was_tested` and
  `test_removing_the_folder_a_tested_reload_waits_for_lets_it_go_on` (both: "Reload" where "Reload (waiting)" was
  expected).
- CI: run 41737877745 on `5558972` concluded success. I didn't read its job logs for RERUN; the landing check does.

### The brief's points

- **No real import under an in-flight compute, on any runner:** met. `_end_round` runs `then` only when
  `_busy(listed)` is 0. `_busy` counts `in_flight()` on the app runner and every plot's runner, and `in_flight`
  keeps a cancelled job until its `compute` returns (`runner_core.py:145`). The two paths that open plots,
  `run_analysis` and `reopen_plot`, hold from the start. Arrangements and presets reopen through `reopen_plot`
  (`arrangement.py:311`), and I found no other `instance.start(`. A run started any other way during the round is
  caught by the backstop.
- **The GUI never waits:** met. The wait is `finished`-driven (`_wait_for_runs`), with no loop or join.
- **No second probe round:** met. `_answered` keeps the answers. While it waits, `_probing` stays set, so
  `_try_reload` only adds to `_pending`, and `_run_ended` and `remove_folder` go back to `_end_round`. The second
  test checks `len(rounds) == 1` until the import.
- **Plots opened during the round get the new code:** met when the import succeeds (`_adopt` → `adopt_script` →
  `run()`, test 1). They don't run at all when the folder's code is kept (C4-1).
- **A reload asked meanwhile follows in its own round:** met. Its plots are held again after this round's `_adopt`,
  then `_try_reload`. Test 2 checks it.
- **Folder removed:** met. `remove_folder` calls `_end_round`. `listed` drops the folder, so `then` runs with
  nothing to import, and `_finish_reload` filters the folder out the same way. Test 3 checks it.
- **Restore path:** met, and the window is empty, as the handoff says: no class of an unrestored folder exists, so
  `_busy` is 0. Plots restored by `foldersRestored` open after `_round` is cleared, and are held only if their
  folder is pending.
- **Holding a plot can't make the wait hang:** a cancelled queued job still runs through the worker and emits
  `finished` (`cancel` only sets the event), so the busy-then-hold order in `_end_round` is safe.

### C4-1 (Medium): a plot opened during the round never runs when its folder's code is kept

`helab/views/plots/script_tree.py:787` (`_hold_if_reloading`), `helab/views/plots/instance.py:1002`
(`keep_script`).

A plot opened while its folder is in a round (or pending) is now held before its first run. When the round keeps
the old code for that folder, `_adopt` calls `keep_script`. That happens when the folder's test import fails
(`_skip_folder`), when its class or action is gone, or when the folder is removed meanwhile (`remove_folder`). But
`keep_script` only calls `_follow_next()` ("what waited while it was held"). A plot held from its start has nothing
waiting, so it never computes. It shows the amber "⚠ Script didn't reload (…): still running the code loaded at
HH:MM", and its dock keeps "Running … on …", with no result until the user presses Rerun.

A scratch test confirmed it at `5558972`. It was the first test's setup with the probe faked, parametrized over the
two ways the code gets kept: answering with `ProbeFailure("it hung")`, or removing the folder before the answer.
After 1.5 s, both gave `shown: False`, `job: ''`, `held: False`, and the status above.

Before C-4 such a plot ran on the old code at once (racing the import, which was the bug). The brief asks that a
plot opened during the round "gets the new code … or says why it kept the old". It says why, but never draws, and
the line claims it is "still running" code it never ran. The same gap existed before for a plot whose *first* run
was cancelled by a Reload, but C-4 makes it the normal outcome for any plot opened during a failing round.

Suggested fix (needs `instance.py`, which the brief allows "only if holding a plot needs it"): in `keep_script`,
when the plot has no result yet (`self.shown is None`), isn't running and isn't waiting for its data or own TXY,
call `self.run()` instead of `_follow_next()`. Its old code is the code that stays loaded, so running it is safe:
no import follows for that folder in this round. A test: the scratch test above, asserting the plot draws "old".

### C4-2 (Low): a run that ends between the busy count and the `finished` connection leaves the reload waiting, and Reload no longer unsticks it

`helab/views/plots/script_tree.py:603-612` (`_end_round`), `:903` (`_wait_for_runs`), `:831` (`_try_reload`'s
`if self._probing: return`).

`_end_round` (like `_try_reload` before it) counts `_busy` and only then connects `runner.finished` to
`_run_ended`. The worker pops the job from `in_flight` and then emits `finished` (`runner_core.py:232`, `:236`). So
a run that ends in the moment between the count and the connection is never seen by `_run_ended`. Qt queues the
signal only to the receivers connected when it is emitted.

- In L2's "Reload (waiting)" this window predates C-4. There, a click on Reload recovers: `_try_reload` counts
  again.
- In C-4's answered wait, `_probing` stays True, so a click only adds to `_pending` and returns. The reload then
  waits until some other run ends on a connected runner, or the folder is removed.

The window is tiny (microseconds on the GUI thread), so this is Low. A simple fix covers both paths: connect the
runners before counting (call `_wait_for_runs`' connect loop first, or connect in `_busy`'s callers before they
count), or let `_try_reload` call `_end_round()` when `_answered` is set instead of returning.

### Doc proposal

The handoff's `plots-and-scripts.md` text is accurate for the code as it is. If C4-1 is fixed, add: "a plot held
from its start that keeps its code runs it then (`keep_script`)".

### Not findings (checked)

- `_hold_if_reloading` normalises both sides (`_folder_key` uses `os.path.normcase` on `folder_of` /
  `class_folder`, against `_round | _pending` normcased), so a folder named with another case still matches on
  Windows.
- `AnalysisInstance(...)` calls the old script's `live_policy` / `constant_keys` on the GUI thread during the
  round. That is not a `compute`, and the rule is about `compute`.
- `answered` checks `sip.isdeleted(self)`. `_run_ended` is a bound slot, so Qt disconnects it when the panel is
  deleted.

## Re-check: C4-1 and C4-2 (`git diff d91c3d3..afe7057`)

Reviewer: Probe2, 2026-11-04. The new commits are `b19a07e` (C4-1), `364ee45` (C4-2) and `afe7057` (handoff).
Nothing else changed: the range touches only `instance.py` (`keep_script`), `script_tree.py` (`_listen`,
`_end_round`, `_try_reload`, `_wait_for_runs`), `tests/test_live_scripts.py` and `handoff.md`.

- **C4-1, `b19a07e`: closed.** When `keep_script` finds no run in flight and the plot isn't waiting for its data, it
  now calls `run()` if the plot has no result yet (`shown is None`) and isn't waiting on its own TXY choice. It calls
  `_follow_next()` otherwise, as before. The kept code is the code that stays loaded: a skipped folder isn't
  imported, and a removed one is left out of `_end_round`'s `listed`. So this first run happens under no import of
  its folder.
  - Test: `test_a_plot_held_from_its_start_whose_folder_keeps_its_code_runs_it`, parametrized over a failed test
    import and the folder removed (my scratch test's two cases), asserting the plot draws "old".
  - With `b19a07e`'s `helab/` change reverted, in a throwaway worktree, **both cases fail** (`waitUntil` timed out).
- **C4-2, `364ee45`: closed.** `_listen()` connects every runner's `finished` before each count, in `_end_round` and
  in `_try_reload` (L2's wait). Both still disconnect through `_stop_waiting` when nothing is busy. `_try_reload`,
  while an answered round waits, calls `_end_round` to count again, so a click on Reload recovers too. There is no
  recursion: `_end_round` clears `_answered` before its `then` and its own `_try_reload`.
  - Test: `test_a_run_ending_as_the_reload_counts_it_doesnt_leave_the_reload_waiting`. A `_busy` wrapper lets the
    counted run end, its `finished` seen on the worker thread through a direct connection, before the count
    returns.
  - With `364ee45`'s `helab/` change reverted, **it fails** (`waitUntil` timed out); the other tests pass.
- **Checks at `afe7057`:**
  - full suite, `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review -rR`: **9296 passed, 673
    skipped, 2 warnings in 164.23 s, no RERUN**;
  - the five type checks: clean, as in round 1;
  - CI run 41741318883 on `afe7057`: success. I didn't read its job logs for RERUN; the landing check does.
- **The handoff** matches the code, including the added `plots-and-scripts.md` sentence.

Not a finding, noted for the record: when the reload *did* import the folder but this plot's class or action is gone,
`keep_script` now runs the plot's old class after that import. Its helper modules are then the new ones. That is
the same thing held plots with a result already did before C-4 ("Rerun and Live run the code it has", L-series), and
no import is under that run.

**Open findings: none.** Round 2 has nothing left open.
