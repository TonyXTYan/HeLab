# Memory Index

See `.ai/coding-workspace.md` for what belongs here vs `.ai/sessions/`.

- [Ask before commit](feedback_ask_before_commit.md) — never `git commit` without asking first, even after verifying a fix works
- [Lab PC QtWebEngine black render](results/lab-pc-qtwebengine-black-render.md) — the Lab Side PC is Sandy Bridge/no-D3D11, so Qt plot panes never paint; export Plotly HTML to a browser instead
- [Lab Side PC caveats](results/lab-side-pc-caveats.md) — HeLab runs from a uv Python 3.13 venv (uv for all users); bare python is 2.7, git and conda are off PATH; old Anaconda3 removed; maestri --raw mangles `\r`/`\v` paths, so send base64 Python
- [Lab Main PC caveats](results/lab-main-pc-caveats.md) — uv Python 3.13 venv (3.11's stdlib is corrupted; bare python is 3.6); never launch HeLab over SSH: elevation poisons its cache settings
- [RSPE office PC caveats](results/rspe-office-pc-caveats.md) — RSPE-064759 (XinTong): uv Python 3.13 venv in ~\git_repos\HeLab; py-launcher Pythons all belong to the GitHub Actions runners, never build on them
- [Lab Pi motion camera](results/lab-pi-motion-camera.md) — webcam is USB/IP-shared, caps stream at 640x480; flip_axis h + rotate 180 fixes orientation; settled framerate 10/stream_maxrate 10/stream_quality 100 (~59-60% CPU); disk-full incident resolved, recording disabled
- [UI vertical space](feedback_ui_vertical_space.md) — no vertical padding around HeLab panel blocks; single-line status rows, details in tooltips
- [Folder I/O queue](results/folder-io-queue.md) — cache first: cached data shows at once via a local lane, checked by one folder stat when unmodified; files still being written (5 s) never read; foreground lane (current tab's browsing + selected load) beside background lanes (default 1) that pause cooperatively; 60 s no-progress timeouts (load files 15/20/30 s), two-step browse, slots held until helper exit confirmed; stopping/paused display
- [Folder summary indicators](results/folder-summary-indicators.md) — fixed 3-line summary under the path bar (selection+counts with Cancel/Retry/Deselect, cache, freshness); tab activity in the main status bar; "Cached data found/loaded" wording, package+clock / amber-clock freshness icons
- [Basic scan defaults & failures](results/basic-scan-defaults-and-failures.md) — auto basic scan off by default and never rescans; persisted failure history suppresses auto scans; magnifying-glass ! badge replaces "Unavailable"
- [v0.0.5a folder-browser open threads](project_v0.0.5a-folder-browser.md) — io-lanes done through Phase 3 (`6637528`); undecided signature-carry fix, open review findings; cache dirs in ~/Library/Caches/HeLab

## TODO

- [ ] [Make status messages reflect actual operations and states](../sessions/2026-10-08-codex-status-message-review/review.md) — 2026-10-08 status-bar merge fixed the main-bar counts, cache-writing indicator, background-load and basic-scan states, and old results hiding errors. Still open: load-phase labels (merged/updated sources), progress % counting unreadable files, queued vs running scans in the counts line, central-message items. Keep "Scanning: checking file counts and status…" for running scans. Full message inventory and reproduced cases are in the linked review (2026-10-08).
