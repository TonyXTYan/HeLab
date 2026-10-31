# Review: Caching v2 stage 0 (`0571ff2..baee813`, merge `92fc597` skipped)

Reviewer: Assay (Claude Opus 5.5), 2026-10-31. Read-only on code. Brief: [brief.md](brief.md); handoff:
[handoff.md](handoff.md), stage 0 section.

**Verdict: no blocker. 2 findings: 0 High, 0 Medium, 1 Low, 1 Nit.** The fence works as described in every
order I traced. The rules hold: helpers-only store, save guards, nothing removed without asking, the row
before the rename, `user_version` 1, Qt-free `PURE`.

## Findings

### S0-1 · Low · A Clear still stops Live's auto-convert when it takes a later conversion's temporary (A~1's window); the handoff says it "is tried again"

- `helab/io_ops/helab_txy.py:396-402` (`_cleared` keeps every `_OWN_FILE` partial of any age, `:350`) and `:522` (removed);
  `helab/io_ops/convert.py:730` (caught only while `fenced()`) and `:740` (re-raised);
  `helab/views/explorer_live.py:828`, `:765`, `:331`; handoff lines 55 and 79.
- **Scenario.** Live auto-convert is on and the user clicks Clear converted TXY. Clear sets its token, then works
  through the folders. Live's next check starts a conversion during that loop, which reads the *new* token. If
  that conversion's in-flight `.d_txy_helab_…partial` is present when Clear scans the folder, Clear removes it.
  The rename then raises `FileNotFoundError`, but `fenced()` is False (the token hasn't changed since this
  conversion started), so the error is re-raised and the whole conversion ends as `error`. In Live that sets
  `convert.error` (`explorer_live.py:828`), and no conversion is submitted again (`:765`) until the user presses
  Retry (`:331`): "auto-convert stopped: …". The handoff says the conversion "fails and is tried again" (line 79)
  and "the app tries again" (line 55, the busy `hold` path). That holds for a manual run or `--once`, not for Live.
- The behaviour predates stage 0: Clear removed partials before A19.2 too. But Clear during a Live conversion is
  exactly A19.2's case, and the fix is A~1 in an owned file.
- **Resolution, either one closes it:** (a) do A~1 now. Clear skips partials younger than `convert.PARTIAL_MAX_AGE`
  (1 h), as housekeeping does, so it removes less (the safe direction) and Settings › Cache's clearable count
  skips them too. Add a test along the lines of the scratch test below. Or (b) CoCo defers A~1: correct handoff
  lines 55 and 79 to say that in Live the conversion stops auto-convert until Retry, and propose a known-issues
  entry for the window.
- **How verified.** By reading, then reproduced with a scratch test (not committed:
  `.ai/temp/assay/test_zz_assay.py`, run from an export of `baee813`). Its `fence_of` sets a Clear's token just
  before the conversion reads it; its `record` (inside `pin`, with the temporary on disk) then removes the
  folder's partials as Clear's loop would. `convert_folder` raises `FileNotFoundError` instead of reporting
  `cleared`.

### S0-2 · Nit · Live lists a `cleared` wait as stuck, "checked again only when it changes"

- `helab/views/explorer_live.py:48` (`CONVERT_SETTLING = ("settling", "changed")`), `:109` (`stuck()`), `:900`,
  `:931`, `:944`.
