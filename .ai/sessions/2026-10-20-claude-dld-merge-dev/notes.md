# Merge of `dev/v0.0.6` into the DLD front panel port (2026-10-20, Claude, cloud)

Branch `agent/dld-merge-dev`, from `origin/agent/dld-front-panel-port` (0eeb624),
merging `origin/dev/v0.0.6` (919ff11). Base of both: 1231025.

## What each side brought

- **dev/v0.0.6** (7f8c794, 9be02fe, 97cf3ef, 2432081 and their merges):
  `helab/analysis/backends.py` (PyQtGraph / Plotly / Matplotlib, `MatplotlibPane`,
  `opengl_available`); `DatasetAnalysis.backends()` / `draw(result, backend)`; the
  Drawing › Library choice in every Basic plots v1 plot (counts per shot, T/X/Y
  histograms, 3D scatter, transfer fractions), switching without a rerun
  (`AnalysisInstance._backend_changed`, "Drawn with …" in the record); every plot
  updated in place on Live reruns in every library; transfer fractions' newest-shot
  highlight (v7); `tests/test_plot_backends.py` and Live tests per library.
- **agent/dld-front-panel-port**: the DLD port (constants, fits, BEC readout, masks,
  ms/mm display, wrapped titles, amber, in-place PyQtGraph updates, eight new plots;
  see the [register](../2026-10-20-claude-dld-coordinator/register.md)).

## Tony's decision (via the coordinator, during the merge)

Not one merged set of plots: the port's plots go into their own Scripts panel group,
**"DLD Front Panel Port"**, and **"Basic plots v1" stays exactly `dev/v0.0.6`'s**.

## Resolution, file by file

