# Review: Plot Identity (`agent/plot-identity`, Reviewer Optic, Claude Opus 5.5, 2026-10-31)

Range `0571ff2..d2d5334` (`3c85905` after it is the handoff only). Read: [brief.md](brief.md),
[handoff.md](handoff.md), `AGENTS.md`, `plots-and-scripts.md`, `dld-analyses.md`, `live.md`, the area
review's `plots.md` (`573361f`). Reviewed the diff itself, not the handoff's account of it.

**Summary: 5 findings, all Low (2 test gaps, 1 code, 1 doc proposal, 1 nit). No blocker.** plots-1,
plots-3, plots-4 and the nits do what the brief asks; the suite and the type checks pass here.

## Findings (most severe first)

### R-1 · Low · Velocity distributions' "fresh load detects again" leg proves nothing

`tests/test_velocity_distributions.py:387-389`. The test's last leg (a fresh load of the folder, one
signature, runs Live and must detect again) passes with the chain token blanked (`build_view`'s
`uuid4().hex` replaced by `""`, checked in a scratch copy): by then `KEPT` holds the *profile* run's
key, so the fresh view's key differs from it whatever its chain. The handoff says both the profile and
the fresh-load cases fail without `chain_key`; only the profile leg does (it also fails with
`chain_key` dropped from `kept_key`). **Fix:** run the fresh-load leg from a kept state of the same
chain and choice (e.g. right after `later_view`'s kept Live run, or with its own owner after a first
run and a kept revision), and check it fails with the token blanked.

### R-2 · Low · Correlations' `detection_key` change has no test

`helab/scripts/dld/correlations_plot.py:556`. With `"data": view.chain_key` removed from
`detection_key` (keeping it in `box_key`), all 17 tests in `tests/test_correlations_plot.py` pass
(checked). `test_another_load_s_live_run_keeps_no_box` covers only the box (`:548`; it fails without
that one, and with the token blanked). **Fix:** in that test, also assert that another load's Live run
detects t_r again (whatever the result exposes of the reused detection: e.g. the detection object or
`release_how` not the kept one), and check it fails without the key.

### R-3 · Low · A cancelled rerun beside an outdated saved result still says ": rerunning"

`helab/views/plots/instance.py:564-568` (and the pinned branch `:569-575`). The nit fix strips
`RERUNNING` from `_cache_note` only on a failure (`:597`). When the user cancels the run that replaces an
outdated saved result, `_finished` returns at the cancelled branch with the amber line still "saved
result from … is outdated (…): rerunning" while nothing runs (status "Cancelled"). Same root as the
area review's nit. **Fix:** the same `removesuffix(RERUNNING)` in the cancelled (and pinned) branches,
with a test like `test_a_failed_rerun_beside_an_outdated_saved_result_says_it_no_longer_reruns` that
cancels instead.

### R-4 · Low · Doc proposal: the known-issues entry on the source label is now outdated

