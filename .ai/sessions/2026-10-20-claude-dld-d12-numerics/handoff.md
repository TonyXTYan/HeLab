# D12/D13 correlation numerics handoff

Branch `agent/dld-d12-numerics`, from `fb47de7`. Not pushed or merged. New files only:
`helab/analysis/correlations.py`, `tests/test_correlations.py` (35 tests, ~45 s with `-n 1`,
most of it the error-calibration runs, the thermal simulation and the speed test). Commits:
the numerics, the Coordinator's review fixes (free baseline, honest errors, shot-pair
matrix, bin-averaged model), then a merge of the integration head 6ed1ec9 with the fit
moved onto `fit_histogram`'s `edges=`/weight averaging. Estimators, derivations, simulation
results and choices for Tony: [notes.md](notes.md).

## API

- `CorrelationSpec(geometry="1d"|"radial", edges, mode="cl"|"bb", axis, window, origin,
  partners, events_key, recentre)`: frozen, validated; `key()` is the in-shot cache key, `centres`,
  `as_record()`. `linear_edges(low, high, bins)`, `radial_edges(high, bins)` (equal volume).
- `ShotEvents(shot, fingerprint, events)`: events (n, 3) in m/s, `VELOCITY_AXES` order;
  non-finite rows are dropped.
- `correlate(shots, spec, *, cache=None, state=None, cancelled=None, budget=None,
  clock=time.monotonic, n_boot=1000, seed=0, fit=True, baseline="free") -> CorrelationResult`.
- `PairCounts(spec, cache)`: the Live state (`update(shots, cancelled, budget, clock)` →
  shots left for lack of time; `add`, `remove`, `arrays()`, `matrix()`, `matrix_kept`);
  `g2_from_counts(state, …)`; `peak_model(spec, baseline)` / `peak_curve(…)`.
- `CorrelationResult`: `centres`, `edges`, `g2`, `se` (+ `se_method`), `counting_se`,
  `jackknife_se`, `in_counts`, `between_counts`, `in_pairs`, `between_pairs`, `shots_used`,
  `shots_total`, `complete`, `failure`, `notes`, `fit` (`FitResult`, bin-averaged model),
  `g2_zero` (`Estimate`: (b + A)/b, SE the larger of bootstrap and jackknife refits,
  `g2_zero_method`; nan for a slope or a failed fit), `near_zero` (pooled g² of the 3 bins
  nearest 0 ± bootstrap SE), `baseline` (b; nan when undetermined), `baseline_mode`,
  `curve(x)`, `bootstrap`, `as_record()` (strict JSON). `robust_centre(events)` is the
  re-centring centre. Failures (no shots, one shot, nothing in range) are results,
  never exceptions.

## How the D12/D13 plot should use it

1. **Events**: from the D8 velocities of the plot's selected shots (Shots selection, D9
   masks applied first), one `ShotEvents` per shot with its `DatasetView` fingerprint.
   Put everything upstream that changes the events but not the fingerprint into
   `events_key` (release time and its source, fall distance, g, masks, unit), e.g. a short
   JSON of those settings; otherwise a cached in-shot count could be reused across them.
2. **Parameters** (proposed): Type (1D / radial), Mode (collinear / back-to-back), Axis
   (v_z, v_x, v_y), Range (max |Δv|), Bins, Window (half-width, 1D), Origin (BB: "from the
   halo centre" once D13's per-shot halo centring exists, else manual or 0), Between-shot
   reference (all / K neighbours), Re-centre each shot (off), Baseline (free / fixed at 1,
   free by default), Time budget (s), Bootstrap resamples. Show g² in the chosen
   velocity unit; convert edges before calling (all inputs are m/s).
3. **Live (L3)**: keep one `PairCounts` and one cache dict per plot in the plot's own state
   (not shared across threads; `compute` runs in the analysis worker), and pass
   `state=` on each rerun with the same spec: new shots are added (each compared with the
   held ones once); shots whose fingerprint changed or that left the selection are removed
   first. A spec change means a new `PairCounts`, but keep the cache dict: in-shot counts
   survive a change of partners or of anything outside `key()`. Drop both when the folder
   changes. Banded mode assumes new shots come at the end (Live's order).
4. **Cancellation and budget**: pass `ctx.cancelled`; `Cancelled` propagates like the other
   analyses. With a budget the plot should show `notes` ("stopped at the time budget: k of S
   shots used") and, under Live, the next rerun continues from the state (the shots not
   added yet are simply added then).
5. **Drawing**: points g² ± `se` at `centres` (radial centres are shell means), the
   fit curve `result.curve(x)` (= `fit.evaluate(x)`, the unaveraged model) on a fine grid, a line at the fitted baseline, the title `g²(0) = …` from `g2_zero.text()`
   (relative to the baseline) and σ from `fit["sigma"]`. Without a g²(0) show
   `near_zero` ("no peak: g² near 0 is …", in the notes) instead. Show the notes: a baseline
   that isn't 1 or "a slope, not a peak" means the reference doesn't match the shots (try
   re-centring) or the range is too narrow ("widen the range"). Empty/failed: show `failure` as the plot's
   note (`helab/analysis/empty.py`). Coverage: `shots_used` with their fingerprints.
6. **Record**: `result.as_record()` plus the velocity settings.

## To do / open

- The integration head (6ed1ec9) is merged: fits go through `fit_peak`, which gives
  `fits.fit_histogram` the spec's exact edges and the r² shell weight (one averaging path).
- A cloud-matched reference (partners by similar centre and width) and a banded shot-pair
  matrix for very long runs: notes.md.

- D13's per-shot halo centring (the BB origin per shot) isn't here: the spec has one
  origin for all shots. With per-shot centres, centre each shot's events before passing them
  and leave `origin` None (proposed).
- Two-port (two-species/two-detector-region) cross-correlations (the legacy 2×S input) are
  not implemented.
- A free-baseline fit and shot-count normalisation are proposals in notes.md.
