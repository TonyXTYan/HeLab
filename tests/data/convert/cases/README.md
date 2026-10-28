# Synthetic raw cases (cross-checker)

Made up, small, safe to commit. Each folder: `d1.txt` (the raw input), `expected-2019.txt` and
`expected-2023.txt` (MATLAB's own output, copied unchanged), and `matlab-<variant>.json` (the
outcome: `file`, `nofile` = the 2019 wrapper writes nothing for an empty result, or `error` with
MATLAB's message; no expected file then). Regenerate: `python3 -I ../tools/gen_cases.py .`,
then `tools/run_matlab_cases.m` once per variant (see `../matlab-walkthrough.md` §8).

MATLAB 25.2.0.3055257 (R2025b) Update 2, macOS. 2019 = `legacy/tdc_autoconverter/lib` via `dld_raw_to_txy_counts(base,1,1)`;
2023 = `legacy/DLD_front_panel/.../import_mcp_tdc_data` via `dld_raw_to_txy(base,1,1)`.

| Case | 2019 | 2023 | What it exercises |
|---|---|---|---|
| `ambiguous_x2` | 3 hits | 3 hits | x1 with 2-3 x2 candidates: first in search order kept (how_many_x==~1 quirk); first-found x2 wrong -> hit dropped, the other x2 never retried; -1 before +1. |
| `ambiguous_y` | 3 hits | 3 hits | Two valid y pairs (first in nested y1/y2 search order kept), a y1 with no partner before one with, one y1 with two y2; `break` leaves only the y2 loop. |
| `basic` | 5 hits | 5 hits | Trigger plus five clean, well-separated hits (centre, off-centre, near edges). |
| `blank_lines` | 2 hits | 2 hits | Two hits with blank lines in the middle and at the end (textscan skips them). |
| `blank_only` | MATLAB error | MATLAB error | A file holding one CRLF: textscan gives 0 rows; MATLAB errors as for empty. |
| `dead_time_x1` | 14 hits | 8 hits | x1 pulses 15000/20000/20001/19999 bins apart and two at the same time, each with its own partners: 2019 matches all; 2023's uniquetol keeps the first of each 20000-bin group (not chained, inclusive), ties keep the first row. |
| `empty` | MATLAB error | MATLAB error | A 0-byte file: MATLAB errors at t_zero = dld_output_raw(1,2). |
| `equal_times` | 5 hits | 3 hits | Pulses at identical times (stable sort keeps file order), two hits with equal T (final sort is stable), and hits generated out of T order (final sort reorders). |
| `first_sorted_x1` | 1 hits | 1 hits | The earliest pulse is an x1 (before the trigger): sorted row 1 is skipped as 'the trigger' though it is a corner, so its hit is lost. |
| `garbage_mid` | no file | empty file | A non-numeric line in the middle: textscan (ReturnOnError) stops there, so only the rows before it are read. |
| `hits_at_edges` | 3 hits | 3 hits | A hit before the trigger (negative T) whose x2 is the first sorted row (reachable at count+dummy = 1), and a hit whose x1 is the last row (search runs past N). |
| `large_times` | 4 hits | 4 hits | Hits at 0.1, 1.0, 2.0 and 10 s after the trigger: T >= 1 prints 8 significant digits (rounding at the 8th digit), quarter bins. |
| `lf_endings` | 2 hits | 2 hits | Two hits with LF line endings. |
| `mcp_absent` | 4 hits | 4 hits | The same four hits without MCP pulses (output must equal mcp_present's). |
| `mcp_present` | 4 hits | 4 hits | Four hits each with an MCP (channel 4) pulse: MCP rows sit in the window but are ignored. |
| `nan_time_mid` | 2 hits | 2 hits | A line '0' (no time) in the middle: (0, NaN) sorts last and counts in N. |
| `no_hits` | no file | empty file | Trigger plus corner pulses that never form a hit: x1 with no x2, x2/y alone. |
| `no_trailing_newline` | 2 hits | 2 hits | Two hits, last line without CRLF. |
| `other_channels` | 3 hits | 3 hits | Channels 6 and 7 among the hits (ignored, but occupy window rows). |
| `phantom_after_hit` | 2 hits | 2 hits | Trigger + one hit + a lone x pair after it (N=7, prealloc 1 row): the lone pair grows row 2 with zeros -> a phantom T=0 row. |
| `phantom_lone_pair` | 1 hits | 1 hits | Trigger + x1 + x2 and no y: NaN(floor(3/4)=0,5) grows with ZEROS when the x pair is stored, so the failed row keeps T=0 and survives the NaN filter: a hit at T=0, Y=0. |
| `phantom_multi` | 3 hits | 3 hits | Trigger + 3 hits + x1,x2,y1 (N=16, prealloc 4 rows, 3 successes): row 4 is preallocated NaN, so no phantom (contrast with phantom_after_hit). |
| `phantom_multi_cut` | 4 hits | 4 hits | phantom_multi without the lone y1 (N=15, prealloc 3, 3 successes): the lone pair grows row 4 with zeros -> a phantom T=0 row. |
| `phantom_none` | 1 hits | 1 hits | Same as phantom_after_hit but the lone pair comes BEFORE the hit: the row is reused by the hit, no phantom. |
| `search_window` | 2 hits | 2 hits | An x2 > T_sum away inside the 36-row window is skipped and the search goes on; partners at row +-19 are out of reach, at +-18 found (offsets -1,+1,...,-18,+18). |
| `small_values` | 5 hits | 2 hits | Hits ~25 ns to 0.5 us after the trigger and |X|,|Y| of a few bins: T and X/Y print with e-05/e-06/e-07 exponents; X or Y exactly 0; odd sums give quarter-bin T. |
| `tol_sum` | 3 hits | 3 hits | x sum - y sum = 398 kept, 400 and 402 dropped, -398 kept, -400 dropped, 400 and 398 with sx != 3200 (T then uses T_sum, not the real sums). |
| `tol_x_window` | 3 hits | 3 hits | |x1-x2| = 3198, 3200 (kept: skip is > T_sum), 3202, 3300, 3398 (dropped by the T_sum skip although < 3400), and -3200/-3202. |
| `tol_y_diff` | 3 hits | 3 hits | |y1-y2| = 3398 kept, 3400/3402 dropped (strict <3400); a y1 exactly 3200 bins from x1 kept, 3201 skipped though the pair is consistent (the window is relative to x1). |
| `trigger_burst` | 3 hits | 1 hits | Twelve channel-5 rows within 1 us of the trigger (as in 2024-11 d1111) and hits starting 50 ns later, inside the trigger rows' window. |
| `trigger_only` | no file | empty file | One trigger row: no hits (2019 writes no file; 2023 an empty one). |
| `trunc_channel` | 1 hits | 1 hits | Last line is '<ch>' only: textscan gives (ch, NaN). |
| `trunc_comma` | 1 hits | 1 hits | Last line is '<ch>,' (time missing): textscan gives NaN, which sorts last. |
| `trunc_cr` | 2 hits | 2 hits | Last line ends in a lone CR. |
| `trunc_digits` | 1 hits | 1 hits | Last line cut mid-number (still being written): its time loses digits, sorts to near the trigger, and the last hit loses a pulse. |
| `tzero_nan` | no file | empty file | The first line is '5,' (no time): t_zero is NaN, every time becomes NaN, no hits. |
| `tzero_not_trigger` | 3 hits | 3 hits | The first line is a corner pulse (x2 of hit 2), the trigger second: t_zero is that pulse's time, so every T shifts by it (some T negative). |
| `unsorted` | 6 hits | 6 hits | Trigger first, then pulses in shuffled order including five earlier channel-5 rows: t_zero is row 1 (the trigger), not the minimum. |
| `used_pulses` | 2 hits | 1 hits | Two x1 sharing one x2 (the first takes it; the pulse is then NaN for the second); an x2 whose x1 found no y stays free for the next x1. |
