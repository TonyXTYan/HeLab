# Quick fixes, batch 1: notes (Rivet, 2026-10-23)

Brief: [brief.md](brief.md). Floor "Quick Fixes", branch `agent/quick-fixes`, base `2994870`.

## Rerun counts (CI, before any fix)

From the test jobs of the last 23 CI runs (39703939483 … 39880474971: dev/v0.0.6 and the agent
branches), read with `gh api repos/TonyXTYan/HeLab/actions/jobs/<id>/logs`:

| Test | Runs (job: reruns) |
|---|---|
| `test_presets_window.py::test_a_live_off_preset_turns_live_off_in_a_real_tab` | 39814028933 Ubuntu 1; 39880474971 Ubuntu 1, Windows 1 (3 of the 4 off-macOS jobs since it exists) |
| `test_live_plots.py::test_a_following_scatter_updates_its_page_in_place` | 39731793369 Ubuntu 1; 39880474971 Ubuntu 1 |
| `test_live_io.py::test_a_live_check_pauses_background_work_only_while_it_reads` | 39731793369 Windows 1 |
| `test_io_service_run.py::test_a_helper_that_dies_leaves_what_it_said_in_the_log` | 39734426913 macOS 2 |
| `test_cache_first.py::test_a_folder_changed_within_its_mtime_tick_is_listed[cached]` | 39731793369 Ubuntu 1, Windows 2; 39734271694 Windows 1; 39745015514 Windows 3 (new since the known-issues entry) |
| `test_plot_settings_panel.py::test_activation_sources` | none in these runs (its last rerun was `f9faefd`, earlier) |

Also seen: `test_left_widgets.py::test_a_teardown_that_raises_still_deletes_the_web_views` failed
5 reruns on all three OSes in 39715190343 and 39716589995 (the two failed runs, 2026-10-22, before
that test was fixed on CI Robustness); not since.

## Job 1: `test_a_live_off_preset_turns_live_off_in_a_real_tab` "worker crashed"

**Not a crash: a hang that CI's timeout kills.** In all three CI logs the worker's previous test
passed ~120 s before "node down: Not properly terminated" (Ubuntu 00:55:06.8 → 00:57:07.5,
16:31:00.7 → 16:33:01.5; Windows 00:59:02.8 → 01:01:04.1). CI runs `--timeout=120
--timeout-method=thread`: pytest-timeout dumps the stacks to the worker's stderr and calls
`os._exit`, and under xdist that dump never reaches the log. Checked with a test that sleeps
(`-n 2 --timeout=3 --timeout-method=thread`): the same "node down: Not properly terminated",
"worker 'gw0' crashed", no stacks. With `-o faulthandler_timeout=3` the stacks do show.

**Reproduced on Linux** (Docker, Ubuntu 24.04 arm64, CI's apt packages plus WebEngine's system
libraries, `requirements.lock`, `QT_QPA_PLATFORM=offscreen`): the module alone hung on its first
run, and on 2 of 2 runs with tracing. Never on macOS: 48 runs of the module and 60 of the crashed
worker's order (6 at once, 12 `yes` processes for load), all clean. The stack:

```
File "helab/views/plots/presets.py", line 573 in _warn        (QMessageBox.warning: modal)
File "helab/views/plots/presets.py", line 676 in apply        ("Preset can't be read")
File "tests/test_presets_window.py", line 112 in test_a_live_off_preset_turns_live_off_in_a_real_tab
```

**Cause.** `test_applying_a_live_preset_in_a_real_tab_starts_live_once_listed` (and any test that
closes a real `HelabMainWindow` while something is still being saved) calls `window.close()`
while its preset's write is still in flight: `quit_saves()` lists Presets, so the window opens its
quit window (`QuitSaveDialog.open()`), calls `cache.cancel_for_quit()` (`FolderCache.quitting =
True`) and ignores the close; the service isn't shut down. The test ends, qtbot deletes the window
and its quit window with it, so the quit never finishes. The worker's next test gets the same
app-wide IOService and FolderCache (`get_io_service()` makes a new one only once it is closed),
still quitting: `write_arrangement` is refused (`set_presets` returns `QUITTING`), so
`read_arrangement("on")` raises "it isn't saved now" and `apply` shows a modal warning, which
nothing dismisses offscreen. Traced in the container: at the setup of the hanging test, the cache
from the previous test, `quitting True closed False`; its teardown had `quit_saves ['Presets']`.
On macOS the preset write ends before `window.close()`, so no quit window opens.

Not an app bug: in the app the quit window ends with the saves and quits. The modal warning is
the app's answer to a preset that can't be read; only a test can reach it this way.

**Fix** (tests only):

