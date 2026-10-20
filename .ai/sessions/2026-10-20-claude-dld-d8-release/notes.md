# D8 part 1 notes: design and judgement calls

Items marked **proposed, for Tony** were decided while he was away.

## Optional constants ("from the data")

- `physics.Constant` gained `optional` (no default: value nan, and not `derived`) and `signed`
  (any finite value, zero and negative included; `Constant.accepts` is the one validity rule, used
  by `resolve`, `clean_layer` and `from_record`). Before, every layer value had to be positive.
- New rows, appended, folder level: `release_time` ("Release time t_r", s, optional, signed),
  `trap_x` ("Trap origin X x₀", m) and `trap_y` ("Trap origin Y y₀", m), optional and signed.
  `physics.OPTIONAL` lists them. Not unconfirmed (no borrowed value to confirm).
- **Unset → origin "detected"**, value nan, `ResolvedConstants.is_set(key)` false. A new `Origin`
  literal, shown as "from the data" (`constant_layers.FROM_THE_DATA`). It means "the run takes it
  from the data", not that anything was detected yet: the plot records what it did (a detected
  `ReleaseTime`, or the origin "assumed" (0, 0) via `release.velocity_origin`). **Proposed**: one
  word for both, as the brief asked ("resolve as detected when unset").
- Records: an unset optional row's value is None in `as_record` (strict JSON); `from_record`
  accepts None only with "detected", and fills the three rows as unset when an older record lacks
  them.
- Equality: Python 3.13's dataclass `__eq__` compares fields one by one, so nan ≠ nan made two
  identical resolutions unequal (and `{DEFAULTS, resolve()}` two items). `ResolvedConstants` now
  has its own `__eq__`/`__hash__` over the values with unset rows as None, plus the origins
  (hash: values only, as before). `changed_keys` treats nan = nan.
- Text: `value_text` says "from the data" for an optional nan; new `value_and_origin` ("848 mm
  (folder)" / "from the data") used by `describe_constants`, `record_text` ("t_r from the data")
  and the plot settings' constant titles (`ScriptTreeSelector._show_constant_titles`, one line).
  `from_defaults` counts "detected" as a default, so the source line doesn't list unset rows.
- Plot overrides of optional rows (for D8 part 2): `constants_specs` gives them `SIGNED_LIMITS`
  and a starting value of 0 (`default_value`), ms/mm as the others.
- Editors: `constant_editor` (Lab parameters tab, Folder constants dialog) bounds signed rows to
  `SIGNED_LIMITS`. The Lab tab lists lab rows only, so the new folder rows don't show there. The
  folder dialog lists them (it shows every folder row): source "from the data (Release time
  plot)", the disabled editor at 0 until Set here; "Set here" tooltip says "instead of taking it
  from the data". **Proposed**: the editor's starting value 0 (there is no sensible default).

## release.py (additive)

- `ReleaseTime` gained what a plot draws: `fit_window` (the fit's T window), `origin_half` (the
  origin's T slice half-width) and `origin_window` ((X low, X high), (Y low, Y high)); in
  `as_record` too. `_origin` keeps its 3-tuple (tests call it); `_origin_drawn` returns the extras.
- `layer_release_time(constants)` (a layer's t_r as a manual `ReleaseTime`, None when unset) and
  `layer_origin(constants)` (the layers' (x₀, y₀) for `velocity_origin`'s `manual`, None unless
  both are set), for D8 part 2.

## The Release time plot (`helab/scripts/standard/release_time.py`)

- Parameters: Shots; Search T from/to (0 = open; crossing ends: searches all, warned); Shot
  bootstrap resamples (0 = off); Constants group for h, t_f, g (`constant_keys` = fall_distance,
  fall_time, g). It does **not** declare release_time/trap_x/trap_y: saving them from the plot
  would otherwise mark the plot itself "constants changed: Rerun".
- Compute: per-shot TXY arrays to `bootstrap_release_time` (XY origin and its bootstrap SE
  included); with one shot or n_boot 0, `detect_release_time` on the summed events, with a note
  that the SE is the fit's alone. Cancellation: `context.cancelled` goes to the bootstrap, which
  raises `Cancelled`; `context.check()` between phases.
- Drawing (PyQtGraph, ms/mm, grouped ticks on both axes): T of the events searched with the
  release (green) and arrival (red) lines; the arrival up close (3× the fit window, the fit's bins)
  with the fitted arrival-time profile over its shaded window; X and Y histograms of the cloud's T
  slice with the robust window (dashed) and the origin line. Wrapped title lines: what was searched,
  `release t_r = 20,031.198 ± 0.011 ms (shot bootstrap) · arrival 20,447.289 ms · t_f 416.0908 ms
  (h 848 mm)`, `origin (2.9909 ± 0.0085, −2.0019 ± 0.0080) mm · background 0.2 %` (or "background
  unknown"), then each warning and note as "⚠ …" (amber, shortened; whole in the record).
- `result_found`: `release` (the full `ReleaseTime.as_record`), `brief` (settings line),
  `record_lines` (t_r with the error kind and the fit's within-run SE, the bootstrap's n and seed,
  the arrival and σ_t, t_f "taken as exact", the fit model and window with χ²/dof, the origin with
  its events and slice, every note), `constants`.
- **Use for this folder…** (button under the plot, enabled when t_r was found): asks first
  (`QMessageBox`, Save/Cancel, **Cancel the default when the detection is unsure**), listing each
  value and what it is now (resolved from the lab and the folder's inherited values in memory),
  warnings for unsure or within-run-only errors, and that a missing origin leaves the folder's as
  it is. Then `set_folder_constants(path, {**folder's own, release_time, trap_x, trap_y},
  owner=<the plot>)`: merged, because that call replaces all the folder sets. The status beside
  the button says "Set for this folder (Folder constants…)", RAM only with the reason, or a failure
  (`folderConstantsFailed` for this plot's owner). Path: the view's source folder. Never written
  automatically.
- Live: `LivePolicy(min_delay=5.0)`. Version "1", id `helab.release_time`, last in `MODULES`.

## Bootstrap cost and the default (**proposed, for Tony**)

Measured (one thread, this container): one detection 0.05 s on 20 shots × 2,200 events, 0.45 s on
100 × 5,500 (the XY origin's medians are ~75 % of it). 200 resamples took 10 s and 65 s. The plot
defaults to **100 resamples** (5 s / 32 s; the SE's own error ~7 % instead of ~5 %), keeping
`release.RELEASE_N_BOOT` at 200 for other callers. A large folder still occupies the single
analysis worker for half a minute per run: options for later are a time budget in
`bootstrap_shots`, a faster origin in the resamples (precomputed T slices), or bootstrapping t_r
only by default.

## Other choices

- The plot always detects, also when the folder sets t_r (it is how t_r is measured); the
  confirmation shows the folder's current value. It does not draw the folder's value. **Proposed.**
- "Use for this folder" writes to the plotted folder itself (its subfolders inherit), not to the
  data root. **Proposed.**
- Origin X/Y histograms rather than an XY image (simpler, and the window is per axis).
