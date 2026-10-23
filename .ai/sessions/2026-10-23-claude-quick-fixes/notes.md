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
later hang (`<commit>`).
