# Handoff: fixes for the re-review of dev/v0.0.9 at `09ca79b`

Worker: Claude (cloud session), 2026-11-17. Branch `claude/gracious-brahmagupta-0cghhu`, started from
`dev/v0.0.9` at `09ca79b` (the reviewed commit). The findings are in [`review.md`](review.md) (N1–N3, laserlock)
and [`previous-review.md`](previous-review.md) (R1–R5, first reported at `d2bd306`); both came in Tony's
`HeLab-v0.0.9-review-09ca79b.zip`. All eight are fixed in the commits below, each with tests that fail before its fix.
Nothing is merged and no PR is open.

| ID | Commit | What changed |
|---|---|---|
| N1 | `d64999b` | Laserlock: a wanted voltage belongs to the mode that asked for it. Every change of mode goes through `Engine._enter`, which withdraws it: Release, a lost lock, a fault, and a manual voltage typed just before a lock, sweep or calibration. The target waits in the engine, never inside the device (`_last_cmd` times every command of the loop thread), and the mode is checked again, holding the lock, in the step that hands the voltage to the device. |
| N2 | `d64999b` | `PILock.update(thz, t, applied)`: the step limit and the anti-windup are measured from the voltage applied, and a hold stays at it. `_flush_output` holds a lock's write to `max_step` from the applied voltage as well. Ten readings before one write now move the output one step (0.01 V), not ten. |
| N3 | `d64999b`, `5aebdc9` | The stable-range hold needs readings: it fails when no new valid reading comes for 1 s (or five update periods), also if the signal comes back, and with fewer than 3 valid readings. A hold of 0 skips the watch but still needs one reading at the target. |
| hop test | `d64999b` | `test_window_draws_hops` waited a fixed 0.8 s for a line the window redraws at most once a second, counted from its last redraw; it now waits for the line (10 s at most). |
| R1 | `a0c2c34` | Updater: the venv's renames (update, its undo, Restore's three) go through `_renames`, which undoes those already made when one fails. The earlier update's `previous.json` is put back instead of deleted when an update fails. `rollback` says whether it put everything back. |
| R2 | `a0c2c34` | Updater holds `<app folder>/update.lock` with its token from before HeLab is told to quit until the code and venv are as they will stay. The app (`running.lock` first) and `helab convert` (instance lock first) look at it second, and stop; `helab.main` also looks before importing Qt or HeLab. The updater checks again that nothing runs before the code moves and before the venv swap. |
| R3 | `ab21cdf`, `92dda56` | The drawn image has equal cells (`cell_mean`, `cell_edges`): a bin on a cell's border counts by its part on either side, so the even stretch every library applies is exact. |
| R4 | `3121dd6` | Plane projections: `estimated_bytes`, the run's warning over half the RAM budget, and a drawn image of at most 1,000 cells a side made on the worker for Plotly and Matplotlib. |
| R5 | `7b1e5ef` | `crash_file.exit_after` gives faulthandler's timer `os.dup` of the crash file's descriptor. |
| manual | `ec6a2b9` | `docs/how-to/update.md` (starting HeLab during an update), `docs/how-to/basic-plots.md` (Plane projections at many bins). |
| not a finding | `05deb92` | `test_dash_server`'s dual-stack test skips where the kernel has no IPv6 (it failed in this container, on `09ca79b` too). |

## Notes on the fixes

- **N1, what "Release" guarantees.** A correction not yet handed to the DG1022 is never written after Release.
  One already on the wire can't be recalled; the window then shows the voltage that was applied
  (`test_release_or_lock_while_a_command_is_on_its_way`). The engine never calls `out.set` for a lock's target
  while the DG1022's turn hasn't come, so nothing waits inside the device
  (`test_a_correction_never_waits_inside_the_dg1022`, on the fake VISA session).
- **N1, a side effect:** a manual voltage typed and not yet written (a 100 ms window) is dropped when Lock, a
  sweep, a scan or a calibration starts. Before, it was written after the sweep had returned, or under the new
  lock. See Q~4.
- **N2, the slew rate changes.** With the wavemeter at ~40 ms and the DG1022 at 100 ms, the lock could move
  0.25 V/s at the default 0.01 V step; it now moves 0.1 V/s. Raise **Max step** if a lock needs the old rate.
- **R1, not done: a durable journal** for a kill or power cut between two renames. A venv-only journal can't tell
  which way to recover without the code's state, and a wrong automatic recovery is worse than none; a journal of
  the whole update (stash, code, venv, record) is a piece of work of its own. The update's log has a line for
  every rename made. See Q~6.
- **R2, the order that makes it certain:** HeLab takes its own lock, then looks at `update.lock`; the updater takes
  `update.lock`, then waits for HeLab's locks. Whichever comes later sees the other. The start the updater makes
  carries `HELAB_UPDATE_TOKEN`, which is the token in the lock, and goes on. The lock is released before the
  previous version is started again after a failure, and before the older venv is deleted.
