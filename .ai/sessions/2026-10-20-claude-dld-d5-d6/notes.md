# Notes: D5 and D6 (2026-10-20, Claude)

## What was built

| File | What |
|---|---|
| `helab/scripts/standard/mean_position.py` | D5, **Mean X, Y against T** (`helab.mean_position_vs_t` v1) |
| `helab/scripts/standard/t_spectrum.py` | D6, **T spectrum** (`helab.t_spectrum` v1) |
| `helab/analysis/spectrum.py` | Windowed one-sided amplitude spectrum (`fft_tx` normalisation), peaks, the window/peak parameter specs |
| `helab/analysis/display_units.py` | mm; T in ms or s by range; SI text (`1.25 kHz`, `50 ns`) |
| `helab/scripts/base.py`, `helab/models/ScriptTreeSelector.py` | `DatasetAnalysis.describe_result` (appended to the dock's settings line) and `result_record` (to its record, as on `agent/dld-d1`), for completed results |
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

1. **Two hooks on `DatasetAnalysis` (additive), called for completed results only.**
   - `describe_result(action, result) -> str`: what the run found, appended to the dock's
     settings line (D6's resolution and Nyquist depend on the auto-crop and the automatic bin
     width, known only after the run): e.g. "T bins 25 µs (auto: ~10 events per bin) · bin
     spacing Δf 20 Hz, resolution ≈ 30 Hz (ENBW 1.5), Nyquist 20 kHz". Also in each title.
   - `result_record(action, result) -> List[str]`: lines appended to the dock's record
     (tooltip): the bins (left out, filled, past the last whole bin), the spectrum's frequencies
     and the correction, and the peak list. **Defined exactly as on `agent/dld-d1`** (same
     signature, docstring, place in `base.py`, and the same three lines in
     `ScriptTreeSelector._show_content`), so the merge takes one copy.
2. **T's unit:** the density images' rule (ms while both ends are under 10 s), in
   `display_units.time_unit`, the shared home for display units. D1, D3 and these plots each
   chose a rule (see the handoff); Tony picks one.
3. **D5 width = SD** only, with SE = SD/√(2(n−1)) (normal data). A robust σ (1.4826·MAD,
   less sensitive to a hot spot) was considered and left out until hot-spot masks (D9).
4. **D5 automatic bins:** about 100 events per bin on average, at least 10 and at most 1,000
   bins (the dock line says when a limit applies, with the events per bin); set widths are
   used exactly (the old GUI's came out about 2× wider, legacy bug 5), widened only past
   100,000 bins (a warning). Minimum events per bin: 10 (≥ 2, for an SD).
5. **Whole bins only (both plots).** Bins of exactly the width from the range's start; a
   remainder shorter than a bin past the last whole one is left out, and the plot and record
   say how many events were in it (its rate would read low and its sample would be off the
   even spacing). Automatic widths divide the range exactly, so nothing is left out then.
6. **D5 spectrum gaps:** the traces from the first kept bin to the last, gaps **filled by
   straight lines while they are at most 20 %** of it (`MAX_FILLED`). Past that, the longest
   stretch without gaps is used when it has at least 8 bins, else no spectrum; the note says
   which, with the share and the stretch (e.g. two clouds 15 ms apart: "gaps are 33 % of the
   traces (over 20 %): spectrum of the longest stretch without gaps, T 400.5–414.5 ms (15
   bins)"). Lomb–Scargle (the review notes' suggestion for uneven samples) is still an option.
7. **Window: Hann by default in both** (the review notes said Hamming for D5; one default
   across plots, and Hann's far sidelobes fall faster, which helps weak peaks near strong
   ones). Choices: Hann, Hamming, Blackman, flat top, none.
8. **Normalisation (`fft_tx`):** mean subtracted, one-sided amplitude `2·|rfft|/sum(window)`
   (DC and Nyquist not doubled): a sine of amplitude A on a bin reads A with every window.
   **Power = amplitude²**, not a density per Hz. A Welch PSD was not built.
9. **Binning correction:** a histogram's bins (and a bin's mean position) average over the
   bin, which multiplies a frequency's amplitude by sinc(f·w) (−24 % at 0.4 of the bin rate,
   −36 % at Nyquist). The spectra are divided by it (`binned`), so a real modulation reads its
   amplitude at any frequency. It is wrong for shot noise, which is white in the bins: the
   drawn noise floor rises towards Nyquist (up to ×1.57). So peaks are found on the
   uncorrected spectrum (flat noise floor) and only their values are corrected. The record
   says the correction was applied.
10. **D6 automatic bins, from the data rate: ~10 events per bin**, at least 256 and at most
    16,384 bins (the dock line says when a limit applies, with the events per bin). Nyquist is
    then a twentieth of the summed events' mean rate. First tried one event per bin up to
    65,536 bins: on 200,000 events that put Nyquist at 655 kHz with the interesting kHz band
    squeezed at the left and a profile of pure shot noise. For higher frequencies, set the
    width (up to 2²⁰ bins, then widened with a warning) or narrow the range.
11. **D6 profile units:** rate per shot in kHz (the front panel's kHz/File; Decided section)
    by default, or summed counts; the spectrum is in the same unit.
12. **Frequencies stated:** "bin spacing Δf" (1 over the trace's length), "resolution ≈
    ENBW·Δf" (the window's equivalent noise bandwidth in bins: none 1, Hann 1.5, Hamming 1.36,
    Blackman 1.73, flat top 3.77) and Nyquist. Zero padding draws a finer grid only.
13. **Peaks:**
    - Found on the **amplitude** (the square root in power mode, so threshold and frequency
      are the same in both modes) of the **unpadded bins** (sidelobes show as separate maxima
      only between them), uncorrected for binning, above "Peaks above" (Hz, 0 = all; never DC).
    - Prominence ≥ 4 × the median amplitude there (a noise-floor estimate): on pure Poisson
      noise, 20 profiles × 50 peaks asked list none, in amplitude and in power mode.
    - At least the window's main-lobe half-width apart (none 1, Hann/Hamming 2, Blackman 3,
      flat top 5 bins).
    - A peak no more than twice the stronger peaks' sidelobe envelope at its distance (the
      window's own leakage, measured once per window) is taken for a sidelobe and left out:
      Hamming's flat −43 dB sidelobes otherwise list as peaks beside a strong line. A weak
      line 60 bins from one 50× stronger still lists (tested with Hann).
    - Ranked by prominence, the top N (D5: 3, D6: 5), marked and listed (plot and record).
    - Each placed on the padded spectrum's highest sample near it and refined by a parabola
      through the **logarithms** (a Gaussian fit to the top; a straight parabola where a value
      is 0). Frequency error without padding, offsets 0–0.5 bin (tested): Hann and Hamming
      < 0.03 bin, Blackman < 0.02, flat top and none < 0.2 (flat top's top is flat, the
      rectangular window's a sinc; flat top is for amplitudes).
14. **Log axis on by default** for both spectra (noise floor and weak peaks visible).
15. **Zero padding** ×1–16 (default 1), lowered so the transform stays ≤ 2²² samples (said).
16. A range with no T extent (equal T) is widened by 0.5 ms each way, as the density images.

## Checks on synthetic data (tests)

- D5: X(T) = 2 mm·sin(2π·100 Hz·(T−T0)) + N(0, 1 mm), Y = 0.5 mm + N(0, 1 mm), 10 shots ×
  20,000 events over 50 ms, 1 ms bins: > 95 % of bin means within 3 SE of the bin-averaged
  truth (mean pull < 0.5), SDs within 3 SE of 1 mm (X: widened by the slosh within its bin,
  computed). Standard errors checked against the scatter (not their own formula): over 300
  bins of known truth, the pulls of the means and of the SDs have SD 0.85–1.15. Spectrum
  (0.5 ms bins): the peak within 0.05 bin of 100 Hz at 2 mm ± 3 %, one peak only with every
  window; a 400 Hz slosh in 1 ms bins reads 2 mm ± 5 % after the binning correction (1.51 mm
  without). Gaps: 10 % filled; two clouds → the longest stretch, or no spectrum; odd trace
  lengths; whole bins (a 3 ms width over 50 ms: 16 bins, the last 2 ms left out and said);
  the automatic width at and between its limits.
- D6: 1 + 0.2·cos(2π·2 kHz·(T−T0)) over 50 ms, 10 shots × 20,000: 10 µs bins give Nyquist
  50 kHz, Δf 20 Hz, resolution 30 Hz (Hann), the one peak within 0.05 bin of 2 kHz at
  80 kHz/shot ± 5 %; every window, no sidelobe listed; half a bin off: within 0.05 bin with
  and without ×4 padding, flat top's amplitude within 5 %; 40 kHz modulation in 10 µs bins
  read at 80 ± 6 % (corrected for sinc(0.4)); counts (16 × 0.2 per bin); power = amplitude²
  at the same frequency; peaks above; pure Poisson noise lists none (amplitude and power);
  under a Gaussian cloud (σ 10 ms) with peaks above 500 Hz; whole bins and the automatic
  width's limits.
- Helpers: every window reads a sine's amplitude on a bin; DC 0; an alternating trace reads
  its amplitude at Nyquist (not doubled), π/2 times it when corrected; frequency error bounds
  per window over offsets 0–0.5 bin, the same in amplitude and power; no sidelobe peaks with
  ×16 padding, every window; a weak line beside a strong one stays.
- Empty and short: no shots / none chosen / no events (shared texts); none in range; no T bin
  full (D5); fewer than 10 events or 16 bins (D6); D5 too short for a spectrum; one event;
  cancellation; describe_result and result_record give nothing for a failed run.

## Review (Coordinator, 645c8cb) and what changed

1. Power-mode threshold on power listed noise: peaks now found on the amplitude (13).
2. Sidelobes listed under zero padding: peaks found on the unpadded bins, the main-lobe
   distance and the sidelobe-envelope test (13).
3. Unlimited gap filling: at most 20 %, else the longest stretch or no spectrum (6).
4. Binning attenuation: corrected, peaks found uncorrected (9).
5. Linear parabola: log parabola, error bounds tested (13).
6. "Δf" renamed: bin spacing, resolution ≈ ENBW·Δf, Nyquist (12).
7. Auto-bin notes at the limits (4, 10).
8. Partial last bin: whole bins only (5).
9. Tests: the always-true `startswith("")`, the circular SE check, the D5 amplitude tolerance
   (25 % → 3 %), Nyquist/DC tests.
10. `describe_result` for completed results only; `result_record` as on `agent/dld-d1` (1).

## Not done (for later)

- Welch PSD; Lomb–Scargle; a robust width; averaged (not summed) profiles per shot.
- Fits of the mean position (e.g. a sine fit with ± from F0's fits) would give the slosh
  amplitude and frequency with uncertainties beyond the spectrum's bin.
