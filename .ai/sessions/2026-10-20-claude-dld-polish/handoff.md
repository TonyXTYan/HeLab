# Handoff: DLD plots polish

Branch `agent/dld-polish` (from `6a9671e`), one commit. Not pushed or merged. Details, judgement
calls and the naming table: [notes.md](notes.md).

## Done (review backlog 1–10; 11 skipped, nothing built)

1. Titles wrap (`helab/analysis/plot_text.py`: `WrapLabel`, `add_label`, `set_plot_title`); one
   note per line; histogram fit notes short in the title, whole in the dock record. Every bundled
   plot fits a 560 px dock (test checks titles and plots, axes included, within the width).
2. Constants editors sized from font metrics (grow with the value); name labels wrap at 14 em;
   Folder constants never smaller than its content and sized after its first update.
3. Histograms and Counts per shot update in place (zoom kept); the histograms rerun at most once a
   second while following Live (always: the policy API is per plot, not per settings; proposed,
   for Tony).
4. One `AMBER` (`helab/utils/colours.py`, `#b26a00`) for plot titles, the Lab tab, Folder
   constants and the folder views; "⚠ …" amber in every title; shot times escapes its title.
5. T spectrum: no-peak line in the amplitude unit; power axis "kHz² per shot²".
6. Shot times: a key line under the title replaces the legends over the data.
7. Mean position: the bins-left-out line once in the record.
8. Titles renamed (keys unchanged): Log Y ×2, Log Y (gaps), Bins (0 = auto), Bins per axis
   (0 = auto), kHz per shot, Restore. Group names kept (proposed, for Tony).
9. Newest-shot highlight in Counts per shot (v3) and Shot times (v2).
10. Density colour bar: "Events per bin · colours log, 3 decades, values linear".

## Renders (scratchpad `rv-ui-probes/`)

| Before (`png2/`) | After (`png3/`) |
| --- | --- |
| `hist_log_newest_small.png`, `hist_default_narrow.png` | `hist_log_newest_small.png`, `n_hist_fits.png` (560 px, all fits, smoothing, newest) |
| `hist_fits_rate_smooth_newest.png` | `hist_fits_rate_smooth_newest.png` |
| `counts_per_shot.png` | `n_counts.png` (newest marked) |
| `shot_times.png` | `n_shot_times.png` (key line, newest, amber warning) |
| `t_spectrum_small_power.png` | `n_tspec.png` (power, no-peak line) |
| `density_XT_rate_log_small.png` | `n_density.png` (log bar label, amber warning) |
| `mean_position_spectrum.png` | `n_mean.png` (notes one per line) |
| `transfer_fractions.png` | `n_transfer.png` |
| `folder_constants_set.png` | `folder_constants_set.png` (416.090779871 ms whole) |
| `lab_parameters.png`, `lab_parameters_narrow.png` | same names |

## Validation

See the commit message for the full-suite line. `mypy helab/ --strict`, `mypy tests --strict`,
`pyright helab tests` and `git diff --check` clean.

## Open

- Mean position's in-plot legends cover the traces' right ends at narrow widths (not in the
  backlog); a key line as in shot times would fix it.
