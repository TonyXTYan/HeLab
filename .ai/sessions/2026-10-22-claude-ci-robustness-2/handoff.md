# CI robustness 2: handoff

Branch `agent/ci-robustness-2` (from `fc0f50d`), floor "CI Robustness". Details, evidence and what
I tried are in [notes.md](notes.md).

## Summary

Five of the six flaky or crashing test items are fixed, each with its cause shown by a
reproduction: A1–A5, and the dead-helper test of A6. `test_activation_sources` stays open, with its
rerun cause now printed on CI. Floor isolation step 1 is done: `pytest.ini` (`pythonpath = .`) and
one settings-defaults table that every settings read goes through.

All fixes are in `tests/` except B2's settings reads. There are no production behaviour changes.
Full suite (`-n 4 --reruns 5`, with `test_typing`): 2394 passed, no RERUN. `mypy --strict` (helab,
tests) and pyright are clean. The fixed files under load: 2890/2890.

| Item | Cause | Fix | Commit |
|---|---|---|---|
| A1 Matplotlib-TransferFractions segfault | A QWebEngineView left to `deleteLater()` was deleted in a later test's event loop or at exit, and Qt crashed. Already fixed for `test_live_plots.py` by `e492409`: no crash in the 33 CI jobs since, 9 before | conftest sends deferred deletes after every test and fails a test that leaves a web view alive. Unfixed copy: 4/6 crashed before, 0/6 after | `f9d4a88` |
| A2 cache-tab test after the io-trace test | One store per worker: the Live save's pending save was restored by the later test (reproduced every time) | A fresh store per test (`private_store`); two cleanup fixtures removed | `c21d5b8` |
| A3 default data path | Already patched in conftest since `d2833f1`; no test guarded it | A real window's tabs must start in the test folder; only the patched modules read the default paths (an AST scan). It fails with the patch removed | `c21d5b8` |
| A4 window-resize painting | A paint still pending for the last tick came first, then the test asserted a new tick (CI failures took about 0.5 s, not a timeout) | Wait for a paint that shows a newer tick. Pending paint forced: old 39/40 failed, new 0/40; under load 240/240 | `ebdc33f` |
| A5 Dash `test_stop_frees_the_port` | The server closes connections first on Linux (TIME_WAIT for about 60 s), and the probe bound without SO_REUSEADDR, unlike `DashServer._bind`. Also 8050 contention | Own free port, a server-closed connection, then a second `DashServer` must get the port. Old 5/5 failed, new 0/5; 120/120 in parallel loops | `45e5b14` |
| A6 dead-helper test (RSPE Windows) | The reader logs the failed close after sending `exit`, so the second scan could finish before the log the test asserted | Wait for the log in the same condition, 10 s. Close delayed 0.3 s: old 5/5 failed, new 0/5 (not confirmed on RSPE itself) | `c472031` |
| A6 `test_activation_sources` | Windows rerun: A1's crash. macOS rerun: a **teardown** failure, no traceback | **Open.** 160/160 local runs pass; the next CI rerun's "rerun reasons" will say why | — |
| CI diagnostics | `-rR` names reruns without a reason | A "rerun reasons" section: the `E` lines and the failing line | `315273d` |
| B1 | pytest imported the editable install's or `PYTHONPATH`'s helab, not the checkout's (shown with another copy first) | `pytest.ini`, `pythonpath = .`, and tests that helab is this checkout's | `50fa36b` |
| B2 | Settings defaults were scattered across 8 files | `helab/utils/settings_defaults.py` and `read_setting`, with tests of the table, the code and real reads | `0f4df65` |

B2 also found that PyQt6's `QSettings.value(key, 8 << 30, type=int)` returns 0 (a 32-bit int).
HeLab reads the budget untyped, so this was never hit; `read_setting` refuses typed reads of
number rows.

## Production files changed (B2 only, behaviour unchanged)

`helab/utils/settings_defaults.py` (new), `constants.py` (the `*_SETTING` names come from the table
and are re-exported; `DEFAULT_*` from `setting_default`; reads use `read_setting`), and reads or key
names in `SettingsDialog.py`, `HelabMainWindow.py`, `CacheMover.py`, `cache_setting.py`,
`io_ops/admin.py` and `lab_parameters.py`. There were no production fixes for item A: every cause
was in the tests.

## Open

- `test_plot_settings_panel.py::test_activation_sources`: one macOS teardown failure on CI
  (`f9faefd`). Wait for the "rerun reasons" output.
