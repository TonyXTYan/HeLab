---
date: 2026-08-20
status: settled
name: lab-main-pc-caveats
description: "Lab Main PC: Python 3.11 stdlib is corrupted (use the 3.12 venv), and launching HeLab over SSH poisons its cache settings"
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

## Use the 3.12 venv; never Python 3.11

Working setup, installed 2026-08-20:

- **Python 3.12.10**, per-user at
  `C:\Users\BEC Machine\AppData\Local\Programs\Python\Python312\python.exe`
- **venv** at `C:\GitHub\HeLab\venv` (pip, all of `requirements.txt`,
  and `pip install -e .`)

It was installed with `winget` using explicit flags so nothing global shifted —
`PrependPath=0 AssociateFiles=0 Include_launcher=0 Shortcuts=0
InstallAllUsers=0`. Consequences to remember: bare `python` is still **Python
3.6.1**, and `py -0p` does **not** list 3.12. Always use the full path or
`venv\Scripts\python.exe`.

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
and Anaconda 3.9.18 (two installs).

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

**Latent code bug behind all this:**
`get_path_from_setting_or_use_default` in `helab/utils/constants.py` validates a
stored path with `os.path.exists(value)` only. Adding
`os.access(value, os.W_OK)` would make HeLab fall back to a fresh temp dir
instead of crashing at import with an error that names neither the directory
nor the permission problem.

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
