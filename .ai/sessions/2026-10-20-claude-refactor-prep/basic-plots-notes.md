# Basic plots track: slice D (2026-10-20)

Branch `agent/refactor-basic-plots` from `agent/refactor-prep` (`9cf8782`),
worktree `/home/user/wt/basic-plots`. Behaviour-preserving moves only. Per Tony,
"Basic plots v1" (`helab/scripts/standard/`) is the group HeLab keeps developing;
`helab/scripts/dld/` and its tests are untouched (nothing they import moved).

## What moved

| From | To |
|---|---|
| `scripts/standard/transfer_fractions.py`: tuning constants (`MAX_DETECTION_BINS` … `JUMP_SLACK`), `Orders`, `Detection`, `Fractions`, `order_label`, `in_box`, `smooth`, `detect`, `guided_spacing`, `count_orders`, `window_half`, `jump`, `unsure`, `chosen_by_search` | `helab/analysis/orders.py` (new, NumPy/SciPy only, no Qt) |
| `transfer_fractions.half_maximum_width`, `transfer_fractions.refine` (copies) | removed; `orders.py` imports `peaks.half_maximum_width` and `peaks.refine` |
| `scripts/standard/basic_plots.py`: `OverlayView`, `overlay_newest` | `helab/analysis/overlay.py` (new, pyqtgraph/Qt, like `plot_axes.py`) |

The script keeps `TransferFractions`, its `ParameterSpec`s, `search_bounds`,
`search_warnings` and all drawing. Both standard scripts import
`overlay_newest` from `helab.analysis.overlay`; no standard script imports
another any more, except `group.py`. Names are unchanged. Tests import the
moved names from their new home (`test_transfer_fractions.py`,
`test_transfer_fractions_matlab.py`, `test_plot_backends.py`); no assertion
changed. No test patched any moved name. Docs: `AGENTS.md` (Transfer fractions
paragraph names `orders.py` and `overlay.py`) and `peaks.py`'s docstring (it
named `transfer_fractions.detect`). `roadmaps/refactoring.md` and
`.ai/memory/results/` name none of the moved code.

## Decisions

- **`half_maximum_width`, `refine`: peaks.py's.** Same code (docstrings and one
  comment differ only).
