# Brief: D5 and D6 from the DLD front panel (2026-10-20, Claude, Worker)

From the Coordinator, while Tony slept: work autonomously, record choices as proposed for Tony.

- Branch `agent/dld-d5-d6` from `1231025`; commit freely, no push or merge.
- **D5** (`dld_avg_pos_plots`): bin T within the View range; per T bin, the mean X and Y (mm)
  and their SD with standard errors over the chosen shots, against T; optionally the spectrum
  of the mean-position trace (sloshing). Bins with too few events left out and counted.
- **D6** (1D FFT, `TOF_averaged`, `fft_tx`): a fine T histogram over the View range (bin width
  choice, default from the data rate, saying why), mean subtracted, window (Hann default),
  rFFT, amplitude or power spectrum in Hz (kHz labels), log option, a peak list (top N:
  frequency, amplitude, prominence; `find_peaks`) in the plot and the result. Frequency
  resolution and Nyquist in the dock line.
- Both: pure NumPy compute in the worker with cancellation checks; notes for empty and short
  cases; update in place; shared Shots, own View range, Live policy, `describe_run`,
  `covered_shots`, RAM budget. New files only (other workers edit `basic_plots.py`), plus
  registration and minimal additive helpers.
- Authority: `roadmaps/dld-front-panel-port.md` (Decided: X/Y in mm, T in ms or s by range,
  view range per plot, no XY rotation) and the review notes' D5, D6 and legacy bugs.
- Acceptance: synthetic slosh recovered within SE with its frequency; a pulse-rate modulation
  found within one frequency bin; Nyquist/resolution; windows; empty/short; update in place;
  discovery; the shared bundled-plot tests; mypy, pyright, `git diff --check`, full suite.
