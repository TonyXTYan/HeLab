---
date: 2026-10-08
status: settled
name: lab-main-pc-caveats
description: "Lab Main PC: HeLab runs from a uv Python 3.13 venv; Miniconda replaced Anaconda3 (condabin on PATH); Python 3.11 stdlib is corrupted; launching HeLab over SSH poisons its cache settings"
metadata:
  node_type: memory
  type: result
---
Working notes for the **Lab Main PC** (repo at `C:\GitHub\HeLab`, user profile
`C:\Users\BEC Machine`, Windows 11 build 26100, Skylake CPU, Tailscale
`100.123.123.200`). Distinct from the Lab Side PC — see
[[lab-pc-qtwebengine-black-render]]. This box is modern enough that the Side
PC's QtWebEngine problem does **not** apply: HeLab starts, renders and shuts
down cleanly here.

## Python: the uv venv (set up 2026-10-08); never Python 3.11

Same layout as [[lab-side-pc-caveats]] and [[rspe-office-pc-caveats]]:

- uv 0.12.23 in `C:\Program Files\uv` (from the GitHub release zip; machine
  `Path`), machine-wide `UV_PYTHON_INSTALL_DIR=C:\ProgramData\uv\python`.
- `C:\GitHub\HeLab\venv` = uv-managed **Python 3.13.16** (`uv venv --seed
  --managed-python`, then `uv pip install -r requirements.txt -e .`; 93
  packages, `pip check` clean, imports OK). HeLab was confirmed launching from the
  desktop with `venv\Scripts\helab`; the old 3.12 venv was deleted.
- uv's cache (`%LOCALAPPDATA%\uv\cache`) is hardlinked with the venv, so
  deleting it frees almost nothing.
- Bare `py` defaults to the uv Python via `%LOCALAPPDATA%\py.ini`
  (`python=Astral/CPython3.13`). The Store `python`/`python3` aliases were
  removed. Bare `python`/`pip` are still **Python 3.6.1** (machine `Path`),
  left alone in case lab tools rely on it.
- Same day: the dead per-user Anaconda3 4.2.0 registrations (PEP 514 keys,
  uninstall entry, three user-`Path` entries) were deleted, and the machine
  `Path` lost missing MATLAB R2020a/R2016a and VISA entries, an empty entry
  and duplicates. Backups (`.reg` exports, old `Path` values, run logs) are in
  `C:\ProgramData\uv-setup-backup\`.
- C: was nearly full (0.8 GB free after the rebuild); Tony cleaned it to
  ~25 GB free the same day. `%TEMP%` had ~14.7 GB older than 7 days, 8 GB
  of it 20 leftover OneDrive delta-update folders (GUID names).

**Python 3.11 on this machine is broken and must not be used.** Someone
extracted a Python 3.6 `Lib` tree over the top of it. 975 pre-2020 files
survive under its `Lib\`, including an ancient scikit-learn in its
`site-packages`. Only 18 are in the real stdlib, and most are 3.6-only modules
that 3.11 never imports — but `Lib\asyncio\base_events.py` is a 2017 file that
*overwrites* the genuine one, so `import asyncio` dies with:

```
ImportError: cannot import name 'coroutine' from 'asyncio.coroutines'
```

pip vendors `tenacity`, which imports `asyncio`, so **pip and `ensurepip` are
both dead on 3.11**. (The stale `Lib\re.py` is inert — the real `re/` package
wins the import.) Other interpreters present and unsuitable: 3.6.1, 3.5,
3.12.10 (python.org, per-user).

**conda:** Anaconda3 2022.10 (`C:\ProgramData\Anaconda3`, envs `HeLab` and
`py311`) was removed by Tony on 2026-10-08. Its uninstaller failed, so the
folder was deleted by hand. Its leftover registry keys (PEP 514
`ContinuumAnalytics\Anaconda39-64` and `PythonCore\3.9`, the uninstall
entry), Start Menu folder, `~\.conda\environments.txt` and
`%LOCALAPPDATA%\conda` were then removed, with backups in
`C:\ProgramData\uv-setup-backup\anaconda-leftovers-*`. **Miniconda**
(conda 26.7.1, base Python 3.14.7) replaced it the same day: all users,
`C:\ProgramData\miniconda3`, installed with `/RegisterPython=0
/AddToPath=0` and no `conda init`, so bare `py` still runs uv's 3.13.
Only `C:\ProgramData\miniconda3\condabin` (conda.bat and activate scripts,
no python.exe) is on the machine `Path`, so `conda` works in any shell incl.
SSH. `conda activate` in PowerShell still needs `conda init powershell`
(not run); `conda run -n <env>` or the Start Menu prompts work without it. Channels are
`defaults` then `conda-forge` (from `~\.condarc`, Tony's choice). Anaconda's
Terms of Service for `repo.anaconda.com/pkgs/{main,r,msys2}` were **not**
accepted by Claude; whoever first uses `defaults` must run `conda tos
accept` (or switch to conda-forge only).

## Never launch HeLab over SSH — it poisons the desktop session

This is the big one, and it cost hours.

Windows OpenSSH gives a user in the Administrators group an **elevated token**,
so everything run over SSH is effectively "as admin". At import,
`helab/utils/constants.py` does `tempfile.mkdtemp(prefix='helab_caches_')` and
then `get_path_from_setting_or_use_default` writes the result into `QSettings`
(`HKCU\Software\ANU_HE_BEC_GROUP\HeLab`, values `dir_temps` and `dir_caches`).

Directories created by the elevated SSH process get owner
`BUILTIN\Administrators`, even though the parent `Temp` folder is owned by the
user. Every later **normal** double-click reads those stored paths back, passes
the `os.path.exists()` check, then fails to write, and the app dies at import
before any window appears:

```
sqlite3.OperationalError: unable to open database file
  diskcache/core.py -> sqlite3.connect(...)
  helab/utils/caching_setup.py:95  status_cache = FanoutCache(DIR_CACHES + '/status_cache', ...)