- **`smooth` kept in `orders.py`, with its `SMOOTHING_BINS`.** It differs from
  `peaks.smooth`: transfer fractions uses `np.convolve(..., mode="same")`,
  peaks takes `mode="full"` and slices the middle. They agree whenever the
  histogram is at least as long as the kernel (11 bins at σ = 1.5), which
  detection's ≥ 50 bins always is, but the code isn't the same, so per the brief
  it stays local (noted in `orders.py`'s docstring).
- **Detection constants kept in `orders.py`.** `MAX_DETECTION_BINS`,
  `MIN_DETECTION_BINS`, `DENSEST_SHARE`, `DENSE_SHARE`, `SIDE_PEAK_SHARE`,
  `SIDE_PEAK_COUNTS` have the same values as `peaks.py`'s `MAX_BINS`,
  `MIN_BINS`, `DENSEST_SHARE`, `DENSE_SHARE`, `PROMINENCE_SHARE`,
  `PROMINENCE_COUNTS`, but they are `detect`'s settings, not those of the three
  shared functions, and `peaks.find_time_peaks` uses its namesakes differently
  (`DENSEST_SHARE` with `DENSEST_EVENTS`, `MIN_BINS` giving way to
  `MIN_EVENTS_PER_BIN`). Importing them would let a D8 (release time) tuning
  change transfer fractions' numbers silently. Sharing them belongs with the
  roadmap item "Transfer fractions' peak finding onto `peaks.py`".
- **`search_bounds` and `search_warnings` stay in the script.** They read the
  plot's values by `SEARCH_MIN.name`, `SEARCH_MAX.name`, `MODE.name` and `AUTO`:
  parameter glue, and moving them would need the specs in `orders.py` (a cycle)
  or new arguments (a signature change).
- **`jump`'s "no detection" sentinel.** It compared with `CENTRE.default`.
  `orders.DEFAULT_CENTRE = 2.1375` now holds the value, and the script's
  `CENTRE` spec takes its default from it, so the two can't drift. Same value,
  same signature; `test_transfer_fractions.py` still passes
  `tf.CENTRE.default`.
- **`DecadeLogAxis` not replaced by `plot_axes.GroupedAxis`.** Their
  `logTickValues` are the same code, and a check over nine log ranges
  (−0.3…0.2 to −1…9 decades, pyqtgraph 0.14.0) gave identical tick values in
  all of them. But the tick *strings* and the axis label differ once the range
  reaches 10⁹: `GroupedAxis.__init__` turns off pyqtgraph's auto SI prefix, so
  for −1…9 `DecadeLogAxis` labels "Events (x1e+09)" with rescaled ticks
  (`10⁻¹⁰ … 1`) and `GroupedAxis` labels "Events" with `0.1 … 10⁹`. Not
  provably identical, so `DecadeLogAxis` stays in `basic_plots.py`
  (`GroupedAxis` reads better there; proposed as a behaviour change for later).
  Check script: kept out of the repo (scratchpad `axis_check.py`).

## Equivalence check

Beyond the tests, a scratch script ran `TransferFractions.compute` from the
pre-move file (`git show 9cf8782:…`, only its `overlay_newest` import repointed)
and from the new code on 60 random datasets (random centres, spacings 5–20 ms,
widths, stray events, XY spread) × 4 settings (auto; manual; Search T with both
ends and a stale centre; highlight with Window ±, orders each side and reference
varied): all 240 `Fractions` were field-for-field identical (arrays with
`array_equal`, notes and floats exactly).

## Tests

- New `tests/test_orders.py` (6 tests): `orders` imports no Qt or plotting
  library (subprocess), `order_label`/`in_box`, `window_half` clipping,
  `guided_spacing` (reference-guided, a bump between orders is none), `unsure`
  (warning vs the plain line with both Search T ends), `chosen_by_search`.
  `count_orders` and `jump` already had direct tests; `detect` is covered by the
  plot tests and the MATLAB comparison.
- Targeted (`-n 2 --reruns 2`): `test_transfer_fractions.py`,
  `test_transfer_fractions_matlab.py`, `test_plot_backends.py`,
  `test_analysis.py`, `test_analysis_gui.py`, `test_live_plots.py`: 318 passed,
  no reruns; `test_orders.py` 6 passed.
- Typing: `mypy helab --strict` (121 files), `mypy tests --strict` (95 files),
  `pyright helab tests`: clean.
- Full suite (`-n 2 --reruns 5 --reruns-delay 1 -rR`, on the final tree):
  2189 passed, 9 skipped, 2 xfailed in 6 min 26 s, **no reruns**. The first
  commit's intermediate tree (orders moved, overlay not yet): the transfer
  fractions, MATLAB, plot backend and orders tests (120 passed) and strict mypy
  on the touched files.

## Open points / proposals (not done, per the brief)

- `DecadeLogAxis` → `GroupedAxis` (see above): a behaviour change at ≥ 10⁹
  events per bin, for Tony.
- Transfer fractions onto `peaks.find_time_peaks` (roadmap item): would share
  `smooth` and the constants, but changes the numbers (few-event bins, grid
  times, edge peaks), so it needs the MATLAB tests rechecked.
- Typed widget subclasses for the standard scripts' ad-hoc attributes
  (`counts_curve`, `histogram_layout`, `order_numbers`, `fraction_curves`,
  `order_windows`, …, read back with `getattr`/`hasattr`); unit/range text and
  title-path consolidation: left for later, as briefed.

## Commits

- `07738f1` Move transfer fractions' order detection into helab/analysis/orders.py
- `ea968ae` Move the newest-shot overlay helpers into helab/analysis/overlay.py
- this notes file

Not pushed, not merged (per the common brief; the coordinator reviews and pushes).

## Review (coordinator, 2026-10-20)

An independent reviewer subagent read `9cf8782..5f4f7be`, comparing definitions by
AST against the originals, and found no correctness issues: verbatim moves (`jump`
differs only by `CENTRE.default` → `DEFAULT_CENTRE`, the same value), identical
`half_maximum_width`/`refine` (neither reads a module constant), no stale patch
targets, DLD untouched, `orders` loads no Qt or plotting library, docs accurate.
One nit fixed by the coordinator: three triple blank lines in `orders.py` left where
removed functions had been (E303). Targeted tests (61) and strict mypy re-run after
the fix.