- **R2, `app_folder`:** `app_folder` and `default_app_dir` moved to `helab/utils/app_dirs.py` (standard library
  only); `constants` and `cache_cli` use it. The check at the top of `helab.main` needs the app folder before Qt.
- **R2, a HeLab that ignores the lock** (holds `running.lock` when the venv is ready): the updater waits
  `others` seconds, then swaps nothing and puts the code back.
- **R3, the title:** "each the mean of 3 × 1 bins" stays where the bins divide; otherwise it gives the bins a
  cell covers to 4 figures ("2.999 × 1 bins"). See Q~2.
- **R5, the cause:** reproduced with Python 3.13.5 (empty crash file) and not with 3.13.14, on the reviewed
  commit; with the fix both write the `__del__` stack.

## Checks

All with the packages of `requirements.lock` (a venv built for this session: the container's own venv has newer
ones, see A~2), Python 3.13.14, Linux, 4 cores. No instrument, real data or network share was used.

- **Full suite**, `pytest -n 4 --reruns 5 --reruns-delay 1`, at `05deb92`: **9,952 passed, 702 skipped, no failure, no rerun** (368 s;
  [`suite-05deb92.txt`](suite-05deb92.txt)).
  The run before it, at `ec6a2b9` ([log](suite-ec6a2b9.txt)): 9,952 passed, 701 skipped, 1 failed, 5 reruns, all of them
  `test_dash_server.py::test_a_port_another_program_holds_on_all_addresses_is_left_to_it[ipv6]`
  (`OSError: [Errno 97] Address family not supported by protocol`: this container has no IPv6; `05deb92` makes it
  skip). The first run, at `92dda56` ([log](suite-92dda56.txt)), also failed `test_typing.py::test_pyright_tests` 5 times: pyright reported
  7 attribute errors in two of my new tests (untyped Plotly figures), fixed in `ec6a2b9`.
