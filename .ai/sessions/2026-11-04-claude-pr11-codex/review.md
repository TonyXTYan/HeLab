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