- `tests/test_presets_window.py`: `quit_window(qtbot, window)` closes the window and waits until it
  has quit (`window._closing`, as `test_live.py`'s quit test does); the module's five closes use it.
- `tests/conftest.py`: `no_quitting_cache` (autouse) shuts the app-wide service down at teardown
  if its FolderCache is quitting, so the worker's next test gets a new one, whichever test left it.
- `pytest.ini`: `faulthandler_timeout = 100`, so a test that hangs dumps every thread's stack
  (under xdist too) before CI's 120 s timeout kills its worker; the next hang names itself.

**Checks.** Linux container: the fixed module plus the old module body, 10 runs, 8 passed each
(before: hung 2 of 2); the old module body with only the conftest guard, 5 of 5 passed. Local
(macOS): full suite `-n 4 --reruns 5`: 2597 passed, 2 skipped, 2 xfailed, no RERUN; `mypy helab/
--strict`, `mypy tests --strict`, `pyright helab tests` clean.

**Proposed known-issues line** (Fixed):
`test_presets_window.py::test_a_live_off_preset_turns_live_off_in_a_real_tab` "worker crashed" on
Ubuntu and Windows CI was a hang killed by CI's 120 s timeout (whose stacks xdist drops): an earlier
test closed its window while a preset was being written, leaving the app-wide FolderCache quitting
for the next test, whose preset was refused and whose `apply` waited on a modal warning.
Reproduced in a Linux container. Tests wait for the window to quit, conftest shuts a quitting
cache's service down after each test, and `faulthandler_timeout = 100` dumps the stacks of any
later hang (`66b771a`).

## Job 2: `test_a_following_scatter_updates_its_page_in_place` teardown "TypeError: 'NoneType' object is not callable"

**Evidence.** Ubuntu, runs 39731793369 and 39880474971, one rerun each; the call passed, the
teardown failed. The rerun reason is the whole report (under the 600-character fallback): pytest-qt's
"Exceptions caught in Qt event loop", then `TypeError: 'NoneType' object is not callable` with **no
"Traceback" line**: pytest-qt got the exception with no traceback at all, so Qt (PyQt/sip) raised it
from C, calling something that was None, before any Python frame. Reproduced the format with
`QTimer.singleShot(0, len)` (a builtin called with no argument): the same frameless report. A
virtual set to None on an instance (`w.resizeEvent = None`) is ignored by sip, so not that. Nothing in
`PlotlyPane`, the Dash server, the follow code or the settings panel's one event filter calls an
optional callable from Qt.

**Not reproduced**: the module 12 times in the Linux container (131 passed each), and the full
suite 11 times there (`-n 4`, CI's timeout; the only failures were 5 tests that need `.git` or
pyright, absent in the container's copy) plus twice locally. CI's rate was 2 in 23 Ubuntu jobs.

**Diagnostics** (`tests/conftest.py`, `where_qt_raised`, autouse): wraps pytest-qt's
`sys.excepthook` (installed before the test's fixtures) for each test; an exception with no
traceback gets a note naming the test's or HeLab's frames (not site-packages) that were running
Qt's event loop at that moment, at most four, so it fits the rerun reason. Checked with a fixture
whose teardown makes Qt raise from C: the rerun reason then ends with "(No traceback: raised by Qt
outside Python code, while this ran its event loop:)" and `File "…", line 12, in late:
QApplication.processEvents()`. If only pytest's own frame shows, it was pytest-qt's own processing
of events or closing of widgets at teardown.

**Proposed known-issues line** (still open):
`test_live_plots.py::test_a_following_scatter_updates_its_page_in_place` teardown error on Ubuntu CI
(2 of 23 jobs): "TypeError: 'NoneType' object is not callable" with no traceback, so raised by Qt
from C. Not reproduced (12 module runs and 11 full suites in a Linux container). Such an exception
now gets a note naming the code that was running Qt's event loop (`<commit>`): read it in the next
rerun's reasons.

## Job 3: `test_a_live_check_pauses_background_work_only_while_it_reads` (Windows, line 102)

**Evidence.** One rerun, Windows, run 39731793369: "waitUntil timed out in 10000 milliseconds",
`tests\test_live_io.py:102`. At that run's commit (`ae72673`) the file is as now: line 102 is
`finished()`'s wait for a Live check's `done` ("live 1": nothing new; or "live 2": reading 201 files
of 2000 rows, 200 of them before the test opens the last gate), not the first wait. The attempt
took about 14.3 s (19.3 s to the RERUN line, minus the 5 s rerun delay): the 10 s wait and about 4 s
of the rest. This test's whole run in the 23 recent CI jobs: Windows 4.7 to 11.9 s (24 runs),
Ubuntu 1.7 to 3.9 s, macOS 1.3 to 7.1 s. Locally (macOS) every wait is under 0.5 s, and under
0.95 s with 4 runs at once and 16 busy processes; "live 2"'s finish took 0.13 to 0.76 s. CI runs
with `--cov`, which also traces the helpers.

**Cause** (probable, unconfirmed: the failed attempt left no detail): timing. The check's reads
and its 201 shots took over 10 s on a slow Windows runner, the slowest of the three by 2 to 4
times. Not shown that it wasn't a stall instead.

**Fix** (test only): `finished()` waits until the check is done, failing only after 10 s without
an event from it (up to 60 s in all), as the app's own timeouts measure time without progress;
then it fails naming what the check had sent (counts by kind, and its last event, e.g. the file it
was reading). Checked: with the last gate never opened the test fails after 10.5 s with "live 2:
no event for 10 s, …; its events: {… 'file_started': 201, 'shot': 200 …}; last: {'kind':
'file_started', 'filename': '…/d_txy_forc211.txt' …}"; otherwise 3 of 3 module runs pass.

**Proposed known-issues line** (Fixed, watch):
`test_live_io.py::test_a_live_check_pauses_background_work_only_while_it_reads`'s Windows rerun was
at `finished()`'s 10 s wait for a Live check's `done` (line 102): probably the check's 201 reads on
a slow Windows runner (this test takes 4.7 to 11.9 s there, 1.7 to 3.9 s on Ubuntu). The wait now
fails only after 10 s without an event from the check, naming what it had done (`<commit>`); a
failure after that is a stall, and says where.

## Job 4: `test_a_helper_that_dies_leaves_what_it_said_in_the_log` ("[Errno 32] Broken pipe")

**Cause.** `IOService._run` writes the request to the helper's stdin after starting it. A helper
that has already exited (the case the test makes: it writes to stderr and exits at once, as a
helper whose import fails does) has closed its end of the pipe, so the write or its flush raises
`BrokenPipeError` (on Windows, `OSError` EINVAL). The generic `except Exception` then reported
"[Errno 32] Broken pipe" and skipped the code that logs the helper's stderr. It was a race between
the child's exit and the parent's write; macOS CI lost it twice. So it is the app's bug, not only
the test's: exactly when a helper dies at startup, what it said was lost from the log and the
error named a pipe instead of the helper.

**Decision: code.** A closed pipe when writing the request means the helper exited: `_run` ignores
the `OSError` of that write and of closing stdin, and goes on to read its output, which has ended,
so it reports "I/O helper exited unexpectedly" and logs the tail of its stderr, as for a helper that
read its request first. (Users see the same message either way now.)

**Test.** The test is parametrized: `dies`, as before, and `died before its request was written`,
where the fake helper has exited before `Popen` returns, which makes the race deterministic.
Before the fix the new case fails every time with CI's message (`{'kind': 'error', 'message':
'[Errno 32] Broken pipe'}`); after it, the file passes 5 of 5 runs with `-W error::ResourceWarning`.

**Proposed known-issues line** (Fixed):
`test_io_service_run.py::test_a_helper_that_dies_leaves_what_it_said_in_the_log`'s macOS reruns
("[Errno 32] Broken pipe"): a helper that exited before its request was written made the write
raise, so the error named the pipe and its stderr wasn't logged. The app now treats that as the
helper having exited (its stderr logged); the test covers both orders (`<commit>`).

## Job 5: `test_a_folder_changed_within_its_mtime_tick_is_listed[cached]` (R-23)

**Evidence.** 7 reruns in 4 jobs of the 23 runs (Ubuntu 1, Windows 6; one Windows job needed 3),
all `assert <mtime> is None` at line 841. R-23 holds: the test sets the folder's mtime to the start
of the current 2 s step, so 0 to 2 s of the 2 s `RACY_SECONDS` margin are gone before the first
load; a listing that starts after the margin records the real mtime. Shown with a 2 s sleep before
the first load: both variants fail at that assert (`assert 1792720204000000000 is None`).

**Fix** (test only, R-23's first option): `RACY_SECONDS` = 30 s while the folder's mtime is the
tick (the first load and the same-tick check, which must both see None), 2 s again for the
listing of the mtime 60 s back, which must record it. Passes as before and with the 2 s sleep.

**Proposed known-issues line** (Fixed):
`test_cache_first.py::test_a_folder_changed_within_its_mtime_tick_is_listed[cached]` (7 reruns in 4
CI jobs, mostly Windows): the test's 2 s tick spent up to all of the 2 s `RACY_SECONDS` margin before
its first listing; it now uses 30 s while the mtime is the tick (R-23; `<commit>`).

## Job 7: `helab/views/plots/presets.py`'s extra blank line at the end

Removed (`git diff --check` clean for it). `<commit>`.

## Job 6: `test_plot_settings_panel.py::test_activation_sources` (macOS teardown failure)

No rerun of it in the 23 recent CI runs (its macOS rerun was at `f9faefd`, before them, and its
Windows rerun was the web-view crash fixed on CI Robustness). It passed in every local full suite
here (2) and in the 11 Linux container suites. The earlier notes say its macOS failure was at
teardown with no traceback, the same shape as job 2's frameless Qt exception, so `where_qt_raised`
(job 2) will name the code running Qt's event loop if it recurs that way, and
`faulthandler_timeout` (job 1) the stacks if it hangs. Nothing else tried: 160 local runs already
passed (CI Robustness 2).

**Proposed known-issues line** (still open): unchanged, plus "no rerun in the 23 CI runs to
2026-10-23; a frameless Qt exception there now names where the event loop ran (`<job 2 commit>`)".
