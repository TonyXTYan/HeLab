# Notes: Transfer fractions hardening

Worker: Claude Code (Opus 5.5), floor "Transfer fractions hardening", branch
`agent/transfer-fractions-hardening` from `9f6ee5a`.

## What the base code did with the brief's cases (probe, 2026-10-19)

A scratch script ran `TransferFractions.compute` on synthetic shots (orders at
2.1375 s + k·12.5 ms, σ = 1 ms unless said):

| Case | Base behaviour |
|---|---|
| NaN / ±inf in T | **crash**: `IndexError` in `shortest_range`/`np.histogram` |
| +1 taller than 0 (600 vs 300) | **silently wrong**: order 0 put on +1 |
| Similar heights (590/600/580) | right by luck, nothing said |
| Search T holding only +1, +2 | **silently wrong**: order 0 put on +1 |
| Wide peaks (σ = 4 ms) | sides not found: neighbours above half max widened the FWHM on both sides, and the 2-FWHM rule then rejected the real side peaks |
| 4 % stray events over 0–4 s, narrow peaks | sides not found: the bin width came from the IQR of the densest 99 %, which the strays stretched to ~3 ms bins |
| Search T from set alone (To 0) | **ignored**: searched every event |
| Malformed (1-D) shot array | crash in `in_box` |
| Orders closer than the FWHM | merged; "no side peak found: spacing as set" (fine) |
| One shot, one peak, all outside the box, no events | fine, with a message |
| Manual Window ± over half the spacing | events between windows counted twice, nothing said |
| Manual centre outside the data | empty lines, nothing said |

## MATLAB reference (read on Ground, read-only)

- `lib/fraction_calc.m`: `num_counts > num_lim` keeps a shot; `Ns(shot, window)`
  = events from `masktxy_square(txy, [t_bounds{i}; bounds])`; `fracs = Ns ./ Ns(:, end)`,
  the last `t_bounds` entry being a wide diagnostic window.
- `masktxy_square.m` (`legacy/DLD_front_panel/lib/Core_BEC_Analysis/lib/txy_tools/`):
  strict inequalities on all three axes (open windows).
- `import_mcp_tdc_data.m`: `num_counts` is counted after rotating X/Y by `-dld_xy_rot`
  and masking with the import's `txylim` (±35 mm, T 0–4 s in `monitor_momentum.m`),
  not the counting box (±30 mm).
- `monitor_momentum.m` also waits until a shot's last event is past `dld_aquire` (2 s),
  its "file written" check; HeLab's settle rules cover that.

## Choices made along the way

- **Order 0 unsure** rather than a cleverer pick: the T histogram alone can't
  say which peak is unkicked. The check uses window counts over all counted
  events (not only the searched ones), so it also catches a Search T that
  leaves the real order 0 out. Threshold 50 % of order 0's events: the original
  test fixture (+1 at ≤ 43 %) stays quiet.
- **Bin width** = half the shortest interval holding 10 % of the events (≈ σ/8–σ/4
  for a dominant peak), independent of how far stray events reach. Past the
  20,000-bin cap, the histogram narrows to the densest 99 % (+5 %); only if still
  more than 4× too coarse *and* no side peak is found does the note mention bins.
  Narrow peaks (σ = 1 µs) are capped too, but correctly found, so no note.
- **FWHM** from the nearer side's half-maximum crossing; side peaks need 0.5 FWHM
  (two equal Gaussians separate only beyond 0.85 FWHM, so this only guards
  against flank wiggles; prominence still keeps out noise).
- **Clip**, not just warn, for Window ± over half the spacing: overlapping
  windows double-count and break fractions over the orders' sum. Manual mode
  also gets a parameter warning (dock line, settings tab); auto clips against
  the spacing it found and says so on the plot only.
- **Half-open windows** [low, high), so touching windows never share an event.
- Versions: 2 (detection), 3 (clipping, half-open windows, empty-window
  messages). The From-shot and MATLAB commits don't change Transfer fractions'
  numbers.

## Checks run

- `pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`:
  1196 passed, 2 skipped, 2 xfailed, **no reruns** (`-rR` listed none).
- `mypy helab/ --strict`, `mypy tests --strict`, both also `--platform win32`: clean.
- `pyright helab tests`, also `--pythonplatform Windows`: 0 errors.
- `git diff --check 9f6ee5a..HEAD`: clean.
- An earlier targeted run reported "1 failed, 6 rerun": the failing
  `test_bundled_plots_say_why_they_are_empty[no events-TransferFractions]` retrying
  (fixed in `ff0f576`), not a flaky test.
- Slip: `ff0f576` had a mypy `--strict` error (a name reused with two types),
  fixed in its own commit `e24db82`; every later commit was type-checked first.
