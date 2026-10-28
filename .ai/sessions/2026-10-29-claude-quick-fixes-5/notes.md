# Quick Fixes 5: notes (Tinker, Claude Code)

## Job 1: `test_disk_cache_summary_tracks_shared_save_completion[cache_saved]` reruns on macOS CI

**Symptom.** `assert 'Cached data loaded · Cached just now · Freshness unknown' == 'Cached data loaded ·
Cached just now'` (`tests/test_folder_summary.py` ~413), macOS CI runs 40279097363, 40679555921 (3×),
40753079487, 40754538456, 40758706117.

**Cause (the test is wrong, not the app).** "Freshness unknown" comes from
`SnapshotFileSystemModel.data_freshness` → `cache_freshness(as_of, node.modified)`: the save date was
there ("Cached just now"), so the second tab's root row had no folder modified time (`node.modified is
None`). The second `FolderExplorer` gets two things on separate zero-timer passes:

1. `open_to_path` (a `QTimer.singleShot(0)` from the constructor) selects the folder, and the test's
   `selectionPathChanged` hook → `load_to_ram_cache` → `_show_cached` → `_display` shows the shared
   dataset from RAM at once. At that moment the row has no `modified` yet.
2. The tab's listing is answered from the shared snapshot by `FolderCache._replay`, which emits its
   `status` (with `modified`) from another `QTimer.singleShot(0, batch)`, i.e. on a later loop pass.

The test waited only for `second.displayed_dataset is not None`. `qtbot.waitUntil` re-checks after each
`qWait`; when one event-loop pass is slow (a loaded macOS runner), `qWait` returns after step 1 and
before step 2, the condition is true, the test emits `cache_saved`, and the label is computed while the
row's date is still missing.

**Evidence.** A probe (not committed) logging `_observe_modified`, `_display` and the wait's polls
showed, in a normal run, `_display second mod=None` followed by the replay's `observe … -> <mtime>`
within the same wait. Adding a 50 ms sleep after `_display` (a slow loop pass) made the poll see
`ds=True mod=None`, and the label became exactly the CI string
`'Cached data loaded · Cached just now · Freshness unknown'`, every time. The same probe showed that
when the replay arrives (one timer later) the label corrects itself to `'Cached data loaded · Cached
just now'` with nothing else happening, so a user sees at most a single-pass transient: no app change.

**Fix.** `tests/test_folder_summary.py`: the wait also requires the second tab's root row to have its
folder date (`second.model.nodes[path].modified is not None`), with a comment saying why.

**Checks.**
- With the 50 ms `_display` slowdown injected (probe fixture, all three params): unfixed test fails
  `[cache_saved]` with the CI assertion; fixed test passes all three.
- Stress loops of the whole module with its neighbours (`tests/test_folder_summary.py -n 6 -p no:randomly`,
  62 tests a run) under busy-loop CPU hogs: 25 runs / 6 hogs gave 24 clean and **one run with one
  failure that I could not identify**: that loop kept only each run's summary line ("1 failed, 61
  passed"), so neither the test nor the reason is known. Two more loops that kept every run's output
  (30 runs / 6 hogs, 40 runs / 10 hogs) were all clean (70 × 62 passed). It may have been this test, a
  neighbour, or load from the type checks I ran beside that first loop; worth watching on CI.
- Full suite, `-n 4 --reruns 5 --reruns-delay 1`: basetemp `.ai/temp/pytest` 8039 passed, 669 skipped,
  no reruns; basetemp outside the checkout (scratchpad) 8039 passed, 669 skipped, no reruns.
- `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`, `mypy --platform win32 --strict`
  (helab/ and tests), `pyright --pythonplatform Windows helab tests`: all clean.

**Proposed known-issues change.** Close the `test_folder_summary.py::…[cache_saved]` entry (Tests and
CI): "Fixed (agent/quick-fixes-5): the test waited only for the second tab's dataset, which shows from
RAM a zero-timer before the shared listing's replay brings the row's folder date; a slow loop pass let
the wait return between them. The test now waits for the date too; the app's label corrects itself one
timer later." In the 2026-10-28 run 40679555921 entry, note that this test's 3 reruns had this cause.

## Job 2: `test_convert_helab.py::test_watch_converts_new_shots_and_stops_on_ctrl_c` fails all 6 attempts

**Symptom.** In a full run on the `agent/txy-ui` floor (load 28-30): `subprocess.TimeoutExpired` at
`watching.wait(20)` after SIGINT, every attempt; passes alone and in CI.

