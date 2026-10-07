# Memory Index

See `.ai/coding-workspace.md` for what belongs here vs `.ai/sessions/`.

- [Ask before commit](feedback_ask_before_commit.md) — never `git commit` without asking first, even after verifying a fix works
- [Lab PC QtWebEngine black render](results/lab-pc-qtwebengine-black-render.md) — the Lab Side PC is Sandy Bridge/no-D3D11, so Qt plot panes never paint; export Plotly HTML to a browser instead
- [Lab Main PC caveats](results/lab-main-pc-caveats.md) — use the Python 3.12 venv (3.11's stdlib is corrupted), and never launch HeLab over SSH: elevation poisons its cache settings
- [Lab Pi motion camera](results/lab-pi-motion-camera.md) — webcam is USB/IP-shared, caps stream at 640x480; flip_axis h + rotate 180 fixes orientation; settled framerate 10/stream_maxrate 10/stream_quality 100 (~59-60% CPU); disk-full incident resolved, recording disabled
- [UI vertical space](feedback_ui_vertical_space.md) — no vertical padding around HeLab panel blocks; single-line status rows, details in tooltips
- [Folder I/O queue](results/folder-io-queue.md) — one shared I/O queue (default 1), 60 s no-progress timeouts (load files 15/20/30 s), two-step browse, slots held until helper exit confirmed; stopping-helper display
- [Folder summary indicators](results/folder-summary-indicators.md) — 4-line summary under the path bar, Deselect/Cancel, "Cached data found/loaded" wording, package+clock / amber-clock freshness icons
- [Basic scan defaults & failures](results/basic-scan-defaults-and-failures.md) — auto basic scan off by default and never rescans; persisted failure history suppresses auto scans; magnifying-glass ! badge replaces "Unavailable"
- [v0.0.5a folder-browser open threads](project_v0.0.5a-folder-browser.md) — committed 2026-10-08; io-lanes Phases 3–4 next, undecided signature-carry fix; cache dirs now in ~/Library/Caches/HeLab

## TODO

- [ ] [Make status messages reflect actual operations and states](../sessions/2026-10-08-codex-status-message-review/review.md) — prioritise current errors over old scan results; distinguish queued/running/paused work and load phases; correct file-progress percentages, background counts and cache-writing indicators. Keep "Scanning: checking file counts and status…" for running scans. Full message inventory and reproduced cases are in the linked review (2026-10-08).
