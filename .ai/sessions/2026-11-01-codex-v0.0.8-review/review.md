# v0.0.8 bug and security review

Reviewed 2026-11-01 (Australia/Sydney).

Target: `TonyXTYan/HeLab` branch `dev/v0.0.8`, commit
`3c8cfa1ad4b6c7f0046d313fa2ab305d34f9ded2`, against `main`
`e03c32a5e7b798c4971b00258ed2e8809bd3cb71`. There is no `v0.0.8` tag;
the branch's package version is still `0.0.7a1`. This reviews the development
branch, not a published v0.0.8 binary.

The original `/workspace/HeLab` checkout is unchanged. The reviewed source is
in `/workspace/HeLab-v0.0.8`; production files are unchanged. Review probes and
complete check output are kept in this session directory. Nothing was committed,
pushed, or posted to GitHub.

## Findings

### R1 — P2 — Export can overwrite files without --force, including through a late symlink

Location: `helab/cache_cli.py:56–69` (especially the opens at 63 and 69,
and `savemat` at 67).

The existence and store-containment checks run before the output is opened in
truncating mode. A second exporter can create the output between the check and
open, and the command overwrites it despite `force=False`. In a directory another
user/process can modify, replacing the output with a symlink in that window also
redirects the write to a different file writable by HeLab's user, including a cache
database which the containment check would normally protect. This needs control
of the output directory during export; it is not evidence of remote code execution.

Reproduction: inject a competing file creation at `out.parent.mkdir`, which runs
after both checks, and call `_write(..., force=False)`. NPZ, MAT and CSV all
overwrite that file. A second probe instead makes `out` a symlink to a temporary
`store-v4/records.sqlite`; all three formats overwrite the database sentinel.
Only private test files were used.

Fix direction: claim the output with exclusive creation when `--force` is absent,
and pass that already-open handle to each serializer (including `savemat`).
Translate a refused claim into `CliError`. If publishing a completed temporary
export, use an atomic publication that cannot replace an existing destination.

Evidence: `repros.py`, `repros.log` (three overwrite probes),
`security-repros.log` (three symlink probes).

### R2 — P2 — Folder export fails for names requiring URL encoding

Location: `helab/cache_cli.py:106–108`.

`folder_key()` joins the literal relative filesystem path to `root://<uuid>`.
The actual cache keys percent-encode path components through `LocalVolumes` /
`CachePaths` and `DataRoots`. A folder named `run 1`, for example, is stored as
`root://<uuid>/run%201`, but the exporter queries `root://<uuid>/run 1`. It exits 1
claiming there are no raw pulses even though `raw_layers` holds the shot. `%` and
non-ASCII folder names fail in the same way. This affects exporting store-v4 data;
store-v4 is currently disabled by default.

Reproduction: create a temporary rooted folder, write a settled raw fixture, fill
one raw layer with the real `raw_fill`, then run `cache export --folder`. For each
of `run 1`, `run%20`, and `測定`, raw filling saves one shot, the stored and queried
keys differ, and export returns 1 instead of 0.

Fix direction: reuse the canonical root-key construction, or percent-encode each
relative path component with the same rules as the cache. Add export coverage for
spaces, percent signs and Unicode names.

Evidence: `repros.py` and the first three probes in `repros.log`.

### R3 — P2 — An unreadable kept legacy cache becomes an empty-cache answer

Location: `helab/utils/cache_store.py:813–819`.

`_kept_legacy()` suppresses `LegacyUnavailable` when a present store-v3 cannot be
opened, then returns `None`. Record lookup consequently reports `missing`, and
`measure_legacy()` reports the store as uncounted without the opening error. With
store-v4 enabled and Keep selected (or the question unanswered), a damaged or
temporarily unreadable legacy store can therefore silently hide its scan-failure
history and saved results. Callers cannot distinguish this from no saved history,
undermining the rule that automatic scans must respect earlier failures.

Reproduction: put a damaged `records.sqlite` in a private `store-v3`, open its
sibling `store-v4`, and request a history record. The result is
`Read(status='missing', value=None, error='')`, rather than a failed read. Inventory
also provides no opening error. Store-v4 is currently disabled by default.

Fix direction: distinguish absence/Ignore from a failure to open a kept store;
propagate the latter to affected record/result read answers and the inventory.

Evidence: `repros.py` and the legacy-store probe in `repros.log`.

## Review coverage

Read the changes to the cache store and its guards, legacy import/read-through,
raw-layer encoding and background filling, `.hlb` parsing, CLI exports, conversion
fences, cache moves, helper lifecycle, plot identities, settings, Dash binding and
release stamp validation. The confirmed security finding is R1. No confirmed new
code-execution vulnerability was found in these changes. This is a source review
with Linux tests, not a packaged Windows/macOS validation or a dependency advisory
scan. The raw `.hlb` format uses typed arrays rather than pickle; existing dataset
pickle storage remains outside that new format.