**Cause (the test, not the CLI): SIGINT was ignored, not slow.** The failed run's child logs were still
in worker gw3's app folder (`$TMPDIR/helab_test_app_gw3__dlkvg5_/logs/helab-92931.log` … `-97735.log`,
08:48-08:50, about 21 s apart): each child converted shot 7 within 0.2 s and never logged "Stopped",
so its KeyboardInterrupt never fired. A non-interactive shell starts a background job (`pytest … &`,
as agents' tools do) with SIGINT and SIGQUIT ignored (POSIX, no job control). An ignored signal
survives fork and exec, so the xdist workers and the `helab convert` child inherit it. Python started
with SIGINT ignored installs no `default_int_handler`, so SIGINT does nothing. Load was a coincidence;
the stderr pipe is not it (a child writes about 2 kB).

**Evidence.**
- `bash -c 'python -c "…getsignal(SIGINT)" & wait'` prints `1` (SIG_IGN); in the foreground it is
  `default_int_handler`.
- `bash -c 'pytest <the test> & wait'` failed with exactly the reported `TimeoutExpired`
  (21.4 s); the same test in the foreground passed in 1 s.
- Ruled out: load (24 probes at load 144 all exited within 0.2 s of SIGINT); a native library setting
  SIG_IGN or blocking SIGINT in a worker (a plugin reading `sigaction` and the main thread's mask after
  every test of a full run saw no change); the store's 30 s busy timeout (each test has its own store).

**The CLI is right.** Leaving an inherited ignore alone is the shell's convention for background jobs,
and Python's own behaviour. From a terminal Ctrl-C reaches it; a backgrounded watcher is stopped with
`kill` (SIGTERM).

**Fix.** The `watching` fixture sets Python's SIGINT handler around `Popen` and restores the previous
one. A handled signal is reset to the default by exec, so the child installs its handler as when
started from a terminal.

**Checks.** Background-job run fails before and passes after; foreground passes both ways.
`tests/test_convert_helab.py -n 4 --reruns 5`, run as a background job 15× under 8 CPU hogs: 15 × 48
passed, no reruns.

**Proposed known-issues line** (Tests and CI; fixed, for the record): "`test_watch_converts_new_shots_and_stops_on_ctrl_c`
failed every attempt in suites started as a background job (`pytest … &`): the shell ignores SIGINT
for those, the convert child inherited it and Python then has no Ctrl-C handler. Fixed in
agent/quick-fixes-5: the fixture starts the child with SIGINT handled. Other tests that send SIGINT to a
child need the same."

## Job 3: heartbeat tests rerun on macOS CI (`assert ([])`)

**Symptom.** `test_a_hung_backend_stops_sending_heartbeats` (:879; 5 reruns in run 40779568331, 2 in
40764414177) and `test_heartbeats_while_computing_stop_after_the_budget` (:855; 2 reruns): no
'converting' heartbeat at all.

**Cause (the tests).** `_Ticker._run` takes `until` = its start + budget, then sends a beat each time
`stop.wait(Heartbeat.INTERVAL)` returns before `until`. The tests set the interval to 0.02 s and the
budget to 0.15 s and about 0.1 s (COMPUTE_SECONDS 0.1) of real time. A ticker thread woken more than
about 0.08-0.13 s late, which a loaded runner can easily cause, found the budget spent and sent nothing.
Not a window shorter than the interval, and not a late start (`until` is taken in the thread).

**Evidence.** Making the first wait on the ticker's own event return 0.2 s late (a probe replacing
`_Ticker.stop`) failed both old tests with exactly `assert ([])`. Load alone didn't reproduce it here
(24 runs at load 13).

**The ticker is right.** With the real 1 s interval and a budget of at least `COMPUTE_SECONDS` = 60 s, it
misses its first beat only if its thread wakes about a minute late, and then the budget is spent.
No change to `helab/io_ops/convert.py`.

**Fix.** The tests replace `io_ops.convert`'s monotonic clock with one only they move (`convert_clock`),
wait for heartbeats (`wait_for`), then spend the budget and check that the ticker thread ends by itself
(stop not set) while the shot still computes. The hung-backend test records the ticker through a
subclass of `convert._Ticker`. No real-time windows remain.

**Checks.** Both pass with the 0.2 s late-wake injection. A ticker that ignores its budget fails both
(the mutation check). mypy --strict and pyright pass on the file. Stress loop and full suites: see the report.

**Proposed known-issues change.** Close both heartbeat entries: "Fixed in agent/quick-fixes-5: the tests
gave the ticker a 0.1-0.15 s real-time budget, which a late-woken ticker thread missed entirely; they
now move convert's clock themselves and wait for the beats."

## Checks for jobs 2 and 3 (tree at f22228c)

- `tests/test_convert_helab.py -n 4 --reruns 5`, 10× under 8 CPU hogs: 10 × 48 passed, no reruns.
- Full suite `-n 4 --reruns 5 --reruns-delay 1`, 8039 passed and 669 skipped each time, no reruns:
  basetemp `.ai/temp/pytest`; basetemp outside the checkout (scratchpad); and the whole suite started
  as a background job (`bash -c 'pytest … & wait'`, SIGINT ignored: job 2's failing mode).
- mypy --strict helab/ and tests, pyright helab tests, mypy --platform win32 --strict (both),
  pyright --pythonplatform Windows: clean.

## CI for jobs 2 and 3: run 40786300323 (8b96fe4)

All jobs succeeded. Tests macOS 8039 passed, no reruns; Windows 8010 passed, no reruns; Ubuntu 8037
passed with **1 rerun**: `tests/test_convert_helab.py::test_a_killed_helpers_workers_exit`,
`assert False` from `all(...)` at :551 (`assert all(convert.partial().match(name) for name in names
if name.endswith(".partial"))`). Not one of my tests. Likely cause, from the code and not reproduced:
`txy.write_atomic` also writes the provenance record (`io_ops/convert.py:550`, before the TXY) and the
folder record (`:272`) under `.partial` temporary names, but `convert.partial()` matches only TXY
temporary names. A kill landing in a record write leaves a `.partial` the test doesn't expect. Neither
the startup sweep nor a later pass then removes it from HeLab's own converted-txy folder (it only
matches the TXY pattern).

Proposed known-issues line: "`test_a_killed_helpers_workers_exit` reran on Ubuntu CI (run
40786300323): a kill during a provenance/folder record write leaves a `.partial` that
`convert.partial()` (TXY names only) doesn't match; such leftovers in HeLab's own folder are never
removed either. Decide whether leftover cleanup covers record temporaries (Q~1), then fix the test or
the pattern."

Q~1 (for Tony, via CoCo): should HeLab's leftover cleanup in its own `converted-txy/` folder also
remove record temporaries (`.d_txy_helab_<N>….partial` of the provenance/`folder.json` writes), or
should only the test widen what it accepts?
