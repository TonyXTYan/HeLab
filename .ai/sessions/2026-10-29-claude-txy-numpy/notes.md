# Notes: TXY converter stage 2, the NumPy backend, fast text I/O and the within-shot split

Worker: Abacus (Claude Code, Opus 5.5), floor TXY numpy, branch `agent/txy-numpy` from `372f2ac`.
Brief: [brief.md](brief.md). Timings: [results.md](results.md). Handoff: [handoff.md](handoff.md).

## What was built

| Path | What |
|---|---|
| `helab/convert/backends/numpy_backend.py` | `numpy` backend: `reconstruct_numpy`, vectorised `uniquetol_keep`; registered on import plus one `_MODULES` line |
| `helab/convert/fastio.py` | `parse_strict` (strict raw files, SWAR digits) and `format_txy` (`%-16.8g` columns, distinct values once); used by `raw.parse_raw` and `txy.format_txy` for every backend |
| `helab/convert/split.py` | `reconstruct_split(pulses, profile, backend, executor=, max_pieces=, min_rows=)`, `plan_cuts`, `cut_threshold`, `sorted_rows` |
| `helab/convert/timing.py` | `WITHIN_SHOT`: shots in turn, each split across a process pool (threads for a backend with `releases_gil`); `time_shot(…, split=, pieces=)` |
| `helab/convert/raw.py`, `txy.py` | the fast paths wired in; stage 1's `_parse_strict` gone; `txy.format_txy_by_value` kept as the general formatter the tests compare with |
| `helab/convert/reconstruct.py` | one `_MODULES` line only |
| `tests/test_convert_backend_numpy.py`, `test_convert_fastio.py`, `test_convert_split.py` | new; `test_convert_raw.py`, `test_convert_harness.py`, `test_headless_imports.py` (PURE) touched |
| `compare_backends.py`, `time_large.py`, `bench_io.py` (this folder) | sample comparison (optionally split), large-shot latency, I/O and first-call timings |

No build files, no packages installed (NumPy 2.5.4 is in `requirements.lock`).

## The backend: what is vectorised and why the result can't differ

MATLAB's match is greedy and order-dependent: each x1 (in sorted-time order) takes the first x2 in
search order −1, +1, −2, …, then the first (y1, y2) pair in nested search order, and marks the
four pulses used (channel NaN), so later x1s can't take them. The phantom row depends on
`which_row` and floor(N/4).

**Vectorised, order-free:** the stable sort (NumPy's stable sort is a timsort for floats and
takes 4 ms on the 1.6 M-row shot, near-sorted; 160 ms shuffled), t_zero, the uniquetol dead-time
cut, the candidate windows, the first x2, the nested y-pair search, T/X/Y and the final stable sort.

**Sequential, exact:** only the x1s an earlier match could interfere with.

The argument:

1. **Marks only remove candidates.** A marked row is one whose channel became NaN, so the
   candidate set of an x1 at its turn is a subset of its candidate set ignoring marks
   ("optimistic").
2. **So an optimistic failure is final.** No x2 optimistically: none with marks. An x2 but no y
   pair: if that x2 is still free, the valid pairs with marks are a subset of the (empty) valid
   pairs without.
3. **And an optimistic choice is final when its pulses are still free.** If the chosen x2 is free
   it is still the first free one in search order (every earlier one in order wasn't a candidate
   at all); same for the chosen pair in nested order (pairs before it were invalid, and marks
   only remove pairs).
4. **Who can mark what.** An x1 marks only itself and its own candidates. So define `touched[j]`
   = the first x1 having row j as a candidate. An x1 s whose chosen rows all have
   `touched[j] ≥ s` ("clean") can't have them marked before its turn: its optimistic result is
   final. The rest are "risky".
5. **Clean hits are marked first.** A clean hit's rows are no earlier x1's candidates, so marking
   them before the sequential pass is invisible to every earlier x1 and correct for every later
   one. Then the risky x1s run in x1 order: keep the optimistic choice if its rows are still
   free, else search again (`_search_one`, the reference's loops over that x1's own candidates
   with the marks). A clean x1 after a risky one is unaffected by whatever the risky one chooses,
   since the risky one can only choose among its candidates, which aren't a clean x1's chosen
   rows (point 4).
