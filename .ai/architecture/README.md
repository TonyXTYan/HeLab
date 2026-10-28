# HeLab architecture reference

This folder explains, area by area, how HeLab works: module and function names, mechanics, and
behaviour users see. [`AGENTS.md`](../../AGENTS.md) keeps only the rules every task must follow,
a map, and a link here. Read the file for the area you are about to change.

The text moved here word for word from AGENTS.md on 2026-10-28, when AGENTS.md was cut from
92 KB to rules and a map (Tony asked for it; Codex loads only the first 32 KiB of project
instructions). The full earlier AGENTS.md is `git show 55c9ca1^:AGENTS.md`: the cut is `55c9ca1`
on `dev/v0.0.6`, which `main` holds only inside the squash `9c477c2`.

| File | Covers |
|---|---|
| [io-and-browsing.md](io-and-browsing.md) | `IOService`, `io_helper` and `io_ops`; the three lanes (foreground, background, local), pausing and settling; Work Offline; cache first; I/O traces; files still being written; shot times; slots and timeouts; two-step browsing; folder icons |
| [data-roots.md](data-roots.md) | `.helab-root` markers, location keys, discovery, verification, placing, duplicates, Settings → Data roots, unsupported mounts, remounts |
| [cache-store.md](cache-store.md) | `store-v3` and `CacheStore`; budgets, pending saves, large folders, folder flags and constants, presets, shot times; saved analysis results; store identity; saved listings; cache folders and moving them; folder metadata and scan history; derived status; data loading |
| [live.md](live.md) | Live checks, saves, errors, quitting, plots following Live, notifications |
| [app-runtime-and-ui.md](app-runtime-and-ui.md) | logging and old logs, threading, window resizing, `FolderCache` memory and the RAM budget, the folder tree, Folder details and the status bar |
| [plots-and-scripts.md](plots-and-scripts.md) | scripts and `DatasetAnalysis`, parameters, presets and reopening, results, Transfer fractions, the Settings panel and floating plots, plotting libraries, the Dash server |
| [dld-analyses.md](dld-analyses.md) | the DLD Front Panel Port: constants, shared numerics, units, hooks, saved results, masks, the plots; the legacy MATLAB references (the converter, the front panel, Momentum_Bells_test) |
| [settings.md](settings.md) | QSettings, `app_settings()`, `settings_defaults.py`, lab parameters |
| [testing.md](testing.md) | test isolation, seams and fixtures, reruns, Windows pytest notes |
| [release-and-ci.md](release-and-ci.md) | versioning, build info, release flow, CI matrices |

Keeping it true:

- On Ground, update the area file in the same commit as the code.
- On a floor, propose the change in your handoff; the Coordinator applies it when landing.
- Settled decisions and Tony's exact wording go to `.ai/memory/results/`.
- Feature plans and open decisions go to `roadmaps/`.
- These files describe what the code does now.
