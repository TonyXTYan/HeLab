---
date: 2026-10-08
status: settled
name: lab-side-pc-caveats
description: "Lab Side PC: HeLab runs from a uv Python 3.13 venv (uv installed for all users); bare python is 2.7, git and conda are off PATH, old Anaconda3 removed, and maestri --raw mangles backslash paths"
metadata:
  node_type: memory
  type: result
---
Working notes for the **Lab Side PC** (RGA machine, host `RSPE-050184`, user
`helium`, Windows 11 build 26100, Sandy Bridge CPU, Tailscale
`100.123.123.201`, repo at `C:\GitHub\HeLab`). Its QtWebEngine plot panes
never paint — see [[lab-pc-qtwebengine-black-render]]. For the Lab Main PC see
[[lab-main-pc-caveats]].

## Python: the uv venv (set up 2026-10-08)

HeLab runs from `C:\GitHub\HeLab\venv`, **Python 3.13.16** — the version CI
requires and Tony's Mac uses.

- **uv** (0.12.23 at setup) is installed **for all users** in
  `C:\Program Files\uv`, which is on the machine `Path`. The previous machine
  `Path` is backed up in `C:\ProgramData\uv-setup-backup\`.
- Machine-wide env var `UV_PYTHON_INSTALL_DIR=C:\ProgramData\uv\python`, so
  uv-managed Pythons are shared by every account (Administrator, bryce, helium,
  scu, Tony) rather than stored per user.
- The venv was built with `uv venv --managed-python --python 3.13 venv`, then
  `uv pip install --python venv\Scripts\python.exe -r requirements.txt -e .`
  (92 packages, `uv pip check` clean, all requirement modules import).
- `pip` was added to the venv afterwards (`uv pip install pip`). Without it, a
  bare `pip` in the activated venv resolved to the python.org 3.12 install.
  New venvs should use `uv venv --seed`.
- The previous venv (python.org 3.12.10, only PyQt6/WebEngine/plotly, so HeLab
  failed at import) was deleted on 2026-10-08.

To start HeLab, sit at the desktop, open a fresh terminal, and run
`cd /d C:\GitHub\HeLab` then `venv\Scripts\helab`. A terminal that was open
before the uv install will not have the new `Path`.

## Other interpreters — don't use them for HeLab

- Bare `python` is **Python 2.7** (`C:\Python27` is on the machine `Path`).
  Always use `venv\Scripts\python.exe`. The Windows Store `python` /
  `python3` app execution aliases were turned off on 2026-10-08.
- `py -0p` lists the python.org **3.12.10** (per-user,
  `C:\Users\helium\AppData\Local\Programs\Python\Python312`), 2.7-32, and
  uv's `Astral/CPython3.13.16` (uv registers it under PEP 514).
- conda (not on `Path`):
  - `C:\ProgramData\miniconda3` — conda 23.7.4, base Python 3.11.5, plus env
    `py311` (3.11.9) at `C:\Users\helium\.conda\envs\py311`. This is the conda
    to keep.
  - The old `C:\Users\helium\Anaconda3` (2019.03: conda 4.6.11, Python 3.7.3,
    Spyder, Navigator) was **removed on 2026-10-08** with its official
    `Uninstall-Anaconda3.exe /S`. `anaconda-clean` was deliberately **not** run:
    it deletes `~\.condarc` and `~\.conda`, which miniconda shares and which
    hold the `py311` env. Before/after snapshots and `.condarc` /
    `environments.txt` backups are in `C:\ProgramData\uv-setup-backup\`.
    Miniconda, uv, the venv and both `Path` values were unchanged. If anyone
    needs Spyder again: `conda install spyder` in miniconda, or
    `uv tool install spyder`.
  - `conda clean --all` on 2026-10-08 cut the package caches from 6.5 GB to
    3.1 GB. The orphaned `%APPDATA%\Python\Python37` user site (left by
    Anaconda's 3.7) was deleted the same day.
  - `~\.condarc` mixes Anaconda's `defaults` channel with `conda-forge`.
    Anaconda's terms may require a paid licence for large organisations; Tony
    has not decided whether to switch to conda-forge only.

## Git

Git **2.22.0** (2019) is at `C:\Program Files\Git\cmd\git.exe`. That folder
was added to the machine `Path` on 2026-10-08; before that, bare `git` failed
over SSH.
GitHub Desktop 3.6.5 bundles its own git under
`%LOCALAPPDATA%\GitHubDesktop\app-3.6.5\resources\app\git`. The user `Path`
had a broken `C:\Users\hel;` entry. It was removed in the 2026-10-08
`Path` cleanup, which also dropped missing AMD entries, an empty entry and
same-scope duplicates. Both old values are backed up in
`C:\ProgramData\uv-setup-backup\`. New SSH logons pick up `Path` changes;
an already-open session does not.

Remotes are the **reverse of Tony's Mac**: `origin` is `HeBECANU/HeLab` and
`upstream` is `TonyXTYan/HeLab`.

## SSH gotchas on this box

- `helium` is an administrator, so SSH sessions get an **elevated token** —
  the same trap as [[lab-main-pc-caveats]]. Never launch HeLab, and never
  import `helab.main` (it initializes caches and `QSettings`), over SSH.
  Importing third-party packages to verify a venv is fine.
- GUI apps launched over SSH run in a non-interactive session, are invisible
  on the console desktop, and appear to hang.
- The PowerShell execution policy is `Restricted`. Pass
  `-ExecutionPolicy Bypass` per command instead of changing it.
- The SSH shell is `cmd.exe`.

## Driving it through Maestri

The SSH terminal is a raw shell, so commands go in with
`maestri ask "SSH Lab Side via Tailscale" --raw "...\n"` and are read back with
`maestri check`. `--raw` interprets backslash escapes, so Windows paths get
mangled: `.git\refs` becomes a carriage return and `\v0.0.5a` a vertical tab.
Reliable patterns:

- Run anything non-trivial as Python sent in base64:
  `py -3.12 -c "import base64;exec(base64.b64decode('<b64>'))"`. This avoids
  escaping entirely.
- Redirect long output to `%TEMP%\x.txt`, echo a marker, poll `check` for the
  marker, then `type` the file. The terminal scrollback is only one screen
  deep.

## RGA data on this box

- The lab's `RGAData` share lives at `C:\Users\helium\Documents\RGAData`, with
  `Analog/` (432+ sweep files), `Histogram/`, `LeakTest/` and
  `PressurevsTime/`. The README's default `/Volumes/100.123.123.201*` path is
  macOS-only and does not resolve on Windows.
- The RGA visualiser parses only mass-sweep files. `LeakTest/` and
  `PressurevsTime/` use `mode: 4` configs with no
  `startMass`/`stopMass`/`pointsPerAmu`, so `_expected_points` in
  `side_projects/rga_visualiser/rga_visualiser.py` rejects them. Both folders
  hold recent data; supporting them is unimplemented work, not a bug.
