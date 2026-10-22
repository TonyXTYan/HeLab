# Result cache R2: notes (Cellar, 2026-10-22)

Floor "Result Cache", branch `agent/result-cache-r2` from `c3d4b50`.

## Commits

| Commit | What |
|---|---|
| `c31ac10` | Store schema and migration (reported to CoCo first) |
| `ef486d3` | Back end: store API, helper ops, codec, key module, script contract, runner prepare/enqueue |
| `bcdc12d` | Plot side: lookup before a run, exact reuse, outdated marker, save; Correlations and Release time opt in |
| `3e5a934` | Settings → Cache and Data roots: Clear cached analysis, purge by age |

## Measured run times (the opt-in list)

macOS (Apple silicon, this floor), synthetic data as the plots' own tests build it: 100 shots of a
released cloud, 5,000 events a shot (500,000 events) for most plots; Correlations on the thermal
source of `tests/test_correlations_plot.py`, 100 shots. Default settings unless named. "Read + unpack"
is the store read, the `.npz` read and `cache_unpack` in one process; "Shown" is the whole path in a
plot (a local-lane helper process, the read, drawing), measured through `AnalysisInstance` with real
helpers. Script: `timing.py` in this folder (run from the floor root after `source .ai/local/floor-env.sh`; it imports the plots' test modules).

| Plot | Settings | Data | Cold run | Read + unpack | Shown from cache | Saved size |
|---|---|---|---|---|---|---|
| DLD Release time | bootstrap 1000 (default) | 100 × 5,000 | **13.3 s** (12.5 s in a plot, with save) | 1.9 ms | **0.08 s** | 18 kB |
| DLD Correlations | radial, 400 events/shot | 100 × ~400 | **4.3 s** | 1.8 ms | ~0.09 s | 69 kB |
| DLD Correlations | radial, 1,500 events/shot | 100 × ~1,500 | **30.9 s** | 1.9 ms | ~0.09 s | 69 kB |
| DLD Correlations | 1D (default), 400 | 100 × ~400 | 0.19–0.33 s | 1.8 ms | 0.09 s | 57 kB |
| DLD Correlations | 1D (default), 1,500 | 100 × ~1,500 | 1.4 s | — | 0.09 s | — |
| DLD Velocity distributions | default | 100 × 5,000 | 0.54 s | — | — | — |
| DLD Density images | default | 100 × 5,000 | 0.39 s | — | — | — |
| DLD Mean X, Y vs T | default | 100 × 5,000 | 0.35 s | — | — | — |
| DLD T spectrum | default | 100 × 5,000 | 0.34 s | — | — | — |
| DLD 3D scatter | default | 100 × 5,000 | 0.35 s | — | — | — |
| DLD T/X/Y histograms | 3 fits on | 100 × 5,000 | 0.12 s | — | — | — |
| DLD T/X/Y histograms | default | 100 × 5,000 | 0.07 s | — | — | — |
| DLD Shot trends | default | 100 × 5,000 | 0.09 s | — | — | — |
| DLD Transfer fractions | default | 100 × 5,000 | 0.04 s | — | — | — |
| DLD Counts per shot, Shot times | default | 100 × 5,000 | < 1 ms | — | — | — |
| Basic v1 histograms / transfer fractions / 3D scatter | default | 100 × 5,000 | 0.06 / 0.04 / 0.33 s | — | — | — |

A local-lane helper starts and exits in ~0.03 s here (median of 5); a lookup is one helper. On the
lab's Windows PCs process start is slower (hundreds of ms), which still beats any run over ~1 s.

Opt-in proposed: **Correlations** and **Release time** only. Velocity distributions (0.5 s, no
bootstrap: one detection) and the others are under a second; a lookup would cost about what they save,
so they stay off. Turning one on later is `cache_supported` plus `cache_types` (and a `cache_unpack`
for a model its fit builds).

## Evidence

- Full suite at `3e5a934` (`pytest -n 4 --reruns 5 --reruns-delay 1`): **2541 passed, 2 skipped, 2 xfailed,
  no reruns**, 79 s.
- Full suite before two test updates: 2537 passed, 2 failed (`test_helper_dispatch` routing table,
  `test_root_remove` menu list: both expected from the new routes and menu item, fixed in `3e5a934`);
  its 10 reruns were those two failing deterministically (5 each), none flaky.
- `mypy --strict helab`, `mypy --strict tests`, `pyright helab tests`: clean at `3e5a934`.
- The I/O trace of the result helpers (`HELAB_TEST_IO_TRACE`) records only `request`, `mounts` and
  `request_end`: no source-folder operation (`test_the_gui_never_opens_the_store_and_helpers_touch_no_source_folder`).
- A fresh interpreter rebuilds a Correlations result from its file and record
  (`test_a_saved_result_reads_back_in_a_new_process`): no in-process registry is needed.

## Things found on the way

- Correlations' per-plot state is keyed by `AnalysisContext.owner` (the plot's instance id, a counter
  per Scripts panel). Two panels' plot "1" share it: harmless in the app (one panel) but the reason a
  test must close a plot before opening another with the same id.
- `cache_move.verify` (not an owned path) checks dataset and pending-save files only; result files are
  copied with the store folder but not verified by size. Proposed follow-up in the handoff.