```

Running as administrator appears to fix it — the tokens then match — but each
elevated launch **re-poisons** the settings for normal launches. Don't.

**Recovery** (delete the dirs and the two stored paths, then launch
non-elevated so they are recreated user-owned):

```
rmdir /s /q "C:\Users\BEC Machine\AppData\Local\Temp\helab_caches_<suffix>"
rmdir /s /q "C:\Users\BEC Machine\AppData\Local\Temp\helab_temps_<suffix>"
reg delete "HKCU\Software\ANU_HE_BEC_GROUP\HeLab" /v dir_caches /f
reg delete "HKCU\Software\ANU_HE_BEC_GROUP\HeLab" /v dir_temps /f
```

Two diagnostics worth knowing:

- `(Get-Acl $dir).Owner` — `BUILTIN\Administrators` means an elevated process
  made it; the user's name means a normal launch did.
- The stored path's form tells you which session created it. The interactive
  desktop session's `%TEMP%` is the 8.3 short form
  (`C:\Users\BECMAC~1\AppData\Local\Temp`); an SSH session's is the long form
  (`C:\Users\BEC Machine\...`).

**Code bug behind all this — fixed 2026-10-08:**
`get_path_from_setting_or_use_default` used to accept any existing stored path.
It now writes a probe file (`usable_directory`; `os.access` would not do, it
ignores Windows ACLs) and falls back to `%LOCALAPPDATA%\HeLab\caches`, so a
poisoned path no longer crashes at import. Defaults also moved out of `Temp`
then: a launch renames an old `Temp\helab_caches_*` folder to
`%LOCALAPPDATA%\HeLab\caches` (an admin-owned one fails to rename, logs a
warning and is skipped). Launching over SSH is still a bad idea — an elevated
launch could create an admin-owned `%LOCALAPPDATA%\HeLab` too; HeLab would then
fall back to `Temp\helab_caches`.

## Shortcuts

`.lnk` files in the repo (untracked; they hardcode `C:\GitHub\HeLab`):

| Shortcut | Target | Arguments |
|---|---|---|
| HeLab | `venv\Scripts\helab.exe` | — |
| `side_projects\rga_visualiser\RGA Compare.lnk` | `venv\Scripts\python.exe` | `-m side_projects.rga_visualiser.rgadata_compare <RGAData folder>` |
| `side_projects\rga_visualiser\RGA Difference.lnk` | `venv\Scripts\python.exe` | `-m side_projects.rga_visualiser.rgadata_diff` |

All three need **Start in = `C:\GitHub\HeLab`**, including the two that live in
the sub-folder, because the tools are invoked as `-m side_projects...`.
`helab.exe` is a `console_scripts` entry point, so a console window always
accompanies the GUI; there is no `gui_scripts` variant. `helab.exe` also
ignores `--help` and just launches.

## RGA data paths from this machine

The lab's RGA data lives on the **Lab Side PC** (Tailscale `100.123.123.201`),
under `C:\Users\helium\Documents\RGAData`. From the Lab Main PC it is reachable
as the mapped drive `H:` or by UNC to that host's `c` share.

Caveats:

- Mapped drives are **per-logon-session**. `net use` over SSH lists every drive
  as `Unavailable`, and an **elevated** process gets its own (empty) mappings,
  so `H:` silently fails to resolve under "Run as administrator".
- UNC access from an SSH session fails with *"The user name or password is
  incorrect"* — an SSH logon does not inherit the interactive session's cached
  network credentials. Share access can only be tested from the desktop.
- `_detect_default_rgadata_folder()` in
  `side_projects/rga_visualiser/rgadata_compare.py` globs `/Volumes/...` and is
  macOS-only, so on Windows it never resolves. `rgadata_compare` accepts a
  folder as a positional argument; `rgadata_diff` has **no** folder option —
  it only takes two file paths, and its pickers fall back to the unresolvable
  `DEFAULT_RGADATA_FOLDER`.

## Shell gotchas on this box

- `winget` must be given `--source winget`. The `msstore` source fails with
  `0x8a15005e : The server certificate did not match any of the expected
  values`, which aborts an otherwise valid install.
- `cmd.exe` expands `%errorlevel%` **at parse time**, before the command runs
  and regardless of quoting — including inside a single-quoted PowerShell
  argument. So `... & echo RC=%errorlevel%` reports the *previous* command's
  code, and generating a `.bat` this way bakes in a literal `0`. Write a
  placeholder and `-replace` it with `[char]37`.
- GUI apps launched over SSH run in a non-interactive session, are invisible on
  the console desktop, and appear to hang.