6. **Blocks.** x1s are processed 8,192 at a time. After a block's candidates are added to
   `touched`, `touched` is final for that block's x1s (later blocks only add later positions), so
   risk is decided per block and the risky x1s keep their candidate lists (rows and times) for
   step 5.
7. **Windows as runs.** Times are sorted and rounding is monotonic, so `not |t[j] − x1| > window`
   holds on one contiguous run of rows around each x1 (with ±Inf too). `_windows` finds the run
   with `searchsorted`, then moves each end to the exact L465 test, capped to the rows the search
   reaches (±18). A block only builds the offsets some x1 of it reaches (a prefix of the search
   order, which goes −1, +1, −2, +2, …).
8. **NaN times** sort last and fail every test (x2 limit, pair tests), so they can't be or change
   a match: left out, and an x1 with a NaN time is a no-x2. Inf − Inf is NaN as in MATLAB
   (warnings silenced with `np.errstate`).
9. **Output.** Rows 1..R of MATLAB's matrix end as the R hits in x1 order; a failed y overwrites
   row `which_row` and steps back. Only row R + 1 can hold anything else: the x pair of the last
   no-y attempt after the last hit, which survives (T = 0, Y = 0) exactly when
   `matlab_overflow_row` and R + 1 > floor(N/4). Rows with a NaN T are dropped (L580–581; can't
   happen with passing tests, kept for the rule). Then T = col·bin, X = (c2 − c3)·v⊥x·bin,
   Y likewise, in MATLAB's operation order, and one `argsort(kind="stable")` by T.

Every expression keeps the reference's operation order (`0.5 * (x1 + x2 − T_sum)`,
`(tx + ty) / 2`, `x1 + x2 − y1 − y2` left to right, `((c2 − c3) · v) · bin`). NumPy ufuncs are
separate IEEE operations, never fused (no FMA contraction), so Anvil's `-ffp-contract` trap
doesn't arise.

**Thread safety:** the backend has no lazy state of its own. Registration happens on import, and
Python's per-module import lock makes a second thread wait for the first's import. Tested: 32
threads using it first, at once, in a fresh process, all get it and the same bytes.

**uniquetol:** for a group starting at k, the next group's start is the first m > k with
`run[m] − run[k] > tol` (a suffix, by monotonic rounding over the finite run). `searchsorted` on
`run + tol` estimates it for every k at once, each estimate is moved to the exact test, then a
Python walk follows the chain (one step per kept pulse). Non-finite values are each their own
group (ends of the sorted order). An infinite tol uses the reference's loop. Tested against the
reference on the measured MATLAB cases, non-finite values and random lists, tol 0 to Inf.

How often the exact pass runs: 2022-07 he3he4 d1 (old plates, dense) 4,917 risky of 39,840 x1s,
2,933 re-searched; 2023-02 d6 (new plates) 6 risky of 70,117, none re-searched.

## The within-shot split: how the cut is chosen and why it can't change the output

`plan_cuts`: on the sorted, t_zero-subtracted times, a cut may go between rows g and g + 1 only
where `t[g+1] − t[g] > max(search_window, every non-zero dead time / bin_time)` (as NumPy
computes it, so a NaN gap never qualifies). Among those gaps, pieces of about `len / max_pieces`
rows and at least `min_rows` (default 50,000) are chosen greedily.

1. **No match crosses a cut.** For an x1 at i ≤ g and any row j ≥ g + 1, `fl(t[j] − t[i]) ≥
   fl(t[g+1] − t[g]) > window` (monotonic rounding, either side; Inf − finite is Inf). Every
   candidate test checks the window (L465, L515, L538) before the channel, so such a row is
   skipped whatever its row distance: the 36-row search never reaches across. A NaN-time row
   (sorted last) isn't skipped by the window but fails every test.
2. **No dead-time group spans a cut.** A uniquetol group is everything within tol of its first
   value. Across a gap over tol, the next same-channel value starts a new group, so each piece's
   own cut is the whole file's. (Ferrous applies the cut globally instead; both hold.)
3. **Global state.** Each piece gets its rows already sorted and shifted (`subtract_time_zero`
   off, so the file's t_zero stays; the piece's stable sort of non-decreasing times is the
   identity). The first-row skip applies only in the first piece, and the phantom row is off.