- **Type checks** at `ec6a2b9`: `mypy helab/ --strict` (245 files), `mypy tests --strict` (244 files),
  `pyright helab`, `pyright tests`, `mypy helab/ --strict --platform win32`,
  `pyright --pythonplatform Windows helab tests` (with `NODE_OPTIONS=--max-old-space-size=8192`: it ran out of
  Node's default heap otherwise): no errors. `ruff check`: passed.
- **Laserlock** (`side_projects/laserlock`, its own run, PyVISA 1.16.2 in a scratch folder, simulated and fake
  instruments): 54 passed at `5aebdc9` (36 before).
- **The review's probes:** [`probes_after.py`](probes_after.py) is its eight probes against the fixed code, with
  [what each now prints](probes_after.txt). R5's was also run with Python 3.13.5 (`uv python install 3.13.5`):
  on `09ca79b` the crash file is empty (3.13.14: the stack is there); with the fix both have the stack.
- **The manual:** `mkdocs build --strict -d .ai/temp/site` built at `05deb92`.
- **Not run:** Windows and macOS (CI runs them on the push); the compiled converter backends.

## Proposals (provisional IDs)

**Decisions for Tony**

- **Q~1 Wording when HeLab is started during an update.** The app: a window titled "HeLab is being updated",
  "HeLab is being updated. It starts again by itself when the update has finished; start it then if it doesn't.",
  which closes itself after 8 s (a HeLab left waiting at a message would hold up the update). A command: "HeLab is
  being updated: run this again when the update has finished." Proposed: keep.
- **Q~2 The drawn image's title when the bins don't divide:** "each the mean of 2.999 × 1 bins" (4 figures), or
  "about 3 × 1 bins". Proposed: keep the figures.
- **Q~3 Laserlock's "Max step / update" label.** It now limits each write to the DG1022. Rename to "Max step /
  write"? Proposed: yes; only a tooltip was added so far.
- **Q~4 Laserlock: a manual voltage not yet written is dropped when Lock or a sweep starts.** Proposed: keep.
- **Q~5 Laserlock's hold limits:** 1 s or five update periods without a valid reading, at least 3 readings, no
  recovery once the limit passed, a hold of 0 needs one reading. Proposed: keep.
- **Q~6 A durable journal for the updater** (a kill between two renames). Proposed: not for v0.0.9.
- **Q~7 `helab cache` (read only) is refused during an update too.** Proposed: keep.
- **Q~8 Plane projections' Bins tooltip** gained a sentence on the drawn image. Proposed: keep.

**Work agents may do**

- **A~1 Laserlock's auto-lock after a plain sweep** (`_sweep` with `lock_thz`) engages without checking a new
  reading at the target, as N3's hold did. Not in the review; the same fix as the hold of 0 would do.
- **A~2 The cloud environment's venv** is installed from `requirements.txt`, not `requirements.lock` (PyQt6 6.12.1
  for 6.11.0, mypy 2.4.1 for 2.4.0). With it `mypy helab` reports 165 errors and
  `test_toggling_planes_removes_and_restores_their_rate_bars[PyQtGraph]` fails ("wrapped C/C++ object of type
  ViewBox has been deleted"), both on `09ca79b` too. Its setup script should install the lock; the ViewBox failure
  is worth a look before PyQt6 is next bumped.

- **A~3 `test_a_killed_helpers_workers_exit`: count a zombie as exited** (the review's two failures; see the
  known-issues proposal below). Not done here: it couldn't be reproduced, so a fix would be unchecked.

**Checks that need Tony, real data or the lab**

- **M~1 Laserlock on the real DG1022 and WS8** (nothing here ran on an instrument): Release while locked with the
  wavemeter fast (the output must not move after it); the size of each write against Max step; Find stable range
  with the beam blocked during the hold (it must return, unlocked).
- **M~2 An update that rebuilds the venv, on Windows and macOS:** start HeLab (and `helab convert`) by hand during
  the build; each must say HeLab is being updated and stop, and the update must finish and start HeLab.

## Proposed doc changes

**`roadmaps/known-issues.md`**

- `test_quit_confirms.py::test_a_teardown_stuck_where_the_watch_cant_run_is_ended_from_the_crash_files_timer`
  (`assert '__del__' in ''`, 2 reruns then failed in both of the review's runs, Python 3.13.5): cause found and
  fixed in `7b1e5ef` (R5). Python 3.13.5 closes the crash file's object in its last collection; 3.13.14 doesn't,
  which is why CI passed.
- `side_projects/laserlock/tests/test_laserlock.py::test_window_draws_hops` (`assert 0 == 1`, the review's
  laserlock run): cause found and fixed in `d64999b`. The window redraws hops at most once a second from its last
  redraw, and the test waited a fixed 0.8 s.
- `test_convert_helab.py::test_a_killed_helpers_workers_exit`, a second symptom for its open entry:
  `assert [psutil.Process…] == []`, three Python processes in `status='zombie'`, 2 reruns then failed in both of
  the review's runs (its sandbox, 2026-11-11 and 2026-11-17). Not seen here in three full runs. The workers had
  exited (a zombie is an exited process nobody has waited for); likely the sandbox's process 1 doesn't reap
  orphans. Not reproduced here, also not with pytest as process 1 (`unshare --pid --fork`), so the cause stays
  open. Likely fix: count a zombie as exited (`psutil.STATUS_ZOMBIE`).
- `test_dash_server.py::test_a_port_another_program_holds_on_all_addresses_is_left_to_it[ipv6]`
  (`OSError: [Errno 97] Address family not supported by protocol`, 5 reruns then failed, this cloud container, on
  `09ca79b` too): cause found (no IPv6 in the kernel while `socket.has_ipv6` is true) and fixed in `05deb92`.
- `test_basic_plots_v2_hist2d.py::test_toggling_planes_removes_and_restores_their_rate_bars[PyQtGraph]`
  (`RuntimeError: wrapped C/C++ object of type ViewBox has been deleted`, in `SpaceScale.fit` → `sizes`): fails
  every time with PyQt6 6.12.1 (the container's unpinned venv), on `09ca79b` too; passes with the lock's 6.11.0.
  A timer's fit after the panels were replaced. Open: to look at before PyQt6 is bumped.
- From the review's first run (2026-11-11, `d2bd306`), not seen since:
  `test_basic_plots_v2_hist2d.py::test_dots_on_a_black_or_white_plot_area[local density]` (worker crashed, passed on
  rerun, cause not established) and `test_correlations.py::test_fifty_shots_of_two_thousand_events_take_seconds`
  (25.5 s against 20, passed on rerun; it has an entry).

**`.ai/architecture/release-and-ci.md`, App updates › The updater:** add
"`update.lock` in the app folder (`UpdateLock`; HeLab's side `cache_locks.update_in_progress`): held with the
run's token from before the ready mark until the code and venv are as they will stay; the app (after
`running.lock`), `helab convert` (after its instance lock) and the top of `helab.main` (before Qt, read only) stop
while another process holds it, unless `HELAB_UPDATE_TOKEN` is the token in it; `check_quiet` before the code moves
and before the swap; the venv's renames all or nothing (`_renames`, `swap_in`, `swap_back`, `swap_previous`);
`rollback` returns whether it put everything back; a failed update puts the earlier `previous.json` back."
Test seams: `FAKE_UV_PAUSE` (the fake uv stops in `pip install` until the file is deleted).

**`.ai/architecture/app-runtime-and-ui.md`:** `helab/utils/app_dirs.py` (Qt-free `app_folder`,
`default_app_dir`); `crash_file._armed` is an OS descriptor (`os.dup`), not the file object.

**`.ai/architecture/plots-and-scripts.md`:** the drawn image is `histogram2d.cell_mean` over `display_shape` equal
cells (`cell_edges`), `Display.factors` are floats; Plane projections has `estimated_bytes` (`planes_bytes`) and
`Projections.displays` (at most `PLOTLY_SIDE` a side, both libraries).

**`AGENTS.md`, I/O and threads, after the one-app rule:** "While HeLab's updater holds `update.lock`, nothing of
HeLab starts but the start it makes (`cache_locks.update_in_progress`; the app and `helab convert` take their own
lock first)."