`roadmaps/known-issues.md:61-66` says "a plot whose folder signature no longer matches says 'Showing
previously loaded data' (`_update_plot_source_label`); not checked: a cache clear, which keeps the
signature, …". The label now compares the data shown (`Held`: shots, fingerprints, origins), and a tab
whose dataset was dropped (`displayed_dataset` None) now gives "Showing previously loaded data". The
handoff's proposals don't touch that entry. **Fix:** add to the handoff's proposed doc changes a
rewording of that entry (compared by `DatasetView.held` / `held_of`, not the signature; what is still
unchecked: the tab's own arrays kept on screen).

### R-5 · Nit · `shot_trends.py:391` comment

The edited comment line is 143 characters, with "GUI thread; ``plot_closed`` drops it." run on
after the new sentence. Rewrap to the file's width.

## Checked and fine

- **plots-1.** `ViewIdentity.chain` is `build_view`'s `uuid4().hex`, kept by `with_shots` (and so by
  `revise`, `hollow`, `restore`); `presets`' placeholder keeps "". `follow.newer` offers any other chain;
  `Follow.due` still skips a new chain with no shot added, changed or gone (`changes` by fingerprint), so
  a fresh load of identical data doesn't rerun. The reuse key (`AnalysisResult.reuse_key`) lists fields
  by name: no `chain`, so saved-result lookup is unchanged; `result_codec` decodes `ViewIdentity` by
  field name, so records without `chain` still read. Nothing else compares `ViewIdentity`/`ViewKey`
  besides `follow`, `shot_trends._drawn`, `RamResults.for_input` (unused) and `instance.py:569`.
  The source label compares `Held` (SHA-256 of shot numbers, fingerprints, origins; `own` plots by shot
  numbers), cached per `Dataset` in a `WeakKeyDictionary` (the cache mutates only `checked_at`,
  `verified`, `disk_cached`/`cache_info` in a dataset's metadata, never its shots, fingerprints or
  origins); `dataSourceSignature` has no other reader. `shot_trends.newer_than_drawn` unchanged: with the
  chain in the identity a new chain notifies from its second revision (a new chain's first drawing never
  notifies, like a plot's first drawing); acceptable reading of the brief.
  Note, not a finding: after a fresh load of identical data the new chain's next Live revision runs once
  whatever "every N" (`due`: another input runs once), as `due`'s docstring says.
- **plots-3.** `chain_key` = identity source, TXY choice, chain, sorted profile hashes; in
  `kept_key` and Correlations' `box_key`/`detection_key`. Computed on the worker, memory only.
- **plots-4.** `_listened_on_all` probes `0.0.0.0:<port>` as HeLab binds (SO_REUSEADDR off Windows),
  closes the probe, sends nothing; TIME_WAIT doesn't refuse it (`test_stop_frees_the_port` passes).
  Linux and another HeLab on 127.0.0.1 move to port 0 as before. The Windows dual-stack `[::]` gap is
  skipped in the test with its reason and proposed for known-issues in the handoff.
- **Nits.** `reuse_on` docstring (off by default, Q27.1); the failed-rerun note (see R-3 for cancel).
  Leaving `_shown_view` unset for an outdated saved result is reasoned and fine.
- **Area rules.** `dataset_view` stays Qt-free (`hashlib`, `json`, `uuid`; `test_headless_imports`
  passes); no shared array copied or written (`Held` reads shot numbers and records only); compute on
  the worker, label on the GUI thread; no pickle; no `destroyed` or sender-capturing connections added.
- **Scope.** Code changes only in `helab/analysis/`, `helab/scripts/dld/`, `helab/views/plots/`,
  `helab/utils/dash_server.py`; the rest are tests and this session folder. No signature code touched.
- **Doc proposals** for `plots-and-scripts.md`, `live.md`, `dld-analyses.md` and known-issues (Windows
  dual-stack, the extra Windows worker-crash occurrence): present and accurate, apart from R-4.

## Each test without its fix (scratch copy of `d2d5334`, one change at a time)

| Fix removed | Result |
|---|---|
| chain token `""` | fail: `test_each_load_of_a_raw_only_folder_is_another_chain`, `test_the_feed_offers_a_new_chain_after_live_starts_again`, `test_a_new_chain_notifies_from_its_second_revision`, `test_another_load_s_live_run_keeps_no_box`; **pass: `test_another_profile_s_or_load_s_next_live_run_detects_again`** (R-1) |
| `chain_key` out of `kept_key` | fail: the velocity test (its profile leg) |
| `chain_key` out of `box_key` | fail: the correlations test |
| `chain_key` out of `detection_key` | **all 17 correlations tests pass** (R-2) |
| the Dash probe | fail: both ipv4 and ipv6 cases (macOS) |
| the failed-rerun `removesuffix` | fail: the result-cache test |
| the label's `Held` compare (always current) | fail: the source-label test |

## Checks run (this floor, `3c85905`)

- Touched tests: `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-optic -rR` on the 7
  touched test files: **274 passed in 11.70 s; no RERUN.**
- Full suite: `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-optic -rR`:
  **8523 passed, 672 skipped, 2 warnings in 151.01 s; no RERUN** (no "rerun reasons" section). Warnings:
  pyqtgraph's NumPy 2.5 `arr.shape` deprecation, unrelated. Log: `.ai/temp/optic/suite.log`.
- `mypy helab/ --strict` (195 files), `mypy tests --strict` (175), `mypy helab/ --strict --platform
  win32`: no issues; `pyright helab tests` and `pyright --pythonplatform Windows helab tests`: 0 errors.
  Log: `.ai/temp/optic/types.log`.
- CI run 41162571197: `success`, head `d2d5334`; every Tests (1/2, 2/2), Converter backends and Build job
  on macOS, Ubuntu and Windows `success` (conclusions read; job logs for RERUN not re-read here, the
  handoff reports none).

## Re-check of the fixes (Optic, 2026-10-31): no open findings

Fix diff `0d00b13..eb0a131` without the merge `75aba55` (which touches none of this floor's code paths):
`a76ba3c` (R-1, R-2, R-3, R-5) and the handoff's R-4 proposal (`c9b311e`).

- **R-1 fixed.** The fresh-load leg now runs right after the kept rerun, on a load of the same choice
  (same signature, TXY choice and profile hashes), so only the chain differs. Fails with the chain token
  blanked (checked).
- **R-2 fixed.** `test_another_load_keeps_no_detection`: a revision keeps the detection ("detected,
  kept"), another load detects again. Fails with `chain_key` out of `detection_key` (17 others pass), and
  with the token blanked (checked).
- **R-3 fixed.** `_finished` now drops `RERUNNING` once, at the top, for every run that ends (failed,
  cancelled, not shown when pinned); a completed run clears the note as before. The test is parametrised
  failed/cancelled; both fail with that line removed (checked).
- **R-4 fixed** as a doc proposal: the handoff rewords the known-issues item (lines 61-66) by `Held`, not
  the signature. Accurate.
- **R-5 fixed.** The comment is wrapped.

Checks at `eb0a131`: the touched tests (`test_correlations_plot.py`, `test_result_cache_plots.py`,
`test_velocity_distributions.py`, `test_shot_trends.py`) with `-n 4 --reruns 5 --reruns-delay 1
--basetemp=.ai/temp/pytest-optic -rR`: **80 passed in 14.32 s; no RERUN** (log
`.ai/temp/optic/recheck.log`). Fix-removed runs in a scratch copy of `eb0a131`, one change at a time.
