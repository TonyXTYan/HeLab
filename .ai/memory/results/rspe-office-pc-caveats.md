---
date: 2026-10-08
status: settled
name: rspe-office-pc-caveats
description: "RSPE office PC (RSPE-064759, user XinTong): HeLab runs from a uv Python 3.13 venv; every py-launcher Python belongs to the GitHub Actions runners; the old venv imported a stale D: checkout"
metadata:
  node_type: memory
  type: result
---
Working notes for Tony's **RSPE office PC** (host `RSPE-064759`, user
`XinTong`, Windows 11 build 26200, i7-11700, repo at
`C:\Users\XinTong\git_repos\HeLab`). Not the Lab Side PC (`RSPE-050184`, see
[[lab-side-pc-caveats]]). Maestri terminal: "SSH RSPE via TailScale"; the same
SSH caveats apply (elevated token, `cmd.exe`, `--raw` mangles backslashes, send
base64 Python — see [[lab-side-pc-caveats]] and [[lab-main-pc-caveats]]).
Remotes match Tony's Mac: `origin` is `TonyXTYan/HeLab`, `HeBECANU` is the lab
repo.

## Python: the uv venv (set up 2026-10-08)

Same layout as the Lab Side PC:

- uv 0.12.23 in `C:\Program Files\uv` (machine `Path`), machine-wide
  `UV_PYTHON_INSTALL_DIR=C:\ProgramData\uv\python`. Previous `Path` values are
  in `C:\ProgramData\uv-setup-backup\`.
- `astral.sh/uv/install.ps1` failed here (`releases.astral.sh` did not resolve
  from PowerShell, though `nslookup` worked), so uv came from the GitHub release
  zip (`uv-x86_64-pc-windows-msvc.zip`). `uv python install` itself worked.
- `venv` = uv-managed **Python 3.13.16**, built with `uv venv --seed
  --managed-python`, then `uv pip install -r requirements.txt -e .` (93
  packages, `pip check` clean, imports OK, `helab` resolves to this repo).
- The Store `python`/`python3` aliases for XinTong were removed.
- Bare `py` defaults to the uv Python via XinTong's
  `%LOCALAPPDATA%\py.ini` (`[defaults]` `python=Astral/CPython3.13` — a tag
  prefix, so it survives uv patch upgrades). `py -3.13` still picks the
  runner's PythonCore 3.13.0; use `py -V:Astral/CPython3.13` to be explicit.
- HeLab was confirmed launching from the desktop with `venv\Scripts\helab`.

## What was wrong before

- The old venv (renamed, then deleted by Tony on 2026-10-08) was copied
  from `D:\git repos\HeLab`: its editable install and `helab.exe` both pointed
  at that **Dec 2024 `dev` checkout** (`d4f9f57`, 3 uncommitted edits — left
  untouched), and it lacked 11 requirements. Its base Python was a runner's.
- There is **no standalone Python**. Everything `py -0p` lists (3.9–3.13.0,
  HKLM PEP 514) is a GitHub Actions tool-cache install under
  `D:\github-action-runners\instance*\_work\_tool`, and `py` defaulted to the
  runner's 3.13.0 until the `py.ini` above. Never build a venv on those — a runner can replace them.
  The runner 3.10.11 (instance5) fails to start (0xc0000135).
- Six self-hosted runners (`RSPE-064759-1..6`, `TonyXTYan/HeLab`) are
  registered, but on 2026-10-08 none were running and Docker Desktop's engine
  was down.

## Other environments

Per-user Miniconda (`~\miniconda3`, conda 23.1.0, base 3.10.13; envs `py311`,
`py311_he34sim`, `open-webui`, plus one under `D:\git repos\AI-Horde-Worker`),
not on `Path`. Package cache 11.4 GB, envs ~17 GB, pip cache 8.1 GB — disk is
not short (C: 180 GB free). HeLab's QSettings cache dirs are
`D:/dev_cache/helab_cache` and `helab_temps`.
