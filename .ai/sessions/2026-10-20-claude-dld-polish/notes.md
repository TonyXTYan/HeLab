# Notes: DLD plots polish

Renders (offscreen, the review's synthetic halo run with a long folder name) are in the
session scratchpad, `rv-ui-probes/`: before = `png2/`, after = `png3/` (script `render3.py`,
the review's `render2.py` writing to `png3/` plus `n_*` renders of every plot at 560 px).

## 1. Titles that fit (`helab/analysis/plot_text.py`)

- A pyqtgraph `LabelItem` never wraps and makes its unwrapped width its minimum, so the
  GraphicsLayout grew past the view and the right of every plot was cut. `WrapLabel` sets the
  text item's `textWidth` to the width its layout gives it (in `setGeometry`) and asks for the
  height that takes; its minimum width is 60 px, its preferred width the unwrapped one.
- Two traps found while checking the renders:
  - A layout's first pass can give 0 px: wrapped one letter a line, the title asked for ~1,900 px
    of height, and the view's top item (which a pyqtgraph view sizes only on resize) kept that
    height, so the plots ran off the bottom. The wrap width never goes under 60 px.
  - When a title gets shorter (the dock widens), `setGeometry` had already grown the top item to
    the old minimum: `WrapLabel._refit` (zero timer, once) sets it back to the view's range.
- `set_plot_title` swaps a `PlotItem`'s title label for a `WrapLabel` (keeping the `titleLabel`
  name, so `plot.titleLabel.text` still works) and lifts `setTitle`'s fixed 30 px title row.
  Plot titles now use the app font, as the headers (they were 11 pt).
- One note per line (`notes_html`), each amber; a title line is amber from its first "⚠" on
  (`line_html`), since every title puts its warnings last. The histograms' fit notes are shown
  without a trailing parenthesis's details in the title (`short_note`: "the Poisson weights did
  not settle in 10 rounds"); the dock's record keeps them whole, and now also the smoothing bins'
  notes (`Histograms.record_lines`).
- Shorter titles: automatic histogram bins say "(auto)" instead of "(automatic, Freedman–Diaconis)"
  (the Bins tip names the rule); mean position and T spectrum put each note and warning on its
  own line.
- Test: `tests/test_plot_text.py::test_every_plot_fits_a_560_px_dock` (8 plots/configurations:
  every title and plot, axes included, within the view's width, and each data area > 100 px).
  Checked that it fails with wrapping disabled (6 of 8 fail). A widening test checks the refit.

## 2. Constants editors

- `LabParametersTab.fit_width`: at least the width of the value shown and of "−0,000.000000" with
  the unit, plus 40 px for the buttons and frame; it grows when a longer value is set, never
  shrinks. `name_label`: names wrap at a 14-em minimum width (a narrow column wrapped the source a
  word a line). Status labels wrap. "Restore default" is "Restore" (as in Folder constants).
- `FolderConstantsDialog`: `SetMinimumSize` (never smaller than its content) and `adjustSize()`
  after the first update. Folder constants now shows "416.090779871 ms" whole.
- Tests: `test_lab_parameters.py::test_editors_are_wide_enough_for_their_values`,
  `test_folder_constants.py::test_the_dialog_shows_whole_numbers_and_sizes_to_its_content`.

## 3. In-place updates

- `HistogramsWidget` keeps its plots and items; `update()` sets their data while
  `histograms_key` (log Y, smoothing on, newest shot on, which axes are fitted, units) is the same,
  else draws anew. Units are in the key because the y scale changes by orders of magnitude (a
  kept zoom would show nothing). The newest shot's overlay is reused (`OverlayView.set_ratio`,
  `update_newest`).
- `CountsPlot` likewise (always in place while there is something to draw).
- Live policy: **always** `LivePolicy(min_delay=1.0)` for the histograms (proposed, for Tony):
  `live_policy` is per plot and action, not per settings, so "only with fits on" isn't expressible
  without changing the policy API; a second's wait is harmless without fits and keeps a fitted
  plot readable while shots arrive. Counts per shot keeps rerunning on every shot.
- Tests: `test_live_plots.py::test_a_following_histograms_plot_updates_in_place_keeping_its_zoom`
  (replaces "old drawing freed when redrawn": it zooms, publishes a revision, checks the same
  widget, the kept range and the moved overlay, then changes log Y and checks the old drawing is
  freed) and `test_a_following_counts_plot_updates_in_place_keeping_its_zoom`.

## 4. One amber

- `helab/utils/colours.py: AMBER = "#b26a00"` (the folder tree's, the most used); the plots'
  `#b06000` and the Lab tab's `#c77700` go. `FolderExplorer.AMBER`, `LabParametersTab.AMBER`,
  `FolderConstantsDialog.AMBER`, `basic_plots.NOTE_COLOUR` and `plot_text.AMBER` are all it.
- Shot times escapes its title now (a folder name with `<` or `&` showed as markup).
- The shot-times TXY points keep their brighter orange (230, 140, 0): a marker colour, not text.

## 5. T spectrum units

- The no-peak line names the threshold in the amplitude unit (`data.unit`), also for power.
- Naming (8): "kHz per shot" everywhere (the histograms' axis labels, from `profiles.RATE_UNITS`,
  already said it, and X/Y say "per mm per shot"; changing those would touch `profiles.py`). Power
  is "kHz² per shot²" / "events²" (it was "(kHz/shot)²").

## 6. Shot-times key

- The legends inside the plots are gone; a key line under the title shows the raw-time dot, the
  TXY triangle only when one is drawn, and the newest shot. Nothing sits over the data.

## 7. Mean-position record

- `left_out_note` is the one wording; the record's first line says it and the notes after it
  leave it out.

## 8. Naming (titles only; keys unchanged, so saved settings stay valid)

| Plot | Before | After |
| --- | --- | --- |
| T spectrum | Log scale | Log Y |
| Mean position | Log amplitude | Log Y |
| Shot times | Log gaps | Log Y (gaps) |
| Histograms | Bins | Bins (0 = auto) |
| Density images | Bins per axis | Bins per axis (0 = auto) |
| T spectrum | kHz/shot | kHz per shot |
| Lab parameters | Restore default | Restore |

Group names stay (Histogram, Smoothing, Fits; T profile, Spectrum; T bins, Spectrum; Image,
Colour; Plot): each names what its settings shape, and renaming them would move nothing.
(proposed, for Tony)

## 9. Newest shot

- Counts per shot and Shot times have "Highlight the newest shot" and its colour (group Plot,
  off by default): a larger point (9 px, `NEWEST_SIZE`) in the colour, in both shot-times plots,
  named in the title (counts) or the key (shot times) and the dock's settings line. Versions:
  Counts per shot 2 → 3, Shot times 1 → 2 (new parameters and result fields).

## 10. Colour bar

- `colour_bar_label`: "Events per bin · colours log, 3 decades, values linear" (sqrt, power γ
  likewise; linear unchanged).

## Not done / seen in passing

- The mean-position plots' legends (X, Y; mean X, mean Y) sit over the traces' right ends at
  narrow widths, like shot times' did; not in the backlog. A key line as in shot times would fix
  it.
- The constants spin boxes' text looks cut at the bottom in offscreen renders (descenders); it
  was so before and looks like the offscreen font, not the width.