- The dead-helper test's cause is shown with a delayed call; RSPE's own output wasn't kept.
- Other tests still prefer port 8050 (with fallback, by design). Patching `DashServer.HOST_PORT = 0`
  in conftest would keep suites off it, at the cost of importing Dash in every worker.

## Restore default and default tooltips (not done; what they'd need)

- **Restore default per setting:** each editor in Settings needs its key (the table's
  `*_SETTING`). Restore sets the editor to `setting_default(key)` and removes the key on save, so a
  corrected default applies later, as Lab parameters already do.
- **Path rows:** `dir_temps` and `dir_caches` default to "" (unset). Restore would show
  `default_app_dir(kind)`. `dir_caches` must go through a cache move (`CacheMover`), never a plain
  write.
- **Tooltips:** they need display text per row: units (bytes as GiB, RAM steps as GB of this
  machine, seconds) and choice labels (`LOAD_MODE_LABELS`, `CHECK_LEVEL_LABELS`). These could go in
  a `display` field on `Setting`, or a function in the Settings view.
- **Profiles:** "start from the hard-coded defaults" means an empty ini. `read_setting` then gives
  the table's values. Nothing else is needed.

## Proposed doc edits (for the Coordinator)

**`roadmaps/known-issues.md`, Tests and CI.** Move to Fixed, with the commits on
`agent/ci-robustness-2`:
- `test_live_plots.py::…[Matplotlib-TransferFractions]` worker crash: fixed in `test_live_plots.py`
  by `e492409` (#6): no crash in 33 CI jobs since, 9 before. Every test is protected now: deferred
  deletes after each test, and a test leaving a web view fails (`f9d4a88`).
- `test_cache_tab.py::test_saves_restored_from_the_store_ask_with_its_numbers` after the io-trace
  test: a store per test (`c21d5b8`).
- Main-window tests and the default data path: patched since `d2833f1`; now a test guards it
  (`c21d5b8`).
- `test_window_resize.py::test_label_keeps_painting_after_resize`: a paint still pending for the
  last tick came first (`ebdc33f`).
- `test_dash_server.py::test_stop_frees_the_port`: TIME_WAIT after the server closed connections,
  and a probe without SO_REUSEADDR; a port of its own (`45e5b14`).
- `test_gui_responsiveness.py::test_output_close_failure_cannot_leave_dead_helper_in_active_queue`:
  the log came after the exit it waited for (`c472031`; shown with a delayed call, not on RSPE).

Keep open, reworded: "`test_plot_settings_panel.py::test_activation_sources`: the Windows rerun was
the web-view crash (fixed); the macOS rerun (`f9faefd`) was a teardown failure, cause unknown. CI
now prints rerun reasons."

Add: "CI logs: rerunfailures sleeps `--reruns-delay` before it logs RERUN, so subtract 5 s from a
rerun's apparent duration."

**`AGENTS.md`, Testing.** Add:
- `pytest.ini` sets `pythonpath = .`, so pytest tests the checkout it runs in, whatever the venv's
  editable install or `PYTHONPATH` names (`tests/test_test_isolation.py`).
- Each test gets a disk cache store of its own (`private_store` in `tests/conftest.py`;
  `cache_dir()` and the helpers' `HELAB_DIR_CACHES_OVERRIDE`). Nothing a test saves reaches another.
- Deferred deletes are sent after every test. A test that leaves a QWebEngineView alive fails (one
  deleted later crashed Qt).
- The summary prints "rerun reasons" (why each rerun failed); quote them when reporting a RERUN.

**`AGENTS.md`, "Settings persistence".** Add: every key HeLab reads is in
`helab/utils/settings_defaults.py` (key, type, default, description; the `lab_constants/` prefix;
retired keys), and reads go through `read_setting` (`tests/test_settings_defaults.py`). Read numbers
untyped: PyQt's `type=int` reads 8 GiB as 0.

**`roadmaps/agent-workflow.md`.**
- Floor setup, Python: the "pytest must import the floor's code" guard is done (`pytest.ini`).
- Floor setup, stale bytecode: confirmed on this floor (a traceback named
  `../../../HeLab/tests/…`). Keep the `__pycache__` deletion in the setup hook.
- Settings isolation, Hard-coded defaults: **done** (`settings_defaults.py`). Restore default and
  default tooltips are left; see above for what they need.

**Floor setup hooks.** Delete `__pycache__` outside `venv/` and `legacy/` after the clone, if the hook
doesn't already. This floor's venv was already its own (editable install → the floor), so the hook
seems to handle that.

## CI

(Filled in after the push.)
