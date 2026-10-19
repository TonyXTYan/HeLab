# Codex review — Plots v1 polish, round 1

Branch `agent/plots-v1-polish`, base `c8e3a2c`, reviewed at `1ee8b80` (7 commits).

## Verdict

**Changes requested.** Shot selection, source identity, parameter visibility, the centre hint, version bumps, and scope look sound. Two edge cases below need correction before this round is ready.

## Findings

1. **Moderate — reversed manual bounds silently show the full axis.** `helab/analysis/selection.py:87–93` treats `min >= max` as an unset bound. The brief specifies `min = max` as full extent. For example, entering T min 5 s and T max 2 s makes `manual_bounds` return `None`, so scatter and histograms use the full T extent while the source line still records `T min 5 s, T max 2 s`. Distinguish equality from reversal: reject or visibly correct a reversed pair before running, and test it through the parameter and plot paths.

2. **Moderate — the POSIX FIFO test still has unbounded waits.** `tests/test_live_io.py:46–49` opens each FIFO for writing in blocking mode. If the reader exits or times out after its `file_started` event, either `release(hold_load)` at line 106 or `release(hold_check)` at line 110 can block indefinitely, outside every `qtbot.waitUntil` timeout. Use a nonblocking writer with a bounded retry/deadline, or another release mechanism that cannot strand the test process. The `os.mkfifo` calls are properly guarded for Windows typing, and the test is intentionally skipped on Windows.

## Reviewed behavior

- `select_shots` handles empty views, N larger than the shot count, gaps, and reversed shot-number ranges; To 0 reaches the last available number. It only selects shot keys. The analysis still uses its original `DatasetView` identity and revision, and its per-shot arrays remain shared; `events()` makes the same concatenated working array as before this round.
- Auto-crop remains the default. Equal manual bounds select the data extent. Scatter counts events inside the joint box; histograms use independent axis bounds. The SI spin box accepts and returns base-unit values (for example `4.125 mm` becomes `0.004125` m), displays an SI prefix, and rejects the wrong unit in a direct offscreen check. Hidden parameters are absent from the source line and retained in the tooltip record.
- `choice` values outside the declared choices fall back to the default; numeric values clamp to limits. The parameter tree updates conditional visibility, while `effective` retains every declared value. There is no persisted plot-settings loader in this round: a newly opened plot starts at its declared defaults, and older result records are not reloaded into the tree.
- The hint is keyed to the dock list, whose add and close paths both update it. The GUI test covers two docks closing in order. All three bundled analyses use `Basic plots v1` and version `2`. All changed paths are within the brief's ownership.

## Checks

- Full suite outside sandbox, `PATH="$PWD/venv/bin:$PATH" venv/bin/pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: **965 passed, 2 skipped, 2 xfailed, no RERUNs** (17.79 s). An initial run without `venv/bin` on `PATH` failed only six typing subprocess tests because it could not find `mypy`/`pyright`; the corrected full rerun passed.
- `mypy helab --strict`: **passed**, 76 files. `mypy tests --strict` and `mypy tests --strict --platform win32`: **passed**, 56 files each. I used a writable temporary cache because the reviewer's sandbox cannot write the checkout's `.mypy_cache`; the first default-cache attempts gave a mypy SQLite internal error.
- `pyright helab tests` and `pyright tests --pythonplatform Windows`: **0 errors, 0 warnings** each.
- `git diff --check c8e3a2c..HEAD`: **clean**.

The offscreen checks do not establish native Mac plot appearance or actual Windows runtime behavior.

## Recheck at 2a72950

**Verdict: round-1 findings resolved; round 2 ready for Maestro's review.** I reviewed `1ee8b80..2a72950` (six commits, including handoff updates). No new blocking finding.

- Reversed manual bounds are still accepted, but the plot now explicitly says the axis uses its full extent. Scatter and histogram figures, the dock source line and full tooltip record, and the settings tab report the warning. Equal bounds remain the silent full-extent convention. The new numerical and GUI tests cover this behavior.
- `HELAB_TEST_READ_GATE` is read once at helper import. When unset, `_read_gate` returns before any filesystem query or sleep; the only normal-path cost is a function call and `None` check before each TXY read. Activating the behavior requires explicitly setting that test-named environment variable to a directory, so normal production launches do not enter it. A closed gate follows `file_started`, emits no progress, and the parent's existing per-file no-progress timeout kills and retries the helper. The stuck-read test asserts three attempts, the timeout error, and confirmed exit before each retry.
- The two Live I/O tests use regular TXY files and touch-file gates. Each event wait has an explicit timeout; opening a gate is a bounded file creation rather than a blocking pipe open. The pause test orders the background read, Live read, pause, Live completion, and background resume. Neither test uses POSIX-only calls or has a Windows skip. Windows typing passed; runtime behavior on Windows remains unverified here.
- `DatasetAnalysis.describe_run` supplies the source selection and short settings, with a default for other dataset analyses. The dock renders one line for folder/revision/selection/analysis and an optional second settings line; `QLabel` has wrapping disabled and a size policy that allows clipping. The tooltip still receives `describe(..., every=True)` and any parameter warning. GUI tests assert the text and no wrapping. Very long settings can be clipped at a narrow dock, with the full record available in the tooltip.

### Recheck validation

- Full suite outside sandbox, `PATH="$PWD/venv/bin:$PATH" venv/bin/pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review2`: **968 passed, 2 skipped, 2 xfailed, no RERUNs** (20.45 s).
- Strict mypy: `helab` **76 files passed**; `tests` **56 files passed**; `tests --platform win32` **56 files passed**. The reviewer's writable temporary cache was used.
- `pyright helab tests` and `pyright tests --pythonplatform Windows`: **0 errors, 0 warnings** each.
- `git diff --check c8e3a2c..HEAD`: **clean**.
