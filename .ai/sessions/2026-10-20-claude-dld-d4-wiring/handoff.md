# D4/D14 wiring handoff (2026-10-20, Claude, Worker)

Branch `agent/dld-d4-wiring` (from `7fa394f`, then merged with integration head `7ff350b`); not
pushed. What changed and the judgement calls: [notes.md](notes.md) ("Proposed, for Tony").

## On-screen checklist (for Tony, on a real folder)

1. T, X, Y histograms › Fits: turn on Fit X with **Bimodal TF² + Bose g_5/2** on a folder with a
   condensate: X's title line ends with `N0/N 0.xx ± 0.0x`; on a thermal folder it says
   `no condensate (z = …)` in black; a borderline one `possible condensate, not reported (z = …)`
   and an amber line saying why.
2. A slice model (TF^3/2 + …): the line says `N0/N (slice)`.
3. Constants rows (Detector QE, trap frequencies, Trap axial axis along, scattering length) appear
   on the Fits page only while a fitted axis has a bimodal model or Show BEC properties is on.
   Changing the lab QE marks a Gaussian-only plot? It must **not**; with a bimodal fit it must.
4. **Show BEC properties** (off by default): the header shows "BEC properties from X (…)" with N,
   N0, N0/N, T, Tc, Tc0, T/Tc, μ/k_B, R(0), n0, QE from R, QE from thermal, wrapped, and an amber
   `⚠ unconfirmed: QE 0.1 …, trap 500 Hz / 50 Hz …` until the lab/folder constants are set.
   Hover the dock's source line: the record has every number and note (Tc ideal / finite size,
   ω̄, a_ho, notes).
5. With a slice fit chosen: only T and R(0), heading says "slice: T and R(0) only".
6. BEC properties on with no fit: amber "BEC properties: need a fit…" and the settings warning.
7. Dock at ~560 px wide: nothing clipped. Live on a running folder with bimodal fits: reruns at
   most every 2 s after each run (≈2–3.5 s per run on ~300k events).
8. Do the QE checks (QE from R, QE from thermal) agree with the lab's QE? A clear disagreement
   points at the QE or the trap frequencies.

## Validation

- `mypy --strict helab tests`, `pyright helab tests`: 0 errors; `git diff --check` clean.
- Full suite before the merge (`594a652`, `-n 2 --reruns 5 --reruns-delay 1 -rR`):
  `2 failed, 1954 passed, 7 skipped, 2 xfailed, 4 warnings, 10 rerun in 450.92s`.
- Full suite after merging `7ff350b` (`4b7848e`): `2 failed, 1975 passed, 7 skipped, 2 xfailed,
  4 warnings, 10 rerun in 470.58s`.
- Both times the two failures are the root-only ones
  (`test_constants.py::test_read_only_saved_folder_is_replaced`,
  `test_cache_mover.py::test_recovery_isnt_usable_after_a_failed_settings_write`) and all 10
  reruns are theirs (5 each): no other test needed a rerun.
- After the review fixes (reuse key without hidden settings, empty layers left out, records
  agreeing, runner key fallback): `3 failed, 1975 passed, 7 skipped, 2 xfailed, 4 warnings, 15
  rerun in 356.54s`: the two root-only failures, plus
  `test_release_time_plot.py::test_a_constants_record_holds_only_the_analysis_s_keys`, which
  expected the empty folder layer; its expectation is updated and it passes (15 passed in that file).
- Cost on 294k events: notes.md, "Cost".