4. **The phantom row.** It needs hits R = floor(N/4) exactly (each hit uses four rows), so at
   most N mod 4 ≤ 3 rows are outside hits, two of them the lone x pair. When R + 1 > floor(N/4),
   the tail from the piece holding the last hit to the end is run again as one piece with the
   phantom row on. Its rows are its own hits, the lone pair and at most one more, so its own
   floor(n/4) is its hit count, i.e. floor(N/4) less the hits before it. Its which_row runs as
   the whole file's less those hits, so it makes the phantom row exactly when the whole file
   does. (A first version padded the tail with NaN rows to make that floor right; the argument
   shows the padding is never needed, so it was removed.)
5. **Merge.** The pieces' hits, concatenated in piece order, get one stable sort by T. Ties keep
   piece order and, within a piece, x1 order: the whole file's x1 order.

Checked against Ferrous's proof (`agent/txy-rust`, notes.md): the same rule. Differences that
are both sound: Ferrous cuts only between finite times; mine also allows a cut next to ±Inf
(Inf − finite is Inf, still skipped). Ferrous applies the dead-time cut globally; mine cuts only at
gaps wider than the dead time and lets each piece cut.

Tested: every case × both profiles × both backends cut at every safe gap (`min_rows=1`); the
`phantom_*` and `dead_time_x1` cases shown to be cut; a hand-built phantom from an earlier piece;
`tests_sample_data/`; thread and process pools; 210 random dense files (reference and numpy); and
all 309 sample shots × 2 profiles cut at every gap, identical to the reference.

## Fast text I/O (shared by every backend)

- **`parse_strict`**:
  - **Validation.** The last byte is `\n`, no byte is above `9`, and the separators (bytes below
    `0`) are exactly `,` `\r` `\n` (or `,` `\n`) per line with non-empty fields. That is the same
    set of files as the stage 1 regexes (tested on every case, probe and 3,000 random near-strict
    inputs).
  - **Digits.** Each field is gathered right-aligned into 16 bytes (a sliding-window view over
    the file after 16 zero bytes) and read as two uint64 words. The bytes before the field are
    cleared with a word mask, and three multiply-shift steps combine 8 digits per word (SWAR).
    One-digit fields (the channels) are one gather.
  - **Values.** Integer then float64, rounding to nearest like textscan. Fields over 16 digits
    take the general reader.
  - **Checked** against Python `int` on 1,000,000 random 1–16-digit fields with leading zeros.
  - **Threads.** NumPy releases the GIL here: 608 MB/s on one thread, 1,081 on 8.
- **`format_txy`**:
  - **How.** Python's `%.8g` (the conversion stage 1 validated against MATLAB) over whole
    columns, padded to 16 bytes (`%-16.8g`). Values that repeat are formatted once per distinct
    bit pattern (X and Y take only as many values as there are corner-time differences; −0 and 0
    stay apart). The fields are laid out with the separators in a byte matrix and the spaces
    dropped. MATLAB's `NaN`/`Inf`/`-Inf` are put back by replacement, since finite `%.8g` text
    has no `n` or `i`.
  - **Speed.** 374 MB/s raw serial, 470 on 8 threads. The `%` part holds the GIL.
  - **A vectorised `%.8g` was tried and dropped.** It used float scaling with a fallback near
    ties. The prototype's main path alone cost about 200 ns per value against `%`'s ~130, so it
    would only win on 3+ threads, and HeLab converts in helper processes.

## Dead ends and measurements behind choices

- An insertion-sort pass before the stable sort (Ferrous) isn't needed. NumPy's stable sort
  already takes 4 ms on the near-sorted 1.6 M-row shot.
- The first `_optimistic` spent half its time in `np.nonzero` over all 36 columns. The window
  runs (point 7) and flat `flatnonzero` made each shot about 2× faster.
- `releases_gil` is left False. Threads across shots reach 163 MB/s wall on 4 threads against
  109 serial and 332 for 4 processes: NumPy releases the GIL for the big steps, but the Python
  parts serialise. Processes are the way to parallelise; the timing harness's within-shot mode
  uses processes for it.
