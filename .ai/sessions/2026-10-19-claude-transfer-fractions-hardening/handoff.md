# Handoff: Transfer fractions hardening

Branch `agent/transfer-fractions-hardening`, from `9f6ee5a`. Brief: [brief.md](brief.md);
probe results, MATLAB reading and choices: [notes.md](notes.md); review of `eea6576` and its
fixes: [review.md](review.md) and [After review](#after-review).

## Summary

Transfer fractions no longer crashes on NaN/inf in T or on malformed shots. Its order 0
checks catch comparable peaks and jumps between runs. When another order holds at least half
as many events, the plot says "⚠ order 0 unsure" and names that order, adding "outside
Search T" when that applies. When order 0 lands a whole number of orders from the last
detection (Live, a scan), it says "⚠ order 0 moved". A first run with a transfer over about
2/3 can still take +1 for order 0 without a note (tested, a known limit). Detection now also works with wide peaks and
with stray events far out. Every other awkward case gets a note on an amber line under
the title. Manual windows wider than half the spacing are clipped, and the plot says so.
A run in flight no longer overwrites a centre typed meanwhile. From shot says why it
chose nothing. A Python reference of `fraction_calc.m` matches HeLab's counts per shot
exactly; the intended differences are tested. A Search T with both ends set is taken as
where order 0 is. Analysis version: 1 → 5.

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
  run still in flight overwriting a typed value (fixed in `6377bf0`). The rule applies to
  each setting separately. Switching to manual mid-run and typing only the centre keeps
  that centre, but the run in flight still fills in its spacing beside it, giving a mixed
  pair. This is consistent with the agreed rule and harmless: the user sees both values
  before rerunning.
- **Intended differences from `fraction_calc.m`**, all tested:
  - Fractions are over the sum of the orders, not a wide window. They are equal when the
    windows touch.
  - Shots are left out by their counts in the counting box, not MATLAB's ±35 mm import box.
  - Half-open windows.
  - **No X/Y rotation.** `monitor_momentum.m` rotates by `dld_xy_rot` = 0.61 rad before
    its ±35 mm import box and ±30 mm counting box, so the square ±30 mm box covers a
    different area. **Decided (Tony, 2026-10-20): no rotation in HeLab's code**, documented
    here, in the module docstring and in the MATLAB test. He doesn't expect it to change the
    counts. The near-edge hot-spot case (review F2) is to be looked at later; the lab has
    changed detector since that MATLAB was written.
- Wide peaks (σ ≳ spacing/4): side peaks are only shoulders, and the spacing found from
  them can be ~10 % off. The "orders overlap" note then shows (FWHM > spacing/2).

## On-screen checklist for Tony (real Bragg and magnetic data)

1. Bragg run, auto: order 0 and the spacing match the shaded windows. There is no ⚠
   unless +1 really holds ≥ half of order 0's events.
2. Amplitude scan with Live (or Rerun as the transfer grows): when +1 becomes the tallest,
   "⚠ order 0 moved by +1 order" shows on every rerun and manual starts from the earlier
   order 0. A folder whose first run is already over ~2/3 transfer shows +1 as order 0 with
   no note: the known limit.
3. A run with +1 about as tall as 0 (transfer ~40–65 %): the plot says "order 0 unsure".
   Set both ends of Search T around the real order 0: the ⚠ goes, the orders are right,
   and a plain line says "order +1 (outside Search T) holds …" or "… is taller than order
   0". An open-ended Search T (one end 0) keeps the ⚠.
4. Such a narrow Search T, leaving out a taller +1, usually holds no side peak: the note
   says "no side peak found … spacing as set", and the spacing is the hidden (last) one.
   Run once without Search T at a low transfer first, so that spacing is a detection.
5. Search T with only To set (From 0), then only From: each searches from the first or
   to the last event. From > To: the warning shows in the dock line and the settings tab.
6. Manual, Window ± 10 ms with a 12.5 ms spacing: the windows touch (6.25 ms), and the
   note and the warning say so. Centre at 5 s: the message says where the events are.
7. Magnetic run (mj states): same checks; "unsure" will be common when the populations
   are similar. Manual orders fix it.
8. Live, auto: centre and spacing follow each rerun (switch to manual to see them). With
   a rerun running, switch to manual and type a centre: it stays after the rerun ends.
9. Shots: From shot past the last shot → "none of N shots (From shot … is past the last,
   …)". As Live adds shots it starts plotting. A range with To below From → "no shots:
   To shot … is below From shot …".
10. Compare with `monitor_momentum.m` on the same shots, keeping the XY rotation
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
> Window ± over half the spacing clipped to it). Its order 0 checks catch comparable peaks
> (another order with ≥ half its events: "⚠ order 0 unsure") and jumps between runs (a
> whole number of orders from the last detection, which the hidden centre then keeps:
> "⚠ order 0 moved"). A Search T with both ends set is the user's word on order 0: no
> warning for orders outside it, and a last detection outside it is replaced. A first run
> with a transfer over about 2/3 can still take +1 for order 0. The plot's notes say what else it left out or couldn't find. `tests/test_transfer_fractions_matlab.py` checks the
> counts against a Python `fraction_calc` and lists the intended differences, among them
> no X/Y rotation. A script's `detected_parameters` fills its settings from a run (here
> the manual centre and spacing), except a setting changed since the run started.

**roadmaps/_readme.md, Transfer fractions item:** replace "Quick version on Ground,
hardening pending: check detection on real Bragg/magnetic data, …" with:

> Quick version on Ground; hardened 2026-10-19 (detection edge cases with "order 0
> unsure" and "moved", clipped manual windows, typed values kept across reruns, From-shot wording,
> counts checked against a Python `fraction_calc`). Left: detection on real
> Bragg/magnetic data (MANUAL_TODO), how auto should find orders 0, ±1, ±2 (Tony to
> describe; it covers a first run at high transfer), a hot spot near the XY box's edge
> without MATLAB's `dld_xy_rot` (to investigate; new detector since), draggable
> windows on the T histogram, the averaged-vs-detuning view (Tony, 2026-10-19).

**.ai/MANUAL_TODO.md**, the "Transfer fractions on real data" item: add "steps in
`.ai/sessions/2026-10-19-claude-transfer-fractions-hardening/handoff.md` (unsure note,
Search T ends, clipped windows, typed centre kept during a Live rerun)".

## After review

[review.md](review.md) (fresh Claude reviewer, head `eea6576`): no crash, all checks clean,
one gap (F1). Fixes, each in its own commit:

| Commit | Finding | What |
|---|---|---|
| `966ecfa` | F1 | "⚠ order 0 moved by ±n orders from the last detection": the found order 0 is a whole number n of spacings (1 ≤ \|n\| ≤ orders each side + 1, ±0.3) from the hidden centre. The default centre is no detection. While it stands moved, runs fill in only the spacing, so the warning repeats on every rerun and manual starts from the last order 0. A first run over ~2/3 transfer is pinned as a known limit. Claims reworded in the module docstring, the Orders tip, this handoff and the proposed AGENTS.md line. Version 4. |
| `20e76a9` | F3 | The MATLAB test's header also lists the open vs closed XY box, MATLAB's T 0–4 s import limit and the `dld_aquire` last-event check. |
| `1462b39` | F3 | The handoff line on the per-setting `_show_detected` rule (above, Decisions), with the review. |
| `d0255ca` | — | The "moved" warning says how to clear it (sticky behaviour confirmed by the Coordinator). |

- **F1 choice beyond the brief:** keeping the hidden centre while order 0 stands moved.
  Without it, the next Live rerun compares with the jumped centre and the warning vanishes
  after one run. The cost: if the *earlier* detection was the wrong one (a first run over
  2/3 transfer, then the transfer falls), the warning stays until order 0 is set by hand
  (manual, type it, Rerun, then back to Auto, which then compares with it), or a Search T
  with both ends set around the real order 0 (after the recheck, below).
- **Option (a), "Order 0 near":** decided (Tony, 2026-10-20): not built. Tony will say later
  how auto detection of orders 0, ±1, ±2 should work (an open roadmap item, from the
  Coordinator).
- **F2, XY rotation:** decided (Tony, 2026-10-20): no rotation in HeLab's code; the
  difference is documented (Decisions above; numbers in review.md). The near-edge hot spot
  is to be investigated later.
- Checks after the fixes: full suite `pytest -n 6 --reruns 5 --reruns-delay 1
  --basetemp=.ai/temp/pytest`: **1201 passed, 2 skipped, 2 xfailed, no RERUN**; `mypy --strict`
  on helab and tests, also `--platform win32`: clean; `pyright helab tests`, also
  `--pythonplatform Windows`: 0 errors; `git diff --check`: clean.

### After the recheck

[review.md](review.md), "Recheck at 1462b39 (head d0255ca)": F1 and F3 fixed, no false jump
warnings; one medium finding (R1) and a nit.

| Commit | Finding | What |
|---|---|---|
| `cf79d22` | — | The recheck, committed. |
| `c3f6b5b` | R1 | A Search T with **both ends set** is the user's word on order 0. An order outside it holding ≥ half of order 0's events gets a plain line ("order +1 (outside Search T) is taller than order 0", or "… holds 70% as many events as order 0"), not "⚠ order 0 unsure". A last detection outside it is replaced by the new one, with no "moved" warning. An open end keeps the earlier rules. The unsure advice is now "set both ends of Search T around order 0, or the orders by hand", which clears it; checklist steps 3 and 4 updated. Version 5. |
| `f54a937` | nit | The "moved" advice ends "… set Order 0 at <c> s in manual mode, Rerun, then back to Auto". |

- Trade-off of R1 (a): a Search T with both ends set that leaves the real order 0 out is no
  longer a ⚠. Only plain lines remain: one naming an order outside it with at least half of
  order 0's events, and, when it replaced a last detection outside it, "order 0 now at X s;
  the last detection, Y s, was outside Search T" (R2, below). A first run with no last
  detection, Search T around the wrong peak and a transfer over ~2/3 says nothing: the known
  first-run limit.

### After the second recheck

[review.md](review.md), "Recheck at b16beb4": R1 and the nit fixed, no blocker; one low
finding (R2) and a nit.

| Commit | Finding | What |
|---|---|---|
| `5126335` | — | The second recheck, committed. |
| `54d1739` | R2 | When a both-ends Search T replaces a last detection outside it (not the default centre), a plain line: "order 0 now at X s; the last detection, Y s, was outside Search T". This covers 10 % → 90 % with Search T around +1, which was silent, and the R1 fix case. Version 6. |
| this commit | nit | Two blank lines, not three, before a section in `tests/test_transfer_fractions.py` (and before the R2 test). |
- Checks after these fixes: full suite `pytest -n 6 --reruns 5 --reruns-delay 1
  --basetemp=.ai/temp/pytest`: **1204 passed, 2 skipped, 2 xfailed, no RERUN**; `mypy --strict`
  on helab and tests, also `--platform win32`: clean; `pyright helab tests`, also
  `--pythonplatform Windows`: 0 errors; `git diff --check`: clean.
