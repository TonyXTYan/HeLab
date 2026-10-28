# Review: Transfer fractions hardening

Reviewer: Claude Code (Opus 5.5), fresh, read-only. Branch `agent/transfer-fractions-hardening`,
base `9f6ee5a`, head `eea6576` (8 commits). Reviewed `git diff 9f6ee5a...HEAD`, the brief,
handoff and notes, and the MATLAB on Ground (`legacy/Momentum_Bells_test`,
`legacy/DLD_front_panel/lib/Core_BEC_Analysis`). Probe scripts (synthetic data, not committed):
`/private/tmp/claude-501/-Users-tonyyan-GitHub--maestri-floors-HeLab--agenttransfer-fractions-hardening--maestri-roles-48acbf34-5a62-4718-ba82-c2ca0dd11786/2fda92ed-5ee3-4e04-a45c-00214d538025/scratchpad/probe/{common,detection,rotation}.py`.

## Verdict

No crash or code-correctness blocker, and every check is clean. One finding falls short of the
brief's acceptance criterion: when more than about 2/3 of the atoms are transferred, auto still
picks the wrong order 0 and says nothing. The handoff and the proposed AGENTS.md wording claim
this never happens. Fix it before landing, or have Tony accept it and reword the claims (F1).
The XY rotation needs Tony's decision; numbers are in F2.

## Findings (most severe first)

### F1. Wrong order 0 is still silent when transfer exceeds ~2/3 (brief item 1)

`helab/scripts/standard/transfer_fractions.py:259-269` (`unsure`), `UNSURE_SHARE` at :82.

The check compares the other orders with the *picked* order 0. When +1 is the tallest peak and
gets picked, the real order 0 sits in the "−1" window. That is only flagged if it holds at least
50 % of +1's events, i.e. transfer ≤ 2/3. Probe (`detection.py`, orders −2…+2, true order 0 at
2.1375 s, 20 shots):

| transfer to +1/+2 | centre found | note |
|---|---|---|
| 30 % | right | none |
| 50 % | right | ⚠ unsure (+1 at 90 %) |
| 60 %, 65 % | **+1 spacing** | ⚠ unsure (names −1, the real order 0) ✔ |
| 70 %, 80 %, 90 %, 97 % | **+1 spacing** | **none**: plot shows "order 0" ≈ 62–86 % |

