# DLD front panel port: coordinator register (2026-10-20, Claude, cloud)

Coordinator: one cloud session on `agent/dld-front-panel-port` (base 1231025,
`dev/v0.0.6`), with worker and reviewer subagents in git worktrees, following
[agent-workflow](../../../roadmaps/agent-workflow.md). Each task was its own branch,
reviewed and fixed, then merged into `agent/dld-front-panel-port` (merges approved
by Tony, 2026-10-20). Nothing is merged into Tony's own branches or `main`.
Plan, what is built and the open decisions:
[roadmaps/dld-front-panel-port.md](../../../roadmaps/dld-front-panel-port.md);
hand checks: [MANUAL_TODO](../../MANUAL_TODO.md#dld-front-panel-port-added-2026-10-20).

## Branches (all merged into `agent/dld-front-panel-port`)

In merge order; "Head" is the branch commit merged, "Merge" the merge on the port
branch. Every branch's `handoff.md` and `notes.md` are in
`.ai/sessions/2026-10-20-claude-dld-<id>/`.

| Branch | Head | Merge | What |
|---|---|---|---|
| `agent/dld-f0a` | e7d0aba | 78a0fa3 | F0 numerics: `physics.py` table and `resolve`, `fits.py`, `estimates.py` |
| `agent/dld-f0b` | 1a56108 | a87b972 | F0 three levels: Lab parameters, `folder_constants`, plot overrides, "constants changed" |
| `agent/dld-d7` | 597a89b | 99e18b0 | Shot times from raw `d<N>.txt` mtimes; `datasets.raw_times`; Shot times plot |
| `agent/dld-d1` | e4a9abd | e95fccd | Fits on the T, X, Y histograms; `profiles.py`; `AnalysisResult.found` |
| `agent/dld-d3` | 2790741 | 7db518f | Density images XY/XT/YT |
| `agent/dld-d5-d6` | 2a3bbfb | 543fc5d | Mean X, Y against T; T spectrum; `spectrum.py` |
| `agent/dld-d8-d10` | f0e8512 | fb47de7 | `velocity.py`, `release.py`, `peaks.py`, `bootstrap.py` |
| `agent/dld-store-fixes` | 236ec34 | e3a07fc | `_migrate` on every writable open; atomic root re-keys; quit waits for flags/constants |
| `agent/dld-decisions` | f937eb9 | 6a9671e | Tony's decisions: ms/mm with grouping, both TF exponents, D1 on the constants API, `memory_raw_times` |
| `agent/dld-physics-fixes` | 157686b, 1c32b26 | 1f01f08, 6ed1ec9 | Arrival-time release fit, offset ≥ 0, bin-averaged fits, `edges=`, robust XY origin, `shot_means` |
| `agent/dld-polish` | 9567786 | 3957415 | Wrapped titles, one amber, in-place updates, newest shot on more plots |
| `agent/dld-d12-numerics` | 26fc2e3, 6bd78a4 | 71f7bba, 52386ec | `correlations.py` (g², BB, Live pair counts, honest g²(0) errors) |
| `agent/dld-d2` | 1df21b8 | c0c9493 | Shot trends; `trends.py`; events hub `helab/utils/events.py` |
| `agent/dld-d4-d14` | 7d76628 | 71302e4 | Bose fits, condensate decision, `bec.py` |
| `agent/dld-d9-d15` | 60bad77 | 7fa394f | Mask group on every event plot; Find hot spots placeholder |
| `agent/dld-d8-release` | 206d69c | 7ff350b | Optional constants; Release time plot (Use for this folder…) |
| `agent/dld-d8-velocity` | 335d2d1 | dbc79bf | Velocity distributions plot; `recoil_wavelength` row |
| `agent/dld-d4-wiring` | b24d435 | e14843f | Condensate decisions and BEC properties on the histograms; `bec_readout.py` |
| `agent/dld-docs` | (this commit) | | AGENTS.md, the plan, `_readme.md`, MANUAL_TODO, this register |

Still open: `agent/dld-d12-plot` (the Correlations plot, D12/D13), being finished
from 7ff350b. TODO(docs): add its row and its checks once it merges.

Each final head ran the full suite (`-n 2 --reruns 5 --reruns-delay 1`); the only
failures were the two tests that fail as root
(`test_constants.py::test_read_only_saved_folder_is_replaced`,
`test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`: the
container runs as root, which ignores chmod), and every other rerun is named in its
handoff. mypy --strict and pyright clean. Not checked here: macOS/Windows UI, the lab
volume, SMB timing, real data.

## What Tony should check first

1. **Look on macOS:** open a run, then T, X, Y histograms (Fits on), Density images,
   Shot times, Shot trends, Release time and Velocity distributions in a narrow dock:
   ms/mm axes with grouped digits, titles wrapped, amber warnings, zoom kept in Live.
   Settings → Lab parameters and right-click › Folder constants….
2. **Lab Side PC paint:** the same plots paint without QtWebEngine.
3. **Real physics:** temperatures on a thermal cloud and a BEC; the condensate
   decision and BEC properties (do the two QE checks agree with 0.1?); Release time →
   Use for this folder… → Velocity distributions with the cloud at rest at v = 0.
4. **D7 on the share:** an I/O trace of an uncached load (one `load: shot time` per
   shot read, none on a cached reload) and the first-load time of a ~10k-shot folder.
5. **Answer the open decisions** in the plan (32, each built as proposed); the
   constants first: fall distance, trap frequencies and axial axis, QE, recoil
   wavelength.

## Tony's decisions (2026-10-20), as built

- T in ms everywhere (axes, titles, records, settings), never s; X/Y in mm; ","
  thousands separators and "." decimals whatever the locale (`1,234.5678 ms`);
  stored values SI.
- Both TF exponents (p = 2 and 3/2) offered, with the caveats in the tooltip.
- Shot times from the `d*` raw files, which are never rewritten: a raw file is
  stat'ed again only when its TXY fingerprint changes.
- Merges of the task branches into `agent/dld-front-panel-port` approved.

Everything else proposed by the workers is an open decision in the plan.

## Also found

- `tests/test_cache_tab.py::test_saves_restored_from_the_store_ask_with_its_numbers`
  fails (all reruns) when `tests/test_io_trace.py::test_a_live_save_keeps_dont_cache_and_the_budget`
  runs earlier on the same xdist worker: a leftover pending save in the shared test
  store. Pre-existing; listed in `roadmaps/_readme.md` Known issues.
- `HelabMainWindow` reads the native QSettings at construction, so tests that build a
  real window see the developer's settings (Known issues).
- `helab/scripts/standard/release_time.py`'s module docstring still says Use for this
  folder… saves t_r and that the bootstrap defaults to 200; the code saves t_a and
  the plot defaults to 100 (`N_BOOT_DEFAULT`).
- In a worktree, bare `pytest` tests the main checkout (the editable install);
  `python -m pytest` tests the worktree. `tests/test_typing.py` needs the venv's
  `bin` first on PATH (a system mypy without NumPy fails it).
- Cloud sessions run as root: QtWebEngine needs `QTWEBENGINE_DISABLE_SANDBOX=1`.

## Not started

D11 (raw-pulse diagnostics, after the TXY converter port) and D13's per-shot halo
centring; the plan's "Left to do on what is built".
