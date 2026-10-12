# GitHub Actions failure investigation — 2026-10-12

Latest development CI run: [38245359149](https://github.com/TonyXTYan/HeLab/actions/runs/38245359149), push to `dev/v0.0.5a`, commit `e7009af5e82b4a0c8ef01b13143743c0c1203ea8`, started 2026-10-12 11:51:31 UTC. The checkout matches this SHA. The run ended **cancelled** because the workflow explicitly cancels after a required Python 3.13 failure. Python 3.14 installation failures are non-blocking and did not trigger this cancellation.

## Required Python 3.13 failures

**Ubuntu:** [job 114797745932](https://github.com/TonyXTYan/HeLab/actions/runs/38245359149/job/114797745932), 1 failed / 675 passed / 1 skipped / 2 xfailed. `tests/test_hover_menu_button.py::test_options_open_left_of_the_triangle_at_the_screen_edge` fails at line 112 after all five reruns. The timeout occurs in the setup condition checking whether the menu would overflow the screen; it happens before opening the menu or asserting its placement. The test moves the window's right edge to the screen edge, but the 32-pixel button sits near the left side of a 200-pixel window. Whether the menu overflows therefore depends on its style/font-dependent width. The test should position the button from its actual global coordinates and the menu's measured size, with a deliberate margin, before exercising the popup.

The same test fails on Ubuntu Python 3.11 and 3.12 in this run, each with 675 passing tests. It also failed on Ubuntu Python 3.13 in the [preceding run 38142972739](https://github.com/TonyXTYan/HeLab/actions/runs/38142972739/job/114480436920), with 628 passing tests. This failure predates the latest build-provenance/release change.

**Windows:** [job 114797746003](https://github.com/TonyXTYan/HeLab/actions/runs/38245359149/job/114797746003), 3 failed / 670 passed / 4 skipped / 2 xfailed. All three failures survived five reruns:

- `test_cache_first.py::test_files_still_being_written_are_left_for_the_next_load`, line 144: expected `read_bytes` and `total_read_bytes` of 6, got 7. The fixture writes `1,2,3\n` with `Path.write_text`, which writes CRLF on Windows. The helper correctly reports on-disk bytes. Derive expected sizes with `stat().st_size`, or explicitly write LF fixtures.
- `test_cache_store.py::test_read_only_open_handles_uri_characters_in_the_path[query?mode=rw]`, line 364: `WinError 123` creating the fixture directory. `?` is forbidden in Windows filenames, so this fails before testing SQLite URI handling. Skip just this parameter on Windows; retain the `%` and `#` cases there.
- `test_large_folder.py::test_the_check_of_data_already_in_ram_counts_only_what_it_adds`, line 116: expected a 6-byte added-file estimate, got 7. Same CRLF assumption; use the added file's actual size.

Ubuntu issued its failure annotation at 11:54:07 UTC and the cancellation API returned `{}` at 11:54:08. Windows finished its tests at 11:54:36 and also ran its failure-report/cancellation steps. Their final job conclusions are cancelled despite recorded test failures. Other cancelled build/test jobs are incomplete evidence, not successful checks or additional confirmed build failures.

## Non-blocking Python 3.14 failures

All six test/build jobs on macOS, Ubuntu and Windows fail at `Install dependencies`. Logs identify the chain `requirements.txt -> pytablericons -> pygame>=2.5.2`; pip selects the `pygame-2.6.1.tar.gz` source distribution on these Python 3.14 runners.

- macOS: compilation fails with `fatal error: 'SDL.h' file not found`.
- Ubuntu: configuration fails because `sdl-config` is unavailable.
- Windows: pygame's MSYS2 prebuilt setup fails invoking its package-install tooling with `FileNotFoundError: [WinError 2]`.

The preceding run had the same platform-specific pygame installation failures. These jobs never reach application tests or PyInstaller. Address the icon package's pygame dependency or provide a validated build/dependency route separately from the required-version test fixes; preserve the existing Python-version failure policy.

## Verification and limits

- The exact menu-edge test passes locally on macOS offscreen: `1 passed in 0.75s`.
- Diagnostic geometry: 800-pixel screen, 204-pixel window frame, button right edge at 641, 159 pixels of free space, menu width 160. Local success has only a one-pixel overflow margin. Ubuntu's actual geometry was not printed in CI, so its precise font/style dimensions remain unmeasured.
- `diagnostic_probes.py` forces CRLF writes and reproduces both Windows assertion failures on macOS, while retaining the project's private-directory/settling test configuration. Final diagnostic run: `3 passed in 1.01s`; the first two probes pass by confirming the expected assertion failures, the third reports geometry.
- Version detection succeeded. The release job and all builds other than Python 3.14 installation failures were cancelled; no completed build/release validation is available from this run.
- Logs contain secondary Dash port-8050 contention warnings during parallel tests; they are not the reported assertion/timeout causes.
- Full-run log retrieval failed because GitHub reported one cancelled build job's log unavailable. Individual relevant job logs were downloaded instead.
- No application, test, or workflow source files changed. Evidence and scratch probes are confined to this session folder. No reruns, commits, pushes, or workflow cancellations were initiated by this investigation.
