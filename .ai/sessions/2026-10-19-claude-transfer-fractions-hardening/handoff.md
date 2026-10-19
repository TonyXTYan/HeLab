# Handoff: Transfer fractions hardening

Branch `agent/transfer-fractions-hardening`, from `9f6ee5a`, 7 commits. Brief:
[brief.md](brief.md); probe results, MATLAB reading and choices: [notes.md](notes.md).

## Summary

Transfer fractions no longer crashes on NaN/inf in T or on malformed shots. It no
longer picks a wrong order 0 without saying so: when another order holds at least half
as many events, the plot says "⚠ order 0 unsure" and names that order, adding
"outside Search T" when that applies. Detection now also works with wide peaks and
with stray events far out. Every other awkward case gets a note on an amber line under
the title. Manual windows wider than half the spacing are clipped, and the plot says so.
A run in flight no longer overwrites a centre typed meanwhile. From shot says why it
chose nothing. A Python reference of `fraction_calc.m` matches HeLab's counts per shot
exactly; the intended differences are tested. Analysis version: 1 → 3.

## Commits

| Commit | Item | What |
|---|---|---|
| `88b465e` | 1 | Detection edge cases. NaN/inf T left out with a note. "Order 0 unsure" note. Bin width from the densest 10 % of events, histogram narrowed to the densest 99 % past the 20,000-bin cap. FWHM measured on its nearer side; side peaks need half a FWHM. Notes for overlapping orders, no side peak (with order 0's width) and coarse bins. Search T: a 0 leaves that end open, and From ≥ To searches every event and warns. Notes on their own amber line. Version 2. |
| `41a4ff4` | 2 | Manual mode. Window ± over half the spacing is **clipped** to it, with a note (in manual mode also a parameter warning). Windows are half-open [low, high). A centre whose windows hold no events shows a message with order 0, the spacing and where the events are. Shots with no events in any window get no fractions (gaps) and a note. Version 3. |
| `ff0f576` | 1 | With no events at all, the plot says the shared "No events in the chosen shots". Removed the 2 special-case lines in `tests/test_live_plots.py` (agreed). |
| `6377bf0` | 3 | `AnalysisInstance._show_detected`: a detected value is written only while its setting still holds the value the run started with, and not when it already holds that value (agreed: `_show_detected` only). |
| `e24db82` | — | Fixes a mypy `--strict` error that `ff0f576` introduced. No change in behaviour. |
| `cb2ce9c` | 4 | From shot. "no shots: To shot 10 is below From shot 20"; "shot 20" for a one-shot range; "none of 6 shots (From shot 31 is past the last, 30)"; "shot 9 (1 of 8)". Tests for gaps, each mode, Live adding shots and every `shots_brief` combination. |
| `c8ef1ba` | 5 | `tests/test_transfer_fractions_matlab.py`: `fraction_calc.m` + `masktxy_square.m` in Python, compared on synthetic fixtures. |

## Decisions

- **Order 0 unsure is a note, not a guess.** A T histogram can't say which peak is
  unkicked. The fix is a Search T around order 0, or manual orders, and the note says so.
  The threshold is 50 % of order 0's events, counted over all counted events, so a
  Search T that leaves the real order 0 out is caught too.
- **Clip overlapping windows** (brief item 2's "say so, or clip"). Clipping keeps each
  event in one window whatever is typed, and fractions over the orders' sum stay
  meaningful. In auto mode the clip uses the spacing found.
- **Half-open windows** [low, high). MATLAB's windows are open, so an event exactly on
  an edge counts nowhere there and in the later order here (tested).
- **Search T semantics changed:** each 0 now leaves only its own end open (From alone
  used to be ignored). Labels: "Search T from (0 = first)" / "Search T to (0 = last)".
- **Detected values and L3:** auto reruns already refilled the hidden centre and spacing
  on every completed run, and switching to manual already kept them. The only gap was a
  run still in flight overwriting a typed value (fixed in `6377bf0`).
- **Intended differences from `fraction_calc.m`**, all tested:
  - Fractions are over the sum of the orders, not a wide window. They are equal when the
    windows touch.
  - Shots are left out by their counts in the counting box, not MATLAB's ±35 mm import box.
  - Half-open windows.
  - **No X/Y rotation.** `monitor_momentum.m` rotates by `dld_xy_rot` = 0.61 rad before
    both boxes, so the square ±30 mm box covers a different area. This changes counts near
    the box's corners on real data. Possible follow-up: an "XY rotation" setting (default 0).
- Wide peaks (σ ≳ spacing/4): side peaks are only shoulders, and the spacing found from
  them can be ~10 % off. The "orders overlap" note then shows (FWHM > spacing/2).

## On-screen checklist for Tony (real Bragg and magnetic data)

1. Bragg run, auto: order 0 and the spacing match the shaded windows. There is no ⚠
   unless +1 really holds ≥ half of order 0's events.
2. A strong-transfer run (+1 ≥ 0): the plot says "order 0 unsure". Set Search T around
   the real order 0: the note goes and the orders are right.
3. Search T with only To set (From 0), then only From: each searches from the first or
   to the last event. From > To: the warning shows in the dock line and the settings tab.
4. Manual, Window ± 10 ms with a 12.5 ms spacing: the windows touch (6.25 ms), and the
   note and the warning say so. Centre at 5 s: the message says where the events are.
5. Magnetic run (mj states): same checks; "unsure" will be common when the populations
   are similar. Manual orders fix it.
6. Live, auto: centre and spacing follow each rerun (switch to manual to see them). With
   a rerun running, switch to manual and type a centre: it stays after the rerun ends.
7. Shots: From shot past the last shot → "none of N shots (From shot … is past the last,
   …)". As Live adds shots it starts plotting. A range with To below From → "no shots:
   To shot … is below From shot …".
8. Compare with `monitor_momentum.m` on the same shots, keeping the XY rotation
   difference in mind.

## Checks

- Full suite `pytest -n 6 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`:
  **1196 passed, 2 skipped, 2 xfailed, no RERUN**.
- `mypy --strict` on helab and tests, also `--platform win32`: clean. `pyright helab
  tests`, also `--pythonplatform Windows`: 0 errors. `git diff --check`: clean.
- Not done: any GUI check on screen (by the rules); real data.

## Files outside the brief's owned paths (both agreed with the Coordinator)

- `helab/models/ScriptTreeSelector.py`: only `_show_detected` (`6377bf0`). The Floating
  plot settings floor also changes this file.
- `tests/test_live_plots.py`: 2 lines removed at 381–382 (`ff0f576`).
- `tests/test_analysis.py`: besides the Shots tests, the import line gains
  `transfer_fractions`.

## Proposed doc changes (for the Coordinator)

**AGENTS.md, Script system, the Shots clause** (currently "the plots share Shots (from
shot N, then all / last N / up to a shot) and View range …"):

> the plots share Shots (From shot N first, then all / last N / up to a shot, by shot
> number so gaps are skipped; the dock says why none are chosen: From shot past the last,
> or To below From) and View range …

**AGENTS.md, the Transfer fractions sentence:**

> **Transfer fractions** (`transfer_fractions.py`, ported from
> `monitor_momentum.m`/`fraction_calc.m` in `legacy/Momentum_Bells_test`) finds order 0
> (the tallest peak in Search T, each end 0 = open) and the spacing in the T histogram,
> and plots each order's share per shot (over the orders' sum; half-open windows, a
> Window ± over half the spacing clipped to it). Never a silent wrong order 0: another
> order with ≥ half its events gives "⚠ order 0 unsure", and the plot's notes say what
> else it left out or couldn't find. `tests/test_transfer_fractions_matlab.py` checks the
> counts against a Python `fraction_calc` and lists the intended differences, among them
> no X/Y rotation. A script's `detected_parameters` fills its settings from a run (here
> the manual centre and spacing), except a setting changed since the run started.

**roadmaps/_readme.md, Transfer fractions item:** replace "Quick version on Ground,
hardening pending: check detection on real Bragg/magnetic data, …" with:

> Quick version on Ground; hardened 2026-10-19 (detection edge cases with "order 0
> unsure", clipped manual windows, typed values kept across reruns, From-shot wording,
> counts checked against a Python `fraction_calc`). Left: detection on real
> Bragg/magnetic data (MANUAL_TODO), the DLD XY rotation (`dld_xy_rot`), draggable
> windows on the T histogram, the averaged-vs-detuning view (Tony, 2026-10-19).

**.ai/MANUAL_TODO.md**, the "Transfer fractions on real data" item: add "steps in
`.ai/sessions/2026-10-19-claude-transfer-fractions-hardening/handoff.md` (unsure note,
Search T ends, clipped windows, typed centre kept during a Live rerun)".
