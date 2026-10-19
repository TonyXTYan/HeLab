# D3 handoff

Branch `agent/dld-d3` from `1231025` (`agent/dld-front-panel-port`), not pushed or merged.

## Done

- **Density images** (`helab/scripts/standard/density_images.py`, `helab.density_images` v1,
  group "Basic plots v1", one **Plot** button): a 2D density image of the chosen shots'
  events, projection XY (default), XT or YT, in PyQtGraph (`ImageItem` and a `ColorBarItem`).
  - Settings: Shots (shared); Projection; View range (auto-crop keep %, default 99 %, or manual
    T/X/Y: a box over all three, the hidden axis a window); Image: bins per axis (0 = auto),
    blur σ in bins, Show (counts per bin / rate per shot), highlight the newest shot (a
    contour); Colour: linear / sqrt / log (N decades) / power γ.
  - X and Y in mm, T in ms (or s beyond 10 s). Colour compression is in the colour map only:
    image and colour bar stay linear, in real values.
  - Empty views and ranges say why; reversed manual bounds warn; reruns draw in place
    (zoom kept); Live reruns at most every 2 s; result arrays count toward the RAM budget.
- Design choices and their reasons: [notes.md](notes.md) (all proposed, for Tony).
- Renders on synthetic data (a pulsed atom laser, 20 shots, blur 1, sqrt, rate per shot,
  newest shot contoured): `render-XY.png`, `render-XT.png`, `render-YT.png`, made by
  `render_density.py` (run with `PYTHONPATH=<checkout> QT_QPA_PLATFORM=offscreen`).

## Checks

- `tests/test_density_images.py`: 22 tests (counts vs `np.histogram2d` for each projection,
  rate per shot, time unit, blur keeps the total for σ 0.5/2/30, colour compression leaves the
  data alone and resamples viridis, auto-crop and bins, Shots and coverage, empty notes,
  reversed range, one-value events, offscreen render shape/rect/labels/levels/aspect, newest
  contour, update in place, RAM-budget visibility, cancellation, discovery).
- Shared tests extended: bundled-group lists (`test_analysis.py`, `test_script_system.py`);
  coverage/reuse key, empty plots, Live policy and a following plot drawing in place
  (`test_live_plots.py`).
- `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`: clean. `git diff --check`: clean.
- Full suite (`-n 2 --reruns 5 --reruns-delay 1`): see the final line below.

`2 failed, 1304 passed, 7 skipped, 2 xfailed, 10 rerun in 202.14s`. The 2 failures (and all
10 reruns, 5 each) are the two tests that always fail as root:
`test_constants.py::test_read_only_saved_folder_is_replaced` and
`test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`. No other test
needed a rerun. (`tests/test_typing.py` needs the venv's `mypy`/`pyright` on PATH and a `venv`
link in the checkout for pyright; with them its 6 tests pass.)

## On screen for Tony (macOS)

1. Load a run, Scripts › Basic plots v1 › Density images › Plot: an XY image appears with a
   viridis colour bar on the right, "Events per bin", axes X (mm) and Y (mm), square aspect.
2. Settings › Projection XT, then YT: T (ms) across, X or Y (mm) up; a pulsed atom laser shows
   its pulses as columns.
3. Blur σ 1–2 bins: smoother, same total. Show › rate per shot: the bar reads
   events / mm² / shot (XY) or events / (mm·ms) / shot.
4. Colour scale sqrt / log / power γ: faint regions brighten, the bar's numbers stay real
   counts (its colours change, not its scale).
5. View range › manual with only T set (e.g. one pulse) on XY: the image shows only those
   events. A T min above max: full extent, "⚠ T: min > max, using full extent" in the title.
   A window with no events: the plot says so (the old GUI crashed).
6. Zoom into the image, then start Live: new shots redraw in place, the zoom stays, at most
   every 2 s. Highlight the newest shot: a contour in its colour.
7. Check the image's orientation against the old front panel's 2D Plot (I could not compare:
   `legacy/DLD_front_panel` is empty in this checkout).
8. Check that the plot paints on the Lab Side PC (no QtWebEngine needed).

## Proposed doc changes (not made; AGENTS.md and roadmaps are not mine to edit)

- AGENTS.md › Script system: after Transfer fractions, add: "**Density images**
  (`density_images.py`, D3) bins the events in its view range (a T/X/Y box: the hidden axis is a
  window) as XY, XT or YT with `np.histogram2d`, optionally blurred (σ in bins, total kept) and
  as counts per bin or a rate per shot; colour compression (sqrt, log, power γ) is in its colour
  map only, so the colour bar reads real values. X/Y in mm, T in ms or s from its range; the
  other plots still show s and m."
- AGENTS.md › Visualization: "PyQtGraph draws ... the 2D density images".
- `roadmaps/dld-front-panel-port.md`: mark D3 done once merged; note the open display-unit
  inconsistency (other plots still s/m) as a follow-up shared with D1, and the open choices in
  notes.md (one plot with a Projection choice, T across in XT/YT, contour for the newest shot).
