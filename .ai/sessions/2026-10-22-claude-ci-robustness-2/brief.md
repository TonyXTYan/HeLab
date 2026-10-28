# CI robustness 2 (Worker brief)

Floor "CI Robustness", branch `agent/ci-robustness-2` from `fc0f50d` (`dev/v0.0.6`, 2026-10-22).
Session folder: `.ai/sessions/2026-10-22-claude-ci-robustness-2/` (save this brief there as
`brief.md`; write notes and `handoff.md` there). Asked by Tony: the CI flake sweep plus the first,
decision-free step of floor isolation, in one floor.

Start by reading `AGENTS.md`, `roadmaps/agent-workflow.md` (Maestri floors; Settings and data
isolation), `roadmaps/known-issues.md` (Tests and CI) and the previous sweep,
`.ai/sessions/2026-10-21-claude-ci-robustness/notes.md` (what was fixed, how it measured CI).

## Objective

### A. Flaky and crashing tests (known-issues.md, Tests and CI)

For each, find the cause (a "flaky" label is not a cause), fix the test or the code, and show it:
reproduce before (e.g. under parallel load, CPU burners, a delayed call, as the last sweep did) and
not after. A fix in production code is fine when the cause is there; keep it minimal.

1. `test_live_plots.py::…[Matplotlib-TransferFractions]` crashed an xdist worker (segfault) 7 times
   on `dev/v0.0.6` CI, macOS and Windows. Highest priority.
2. `tests/test_cache_tab.py::test_saves_restored_from_the_store_ask_with_its_numbers` fails after
   `tests/test_io_trace.py::test_a_live_save_keeps_dont_cache_and_the_budget` on the same worker
   (a pending save left in the shared test store): isolate the store per test, or clean it.
3. Main-window tests resolve the default data path, `/Volumes/dld_output` when it is mounted: tests
   must never touch the real volume (AGENTS.md, Testing). Make the default path a test seam or
   patch it in conftest for every window, and add a test that fails if it leaks.
4. `test_window_resize.py::test_label_keeps_painting_after_resize[repeated]/[single]` (12 reruns on
   dev CI, macOS/Ubuntu).
5. `test_dash_server.py::test_stop_frees_the_port` (reruns even alone on Ubuntu CI: the port may
   not be free at once; also contention on 8050 when suites run at once — consider a free port
   per test).
6. `test_plot_settings_panel.py::test_activation_sources` (one macOS CI rerun) and
   `test_gui_responsiveness.py::test_output_close_failure_cannot_leave_dead_helper_in_active_queue`
   (Windows reruns): look; fix if you find the cause, else record what you tried.

Use `gh run list` / `gh run view --log` on `TonyXTYan/HeLab` for the CI evidence (reruns are in
the `-rR` summary). Report each item in the handoff as fixed (commit, evidence), or open (what's
known), for known-issues.md.

### B. Floor isolation, step 1 (no open decisions)

1. **pytest `pythonpath` guard**: pytest must import the checkout it runs in, never another
   checkout's `helab` through an editable install or a copied venv. There is no pytest config
   today (no `pytest.ini`/`pyproject.toml`); add the smallest one (e.g. `pytest.ini` with
   `pythonpath = .`), keeping CI's commands and `tests/test_typing.py` working. Add a test that
   `helab.__file__` is under the repo the tests run from. Check that nothing in CI or the
   PyInstaller build reads a new config file by surprise.
2. **Hard-coded settings defaults table** (`roadmaps/agent-workflow.md`, "Hard-coded defaults"):
   one table, e.g. `helab/utils/settings_defaults.py`, with key, type, default and a short
   description for every `QSettings` key HeLab reads (`constants.py`, `SettingsDialog.py`,
   `CacheTab.py`, `CacheMover.py`, `HelabMainWindow.py`, `cache_setting.py`, `io_ops/admin.py`,
   `lab_parameters.py`'s prefix rule). Every read takes its default from the table, so behaviour
   is unchanged; a test fails when code reads a key the table doesn't list or the defaults differ.
   Restore default buttons and default-value tooltips in the UI are **not** in scope (note in the
   handoff what they'd need).

Not in scope: settings profiles / `HELAB_SETTINGS_OVERRIDE` (Tony's decisions pending), any change
to what a setting means, the floor setup hooks (propose changes in the handoff).

## Owned paths

`tests/` (any), the new pytest config file, `helab/utils/settings_defaults.py` (new),
`helab/utils/settings_store.py`, the settings reads in the files listed in B2, `.github/workflows/`
only if a CI command must change for the pytest config (say why), and minimal production fixes
that item A's causes need (name each in the handoff). Don't touch `helab/scripts/`,
`helab/analysis/` beyond a fix item A1 needs, `roadmaps/`, `AGENTS.md`, `.ai/MANUAL_TODO.md`,
`.ai/memory/`, `requirements*`.

## Checks

From the floor root, after `source venv/bin/activate && source .ai/local/floor-env.sh`:
`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest` (report every RERUN),
`mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`. Repeat the fixed tests many
times under load (e.g. `pytest-repeat` or a loop with `-n 8` plus CPU burners) and give the counts.
Don't launch the HeLab GUI.

## Handoff

Commit as you go on `agent/ci-robustness-2` (subject + body with validation). When done: write
`handoff.md` (per item: cause, fix, commit, evidence; open items; proposed edits to
`roadmaps/known-issues.md`, `roadmaps/agent-workflow.md`, `AGENTS.md` Testing, the floor setup
hooks), push the branch once to `TonyXTYan/HeLab` and check its CI run (`gh run watch`); report the
CI result (every RERUN by test and OS). Then `maestri floor status "<summary>" --state review` and
send the Coordinator (CoCo) the handoff's summary. Ask CoCo (`maestri ask "CoCo" …`) when blocked
or unsure of scope.
