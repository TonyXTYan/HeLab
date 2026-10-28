# Brief: Quick Fixes 4, CI-flaky tests (`agent/quick-fixes-4`)

Coordinator: CoCo, 2026-10-29 (overnight build; Side approves on Tony's behalf within the
[mandate](../2026-10-29-claude-v0.0.7-overnight/mandate.md): the v0.0.7 PR needs clean CI). One
Quick Fixer, then a Reviewer. Runs beside the converter's stage 4 floors.

## Base and branch

Base `b08627a` (`dev/v0.0.7`). Branch `agent/quick-fixes-4`.

## Jobs (all in `roadmaps/known-issues.md`, Tests and CI; read each entry first)

1. `tests/test_preset_folder_live.py::test_offline_a_folder_never_listed_is_named_as_such`:
   `pytestqt.exceptions.TimeoutError: waitUntil timed out in 30000 milliseconds` (line 82). Four CI
   reruns on 2026-10-29, macOS and Windows (runs 40713926667, 40722925594 twice, 40740875291).
2. `tests/test_folder_summary.py::test_scan_metadata_survives_restart_without_reading_txy_contents`:
   its process-wide `os.scandir` patch recorded an `os.scandir(<fd>)` that wasn't the test's own
   call (line 725; macOS CI run 40722845197 and once locally): likely another thread's
   `shutil.rmtree`.
3. `tests/test_io_trace.py::test_tracing_changes_no_event_and_no_source_call`: event lists differ
   at index 2 (a `scan_summary` event), Windows CI run 40725480099 (job 122947593152).
4. `tests/test_helabMainWindow.py::test_the_view_menu_has_no_thread_status_item_and_its_setting_is_retired`
   (line 533): I/O from the window the previous test built
   (`test_window_icon_is_found_from_any_launch_folder`, line 500: chdir to `tmp_path`,
   `window.close()`) reaches the next test; it shows only with `--basetemp` outside the checkout,
   where the source guard is strict. Reproduce that way.

CI logs: `gh api repos/TonyXTYan/HeLab/actions/jobs/<id>/logs` (quote the "rerun reasons").

## Rules (Side's conditions on top of your role)

- Cause before change; "flaky" is not a cause. A longer timeout only when the cause is timing and
  you say why. If you can't reproduce, say what you tried and add diagnostics that will name the
  cause at the next CI failure.
- Fix the test when the test is wrong; app code only where the cause actually is, kept small. If
  a job turns out not to be small (a design change, more than a few files, behaviour users see),
  stop and ask CoCo.
- **No converter paths**: nothing under `helab/convert/`, `helab/io_ops/convert.py`, `native/`,
  `dev/txy/`, `tests/test_convert_*` (stage 4 floors own them).
- Notes in `.ai/sessions/2026-10-29-claude-quick-fixes-4/notes.md`: a section per job (cause,
  evidence, fix, checks, the known-issues line to change). Never edit `roadmaps/` or the `.ai/*`
  lists; propose instead.
- Before the report: `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest` AND one
  run with `--basetemp` outside the checkout (under `$HELAB_DIR_TEMPS_OVERRIDE`), each fixed test
  in a stress loop (e.g. `-p xdist -n 8 --count`/repeat, or a shell loop under load), `mypy helab/
  --strict`, `mypy tests --strict`, `pyright helab tests`; report every RERUN.
- Push once, when the jobs are done (a CI run is worth it here: say the run URL). Report each job
  to CoCo with `maestri ask "CoCo" "…"`, then go on.
