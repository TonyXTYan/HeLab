# DLD decisions: notes

Judgement calls are marked **proposed, for Tony**.

## 1–2. Display units: T in ms, X/Y in mm

One module, `helab/analysis/display_units.py`:

- `axis_unit`/`axis_scale`/`axis_label` ("T (ms)", "X (mm)"), `number_text`, `grouped`,
  `axis_text`/`time_text`/`length_text`, `range_text`, `estimate_text` (value ± SE in a fixed unit,
  grouped *after* `estimates.format_fixed` has rounded, so `_largest`/`_bracket` never see commas),
  `tick_strings`, and the one `si_text` (rounded before the prefix, with carry; `estimates.si_prefix`
  over y…Y; "−"; nan → "–") with `frequency_text`.
- Grouping is Python's `f"{x:,}"`: always "," and ".", never the locale's (as Tony wrote).
- Deleted duplicates: `profiles.display_unit`/`si_text`/`T_SECONDS_FROM`/`unit_of`/
  `constants_text`/`CONSTANT_NAMES`/`ORIGIN_TEXT`, `density_images.time_unit`/`LENGTH_*`,
  `display_units.time_unit`, `stats.axis_text`, `selection.SI_PREFIXES` and its `range_text`. The
  plots no longer carry a `time_unit` field, and their `update()`s no longer redraw on a "T unit
  changed" (it can't).
- **Text rule (proposed, for Tony):** a position keeps up to 9 significant digits and at most 4
  decimals (0.1 µs in ms, 0.1 µm in mm), trailing zeros dropped: `20,450.1234 ms`, `2,137.4758 ms`,
  `0.5 ms`. A width along an axis (bin width, σ, spacing) keeps 4 significant digits and as many
  decimals as those need: `0.1235 ms`, `0.00005 ms`. Fit centres, widths, R: `estimate_text`, the
  error to 2 significant digits: `(20,916.12 ± 0.12) ms`, `(−1,234.5 ± 2.1) mm`.
