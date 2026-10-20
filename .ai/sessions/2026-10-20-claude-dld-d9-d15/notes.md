# Notes: D9 masks and the D15 finder placeholder

[Brief](brief.md) · [Handoff](handoff.md)

## What was built

- **`helab/analysis/masks.py`** (new): `Circle`, `Mask`, `MASK_SPECS` (the Mask group: `mask_mode`
  none / preset / custom, `mask_preset`, `mask_circles`), `parse_circles` / `format_circles`,
  `mask_from`, `mask_brief`, `mask_warnings`, `apply_mask`, `masked_counts_per_shot`, the presets
  and the rotation helpers. `selection.py` is untouched (kept the shared module conflict-free).
- **`ParameterSpec` kind `"text"`** (`helab/analysis/parameters.py`): free text, coerced to `str`,
  a pyqtgraph `text` item (multi-line) in the settings tree; its source-line text joins lines
  with "; ". Additive: no other kind changed.
- **`helab/analysis/hotspots.py`** (new): `find_hot_spots`, `HotSpotSearch`, `search_lines`.
- **Wired plots** (each with the Mask group, `mask_brief` in its settings line, `mask_warnings`,
  "N masked out" in its title, "All N events … are masked out (Mask settings)" when nothing is
  left, and its version bumped):

  | Plot | Version | Where the mask applies |
  | --- | --- | --- |
  | Counts per shot | 3 → 4 | each shot's count (`masked_counts_per_shot`) |
  | Shot times | 2 → 3 | each shot's count |
  | T, X, Y histograms | 5 → 6 | the chosen events and the newest shot's |
  | Density images | 1 → 2 | before the view range; the newest shot's contour too |
  | Mean X, Y against T | 1 → 2 | before the view range |
  | T spectrum | 1 → 2 | before the view range |
  | 3D scatter | 3 → 4 | before the crop; the newest shot's points too |
  | Transfer fractions | 6 → 7 | per shot, before its XY box |

  Shot trends (D2) is not merged: not wired. When it is, add `*MASK_SPECS` and apply
  `mask_from(values).apply(...)` (or `masked_counts_per_shot`) as above.

## Rules (choices; proposed, for Tony where marked)

- **Keep/cut:** as `masktxy_2d_circle`: an event stays when inside every keep circle and outside
  every cut circle (ANDed, so two keep circles keep only their overlap).
- **Boundary:** inside is strictly closer than r (`radial_diff < radius` in the MATLAB): an event
  exactly on a circle is outside, so a cut keeps it and a keep drops it. Matches the lab.
- **T is never masked**; the mask is XY only, before the view range / auto-crop (the crop then
  finds its box among the events that remain).
- **Text format:** `x, y, r[, keep|cut]` in mm, circles separated by ";" or new lines, cut if the
  fourth is left out; "keep"/"cut" (also k/c, and 1/0 as the lab's polarity), "−" read as minus.
  "," separates numbers, so decimals must use "." (the tip says so). Errors name the circle and
  why ("Mask circle “1, 2”: needs x, y and r in mm…"); the run then **fails** with that message
  (the last plot stays, status "Failed: …") rather than plotting unmasked, and the settings tab
  shows it as a warning. Proposed, for Tony: failing beats silently ignoring a typo.
- **An empty mask** (custom with no circles, or the empty current-detector preset) masks nothing
  and warns ("Mask preset “current detector” has no circles yet: nothing masked").
- **Drawn circles** (XY only): keep white, cut red, found amber, all dashed, over the image.
- **Mask in the reuse key:** it is part of the run's parameters (`mask_mode`, `mask_preset`,
  `mask_circles`), so `reuse_key()["parameters"]` and the dock record carry it. A preset is
  recorded by name, not by its circles: if a preset's circles ever change, bump the plots'
  versions or add the circles to the record (proposed, for Tony).

## Presets: source and transform

- **Source:** `HeBECANU/Core_BEC_Analysis` `lib/txy_tools/hotspot_mask.m` at `408d856`
  (2021-11-05), the active list "updated 2020-06-14 using some tune out data" (count rate 474 Hz
  without the mask, 30.7 Hz with it). Read from a fresh clone of the public repo, since
  `legacy/DLD_front_panel` is empty in this worktree.
- **Correction to the review notes:** [core-update.md](../2026-10-20-claude-dld-front-panel-review/core-update.md)
  listed nine cut circles of r 2–4 mm; that is the commented-out 2019-11-20 list. The active list
  has **one keep circle (0, 0, r 38 mm) and 13 cut circles of r 1–6 mm**, ported here as they are.
  Not ported: its square pre-mask (T all, X/Y ±50 mm), which the 38 mm keep circle already lies
  inside; three commented-out circles; the 2023 front-panel "new detector" spot
  (3.44, 18.96) mm r 5.5 mm (a hint, not a preset, as Tony decided; mentioned in no preset).
- **Frame:** the lab masked after `import_mcp_tdc_data` rotated XY by `dld_xy_rot` = 0.61 rad:
  `txy · [1 0 0; 0 cos α −sin α; 0 sin α cos α]`, α = −0.61, row vectors, i.e. a rotated point is
  R(+0.61)·(x, y) (x′ = x cos 0.61 − y sin 0.61, y′ = x sin 0.61 + y cos 0.61). HeLab never
  rotates, so each centre is `unrotate`d by R(−0.61); radii and the origin keep circle don't
  change. 0.61 rad, not 0.93: the list dates from 2020, before the 2023 change to 0.93 with the
  new plates. The test checks the round trip and that the lab's own matrix maps HeLab's centres
  back onto the MATLAB values.

