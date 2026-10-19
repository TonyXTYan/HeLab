# Notes: D5 and D6 (2026-10-20, Claude)

## What was built

| File | What |
|---|---|
| `helab/scripts/standard/mean_position.py` | D5, **Mean X, Y against T** (`helab.mean_position_vs_t` v1) |
| `helab/scripts/standard/t_spectrum.py` | D6, **T spectrum** (`helab.t_spectrum` v1) |
| `helab/analysis/spectrum.py` | Windowed one-sided amplitude spectrum (`fft_tx` normalisation), peaks, the window/peak parameter specs |
| `helab/analysis/display_units.py` | mm; T in ms or s by range; SI text (`1.25 kHz`, `50 ns`) |
| `helab/scripts/base.py`, `helab/models/ScriptTreeSelector.py` | `DatasetAnalysis.describe_result`: what a run found, appended to the dock's settings line (one line each) |
| `helab/scripts/standard/__init__.py` | Registration, between the histograms and Transfer fractions |
| `tests/test_mean_position.py`, `tests/test_t_spectrum.py` | The plots' own tests |
| `tests/test_analysis.py`, `test_script_system.py`, `test_live_plots.py` | The shared bundled-plot lists, the Live policy test, and one Live update-in-place test for both |
| `render_plots.py` (here) | Renders both plots on synthetic data to PNGs, offscreen |

Both plots: the shared Shots settings, their own View range (auto-crop by default; the box
applies to T, X and Y, as the Decided section's "box and T window applied first"), X/Y in mm,
T in ms below 10 s else s, no XY rotation, update in place (zoom kept; drawn anew when the
axes change: spectrum on/off, log, power, units, T's unit), Live at most every 2 s (their
auto-crop costs a second or more on a large folder, as the density images'), coverage from
the Shots settings, results as dataclasses of NumPy arrays (counted by the RAM budget's
`arrays_in`), and a note instead of a plot when empty or too short.

## Choices, proposed for Tony

1. **`describe_result` hook (new, additive).** The dock's settings line came only from the
   settings (`describe_run` gets no result), but D6's resolution and Nyquist depend on the
   auto-crop and the automatic bin width, known only after the run. The hook returns "" by
   default; `AnalysisInstance._show_content` appends it. Used for "T bins 25 µs (auto: ~10
   events per bin) · Δf 20 Hz · Nyquist 20 kHz" and D5's "T bins 1 ms (auto) · 3 of 50 bins
   left out · Δf …". They are also in each plot's title.
2. **T's unit:** the density images' rule (ms while both ends are under 10 s), copied into
   `display_units.time_unit` because `density_images.py` is on another branch. At merge,
   `density_images.py` could import it from there (same function).
3. **D5 width = SD** only, with SE = SD/√(2(n−1)) (normal data). A robust σ (1.4826·MAD,
   less sensitive to a hot spot) was considered and left out until hot-spot masks (D9).
4. **D5 automatic bins:** about 100 events per bin on average, 10–1,000 bins; set widths
   are used exactly (the old GUI's came out about 2× wider, legacy bug 5), widened only past
   100,000 bins (a warning). Minimum events per bin: 10 (≥ 2, for an SD).
5. **D5 spectrum:** of the mean X and mean Y traces, from the first kept bin to the last, gaps
   inside **filled by straight lines** (the plot says how many). The review notes suggested
   Lomb–Scargle for uneven samples; with a few gaps, filling keeps one method and the same
   normalisation. Under 8 bins: no spectrum, said so.
6. **Window: Hann by default in both** (the review notes said Hamming for D5; one default
   across plots, and Hann's far sidelobes fall faster, which helps weak peaks near strong
   ones). Choices: Hann, Hamming, Blackman, flat top, none.
7. **Normalisation (`fft_tx`):** mean subtracted, one-sided amplitude `2·|rfft|/sum(window)`
   (DC and Nyquist not doubled): a sine of amplitude A on a bin reads A with every window.
   **Power = amplitude²**, not a density per Hz. A Welch PSD was not built.
8. **D6 automatic bins, from the data rate: ~10 events per bin**, 256–16,384 bins; Nyquist is
   then a twentieth of the summed events' mean rate. First tried one event per bin up to
   65,536 bins: on 200,000 events that put Nyquist at 655 kHz with the interesting kHz band
   squeezed at the left and a profile of pure shot noise. For higher frequencies, set the
   width (up to 2²⁰ bins, then widened with a warning) or narrow the range.
9. **D6 profile units:** rate per shot in kHz (the front panel's kHz/File; Decided section)
   by default, or summed counts; the spectrum is in the same unit.
10. **Peaks:** `find_peaks` above "Peaks above" (Hz, 0 = all; never DC), prominence ≥ 4 × the
    spectrum's median there (a noise-floor estimate: shot noise rarely gets there), at least
    the padding apart, **ranked by prominence**, the top N (D5: 3, D6: 5) marked and listed;
    each refined by a parabola through its bin and neighbours (frequency and value). With
    flat top the parabola places a peak less well (its top is flat): within one bin, tested.
    "Peaks above" lets the cloud's own shape (low frequencies) be skipped.
11. **Log axis on by default** for both spectra (noise floor and weak peaks visible).
12. **Zero padding** ×1–16 (default 1), lowered so the transform stays ≤ 2²² samples (said).
13. **Edges:** bins start at the range's start and are exactly the width; the last one may
    reach past the range's end, so its rate reads low (a small edge effect the window tapers).
    A range with no T extent (equal T) is widened by 0.5 ms each way, as the density images.

## Checks on synthetic data (tests)

- D5: X(T) = 2 mm·sin(2π·100 Hz·(T−T0)) + N(0, 1 mm), Y = 0.5 mm + N(0, 1 mm), 10 shots ×
  20,000 events over 50 ms, 1 ms bins: > 95 % of bin means within 3 SE of the bin-averaged
  truth (mean pull < 0.5), SDs within 3 SE of 1 mm (X: widened by the slosh within its bin,
  computed); SE formulas exact. Spectrum (0.5 ms bins): top peak within one bin (20 Hz) of
  100 Hz, amplitude 2 mm ± 25 %, every window; Δf 20 Hz, Nyquist 1 kHz. Gaps counted and
  filled; odd trace lengths; no NaN spectra.
- D6: 1 + 0.2·cos(2π·2 kHz·(T−T0)) over 50 ms, 10 shots × 20,000: 10 µs bins give Nyquist
  50 kHz, Δf 20 Hz, the top peak within one bin of 2 kHz at 80 kHz/shot ± 10 % (the profile's
  400 kHz/shot × 0.2); every window; half a bin off (2.01 kHz, 40 shots): ×4 padding places it
  within a quarter bin, flat top reads its amplitude within 5 %; counts (16 × 0.2 per bin),
  power = amplitude²; peaks above; under a Gaussian cloud (σ 10 ms) with peaks above 500 Hz.
- Empty and short: no shots / none chosen / no events (shared texts); none in range; no T bin
  full (D5); fewer than 10 events or 16 bins (D6); D5 too short for a spectrum; one event;
  cancellation.

## Not done (for later)

- Welch PSD; Lomb–Scargle; a robust width; averaged (not summed) profiles per shot.
- Fits of the mean position (e.g. a sine fit with ± from F0's fits) would give the slosh
  amplitude and frequency with uncertainties beyond the spectrum's bin.