| File | Resolution |
|---|---|
| `helab/scripts/standard/basic_plots.py`, `transfer_fractions.py`, `scatter_3d.py`, `__init__.py` | `dev/v0.0.6`'s, byte for byte (`git diff origin/dev/v0.0.6 -- helab/scripts/standard/` is empty). Same ids and versions: counts per shot v2, histograms v3, scatter v3, transfer fractions v7. |
| `helab/scripts/dld/` (new package) | `group.py` (`NAME = "DLD Front Panel Port"`), `__init__.py` (`MODULES`, same order as the port had). Our `basic_plots.py`, `transfer_fractions.py`, `scatter_3d.py` from 0eeb624 with new ids `helab.dld.counts_per_shot`, `helab.dld.txy_histograms`, `helab.dld.scatter_3d` (its Plotly `uirevision` too), `helab.dld.transfer_fractions`, all version 1; titles unchanged. The eight other port plots moved here from `standard/` (`git mv`), ids and versions unchanged (a group move doesn't change results). Imports `helab.scripts.standard.*` → `helab.scripts.dld.*`. PyQtGraph only (the scatter Plotly), as on the port: `backends()` is the default `()`, so no Drawing group. |
| `helab/analysis/selection.py` | dev's plots need the old SI display: `BOUNDS` again without a fixed prefix (SI prefixes, as on dev), `FIXED_BOUNDS` with `unit_prefix="m"`; `range_specs(tip, fixed=False)`; `range_text` is dev's SI one again, and `range_brief(values, fixed=False)` uses it, `fixed=True` the port's `display_units.range_text` (ms/mm grouped). Every port plot passes `fixed=True` to both. Same parameter names and values (s, m) either way. |
| `helab/analysis/stats.py` | `axis_text` restored (dev's scatter imports it). |
| `helab/models/ScriptTreeSelector.py` | Union: our constants/hooks/owner/live/unused code and dev's `backend()`, `_draw`, `_backend_changed`, `_drawn_with` (`_updated` refuses another library). The dock record gets our constants and `result_record` lines, then "Drawn with …". `_backend_changed` uses our guarded `_hook("parameter_warnings", …)`. Registers `(*standard.MODULES, *dld.MODULES)`. |
| `helab/scripts/base.py`, `tests/test_analysis_gui.py`, `scatter_3d` | auto-merged, then `scatter_3d` replaced by dev's (above). |
| `AGENTS.md` | Union; Script system describes both groups; Visualization keeps dev's libraries text for Basic plots v1 and says the port's plots name no library; the DLD paragraph's units and plot list say they're the port's (Basic plots v1 keeps s/m). |
| `roadmaps/dld-front-panel-port.md`, coordinator register | where the code is now and why. |

## Tests

- `test_plot_backends.py`: dev's (Basic plots v1 × every library), plus
  `test_the_dld_port_plots_offer_no_choice_of_library` (all 12 port plots: fewer
  than two backends, no Drawing spec).
- `test_live_plots.py`: dev's file, plus the port's: the coverage/reuse-key and
  "say why they're empty" lists hold both groups (ids name the package), our Live
  tests (release time, correlations, shot times, density, position/spectrum), our
  in-place tests on the port's histograms and counts (`test_a_following_dld_…`), the
  port's live policies and versions.
- `test_analysis.py`: dev's file plus: fixed (ms/mm) range text, the port's
  histograms' settings line, `test_dld_scatter_draws_in_ms_and_mm`, both groups'
  identities (no shared ids), shots brief for the port's plots, our runner
  `result_found` test.
- `test_analysis_gui.py`: dev's expectations for Basic plots v1 (v3, "T min 0 s");
  our mask, hot spots and fits tests on the port's plots, which also check no
  Drawing group and no "Drawn with".
- `test_transfer_fractions.py` is dev's (Basic plots v1); our version is
  `test_dld_transfer_fractions.py` on `helab.scripts.dld.transfer_fractions`.
  `test_transfer_fractions_matlab.py` (untouched by either side) tests Basic plots v1.
- `test_script_system.py`: both groups, Basic plots v1 shown first.
- The port's own test files import `helab.scripts.dld` and expect group
  "DLD Front Panel Port"; version checks of the port's histograms and counts say 1.
- `test_display_units.py`: `range_specs` shows SI prefixes by default, ms/mm with `fixed`.

## What each library can't draw

Nothing new: Basic plots v1 is dev's (its own limits: Plotly draws the newest shot
scaled with its real counts in the hover text, no right axis; PyQtGraph's 3D view needs
OpenGL). The port's plots draw with PyQtGraph only (3D scatter: Plotly), so fits,
BEC readout, smoothing, rates, masks and ms/mm aren't drawn in Plotly or Matplotlib;
porting them to more libraries is open.

## Checks

- `mypy helab tests --strict`: no issues (210 files). `pyright helab tests`: 0 errors.
  `git diff --cached --check`: clean.
- Offscreen renders in the scratchpad (`merge-dev/`): dev's counts, histograms
  (newest shot) and transfer fractions (newest shot) in PyQtGraph, Matplotlib and
  Plotly (HTML + figure titles/traces), dev's scatter in Matplotlib; the port's
  histograms with a bimodal TF² + Bose fit on X and the BEC readout (N0/N 0.615,
  T 602 nK, QE checks 0.101 / 0.099: the synthetic truth), transfer fractions (ms,
  grouped), counts and a density image. All sane.
- Seen, not changed (the port's, before this merge): the port's transfer fractions
  label its fraction axis "Transfer fraction (x0.001)" (pyqtgraph's SI prefix on a
  plain axis); worth `enableAutoSIPrefix(False)` or a `GroupedAxis` there.
- Full suite, `python -m pytest -n 4 --reruns 5 --reruns-delay 1 -rR`: 2 failed, 2152
  passed, 7 skipped, 2 xfailed, 12 reruns. The two failures are the root-only ones
  (`test_constants.py::test_read_only_saved_folder_is_replaced`,
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`, 5
  reruns each); the other reruns, each passing on its first retry:
  `test_analysis_gui.py::test_scatter_from_the_panel` and
  `test_live_plots.py::test_a_following_plot_keeps_following_in_every_library_and_after_switching[Matplotlib-TransferFractions]`.
