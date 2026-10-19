# Handoff: D5 and D6 (2026-10-20, Claude, Worker)

Branch `agent/dld-d5-d6` from `1231025`, not pushed or merged. Choices proposed for Tony:
[notes.md](notes.md#choices-proposed-for-tony).

## Done

- **Mean X, Y against T** (D5, `helab/scripts/standard/mean_position.py`): per T bin, the mean
  and SD of X and Y in mm with standard errors over the chosen shots; bins under the minimum
  events are gaps, counted; optional spectrum of the mean-position traces with a peak list.
- **T spectrum** (D6, `helab/scripts/standard/t_spectrum.py`): the summed T profile (kHz per
  shot or counts) and its windowed amplitude/power spectrum, log axis, zero padding, and the
  top N peaks (frequency, value, prominence) marked, listed and kept in the result.
- Shared helpers in new files: `helab/analysis/spectrum.py`, `helab/analysis/display_units.py`.
- One additive hook: `DatasetAnalysis.describe_result` (base.py), appended to the dock's
  settings line by `AnalysisInstance._show_content` (one line in ScriptTreeSelector.py).
- Registered in `helab/scripts/standard/__init__.py`; the shared tests list both.

## Checks

- `tests/test_mean_position.py`, `tests/test_t_spectrum.py`: 27 tests (synthetic slosh and
  pulse-rate modulation, Nyquist/resolution, windows, units, power, padding, empty and short
  cases, cancellation, update in place).
- Shared: `test_analysis.py`, `test_script_system.py`, `test_live_plots.py` (both plots in
  the coverage, empty-plot and Live-policy tests, plus a Live update-in-place test that also
  checks the dock line).
- `mypy helab tests --strict`: clean (151 files). `pyright helab tests`: 0 errors.
  `git diff --check`: clean.
- Full suite (`-n 2 --reruns 5 --reruns-delay 1`, venv on PATH): `2 failed, 1314 passed, 7 skipped,
  2 xfailed, 10 rerun in 182.83s`. The 2 failures (and all 10 RERUNs, 5 each) are the known
  root-only tests `test_constants.py::test_read_only_saved_folder_is_replaced` and
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`; no other test
  needed a rerun. (A first run without the venv on PATH also failed the 4 `test_typing.py` mypy
  tests: the system mypy saw PyQt6 as untyped; with the venv's mypy they pass.)

## On-screen checks for Tony

1. Scripts panel → Basic plots v1 lists "Mean X, Y against T" and "T spectrum" between the
   histograms and Transfer fractions.
2. Mean X, Y against T on a real folder: T axis in ms, means/SDs in mm with error bars,
   gaps where bins are sparse and the note saying how many; the dock's second line ends with
   "T bins … (auto)". Turn on Spectrum: a third panel, the peaks listed under it.
3. T spectrum on a real folder: the profile (kHz per shot) and spectrum; the dock line ends
   "T bins … (auto: ~10 events per bin) · Δf … · Nyquist …". Do the listed peaks match the
   pulse rate and known noise (50 Hz harmonics)? Try Peaks above to skip the cloud's shape.
4. Zoom either plot, then let Live add a shot: the zoom stays. Toggle Log: drawn anew.
5. A large folder: the auto-crop's time and how the 16,384-bin profile draws.
6. Decide on the proposals in notes.md (auto bin rules, Hann default, gaps filled by lines,
   SD only, power = amplitude², peak threshold 4× median).

## Proposed doc changes (not made: AGENTS.md and roadmaps are off limits here)

- AGENTS.md, Script system: after Transfer fractions, a sentence: "**Mean X, Y against T**
  (`mean_position.py`, D5) and **T spectrum** (`t_spectrum.py`, D6) bin T in their view range;
  spectra use `helab/analysis/spectrum.py` (`fft_tx` normalisation, peaks by prominence). A
  script's `describe_result` adds what a run found (an automatic bin width, a spectrum's Δf and
  Nyquist) to the dock's settings line." And mention `display_units` (mm, T ms/s).
- `roadmaps/dld-front-panel-port.md` / `_readme.md`: D5 and D6 built (pending Tony's review).
- At merge with `agent/dld-d3`: `density_images.time_unit` can import
  `display_units.time_unit` (identical rule); MODULES and the shared test lists conflict
  trivially (keep every plot).