## Validation

- All six type-check tests pass after activating the venv and providing its
  expected `venv` link in the isolated checkout: `typing.log` (89.36 s).
- Seven expected failures establish R1–R3 in `repros.log`; three additional
  expected failures establish R1's symlink variant in `security-repros.log`.
  These probes were temporarily copied into `tests/` to use its isolation
  fixtures, then moved back here. They are not production-suite additions.
- Existing tests covering the new cache areas all pass: 247 passes across
  `test_hlb`, `test_cache_cli`, `test_store_v4`, `test_raw_layer`,
  `test_raw_layers_store`, `test_raw_fill` and `test_caching_v2_session`.
  Per-module counts are in `new-area-outcomes.txt`. These tests did not cover
  the three regression scenarios above.
- The full parallel run was interrupted after **8,660 passed, 691 skipped,
  12 failed, 1 error and 64 reruns**, at 725.02 s. The whole output is
  `pytest-full.log`; it is not a clean full-suite result. Six failures were
  the initial invocation's missing `mypy`/`pyright` on PATH; all six pass in
  the corrected invocation (`typing.log`).
- All six other initial failing test cases also fail on unmodified `main`:
  the failed-listing history guard, immediate offline preset, saved result
  offline, offline window restoration, saved-result badge, and killed helper
  workers. Five hit volume verification in this container, where `/tmp` is
  a separate tmpfs mount rather than a trusted fixed system mount. The helper
  test finds already-dead orphan workers still listed as zombies by the
  container. Baseline logs: `baseline-recheck.log`,
  `baseline-offline-result.log`, `baseline-result-badge.log`, and
  `baseline-helper-and-window.log`.
- A follow-up selected 189 collection IDs not matched to completed IDs in
  the first log and disabled retries. It was also stopped when the same
  volume-verification condition repeatedly prevented saved-result tests:
  **11 passed, 9 failed, 1 teardown error**, at 114.11 s
  (`pytest-remaining.log`). Those nine failures all log "not yet verified";
  they were not each rerun on main. The teardown error was
  `AttributeError: 'AnalysisRunner' object has no attribute 'results'` after
  the failed plot test. Some tests remain unexecuted; release validation
  needs a working native/CI environment.
- `git diff --check` passes. No production edits were made.

### RERUN accounting

The first run's exact **"rerun reasons"** section is retained in
`rerun-reasons.txt` and in the full log. Every test with a RERUN is named here;
none of this run is described as clean:

- `test_typing.py::test_mypy_helab_soft`, `test_mypy_helab_strict`,
  `test_mypy_helab_tests_soft`, `test_mypy_helab_tests_strict` (5 each):
  `FileNotFoundError: [Errno 2] No such file or directory: 'mypy'`.
- `test_typing.py::test_pyright_helab`, `test_pyright_tests` (5 each): the
  same `FileNotFoundError` for `pyright`. Corrected invocation: all pass.
- `test_cache_admin.py::test_failed_listing_history_write_keeps_the_listing_guard`
  (5): expected `Cache was cleared before saving completed`, got
  `The volume of .../unavailable is not yet verified`.
- `test_convert_helab.py::test_a_killed_helpers_workers_exit` (5):
  `assert [psutil.Process(... status='zombie' ...)] == []`.
- `test_preset_folder_live.py::test_offline_a_folder_never_listed_is_named_as_such[at_once]`
  (5): expected the offline/unlisted notice, got a volume-not-yet-verified notice.
- `test_offline_browsing.py::test_a_saved_analysis_result_shows_offline_without_computing`
  (7 displayed markers): `waitUntil timed out in 30000 milliseconds`, plus
  `RuntimeError: wrapped C/C++ object of type QLabel has been deleted` in a
  later verification callback.
- `test_offline_browsing.py::test_the_window_starts_offline_when_asked_last_time_and_work_online_relists_every_tab`
  (6 displayed markers): `waitUntil timed out in 10000 milliseconds`, plus
  the same deleted-QLabel callback.
- `test_result_cache_badge.py::test_a_plots_save_shows_the_badge_without_listing_and_a_clear_hides_it`
  (5): `waitUntil timed out in 30000 milliseconds`.
- `test_result_cache_plots.py::test_a_saved_result_is_shown_after_a_restart_without_computing`
  (1, before interruption): `waitUntil timed out in 30000 milliseconds`.

The 7/6 marker counts include separate call/teardown failures, not successful
retries. Coordinator: retain these observations with the review evidence; the
known-issues list should distinguish the cloud mount/zombie conditions from
product regressions.

## Handoff proposals

Coordinator: record R1–R3 in `roadmaps/known-issues.md`; R2 and R3 apply to the
optional caching-v2 path. Fix R1 before treating exports into shared directories
as safe. Fix R2/R3 before enabling store-v4 broadly. These are review findings,
not authorization to change application behavior in this session.