- **Scenario.** Shots that wait with reason `cleared` aren't in `CONVERT_SETTLING`, so until the next check
  Live's line shows "N waiting". The tooltip lists them under "Waiting" with "HeLab's converted TXY were
  cleared…" and ends "A waiting file is checked again only when it changes". That last line is wrong for
  `cleared`: the next check converts them (the `seen` entry matches its stat, so the shot goes to `todo`,
  `convert.py:623-633`; the tests' `later` runs show it). It lasts only until that check.
- **Resolution:** CoCo's call, since `explorer_live.py` is the `app` area and outside the owned paths. Either leave
  the stuck set out of `cleared` (one line), or accept it as transient and say so in the handoff.
- **How verified.** By reading the code paths named above. Not run in the app.

## Checked, no finding

- **A19.2 orderings.**
  - Fence set before the row: `record` refuses it (`Cleared`) and nothing is written.
  - Set between the row and `hold`: `hold` refuses, `write_atomic` removes the temporary, the row is forgotten.
  - Set after `hold`: `set_fence` waits in `_patient` for `release`. The Clear's scandir then finds the TXY,
    removes it, and `forget_removed` matches its row.
  - In both journal modes, `BEGIN IMMEDIATE` reads the latest token: WAL starts a write transaction on the newest
    snapshot, and DELETE takes RESERVED with readers still allowed.
  - `release` is idempotent, and both the `after_rename` and the `finally` call are safe.
  - In pool mode, `read`/`finish` and so `index.fence()` run on the thread that opened the index, so no
    `check_same_thread` error is swallowed as "not fenced".
- **Row before the rename** is kept (`pin`: `record` then `hold`, both before `os.replace`).
- **0.0.7a1 compatibility.** `user_version` stays 1. 0.0.7a1 (`e03c32a5`) has no `sqlite_master`/`table_info`
  check on the index (its only such checks are store-v3's), and `_prepare` checks only `user_version` and
  `folders`. An index this build makes, with `fence` in `_TABLES`, therefore reads and writes as before.
  `test_the_fence_table_is_added_within_schema_1` covers the reverse: an index without the table.
- **Rare and harmless:** if a token was read but the index is then set aside as damaged and remade (`_write`'s
  retry, `read_shots(repair=True)`), the conversion's shots wait as `cleared` though nothing was cleared, and
  they convert at the next check. No action needed.
- **cache-5.** `_guard_holds` is reached only through `_check`. Every caller that caught `ValueError` was reading
  a file, not saving to the store (`loading.py:213/666/740`, `live.py:355`, `save_held.py:187`), so none starts
  letting `SaveRejected` through. Dataset saves still report `cache_save_failed`, but the file is now retired at
  once. A re-keyed result is now logged at info in `cached_results.py:512`, with no note: right for a rare
  re-key. The tests cover result, dataset and pending saves, plus `result_save` through the helper.
- **cache-4.** All 29 `with sqlite3.connect` blocks (11 files, counted at `0571ff2`) now use `closing`. The other
  direct connections close in `finally` or at the end. `test_convert_helab.py:1759` looked open but is closed at
  `:1814`.
- **cache-6.** The comment matches the area review's text, and `cache-store.md:31` says "flags still trust every
  hint".
- **Doc proposals** in the handoff are accurate apart from S0-1's wording.

## Checks (run by the reviewer)

To keep Vault's later commits out of the run, I tested an export of `baee813` (`git archive`, with `testdata` and
`legacy/tdc_autoconverter` symlinked) in `.ai/temp/assay/src`.

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-assay`: **8518 passed, 673 skipped,
  3 failed, 15 rerun in 151.88 s.**
  - **All 3 failures and all 15 RERUNs come from my export having no `.git`**, not from the code:
    - `test_release_recovery.py::test_detached_pr_stamp_records_source_branch_and_merge_ref_without_replacing_commit`
      ("rerun reasons": `git clone … returned non-zero exit status 128`)
    - `test_versioning.py::test_frozen_metadata_survives_no_git_and_unrelated_cwd` (`commit='unknown'`)
    - `test_versioning.py::test_source_provenance_ignores_launch_directory` (`'unknown' == 'aaaa…'`)
  - I reran those three in the floor's checkout (HEAD `9767d15`, whose `helab/` and `tests/` equal `baee813`'s):
    **3 passed, no RERUN.** No other test needed a rerun.
  - The one extra skip against the worker's 672 is also the export's.
- `mypy helab/ --strict`, `mypy tests --strict`, `mypy helab/ --strict --platform win32`: no issues (195, 175,
  195 files).
- `pyright helab tests` and `--pythonplatform Windows`: 0 errors (floor root).
- The S0-1 scratch test: passes, meaning the failure reproduces.

On a fix diff I re-check only that diff, its tests and the touched files' type checks.

## Re-check of the fix (`64280e0..03fc012`)

**Open findings: none.** S0-1 is fixed. S0-2 is deferred to known-issues (CoCo's call), and the handoff
proposes it.

- **S0-1: fixed.** `helab_txy._young_partial` keeps every `….partial` modified within `convert.PARTIAL_MAX_AGE`
  (1 h), as housekeeping does. A failed stat counts as young, so the file stays. Clear (`clear_converted`) and
  Settings › Cache's clearable count (`converted_usage`) both go through `_cleared(entries, now)`, so the two
  agree: a young partial counts in `bytes` but not in `clearable`, and its folder stays. A conversion that started
  before the Clear still never renames (the fence), and `write_atomic` removes its own temporary. This removes
  less than before, the safe direction; no removal rule changes.
- **Tests prove it.** I reverted `helab/io_ops/helab_txy.py` alone to `64280e0` in an export of `03fc012`:
  - `test_a_clear_still_running_leaves_a_later_conversions_temporary_alone` fails with `FileNotFoundError` from the
    rename (`txy.py:120`). This is S0-1's failure, now reached through the real `clear_converted`.
  - `test_the_helper_measures_and_clears_converted_txy` fails at its usage assertion (`:217`).
  - Both pass on `03fc012`.
- **Handoff.** Lines 54-57 and the Gaps entry now say that in Live a failed conversion stops auto-convert until
  Retry. A~1 is marked done, and the cache-store.md wording is proposed.
- **S0-2's proposed fix needs one change** when CoCo applies the known-issues text: adding `cleared` to
  `CONVERT_SETTLING` would list those shots under "Being written: … (converted once written)", which is wrong too.
  Better wording: "leave `cleared` out of `stuck()`, with its own line or none".
- **Cosmetic, not a finding:** `helab_txy.py:502`, a 180-character docstring line, missed the rewrap. No lint
  checks line length; the file already has lines up to 126.

**Checks.**
- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-assay` on the export of `03fc012`, running
  `test_convert_helab.py`, `test_converter_tab.py`, `test_helper_events.py`, `test_txy_sources.py` and
  `test_headless_imports.py` (every test file that calls `clear_converted`, `converted_usage` or `converted_summary`,
  plus `PURE`): **177 passed in 12.83 s, no RERUN.**
- `mypy --strict` on the 3 touched files, and on `helab_txy.py` with `--platform win32`: no issues.
- `pyright` on the same files, also with `--pythonplatform Windows`, in the floor root (`helab/`, `tests/` equal
  `03fc012`): 0 errors.
