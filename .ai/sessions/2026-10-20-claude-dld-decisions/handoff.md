# DLD decisions: handoff

Branch `agent/dld-decisions` from `fb47de7`. Not pushed or merged. Design and the calls proposed
for Tony: [notes.md](notes.md). Brief: [brief.md](brief.md).

## Done

1. **T in ms, X/Y in mm everywhere**, grouped `1,234.5678 ms` ("," and "." whatever the locale):
   one module `helab/analysis/display_units.py` (duplicates in profiles, density_images, stats,
   selection deleted), `helab/analysis/plot_axes.py` `GroupedAxis` for tick labels (every T/X/Y
   axis of the PyQtGraph plots), Plotly scatter in mm/ms with grouped ticks and hover, fit numbers
   via `estimate_text`. View-range bounds and other T/X/Y settings shown in ms/mm through
   `ParameterSpec.unit_prefix` / `UnitSpinBox(fixedPrefix=…)`, values stored in s and m.
2. **TF exponent**: Bimodal TF² and TF^3/2 + Gaussian on T, X and Y, with the physics tooltip;
   `max_radius_ratio` through `fit_axis`; cap comment corrected (axis-dependent).
3. **D1 on F0b's constants API**: `constants_specs`, `constant_keys` (h, t_f, g, m, k_B),
   `run_constants` → `None` without fits; constants once in the record; version 5; arrival-time
   model on the effective fall distance.
4. **Shot times**: rule explained; a held shot's raw file is no longer re-stat'ed when the cache
   save reads its TXY again (`memory_raw_times`).
5. Coordinator review items: raising dock hooks logged, D5/D6 record/brief in `found`,
   `SpectrumPeak`, `record_text` limited to an analysis's keys, constants test fixture, density
   transposition test.

## Checks

- `mypy helab tests --strict`: no issues (178 files). `pyright helab tests`: 0 errors.
  `git diff --check`: clean.
- Full suite `python -m pytest -n 2 --reruns 5 --reruns-delay 1 -rR`: **2 failed, 1701 passed,
  7 skipped, 2 xfailed, 10 rerun**. Failed and rerun (5 each): only the two root-only tests
  (`test_constants.py::test_read_only_saved_folder_is_replaced`,
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`). No other RERUN.
  (Run before the last test-only edit to `test_density_images.py`, which passed on its own.)

## For Tony

See notes.md: the text rule for positions/widths, ms for T widths and the fall time in settings,
the grouped-comma reading in German-locale boxes, `h 848 mm` (SI prefixes for constants), the DLD
trigger still shown in s, D1 version 5 dropping saved fall overrides. Found, not fixed:
`HelabMainWindow` reads native QSettings in tests (proposed follow-up).

## On-screen checklist

1. T, X, Y histograms on a run at T ≈ 20.4–20.6 s: bottom axes "T (ms)" with ticks like
   `20,450`, `20,500` (no `2.045e+04`), X/Y "(mm)". Fits on: titles `centre (20,916.12 ± 0.12) ms`.
2. Model choices list "Bimodal TF^3/2 + Gaussian"; hover a model choice: the exponent tooltip.
3. Fits tab › Constants: Fall distance / Fall time choices; set Fall time "this plot": the box shows
   `416.091 ms`; type `417` → 417 ms. Settings line "constants: t_f 417 ms (this plot)"; tooltip has
   one "Constants:" line. Change Settings › Lab parameters › g: amber "constants changed" only on
   plots with a fit on.
4. View range › manual: T min shows `20,450 ms`-style; type `20,450.5` and `20450.5` (both
   20,450.5 ms), `20.45 s` (20,450 ms). `20,5` or `0,450` outline red and are refused, on a
   German-locale Windows PC too (second commit: "," only groups thousands in these boxes).
   Settings › Lab parameters: DLD trigger `20,500 ms`, fall distance `848 mm`.
5. Density images XT/YT, Mean X, Y against T, T spectrum, Transfer fractions: T axes in ms,
   grouped; Transfer fractions' title `order 0 at 2,137.4758 ms, spacing 12.52 ms`.
6. 3D scatter: axes X/Y (mm), T (ms); hover reads `T 20,450.1234 ms`; Open in browser the same.
7. Mean position / T spectrum: release a plot (RAM budget), hover the dock: the bins/spectrum lines
   and the settings-line addition are still there.
8. Live on a folder held in RAM without a cache: an I/O trace shows one `load: shot time` per new
   raw file only.

## Proposed text (not edited)

- **AGENTS.md, Script system** (after "Each plot dock's source is two lines…"): "Plots show T in ms
  and X and Y in mm, digits grouped by thousands with "," and "." whatever the locale
  (`helab/analysis/display_units.py`; tick labels `plot_axes.GroupedAxis`); settings of T, X and Y
  (`ParameterSpec.unit_prefix`) show ms or mm and store s and m. Frequencies keep SI prefixes;
  durations that aren't T positions (Shot times' gaps) keep theirs."
- **AGENTS.md, Script system** (D1 sentence): "… fit each axis (Gaussian, the arrival-time thermal
  profile on T, bimodal TF² or TF^3/2 + Gaussian: p = 2 for a full projection, 3/2 for a thin
  slice) …; its Constants group is F0b's (h, t_f), and a run with a fit resolves h, t_f, g, m, k_B."
- **AGENTS.md, Data loading/Live** (shot times): "Raw `d<N>.txt` files are never rewritten: a
  shot's raw time is stat'ed once, and again only when its TXY fingerprint changes; a load sends
  the held shots' times (`memory_raw_times`)."
- **roadmaps/dld-front-panel-port.md, Decided → Axis units:** replace "T in ms or s, chosen
  automatically from its range" with "T always in ms (never s), thousands grouped (`20,450.1234
  ms`); X and Y in mm; also in settings, records and titles (Tony, 2026-10-20)". Fits: "the TF
  exponent is offered as p = 2 and p = 3/2 (Tony, 2026-10-20)".
- **.ai/MANUAL_TODO.md:** "Check the ms/mm display and grouped ticks on macOS and the Lab Side PC,
  and typing grouped numbers in a German-locale settings box (DLD decisions handoff, checklist)."
