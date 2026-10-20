# D3 notes: design choices (proposed, for Tony)

Code: `helab/scripts/standard/density_images.py` (`DensityImages`, "Density images",
`helab.density_images` v1), registered in `helab/scripts/standard/__init__.py`. Tests:
`tests/test_density_images.py`, plus the shared lists in `tests/test_analysis.py`,
`tests/test_script_system.py` and `tests/test_live_plots.py`. No shared helper changed:
`selection.py` and `stats.py` are used as they are.

## Choices

1. **One plot with a Projection choice (XY default), not one action per projection.** The
   Scripts panel shows at most two action buttons per script (`actions[:2]` in
   `ScriptTreeSelector`), so three actions would not fit; and a choice lets a plot switch
   projection in its settings and rerun, keeping its Shots and range. Opening three plots
   gives the old GUI's three panels side by side. *Proposed.*
2. **Orientation:** XY has X across and Y up, with the aspect locked (both in mm: the cloud's
   true shape). XT and YT have T across (time along the horizontal axis), X or Y up, aspect
   free. The legacy `dld_2dplotter_window_a.m` wasn't in this checkout to compare.
   *Proposed.*
3. **View range is a box over T, X and Y**, from the same rule as the 3D scatter: auto-crop
   (`stats.crop_box`, default keep 99 %) or the manual bounds (`selection.manual_box`). The axis
   not shown is a window: e.g. XY with T bounds shows one pulse. The image spans the box's two
   shown axes. Reversed manual bounds use the full extent and warn (the shared
   `range_warnings`), on the figure, in the dock's line and in the settings. *Proposed:* an
   alternative was the histograms' per-axis 1D ranges, but then XY could not select a T window.
4. **Bins per axis:** one setting for both axes; 0 (default) = automatic per axis
   (Freedman–Diaconis over the box, at most 400). Set: up to 1000 (8 MB per image). The old
   GUI's default of 201 and its forced-odd count are not kept. The bin area uses the real bin
   count (the old GUI divided by `bins` where there are `bins − 1`).
   **XY with automatic bins (after review):** one bin width for both axes, the smaller of the
   two Freedman–Diaconis widths (widened if an axis would pass 400), so pixels are square under
   the locked aspect, to within one bin's rounding (`automatic_bins`). XT/YT keep a width per
   axis; set bins stay as set. *Proposed.*
5. **Blur:** `scipy.ndimage.gaussian_filter`, σ in bins (0 = off), `mode="reflect"`, which
   keeps the image's total (tested); `constant` would lose events at the edges.
   **Capped (after review):** σ is at most a quarter of the image's longer side (at least 1 bin;
   `blur_limit`), and the figure's title warns when it was lowered ("blur σ 30 bins is over a
   quarter of the image's 25 bins: using 6.25"). Beyond that the image is nearly flat, and the
   cap with the 1000-bin and 50-bin limits bounds a Live rerun's blur cost. *Proposed.*
6. **Show: counts per bin, or rate per shot** = counts / shots chosen / bin area in display
   units: events / mm² / shot (XY) and events / (mm·ms) / shot (XT, YT; per s when T is in s).
   The rate is computed after the blur (the blur keeps the total, so the order doesn't matter).
   The colour bar is labelled accordingly, with "(blurred)" when blurred.
7. **Colour compression in the colour map only:** linear (default), sqrt (the old GUI's
   "LogScale", `counts.^0.5`), log (spanning N decades below the maximum, default 3), power γ
   (default 0.5). The result's image stays linear. **Fixed after review:** the first version
   attached the image to a `ColorBarItem` with a resampled viridis map, but pyqtgraph applies a
   bar's map in 256 steps (`getLookupTable(nPts=256)`), so every value below 1/256 of the
   maximum was drawn in the darkest colour (log 3+ decades, small γ). Now the image item draws a
   display copy, `compress(image / max)`, over plain viridis (a 1024-entry LUT) with levels 0…1,
   which is exact at any depth (tested on the rendered QImage's pixels at 1e-3 and 1e-2 of the
   max); the bar is only a legend, not attached to the image: the resampled gradient over a
   linear axis in real values, 0…max (not interactive: a rerun would reset it).
   *Proposed:* an interactive colour bar (drag the levels) is a later option.
8. **Units:** X and Y in mm; T in ms while both ends of its range are under 10 s, else s
   (`density_images.time_unit`), per the roadmap. **Inconsistency to note:** the existing plots
   (histograms, 3D scatter, Transfer fractions) still label s and m, and the manual View range
   bounds stay in s and m with SI prefixes (shared `selection.BOUNDS`). This plot follows the
   roadmap for its display axes only. A shared display-unit helper (for D1's histograms too) is
   proposed; `time_unit` could move to `stats.py` then.
9. **Newest shot:** the shared "Highlight the newest shot" option draws its image (same bins,
   blurred at least 2 bins) as a contour at half its maximum, in the chosen colour (the notes'
   "highlighted as a contour"). *Proposed:* contour level and blur fixed for now.
10. **Live:** `LivePolicy(min_delay=2.0)`: the auto-crop of ~1.1 M events took about 1.5 s here
    (4 shared cores), as the scatter's does. Reruns draw in place (`update`): the same
    `DensityPlot`, image and colour bar, keeping zoom and pan, unless the projection changes,
    T's unit changes on a plot showing T (XT, YT; never XY), or the plot was or becomes empty; a
    new colour scale changes the bar's gradient, and counts ↔ rate per shot its label.
11. **Empty:** no shots, none chosen, no events (the shared `empty_text`), and a manual range
    with no events inside ("None of the N events in the chosen shots is inside the view range
    (View range settings)", plus any range warning). The old GUI crashed on an empty window.
12. **RAM budget:** the result is a frozen dataclass of NumPy arrays (`image`, `newest`,
    `edges_h`, `edges_v`), which `ram_buffers.arrays_in` finds, so plots count them (tested).
    Only the displayed image is kept, not a second copy of the raw counts.
13. **Widget:** `DensityPlot` is a `QWidget` holding a `pg.GraphicsLayoutWidget` (`graphics`),
    not a subclass of it: pyright can't see pyqtgraph's methods on a subclass.

## Not done (later)

- 2D Gaussian fit (the old GUI's fit block was broken anyway).
- Hot-spot circles on XY (D9 / D15).
- Choosing the colour map; an interactive colour bar.