A π pulse, or the top of a Bragg amplitude scan (the lab's `*_bragg_amp_scan_*` folders), is
exactly this case. The plot then reads as *little* transfer, which is the worst way to be wrong.
The T histogram alone can't settle it, as the handoff says, so a note keyed on the picked peak
can't catch it either. Options for Tony/Maestro:
- (a) an "Order 0 near" (expected T₀) setting, since order 0's arrival is fixed by the trap and
  fall: warn, or snap, when the tallest peak is about one spacing or more from it. This is the
  only fix that covers a first run.
- (b) cheap, and catches Live and amplitude scans: compare the found centre with the hidden
  CENTRE, which holds the last detection. A jump of about a whole number of spacings (≥ 0.5) gives
  "⚠ order 0 moved by k orders since the last run".
- At least, reword the claims. Handoff "It no longer picks a wrong order 0 without saying so",
  the proposed AGENTS.md "Never a silent wrong order 0", and the module docstring (:16-18) should
  say "unless another order holds well over half the events" or similar. Add a test pinning the
  >2/3 behaviour, whichever way it's decided.

### F2. No XY rotation: quantified (decision for Tony; doc OK)

MATLAB (`import_mcp_tdc_data.m:180-183`) does `txy * [1 0 0; 0 c −s; 0 s c]` with
α = −0.61 rad (35°) before both the ±35 mm import box and the ±30 mm counting box. HeLab boxes the
TXY files' X/Y as written, unrotated (nothing in `helab/` rotates). The square box and its
rotated twin differ only at radius 30–42.4 mm (outside the inscribed circle). Probe
(`rotation.py`, 200 shots, populations 20/150/500/250/30, σ_T = 1 ms):

| XY distribution | box events changing in/out | Δ fraction, mean (systematic) | Δ fraction, rms per shot |
|---|---|---|---|
| isotropic, σ 5 mm | 0 % | 0 | 0 |
| isotropic, σ 10 mm | 0.7 % | ≤ 0.02 pp | ≤ 0.13 pp |
| isotropic, σ 15 mm | 6.8 % | ≤ 0.04 pp | ≤ 0.4 pp |
| isotropic, σ 20 mm | 14 % | ≤ 0.05 pp | ≤ 0.7 pp |
| off-centre (+10, −5) mm, σ 10 | 3.1 % | ≤ 0.02 pp | ≤ 0.3 pp |
| elongated σx 15 / σy 5 mm | 3.0 % (totals +2.9 %) | ≤ 0.01 pp | ≤ 0.3 pp |
| orders shifted 8 mm/order in X | 1.5 % | ≤ 0.12 pp | ≤ 0.23 pp |
| σ 10 + flat dark counts on a 40 mm MCP | 6.3 % | ≤ 0.05 pp | ≤ 0.36 pp |
| **σ 10 + hot spot at (+33, 0) mm, 300 ev/shot** | **32 %** | **order 0 −7.9 pp, ±2 +4 pp** | 8 pp |

So when every order shares one XY distribution, the rotation changes per-shot counts but leaves
the fractions alone (≤ 0.1 pp systematic, sub-pp noise). Where it matters is a localized hot spot
near the box edge, which is what the box is for (XY box tip: "keeps a hot spot out"). (+33, 0) mm
is outside HeLab's box but at (27.0, 18.9) mm, inside MATLAB's. The lab's ±30 mm was chosen in
rotated coordinates, so with HeLab's unrotated box a hot spot it was meant to exclude can come in,
or one it let in can drop out. Recommendation: an "XY rotation" setting under Counting. A default
of 0.61 rad would match the lab's MATLAB; 0 would keep HeLab's raw-detector convention, with a note
in the tip. Tony's choice. The doc's description of the difference is accurate.

### F3. Minor

- `tests/test_transfer_fractions_matlab.py:1-19`: the intended-differences list omits that
  HeLab's XY box is closed (`<=`, `transfer_fractions.py:141`) and MATLAB's `masktxy_square` is
  open (`<`). It is also missing MATLAB's T 0–4 s import limit (HeLab has none) and
  `monitor_momentum.m`'s "last event past `dld_aquire`" check (the notes mention it). Doc nit.
- `ScriptTreeSelector.py:368-370`: the rule is per setting. If the user switches to manual
  mid-run and types only the centre, the in-flight run still writes its spacing next to the typed
  centre, giving a mixed pair. That is consistent with the agreed rule and harmless, but worth a
  line in the handoff.
- `selection.py:66-73`: a range lying entirely in a gap of shot numbers (From 5, To 9, shots
  4 → 10) says only "none of 6 shots". The settings line "shots 5–9" makes it clear enough. No
  change needed.

## What I checked and found right

- **Detection** (probes): NaN/±inf in T are left out with a count, and an all-NaN shot is
  dropped. Malformed arrays go through `txy()`. Narrow (σ = 1 µs) and wide (σ = 3–4 ms) peaks
  work: wide ones get "orders overlap", plus "unsure" when the populations warrant it. Far strays
  (0–4 s, 0–1000 s, and 0–100 s with σ = 1 µs) are found correctly with no note. No false side
  peaks from noise with `SIDE_PEAK_FWHMS` lowered to 0.5 (8 seeds, 100 shots × 5600 events). A
  lone order 0 keeps the spacing as set, with a note. Search T works with From alone, To alone,
  From ≥ To (searches all, warns in the plot and in `parameter_warnings`), only side peaks in
  range (unsure + "outside Search T"), and a range past all events. Version 1 → 2 → 3, bumped in
  the two commits that change output; the others don't change Transfer fractions' numbers.
- **Manual:** Window ± 10 ms on a 12.5 ms spacing is clipped to 6.25 ms with the note, and with
  the parameter warning in manual mode. Windows are half-open (`count_orders` gives
  low ≤ t < high). A centre at 5 s renders "No events in the orders' windows … events counted
  are at T …". Shots whose windows are all empty get NaN, drawn as gaps (`connect="finite"`).
- **`_show_detected`:** exactly the agreed change. Live reruns still refill: `_submit` captures
  `values()` at submission, Follow submits the next run only after `_finished` → `_show_detected`
  (`_follow_next` last), and a Rerun cancels the in-flight job, whose cancelled result never
  refills. `tests/test_transfer_fractions.py` covers refill on Live data, no write when unchanged,
  manual keeping the last values, and in-flight typing kept. The base Live test
  (`test_live_plots.py` ~986–995) still passes. Expect a textual merge with Floating plot settings
  only if that floor touches these lines.
- **From shot:** goes by shot number over gaps. Last N slides, and a range up to a shot fixes once
  reached. From past the last shot gives "none of N shots (From shot … is past the last, …)", then
  plots once Live brings a shot. `shots_brief` covers all twelve combinations, and the Transfer
  fractions and Counts settings lines start with it.
- **Python `fraction_calc`:** line-for-line with `fraction_calc.m` and `masktxy_square.m`
  (strict inequalities, `Ns ./ Ns(:,end)`, `num_counts > num_lim`). Counts per shot are identical
  (`array_equal`) for 3 seeds × 2 widths and in auto mode, when the import box equals the counting
  box (how the test sets it) and no event sits on an edge. The documented differences are right:
  fractions over the orders' sum (equal when windows touch, tested); left out by the counting box
  vs the ±35 mm import box (tested); half-open vs open windows (tested on an edge event); no XY
  rotation (F2).
- **compute** is I/O-free: numpy only (`html` is used only in `render`). The title is now
  HTML-escaped, a small fix since pyqtgraph labels are HTML.
- **Ownership:** only the brief's paths, plus `ScriptTreeSelector._show_detected` (that function
  only), 2 lines removed in `tests/test_live_plots.py` and the import line in
  `tests/test_analysis.py`.

