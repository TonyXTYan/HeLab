# DLD front panel port: coordinator register (2026-10-20, Claude, cloud)

Coordinator: one cloud session on `agent/dld-front-panel-port` (base 1231025,
`dev/v0.0.6`), with worker and reviewer subagents in git worktrees, following
[agent-workflow](../../../roadmaps/agent-workflow.md). Tony was asleep; nothing was
merged (the session's permission check refused merges without review), so
each task is its own pushed branch, reviewed and fixed, for Tony to land.
Plan: [roadmaps/dld-front-panel-port.md](../../../roadmaps/dld-front-panel-port.md).

## Branches (all pushed to TonyXTYan/HeLab, none merged)

| Branch | Base | Final | What | Review rounds |
|---|---|---|---|---|
| `agent/dld-f0a` | 1231025 | e7d0aba | F0 numerics: `physics.py` constants table + `resolve`, `fits.py` (bounded fits ± SE, Poisson ML weights, Gaussian/TF/bimodal), `estimates.py` (± formatting, pooled stats, sewm) | 2 (bimodal inventing a condensate; R/σ cap made an option) |
| `agent/dld-f0b` | e7d0aba | 1a56108 | F0 three levels: Settings › Lab parameters; folder constants in a new `folder_constants` store table (helpers only); plot overrides (`constant_layers.py`); resolved at submit; "constants changed" mark | 3 (session-only values never saved; failed auto-save wiped values) |
| `agent/dld-d1` | e7d0aba | e4a9abd | Fits on "T, X, Y histograms" (off by default): arrival-time model, rates per shot, smoothing, X/Y mm, T ms/s, fit record (`AnalysisResult.found`) | 3 (smoothed-fit SEs 4× too small; gating on old SEs) |
| `agent/dld-d3` | 1231025 | 2790741 | "Density images" XY/XT/YT | 1 (colour compression lost below 1/256 of max) |
| `agent/dld-d5-d6` | 1231025 | 2a3bbfb | "Mean X, Y against T" and "T spectrum" with peak lists (`spectrum.py`, `display_units.py`) | 3 (power-mode noise peaks; sidelobe rule dropped real lines) |
| `agent/dld-d7` | 1231025 | 597a89b | Shot times from raw `d<N>.txt` mtimes through helper, cache (`datasets.raw_times` column) and `DatasetView`; "Shot times" plot | 2 (Log gaps drawn as exponents; stale times on a copied-over run) |
| `agent/dld-d8-d10` | e7d0aba | f0e8512 | Numerics only: `velocity.py` (z up), `release.py` (release time from one cloud, plus `bootstrap_release_time`), `peaks.py`, `bootstrap.py` (over shots) | 1 (sparse clouds missed; hand-set fall time gave v_z ≠ 0 at rest; unusable bootstrap SE reported ok) |

Every final head ran the full suite (`-n 2 --reruns 5 --reruns-delay 1`) with only
the two tests that fail as root: `test_constants.py::test_read_only_saved_folder_is_replaced`
and `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`
(the container runs as root, which ignores chmod). mypy --strict and pyright clean.
Not checked here: macOS/Windows UI, the lab volume, SMB timing.

## Suggested landing order and expected conflicts

`git merge-tree` on the pushed heads:

1. `agent/dld-f0a`, then `agent/dld-f0b` (clean on f0a).
2. `agent/dld-d7` (clean with f0b, d1, d3).
3. `agent/dld-d1`: conflicts with f0b in `helab/analysis/results.py` and
   `ScriptTreeSelector._show_content` (keep both). Then make D1 declare
   `constant_keys` / use `constants_specs` and drop D1's own "Constants:" record
   lines, as f0b's handoff writes out; otherwise D1's reuse_key and the
   "constants changed" mark don't cover it.
4. `agent/dld-d3`, `agent/dld-d5-d6`: list-only conflicts with d7 and each other in
   `helab/scripts/standard/__init__.py`, `tests/test_analysis.py`,
   `tests/test_live_plots.py`, `tests/test_script_system.py` (keep every entry).
   d5-d6 also conflicts with d1/f0b in `scripts/base.py` and
   `ScriptTreeSelector.py`: its `result_record` copies D1's, so keep one copy
   (D1's, which reads `found`).
5. `agent/dld-d8-d10` (new files only).

After merging, unify the display units in `helab/analysis/display_units.py` (D1's
`profiles.display_unit`, D3's `time_unit` copy), once Tony picks the T rule.

## Decisions for Tony

Cross-branch (answer once):
- **T in ms or s.** D1: ms while the range spans < 1 s; D3/D5/D6: ms while both
  ends are < 10 s. The lab's 20.4–20.6 s window is ms in D1, s in the others.
- **X/Y rates per mm per shot** (D1, D3) vs the roadmap's "per m".
- **Existing plots and View-range bounds** still in s/m; only new axes are mm/ms.
- **Live rerun policy:** D3, D5/D6 at most every 2 s; D1, D7 every shot.
- **D1 placement:** fits as an option on the existing histograms (built so), not a
  separate plot.
- **Open decision 5** built as suggested: amber "constants changed: Rerun".

Physics and statistics (proposed, with reasons in each branch's notes):
- TF exponent p = 2 on every full T/X/Y histogram (3/2 only for a slice): corrects
  the review notes.
- Fits default to Poisson maximum likelihood (plain √n weights biased widths low).
- Bimodal R/σ_th cap default 2 (μ ≤ 2k_BT), with a "TF radius at its limit" note;
  cold clouds need it raised (proposed as a D4 setting).
- He* mass = He-4 atomic mass 4.00260325413 u (not the standard atomic weight).
- Fall-time rule: a hand-set fall time counts only at the distance's layer or
  more specific; disagreement > 0.1 % noted. D1's arrival model and D8's
  velocities use h and g; D8 (after review) uses h_eff = ½ g t_f² when t_f is
  hand-set.
- Smoothed-curve fits smooth the model too (honest sandwich SEs); refused when
  σ_s > range/5.
- Release time: tallest peak, Gaussian centre ± within-run SE, labelled so; the
  shot bootstrap (`bootstrap_release_time`) gives the honest error with shot jitter
  and is recommended wherever an error is shown; wide-cloud skew noted, not corrected.
- Bootstrap defaults: 1000 resamples, seed 0, 68.27 % percentile interval.
- D6: Hann window, power = amplitude², sinc binning correction, peaks ≥ 4× median
  prominence. D5: Hann (notes said Hamming), SD only.
- Recoil wavelength 1083.331 nm as a proposed lab constant (unconfirmed).

Data and storage:
- D7: a shot keeps its raw time only while its TXY fingerprint is unchanged
  (coordinator's call, reversing the worker's first proposal).
- D7: `datasets.raw_times` column added to store-v3 on open (no layout bump); an
  older HeLab's save resets it to `[]`, refilled on the next listing load.
- F0b: folder constants inherit from the nearest folder at or above, up to the data
  root; never cleared by Clear all/purges/clear_root; newest `set_at` wins (a clock
  stepping back can lose a new choice); "It's a copy…": should the new-UUID side
  copy the constants?
- D7 plots shots with zero events at 0 instead of the shared empty note.

## For Tony to check by hand

Each branch's `handoff.md` has the full on-screen checklist. Highest value:
- D7 on the lab share: I/O trace shows one `load: shot time` per raw file on an
  uncached load and none on a cached reload or an unchanged Live check; time a
  ~10k-shot first load with and without the branch (proposed MANUAL_TODO entry).
- D3: compare the XY orientation with the old front panel's 2D plot
  (`legacy/DLD_front_panel` isn't checked out in the cloud).
- D1: temperatures on a real thermal cloud and a BEC; Gaussian vs arrival-time.
- D6: peaks at the pulse rate and mains harmonics on real data.
- F0b: Lab parameters tab and Folder constants dialog on macOS; values survive a
  restart.
- Everything paints on the Lab Side PC.

## Also found

- `tests/test_cache_tab.py::test_saves_restored_from_the_store_ask_with_its_numbers`
  fails (all reruns) when `tests/test_io_trace.py::test_a_live_save_keeps_dont_cache_and_the_budget`
  runs earlier on the same xdist worker: a leftover pending save in the shared
  test store. Pre-existing; offered as a separate task.
- In a worktree, bare `pytest` tests the main checkout (the editable install);
  `python -m pytest` tests the worktree. `tests/test_typing.py` needs the venv's
  `bin` first on PATH (a system mypy without NumPy fails it).
- Cloud sessions run as root: QtWebEngine needs `QTWEBENGINE_DISABLE_SANDBOX=1`.

## Not started

D2 (trends and low-count notice: needs D1 + D7 merged), D4 + D14 (BEC fits and
properties: on F0a/D1), D9 + D15 (masks and the placeholder hot-spot finder:
touches shared selection code), D8's plot axes and release-time row, D11, D12, D13.