- **Ticks:** `helab/analysis/plot_axes.py` `GroupedAxis(pg.AxisItem)` (auto SI prefix off; log mode
  keeps pyqtgraph's labels): decimals from the spacing as pyqtgraph picks them, plus enough to write
  the spacing itself (2.5 → one decimal), never exponent form (pyqtgraph switches to `%g` from
  10,000, i.e. `2.045e+04` for a T of 20.45 s). It is in its own module because `display_units` has
  no Qt (spectrum.py and the analysis worker import it). Used on every T axis and the T/X/Y axes:
  histograms (bottom), density images (both), mean position (both), T spectrum's profile, transfer
  fractions' T histogram. Counts per shot and Shot times keep pyqtgraph's axes (no T/X/Y).
- **3D scatter:** points drawn in mm and ms (a scaled copy of the display sample only), axis titles
  "X (mm)"/"T (ms)", d3 `tickformat ",~f"`, hover `%{z:,.4f} ms`; the crop line uses `range_text`.
- **Settings (proposed, for Tony):** `ParameterSpec.unit_prefix` ("m") shows a value always in ms or
  mm, grouped; the value stays in s or m, so saved settings keep their meaning. `UnitSpinBox` got a
  `fixedPrefix` option: grouped display (`20,450.1234 ms`, up to 6 decimals), and it reads a number
  whose commas sit exactly between groups of three ("20,450.5") with them as thousands separators;
  any other comma follows the old rule (German "20,5" is 20.5). So "20,450" in a German box is
  20,450 ms, not 20.45: the box shows that form itself, so it is the consistent reading. Applied to
  the View-range T, X and Y bounds (all plots, shared `range_specs`), and, for one time unit in the
  app, to T widths and times as well: σ T and σ X/Y (histograms), T bin width (mean position,
  T spectrum), Transfer fractions' Order 0 at, Spacing, Window ±, Search T from/to (ms) and XY box ±
  (mm), and the fall time (F0b's Constants group: every constant in s is shown in ms). The fall
  distance is a distance, not an X/Y position: SI prefixes as before. Stepping is unchanged
  (a tenth of the value's decade). `ParameterSpec.text` (dock record) writes these in ms/mm too.
- **Constants' values** (`constant_layers.value_text`, coordinator's item A8): SI prefixes for m, s
  and Hz, 6 significant digits: `h 848 mm`, `t_f 416.091 ms`, but the DLD trigger reads `20.5 s`
  (an SI prefix by size). **Proposed, for Tony:** the trigger is a T position; if wanted, show it
  in ms too (one line in `value_text`).
- **Not time axes, left as they were:** Shot times' gaps and elapsed times ("2.0 min"), run times,
  live intervals, the spectrum's frequencies (Hz/kHz), the T spectrum's rate (kHz per shot), the
  fall distance.
- Density images: per-shot rate is per mm² (XY) or per mm·ms (XT/YT); the "or per s" branch is gone.

## 3. TF exponent

`profiles.T_MODELS`/`XY_MODELS` offer "Bimodal TF² + Gaussian" (default stays Gaussian; the bimodal
default exponent is 2) and "Bimodal TF^3/2 + Gaussian" (`bimodal_tf1_5_gaussian`, already in
`fits.MODELS`). Physics checked and tested on sampled 3D TF clouds: integrating (1 − r²)₊ over k
other axes gives (1 − u²)^(1+k/2); a full projection fits p = 2 and recovers R to 2 %, a thin slice
(|y| < 0.05 R) fits p = 3/2; the wrong exponent biases R by > 4 % (the reviewer's 8–9 %) and fits
worse. Tooltip (`profiles.TF_EXPONENT_TIP`, on each model choice) per the physics review: p = 2 full
projection (a crop to ~0.7 R still p = 2), p = 3/2 thin slice, p = 1 not offered, bias of the wrong
one, windowing the other axes windows the thermal cloud too, g_5/2 / g_2 thermal partners (Gaussian
= Boltzmann limit); the exponent follows the integration, not the expansion (TF shape preserved by
the scaling solution). `fit_axis`/`fit_smoothed` pass `max_radius_ratio` through; the cap comment in
fits.py now says R/σ_th = √(2μ/k_BT) is the radial axes of a cigar trap (isotropic √(4μ/3k_BT), axial
≈ (π/2)(ω_z/ω_⊥)√(2μ/k_BT)): axis-dependent, for D4.

## 4. D1 on F0b's constants API

`basic_plots`: `*constants_specs(("fall_distance", "fall_time"), page="Fits")` replaces D1's
FALL_DISTANCE/FALL_TIME ("0 = default" overrides); `constant_keys` → fall distance, fall time, g,
mass, k_B (so a lab mass/g change marks it); `run_constants` returns `None` when no fit is on (the
base signature is now `ResolvedConstants | None`): no-fit histograms aren't keyed on constants nor
marked. `compute` reads `context.resolved_constants` (fallback `resolve_for_run`, which cleans bad
layer values: D1's `plot_constants` raised on them). The record has the constants once (F0b's
"Constants:" line, now limited to the analysis's keys via `AnalysisContext/AnalysisResult.
constant_keys` and `record_text(…, keys)`); D1's own Constants lines and the settings-line overrides
are gone; the header uses `describe_constants(…, every=True)`. Version 4 → 5 (parameter names
changed: a saved D1 plot's fall distance/time overrides don't carry over).
D1's arrival-time model now uses `velocity.effective_fall_distance` (½ g t_f² when t_f is hand-set),
matching D8; its tip says so.

## 5. Shot times

Rule kept and explained in `io_helper` (raw `d<N>.txt` files are never rewritten; a time is stat'ed
once, and again only when the TXY fingerprint changed, which covers a run copied over the folder;
the fingerprint check is free). Found one re-stat: a load updating data held in RAM (no cached
dataset) re-read the held shots' TXY files for the disk cache and stat'ed their raw files again.
Fixed: `FolderCache` sends `memory_raw_times` with `memory`, and the helper seeds its times with the
held, unchanged shots'. Tested (the test fails without the fix: `d1`, `d2` re-stat'ed).

## Also (coordinator items B, C, E)

- `AnalysisInstance._hook`: describe_run, describe_result, result_record, parameter_warnings and
  detected_parameters are called through try/except + `logging.exception` with a fallback (they run
  in Qt slots). Test with a script whose hooks all raise.
- Mean position and T spectrum put their record lines and settings-line "brief" in
  `result_found` (`found["record_lines"]`, `found["brief"]`); their `result_record` overrides are
  gone (the default reads `found`); `describe_result` reads `found["brief"]`. Survives a release
  (tested).
- `spectrum.Peak` → `SpectrumPeak`; `AnalysisResult.describe` imports `record_text` at module level.
- Tests: autouse `default_constants` in conftest resets the app-wide FolderCache's lab/folder
  constants (if one exists). **Found, not fixed (proposed follow-up):** `HelabMainWindow` reads the
  native `QSettings(ORG, APP)` at construction for everything (budgets, check level, Live, lab
  constants), so tests that build a real window read the developer's own settings. Qt's
  `setDefaultFormat` doesn't affect that constructor; the fix is to give the window a settings
  factory that tests point at a tmp ini (as AGENTS.md asks). Outside this branch's scope.
- Density images: a test with an asymmetric hot spot (late T, high X, low Y) checks the brightest
  pixel is drawn at the spot's ms/mm place on XY, XT and YT (catches a transpose).