## Checks (rerun by me, floor root, venv + floor-env)

- `pytest -n 6 --reruns 5 --reruns-delay 1 -rR --basetemp=.ai/temp/pytest-review`:
  **1196 passed, 2 skipped, 2 xfailed in 52.9 s, no RERUN**.
- `mypy helab/ --strict`, `mypy tests --strict`, both also `--platform win32`: no issues (79 / 62 files).
- `pyright helab tests`, also `--pythonplatform Windows`: 0 errors, 0 warnings.
- `git diff --check 9f6ee5a..HEAD`: clean.

## Recheck at 1462b39 (head d0255ca)

Reviewed `git diff eea6576..d0255ca`: `966ecfa` (F1 jump warning), `20e76a9` (F3 differences),
`1462b39` (review + handoff), `d0255ca` (jump note's wording only). New probe:
`/private/tmp/claude-501/-Users-tonyyan-GitHub--maestri-floors-HeLab--agenttransfer-fractions-hardening--maestri-roles-48acbf34-5a62-4718-ba82-c2ca0dd11786/2fda92ed-5ee3-4e04-a45c-00214d538025/scratchpad/probe/jump.py`.
It runs plots in sequence and writes each run's `detected_parameters` back the way `_show_detected` does.

**Verdict: F1 and F3 are fixed, with one new medium finding (R1).** It errs loud, not silent, so it
doesn't block landing, but the advice the plot and handoff give for "unsure" doesn't do what they
say. F2 (XY rotation) is still Tony's decision.

### Jump warning: works as intended

- **My 70–97 % cases on a second run:** the warning fires every time. Live, last 5 shots, an
  amplitude scan 5 → 100 → 5 %: every run is right, warns, or both. None is silently wrong.
  At 80 % (pool still mostly low) it is right with "unsure". From 90 % up to 35 % on the way back
  down it shows "moved by +1" (some runs with "unsure" too). It settles silently once the pool is
  low again. Last 1 shot, 10 → 95 → 10 %: warns on both 95 % shots, then is quiet.
- **Scans by shot choice:** From shot 11 (the 90 % half) warns "moved"; back to all shots, it doesn't.
- **No false warnings:** none when transfer wanders between 0 and 45 % (15 Live runs). None when
  order 0 drifts slowly by 0.05 spacing per run (0.55 spacing in total), because each run refills
  the centre. None from the default centre, from half a spacing, or in manual mode (also tested).
- **d0255ca's "accept" advice works:** after a wrong first run at 90 % and then 30 %, typing the
  note's centre in manual, Rerun, then Auto clears the warning. That holds for the default
  centre and for an offset one (the 6-digit value is within `JUMP_SLACK`). Small wording nit: the
  note should also say "then back to Auto". Otherwise the plot stays in manual and stops following
  Live's order 0.
- **Known cost (documented in the handoff):** after a wrong first run (> 2/3 transfer), the
  "moved by −1" warning stays on every later run until order 0 is set by hand, even though those
  runs are right. That is loud, not silent, so acceptable.

### R1 (medium): "Set Search T around order 0" never clears "unsure", and after a wrong pick it makes "moved" stick

`transfer_fractions.py:259-271` (`unsure`) counts rivals over every window regardless of Search T.
Search T only adds "(outside Search T)" to the note. So with a correct Search T around the real
order 0, the note stays whenever +1 holds ≥ half of order 0's events: 45 % transfer gives
"+1 (outside Search T) holds 72 %", 60 % gives 132 %. That is every case the handoff's checklist
step 3 covers ("transfer ~40–65 % … Set Search T around the real order 0: the note goes"), which
is false (and was in step 2 at eea6576 too: I missed it). The note's own advice ("set Search T
around order 0, or the orders by hand") likewise never clears it.

And if the first run picked +1 (60 % transfer, "unsure"), fixing it with Search T makes the
detection right, but the hidden centre is still the wrong +1. So "⚠ order 0 moved by −1" shows on
every rerun, and manual would start from +1. Options:
- (a) treat a Search T with both ends set as the user's statement of where order 0 is: no
  "unsure" for rivals outside it, and no "moved" when the last centre lies outside it. The
  original reason for counting rivals outside Search T (a range that leaves the real order 0 out)
  would then go unflagged, so maybe keep a softer "order +1 outside Search T is taller"
  information line.
- (b) keep the logic and fix the words: step 3 and the note's advice should say the note stays
  while another order is that tall, and point to manual orders as the way to silence it.

Also, a Search T narrow enough to leave out a taller +1 usually holds no side peak, so the spacing
falls back to the hidden one ("no side peak found … spacing as set"). That's fine, but worth a
line in the checklist.

### Claims now true?

- **Module docstring (:16-22):** true, including the first-run > 2/3 limit (pinned by
  `test_a_first_run_over_two_thirds_transfer_takes_plus_1_for_order_0`, 75/90/97 %).
- **Orders tip:** true.
- **Handoff summary, proposed AGENTS.md sentence and `_readme.md` line:** true.
- **Handoff checklist:** step 2 is true; step 3 is not (R1).
- **The per-setting `_show_detected` line:** true.
- **F3 header in `test_transfer_fractions_matlab.py`:** right; matches `masktxy_square.m`,
  `txylim` and `dld_aquire` in `monitor_momentum.m`.
- **Version 3 → 4 for the jump note:** right (output changes).

### Checks at d0255ca (rerun by me, floor root, venv + floor-env)

- `pytest -n 6 --reruns 5 --reruns-delay 1 -rR --basetemp=.ai/temp/pytest-review`: **1201 passed,
  2 skipped, 2 xfailed, no RERUN** (also at 1462b39: same).
- `mypy --strict` on helab and tests, also `--platform win32`: no issues.
- `pyright helab tests`, also `--pythonplatform Windows`: 0 errors.
- `git diff --check 9f6ee5a..d0255ca`: clean.

## Recheck at b16beb4

Reviewed `git diff d0255ca..b16beb4`: `c3f6b5b` (R1, option (a)), `f54a937` ("then back to
Auto"), `b16beb4` (handoff). Probes as before (`jump.py` plus inline runs that write each run's
`detected_parameters` back, as `_show_detected` does).

**Verdict: R1 is fixed and the nit is done. No blocker.** One low finding (R2): a consequence of
option (a) that the handoff's trade-off line describes only in part. F2 (XY rotation) is still
Tony's decision.

### What I checked

- **45 % / 60 % (and 90 %) with Search T both ends around the real order 0:** right centre, no ⚠.
  A plain line says "order +1 (outside Search T) holds 72 % as many events as order 0" or "… is
  taller than order 0". At 90 % the real order 0 is found too.
- **Wrong first pick (60 %, "unsure"), then both ends around the real order 0:** the right centre
  replaces the hidden +1 with no "moved". The rerun is quiet (plain line only). Clearing Search T
  afterwards gives "unsure" + "moved by +1" again, which is correct because +1 is the tallest.
- **Open-ended Search T unchanged:** To only, after the same wrong first pick, gives the right
  centre with "⚠ unsure … (outside Search T)" and the sticky "⚠ moved by −1", as at d0255ca.
- **No regression with a wide both-ends Search T:** Live, last 5, amplitude scan 5 → 100 → 5 %, with
  Search T over orders −2…+3. "unsure", then "moved by +1" while +1 is the tallest, then quiet.
  Same as an open Search T, because the last centre is inside it. With a both-ends Search T
  over orders 0 and +1, Live scan 10 → 90 → 10 %: the same.
- **Search T both ends around the WRONG peak (+1), first run:** 10 / 30 / 60 % give the wrong
  centre with only the plain line ("order −1 (outside Search T) is taller than order 0" /
  "holds 76 %"). Not silent, but no longer ⚠: the handoff's stated trade-off. At 90 % it is
  silent, which is the known first-run limit (it was silent before c3f6b5b too).
- **Right detection at 30 %, then both ends set around +1 by mistake:** the centre moves to +1
  with only the plain line. Before c3f6b5b this gave ⚠ unsure + ⚠ moved.

### R2 (low): a both-ends Search T around the wrong peak at high transfer replaces a right centre silently

Steps: a right detection at 10 %, then 90 % transfer with Search T both ends around +1. That gives
order 0 = +1 and `jumped` 0, with **no** ⚠ and no plain line; the only note is "no side peak
found … spacing as set". Before c3f6b5b the "moved by +1" warning caught it. This follows from "the
user's word", and it needs an explicit Search T around the wrong peak. But the handoff trade-off
("only the plain line naming the taller order outside it") isn't true here: there is no line,
because the real order 0 holds under half of +1's events.

The cheap fix: when `chosen_by_search` replaces the last detection, add a plain (non-⚠) line,
"order 0 now at X s; the last detection, Y s, was outside Search T". It's informative both in the
R1 fix case and in this one, and needs no extra rule. Otherwise, extend the handoff's trade-off
line to say "at a transfer over ~2/3, nothing".

### Nits

- `tests/test_transfer_fractions.py:458-460`: three blank lines before the "# Search T with both
  ends set" section (two elsewhere). `git diff --check` doesn't flag it.

### Claims

- **Module docstring, Search T tip, proposed AGENTS.md sentence, checklist steps 3–4, the "moved"
  advice ("… Rerun, then back to Auto") and "set both ends … which clears it":** true (probed).
- **The handoff's R1 trade-off line:** true except at high transfer (R2).
- **Version 4 → 5:** right (notes change).

### Checks at b16beb4 (rerun by me, floor root, venv + floor-env)

- `pytest -n 6 --reruns 5 --reruns-delay 1 -rR --basetemp=.ai/temp/pytest-review`: **1204 passed,
  2 skipped, 2 xfailed, no RERUN**.
- `mypy --strict` on helab and tests, also `--platform win32`: no issues.
- `pyright helab tests`, also `--pythonplatform Windows`: 0 errors.
- `git diff --check 9f6ee5a..b16beb4`: clean.
