# CI investigation and robustness tests (2026-10-21)

Branch `agent/ci-robustness`, started from `agent/refactor-integration` (`11a45fa`), so it
holds the whole refactor plus this work. Asked by Tony: investigate the GitHub CI jobs and add
tests to make the code more robust.

## What CI showed

These figures come from the logs of 48 runs (16 on `agent/refactor-*` since 2026-10-20,
32 on `dev/v0.0.6` since 2026-10-19) and 144 py3.13 Tests jobs. Build jobs never failed.

| Problem | Where | Cause | Done |
|---|---|---|---|
| `test_settings_store.py::test_tests_get_an_ini_file_of_their_own` failed every time | Windows; agent branches only (new test) | Qt gives `QSettings.fileName()` with `/` | Compared as paths (`94a4fb5`) |
| `test_cache_mover.py::test_a_lock_is_exclusive_and_released_when_its_process_ends`: reran in 12 of 16 agent jobs, failed in 1 | Windows; dev too | Windows releases a killed process's `LockFileEx` lock a little later ("depends upon available system resources"); production already waits | Tests poll up to 10 s (`ff4d91e`) |
| `test_live.py::test_quitting_straight_after_a_save_waits_for_another_tabs_load_waits_for_the_save`: reran in 12 of 16 agent jobs, failed in 3 | Windows; dev too (4 of 32) | The helper's new warning on CI (`802f126`) gave the cause: "Disk cache could not be opened: disk I/O error". On Windows, opening the store while another process's last connection closes and removes the WAL files gives SQLITE_IOERR, which the busy timeout doesn't cover. The app can hit this too. | The reason is reported (`659cedc`, `a8f1c3a`). The store open retries SQLITE_IOERR only, 5 attempts over about 1.5 s (`ab83c0c`, `tests/test_cache_store_open.py`) |
| Two new marker tests failed on Windows | Windows | `root_create` hides the marker, and Windows refuses a truncating write to a hidden file | The tests rewrite it in place (`990be44`) |
| `test_two_step_browse.py::test_refresh_cancels_only_automatic_subscriptions_and_suppresses_new_checks` (Known issue) and `…test_refresh_requests_details_for_new_subfolders_after_it_finishes` | macOS (dev also Windows) | Refresh's details are re-requested from `QTimer.singleShot(0)`; the tests looked before the posted call ran | Wait for it (`0550e28`). With the call delayed to 300 ms, the old tests fail and the new ones pass |
| `test_folder_cache.py::test_two_tabs_share_snapshot_arrays_and_default_resolution` (Known issue) | macOS; RSPE Windows PC | The second tab's tree comes from replays in posted batches; the test checked it as soon as the data showed | Wait for replays (`2069c3c`). Under 4 parallel loops plus CPU burners: 10 of 48 failed before, 0 of 48 after |
| macOS Tests cancelled at 15 min (3 of 16 agent jobs; others 830–900 s) | macOS | The suite ran twice: the xdist run (already `--cov`) and a serial coverage run, which also segfaulted twice on dev (`d2833f1`, `919ff11`) | One run writes `coverage.xml`; serial run removed; `-rR`; limit 20 min (`f9faefd`). macOS Tests took 6:44 on this branch's first run |

Left as they are:
- `test_plot_settings_panel.py::test_activation_sources`: one rerun on macOS. It didn't fail in 60 local runs under load.
- `test_window_resize.py::test_label_keeps_painting_after_resize[repeated]/[single]`: 12 reruns on dev, 3 on agent branches, macOS/Ubuntu.
- `test_dash_server.py::test_stop_frees_the_port`: port 8050 contention when suites run at once.
- `test_live_plots.py::…[Matplotlib-TransferFractions]` crashed an xdist worker 7 times on dev (macOS/Windows), never on the agent branches.

The first CI run of this branch (`f9faefd`) was green on all three OSes. The quitting test still
reran once on Windows, and passed.

## Tests added (2201 → 2366 tests on the branch; full suite 2366 passed, 3 xfailed, no reruns)

- `tests/test_txy_files.py`: TXY files as the converter writes them and as interrupted or foreign writes leave them.
- `tests/test_helper_dispatch.py`: the helper's dispatcher (`io_helper.main()`) in-process. It covers every route, refusals, errors, `unverified`, the source guard, pause and the trace. `io_helper.py` coverage went from 0 % to 96 %.
- `tests/test_root_marker_errors.py`: `.helab-root` placing, replacing and deleting when the OS refuses, by failing `os.open`/`fsync`/`replace`/`remove` for the marker only, so they run as root and on every OS. `io_ops/markers.py` went from 78 % to 91 %.
- `tests/test_events_hub.py`: the notification hub (keys, rate limit, held-back counts, hooks, delivery fallbacks). `utils/events.py` went from 80 % to 100 %.
- `tests/test_scripts_folder.py`: Load Scripts… for a user's folder (reloads, broken files, hashes). `scripts_manager.py` went from 74 % to 100 %.

## Bugs found and fixed

- **TXY files with four numbers a row loaded with their columns shifted.** pandas took the extra leading column as the index, so `t` held x's values. Files whose first row has more than three fields are now unreadable (failed, shot problematic, the rest of the folder loads). Short rows keep the old handling: dropped, shot flagged. The lab converter (`dld_raw_to_txy_counts.m`, `dlmwrite` precision 8) is never affected.
- **Load Scripts…:**
  - A script whose metadata `file_path` isn't its own file was listed once more on every reload, and stayed after its file was deleted.
  - An abstract helper base class in a file stopped the file's later scripts from loading.
  - A script calling `sys.exit` or argparse at import raised `SystemExit` out of Load Scripts….
  - A script missing a method is now reported by name.

## For Tony

1. **Decision:** an invalid known `.helab-root` is forgotten in the store but reported only as a `cache_warning`, not `root_changed` (`helab/io_ops/markers.py:46-50`). `FolderCache` keeps the folder in `data_roots` (anchor badge) and the old root's RAM state for the session. A removed marker gets `root_changed`. The suggested fix is to send `root_changed` (reason "marker invalid") the same way. It is left as a strict xfail in `tests/test_root_marker_errors.py` because it changes data-root state across components.
2. `roots_verify` is missing from `io_helper.CACHE_ONLY` (it is in `IOService.CACHE_OPERATIONS`). This is harmless today because `FolderCache` always sends a cache.
3. `helab/utils/synchronised_dict.py` is unused (0 % coverage, no importers). Remove it?
4. The store-open warning reads "Disk cache could not be opened: Disk cache could not be opened: …" (`io_ops/stores.py:87` adds the prefix that `CacheStore`'s `StoreError` already carries). It is user-visible wording, so I left it unchanged: drop one?
5. Proposed for `roadmaps/_readme.md` Known issues:
   - tick the two-tabs and two-step-browse flakes (fixed);
   - add the Windows quitting-test flake (diagnostics in place), the Matplotlib transfer-fractions worker crash on dev, and the marker decision above.