| Lab (rotated frame), mm | HeLab, mm | r, mm | |
| --- | --- | --- | --- |
| 0, 0 | 0, 0 | 38 | keep |
| 5.788, 35.61 | 25.14, 25.87 | 4 | cut |
| 13.99, 31.79 | 29.68, 18.04 | 2.5 | cut |
| 22.69, 28.41 | 34.87, 10.29 | 3 | cut |
| 29.82, 20.82 | 36.37, −0.02 | 3 | cut |
| 30.5, 5 | 27.86, −13.37 | 4.5 | cut |
| 35.6, 5.6 | 32.39, −15.80 | 4.5 | cut |
| 30.5, −15.71 | 16.00, −30.35 | 6 | cut |
| 25.36, −19.8 | 9.44, −30.76 | 3 | cut |
| 27.79, −23.24 | 9.46, −34.97 | 3.5 | cut |
| 23.81, −26.49 | 4.34, −35.35 | 3 | cut |
| 19.16, −29.46 | −1.17, −35.12 | 4 | cut |
| 2.48, −34.8 | −17.90, −29.94 | 2 | cut |
| 26.96, 21.46 | 34.39, 2.15 | 1 | cut |

All cut circles sit at 30–37 mm from the centre: the earlier detector's edge. The lab's import
also cut to ±30 mm (a square in the rotated frame) before masking, so some never mattered there.

- **Current detector:** empty (`PRESETS[CURRENT] = ()`, a TODO(D15)). Fill it from the finder on
  the current detector's data once Tony accepts the circles (a code change for now; saving a
  preset from the finder is later work).
- Preset names: "earlier detector (2020)" and "current detector" (proposed, for Tony).

## D15 placeholder finder

- **Where:** a second action of Density images, **Find hot spots** (no new module, so the bundled
  plot list and `standard.MODULES` don't change while D2 adds its plot). Its own settings: Shots,
  View range (auto-crop default **100 %** here, so edge spots stay in), Mask, Bin width
  (0.5 mm), Above (5 × median), colour scale.
- **Rule** (roadmap's placeholder plus a noise floor; proposed, for Tony):
  - image: XY counts in square bins of the set width over the view range (at most 1000 a side);
  - background: the median of all bins, or of the non-empty ones when most are empty (noted);
  - flagged: count > max(k × median, median + 5 √median, 1), so Poisson noise on a sparse image
    isn't flagged (k alone flags noise when the median is ~1); **k = 5 proposed**;
  - touching flagged bins (8-connected) make one spot: centre = excess-weighted mean of their
    bin centres, radius = farthest flagged bin centre + half a bin's diagonal, rounded up to
    0.01 mm; strongest (largest excess) first, at most 50 listed.
- **Offer, never apply:** the found circles are drawn amber on the image, listed in the dock
  record (each spot, the rule, and the circles as mask text) and the settings line ("3 hot spots
  found"), and **Copy circles** puts them on the clipboard as cut circles in the custom-mask
  format. Nothing writes them into any setting: no `detected_parameters`, the mask mode stays as
  set. Proposed, for Tony: a "Use as this plot's mask" button could come later, still a click.
- **Limits:** anything bright is a "spot" (an atom cloud too): set a T window without atoms.
  The real finder (persistence across shots, a smoothed background, a saved detector preset) is
  still to be designed on current-detector data, as the roadmap says.

## Validation

- `tests/test_masks.py` (new, 40 tests): keep/cut and the boundary, ANDed circles, parsing and
  round trip, every invalid case with its message, a failing run and its warning, briefs and
  empty masks, the rotation round trip and the lab's matrix, a preset cutting a spot in HeLab's
  frame, every wired plot's total dropping by exactly the events inside the circle plus `masked`,
  the dock line and the reuse key, all-masked empty panes, the newest shot masked, density's
  dashed circles (and none on XT or without a mask), the text kind in the tree, the finder on
  three planted spots over a flat field, on dense and sparse noise (nothing found), its rule on a
  hand-made image, and nothing auto-applied (copy button, then pasting cuts the spots).
- `tests/test_analysis_gui.py`: a mask typed in a plot's settings tab (dock line, record, then a
  bad circle failing with its reason and keeping the last plot); Find hot spots from the panel.
- Version expectations updated in `test_analysis.py`, `test_analysis_gui.py`, `test_live_plots.py`,
  `test_plot_text.py`, `test_density_images.py`; the Scripts panel test (`test_script_system.py`)
  expects Density images' second button, Find hot spots.
- Full suite (`-n 2 --reruns 5 --reruns-delay 1`): 2 failed, 1819 passed, 7 skipped, 2 xfailed,
  10 reruns, all of them the two root-only failures (`test_constants.py::test_read_only_saved_folder_is_replaced`,
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`, 5 reruns each).
  An earlier run also reran `test_dash_server.py::test_stop_frees_the_port` and
  `test_two_step_browse.py::test_refresh_cancels_only_automatic_subscriptions_and_suppresses_new_checks`
  once each (timing, unrelated). The typing tests need the venv's `mypy`/`pyright` first on PATH.
- mypy --strict helab and tests, pyright helab tests: clean. `git diff --check`: clean.
- Renders (scratchpad, not committed): `preset.png` (density XY, earlier preset: white keep,
  red cuts), `find.png` (three planted spots found, amber circles, Copy circles),
  `find_masked.png`.

## Follow-ups (proposed, for Tony / the Coordinator)

- AGENTS.md's Script system paragraph could name the Mask group next to Shots and View range
  (left to the Coordinator to avoid merge conflicts).
- D2 shot trends: wire the Mask when merged.
- A Mask in the 3D scatter could draw the circles too (Plotly cylinders); not done.
