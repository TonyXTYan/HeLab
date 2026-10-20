# Handoff: D5 and D6 (2026-10-20, Claude, Worker)

Branch `agent/dld-d5-d6` from `1231025`, not pushed or merged. Choices proposed for Tony:
[notes.md](notes.md#choices-proposed-for-tony); the Coordinator's review of `645c8cb` and
what changed: [notes.md](notes.md#review-coordinator-645c8cb-and-what-changed), and the
re-review of `2c1929e`: [notes.md](notes.md#re-review-coordinator-2c1929e-and-what-changed).

## Done

- **Mean X, Y against T** (D5, `helab/scripts/standard/mean_position.py`): per T bin (a last
  partial one kept for the traces),
  the mean and SD of X and Y in mm with standard errors over the chosen shots; bins under the
  minimum events are gaps, counted; optional spectrum of the mean-position traces (gaps filled
  up to 20 %, else the longest stretch without gaps, else none) with a peak list.
- **T spectrum** (D6, `helab/scripts/standard/t_spectrum.py`): the summed T profile (kHz per
  shot or counts, whole bins) and its windowed amplitude/power spectrum, corrected for the
  bins' averaging, log axis, zero padding, and the top N peaks (frequency, value, prominence)
  marked, listed, in the dock's record and in the result.
- Shared helpers in new files: `helab/analysis/spectrum.py` (normalisation, binning
  correction, ENBW, peaks on the unpadded amplitude with a sidelobe test and a log parabola,
  whole bins), `helab/analysis/display_units.py` (the shared home for display units).
- Two additive hooks on `DatasetAnalysis` (base.py), for completed results only:
  `describe_result` (end of the dock's settings line) and `result_record` (lines of the
  dock's record), the latter **identical to `agent/dld-d1`'s** (signature, docstring, place,
  and the three lines in `ScriptTreeSelector._show_content`), so the merge keeps one copy.
- Registered in `helab/scripts/standard/__init__.py`; the shared tests list both.

## Checks

- After the re-review fixes: `tests/test_mean_position.py` (13) and `tests/test_t_spectrum.py`
  (39) with `test_analysis.py`, `test_live_plots.py`, `test_script_system.py`
  (`-n 2 --reruns 5 --reruns-delay 1`): `175 passed in 13.86s`, no RERUN. (After the first
  review: 168 passed, no RERUN; `test_typing.py` with the venv first on PATH: 6 passed.)
- `mypy helab tests --strict` (the venv's): clean, 151 files. `pyright helab tests`: 0 errors.
  `git diff --check`: clean.
- The Coordinator's full suite on `2c1929e`: clean except the root-only pair, one rerun of
  `test_scatter_from_the_panel`.
- Full suite on `645c8cb` (before the review fixes; `-n 2 --reruns 5 --reruns-delay 1`, venv
  on PATH): `2 failed, 1314 passed, 7 skipped, 2 xfailed, 10 rerun in 182.83s`. The 2
  failures (and all 10 RERUNs, 5 each) are the known root-only tests
  `test_constants.py::test_read_only_saved_folder_is_replaced` and
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`. (A first run
  without the venv on PATH also failed the 4 `test_typing.py` mypy tests: the system mypy saw
  PyQt6 as untyped.) Not rerun in full after the review fixes, which touch only these plots,
  their helpers and the two hooks (the Coordinator asked for the targeted set).

## On-screen checks for Tony

1. Scripts panel → Basic plots v1 lists "Mean X, Y against T" and "T spectrum" between the
   histograms and Transfer fractions.
2. Mean X, Y against T on a real folder: T axis in ms, means/SDs in mm with error bars,
   gaps where bins are sparse and the note saying how many; the dock's second line ends with
   "T bins … (auto: ~100 events per bin)". Turn on Spectrum: a third panel, the peaks listed
   under it; the dock's tooltip lists the bins and peaks.
3. T spectrum on a real folder: the profile (kHz per shot) and spectrum; the dock line ends
   "T bins … (auto: …) · bin spacing Δf …, resolution ≈ … (ENBW 1.5), Nyquist …". Do the
   listed peaks match the pulse rate and known noise (50 Hz harmonics)? Try Peaks above to
   skip the cloud's shape. Is the noise floor's rise towards Nyquist (the binning correction)
   acceptable on the plot?
4. Zoom either plot, then let Live add a shot: the zoom stays. Toggle Log: drawn anew.
5. A large folder: the auto-crop's time and how the 16,384-bin profile draws.
6. Decide on the proposals in notes.md (auto bin rules, Hann default, gap limit 20 %, SD only,
   power = amplitude², the binning correction, peak threshold 4× median, the sidelobe test).

## T's display unit: three rules on three branches (for Tony to choose)

- D3 (`agent/dld-d3`, `density_images.time_unit`) and these plots
  (`display_units.time_unit`): **ms while both ends of the range are under 10 s**, else s
  (by value: T after the trigger is typically 0.3–0.5 s).
- D1 (`agent/dld-d1`, `profiles.display_unit`): **ms while the range spans under 1 s**, else s
  (by span).
- So a range 20.40–20.45 s is in ms for D1 and in s for D3/D5/D6. Whichever Tony picks, one
  function in `helab/analysis/display_units.py` (the shared home) should serve all plots.

## Proposed doc changes (not made: AGENTS.md and roadmaps are off limits here)

- AGENTS.md, Script system: after Transfer fractions, a sentence: "**Mean X, Y against T**
  (`mean_position.py`, D5) and **T spectrum** (`t_spectrum.py`, D6) bin T in whole bins of
  their view range; spectra use `helab/analysis/spectrum.py` (`fft_tx` normalisation divided by
  the bins' sinc, peaks found on the unpadded amplitude, by prominence). A script's
  `describe_result` adds what a run found (an automatic bin width, a spectrum's bin spacing,
  resolution and Nyquist) to the dock's settings line, and `result_record` lines to its
  record." And mention `display_units` (mm, T ms/s).
- `roadmaps/dld-front-panel-port.md` / `_readme.md`: D5 and D6 built (pending Tony's review).
- At merge with `agent/dld-d3`: `density_images.time_unit` can import
  `display_units.time_unit` (identical rule); with `agent/dld-d1`: `result_record` in
  `base.py` and its three lines in `ScriptTreeSelector._show_content` duplicate D1's, so keep a
  single copy;
  MODULES and the shared test lists conflict trivially (keep every plot).
