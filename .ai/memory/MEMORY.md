# Memory Index

See `.ai/coding-workspace.md` for what belongs here vs `.ai/sessions/`.

- [Ask before commit](feedback_ask_before_commit.md) — never `git commit` without asking first, even after verifying a fix works
- [Preferred address](user_preferred_address.md) — address the user as "🎓Tony"
- [Lab PC QtWebEngine black render](results/lab-pc-qtwebengine-black-render.md) — the Lab Side PC is Sandy Bridge/no-D3D11, so Qt plot panes never paint; export Plotly HTML to a browser instead
- [Lab Main PC caveats](results/lab-main-pc-caveats.md) — use the Python 3.12 venv (3.11's stdlib is corrupted), and never launch HeLab over SSH: elevation poisons its cache settings
- [Lab Pi motion camera](results/lab-pi-motion-camera.md) — webcam is USB/IP-shared, caps stream at 640x480; flip_axis h + rotate 180 fixes orientation; stream_quality 95/maxrate 3 tuned; disk-full incident resolved, recording disabled
