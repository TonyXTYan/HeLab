# MATLAB raw → TXY: the running path, line by line (cross-checker)

Lens, 2026-10-29, written from the sources without reading the builder's port, and checked
against MATLAB R2025b (25.2.0.3055257 Update 2) on macOS: the probes in §1, §4 and §7 and the
39 synthetic cases in [`cases/`](cases/README.md). An independent stdlib transcription of this
walkthrough, [`tools/oracle.py`](tools/oracle.py), is byte-identical to MATLAB on all 39 cases ×
2 variants and on three sample shots (2024-11 `d1111`, 2022-11 `d1`, 2019 `d95`), which is the
evidence that the reading below is complete.

Sources (line numbers are these files'):

- **2019** (`matlab-2019`): `legacy/tdc_autoconverter/lib/dld_read_5channels_reconst_multi_imp.m`
  (1,660 lines), called by `dld_raw_to_txy_counts.m`.
- **2023** (`matlab-2023-lab-edit`):
  `legacy/DLD_front_panel/lib/Core_BEC_Analysis/lib/import_mcp_tdc_data/dld_read_5channels_reconst_multi_imp.m`
  (1,733 lines), called by that folder's `dld_raw_to_txy.m`. Where a 2023 line differs it is
  given as "2023 L…".

Both wrappers call `dld_read_5channels_reconst_multi_imp(filename_read, 1, 0, 1, 0)`:
`normalise_time_flag = 1`, `reconst_4_corners_and_mcp_flag = 0`,
`reconst_4_corners_nomcp_flag = 1`, `reconst_3_corners_flag = 0`. Only the import (L29–66), the
4-corner section (L424–599; 2023 L426–669) and the combine (L1525–1530; 2023 L1598–1603) run.

Units: times are TDC bins of 25 ps, as read from the file, in `double`.

## 1. Reading the raw file (L43–46, L1650–1661)

- `filename_input = [filename, '.txt']` (L43): the wrapper passes `<base><N>` (no extension).
- `tdc_importer` (L1650): `fopen`; `textscan(fid, '%f64%f64', 'Delimiter', ',',
  'MultipleDelimsAsOne', 0, 'ReturnOnError', true, 'NumCharactersToSkip', 0, 'CollectOutput',
  true)`; `fclose`; `data = data{1}` → an N×2 double matrix `[channel, time]`.
- No check of the result: any number of rows, including 0.

textscan reads a flat stream of fields, two per row; probed (`.ai/temp/crosscheck/probe/ts/`):

| Input | Rows MATLAB gets |
|---|---|
| CRLF or LF endings, last line with or without EOL, last line ending in a lone CR | the same rows |
| Blank lines (middle or end) | skipped |
| Last line `1,` or `1` (truncated after the channel) | `(1, NaN)` |
| A middle line `0` or `0,` | `(0, NaN)`, reading goes on |
| Last line cut mid-number (`0,1365664`) | the shorter number (a valid, much smaller time) |
| A line that isn't a number (`abc`, `x,123`) | reading **stops**: only the rows before it |
| `0,12x4` | `(0, 12)`, then stops |
| `5,100,7` (a third field) | `(5,100)` then `(7, NaN)`: the extra field starts a new row |
| Spaces or tabs around fields | ignored |
| `NaN`, `Inf` as a time | NaN, Inf |
| UTF-8 BOM at the start | **0 rows** |
| A NUL byte | stops there |
| 0-byte file, or one holding only `\r\n` | 0×2 |
| Times above 2^53 | rounded to double (`9007199254740993` → `…992`) |

Real raw files are CRLF, `<channel>,<integer time>`, ending in CRLF; times ~1.4e13 bins, exact
in double.

## 2. Count, sort and t_zero (L55–66)

- L55 `num_trigs = size(dld_output_raw,1)`: N includes NaN-time rows. (Used only by the
  5-hit section, which doesn't run.)
- L58 `[~, NewRowNumber] = sort(dld_output_raw(:,2))`: ascending by time. **MATLAB's sort is
  stable** (equal times keep file order) and puts **NaN last**. A port must do the same
  (`sorted` in Python is stable; NumPy needs `kind="stable"`, and NumPy's NaN-last matches).
- L60 `dld_output_sorted = dld_output_raw(NewRowNumber,:)`.
- L62 (2023 L64) `t_zero = dld_output_raw(1,2)`: the time of the **first row of the file**
  (unsorted), not the minimum and whatever its channel. **0 rows → MATLAB errors here**
  (`MATLAB:badsubscript`, "Index in position 1 exceeds array bounds."), no output file (cases
  `empty`, `blank_only`). If that time is NaN (first line `5,`), every time becomes NaN and no
  hit forms (`tzero_nan`).
- L64–66 `dld_output_sorted(:,2) = dld_output_sorted(:,2) - t_zero` (flag is 1).
- L72–80 set the 3-corner polynomial constants; unused.

## 3. The skipped sections (L97–403)

`reconst_4_corners_and_mcp_flag_call` is 0, so L399–402 run: the 5-hit outputs are set to
`zeros(0,3)`. L407 `hits_left = size(...)` is unused. Nothing else from L89–417 runs.

## 4. The 2023 x1 dead-time cut (2023 L429–437; absent in 2019)

Inside `if reconst_4_corners_nomcp_flag == 1`, before the constants:

```matlab
dld_output_sorted_temp = dld_output_sorted;
mcp_vec  = dld_output_sorted_temp(dld_output_sorted_temp(:,1)==4,2);   % unused
x1_vec   = dld_output_sorted_temp(dld_output_sorted_temp(:,1)==0,2);   % x1 times, sorted order
x1_index = find(dld_output_sorted_temp(:,1)==0);                       % their rows
[~,I_tol,IC_tol] = uniquetol(x1_vec, 0.5e-6/bin_time, 'DataScale', 1);
lgc = true(length(x1_vec),1);  lgc(I_tol) = false;
dld_output_sorted(x1_index(lgc)) = nan;
```

- The tolerance `0.5e-6/25e-12` is exactly 20000 in double.
- `'DataScale', 1` makes it absolute: u, v are "within tolerance" when `|u − v| ≤ 20000`.
- **Grouping, probed:** uniquetol sorts, starts a group at its smallest value, puts every value
  within ≤ 20000 **of that first value** in the group (not chained: 0, 15000, 30000, 45000 →
  groups {0, 15000} and {30000, 45000}), and the next value outside starts a new group. The
  boundary is inclusive (0 and 20000 are one group; 40000 and 60001 are not). `I_tol` is each
  group's first element; among equal values, the **first index** (x1_vec is in sorted order,
  so the first row in file order among equal times). Empty x1_vec works (no error).
- `dld_output_sorted(x1_index(lgc)) = nan` is **linear indexing** into the N×2 matrix; the
  indices are ≤ N, so it sets **column 1 (the channel)** of each dropped x1 row to NaN. The
  row stays (its time too); it just never matches anything again. Dropped x1 rows still count
  in N, in the 36-row window and in the prealloc.
- Applies to every channel-0 row, including sorted row 1 (which the loop skips anyway).
- The x2/y1/y2 cuts (2023 L438–458) are commented out.

## 5. The 4-corner match (L424–578; 2023 L426–640)

### 5.1 Constants (L426–447)

| Name | Value | Note |
|---|---|---|
| `number_detections` (N) | `size(dld_output_sorted,1)` | all rows, trigger and NaN rows included |
| `T_sum` | `tsum` = 3200 | the match window and (2019) the T offset |
| `tolerance_throw`, `tolerance_keep` | 200, 200 | |
| `search_no` | 36 (2023: `9*4`) | |
| `T_sum_x`, `T_sum_y` | 0, 0 (unused) — **2023: 3390, 3275** | used for tx/ty only in 2023 |
| `T_sum_tol_throw`, `T_sum_tol_keep` | 3400, 3400 | |
| `two_tolerance_keep` | 400 | |
| `five_channel_output_4corners` | `NaN(floor(N/4), 5)` | see §6.1: it can grow |
| `which_row` | 0 | |

`count = int32(0)`, `dummy = int8(0)`, `count2 = int8(0)` (L446–448) are overwritten as
doubles (`for` over a double range; `dummy = 0` at L452), so no integer saturation.

### 5.2 Outer loop (L449–452)

`for count = 2:N` — **sorted row 1 is never an x1** ("first hit is a trigger to ignore"),
whatever its channel; it can still be an x2/y partner (case `first_sorted_x1`: an x1 that is
the earliest pulse loses its hit; `hits_at_edges`: an x2 at row 1 is used).
`if dld_output_sorted(count,1) == 0` (a NaN channel is never 0): `x1_val` = its time;
`dummy = 0; how_many_x = 0`.

### 5.3 x2 search (L456–496)

```
for count2 = 1:36
    dummy = dummy + count2*(-1)^count2        % offsets -1,+1,-2,+2,…,-18,+18
    r = count + dummy
    if r <= 0: continue                         % L459
    if r > N:  continue                         % L462
    if abs(time(r) - x1_val) > T_sum: continue  % L465: skip rows > 3200 away (NOT break)
    if chan(r) == 1:                            % L474 (used pulses are NaN: never equal)
        x2_val = time(r)
        if abs(x1_val - x2_val) < 3400:         % L477
            how_many_x += 1
            if how_many_x > 1: break            % L479: a 2nd candidate ends the search
            x1 = x1_val; x2 = x2_val
            which_row += 1
            tx = 0.5*(x1 + x2 - T_sum)          % 2023: T_sum_x (3390)
            out(which_row,2) = x1 - tx          % 2023: x1
            out(which_row,3) = x2 - tx          % 2023: x2
            x2_index = r
```

- The window is **±18 rows** (36 positions), offsets in the order −1, +1, −2, +2, …, −18, +18
  (case `search_window`: partners at ±18 found, at ±19 not).
- L465 is relative to **x1**, inclusive at 3200 (`> T_sum` skips), and `continue`s, so a far
  row inside the window doesn't stop the search.
- L477's `< 3400` never binds: L465 already removed everything beyond 3200. The effective x2
  rule is `|x1 − x2| ≤ 3200` (case `tol_x_window`: 3200 kept, 3202 and 3300 dropped).
- A NaN time compares false everywhere: never skipped by L465, never a candidate.
- The **first** candidate in search order is stored; a second only sets `how_many_x = 2` and
  breaks. The stored row and `which_row` are not undone.

### 5.4 The quirk (L498–500)

`if how_many_x == ~1` — `~1` is logical false, so this is `how_many_x == 0`: only "no x2"
skips. An ambiguous x2 keeps the first candidate (the comment says "If cant find X or is not
unique", so rejecting was intended). Case `ambiguous_x2`.

### 5.5 y search (L502–573)

```
dummy2 = 0; how_many_y = 0
for count3 = 1:36                               % same offsets, from the x1 row
    dummy2 += count3*(-1)^count3; r2 = count + dummy2
    bounds, then abs(time(r2) - x1_val) > T_sum: continue   % relative to x1 again
    if chan(r2) == 2:
        y1_val = time(r2); dummy3 = 0
        for count4 = 1:36                       % y2 search, ALSO from the x1 row
            dummy3 += count4*(-1)^count4; r3 = count + dummy3
            bounds, then abs(time(r3) - x1_val) > T_sum: continue
            if chan(r3) == 3:
                y2_val = time(r3)
                if abs(y1_val - y2_val) < 3400 and abs(x1 + x2 - y1_val - y2_val) < 400:  % L544
                    how_many_y += 1
                    if how_many_y > 1: break    % L547: leaves the y2 loop ONLY
                    y1 = y1_val; y2 = y2_val
                    ty = 0.5*(y1 + y2 - T_sum)  % 2023: T_sum_y (3275)
                    t = (tx + ty)/2
                    out(which_row,4) = y1 - ty  % 2023: y1
                    out(which_row,5) = y2 - ty  % 2023: y2
                    out(which_row,1) = t
                    chan(count) = chan(x2_index) = chan(r2) = chan(r3) = NaN   % L557–560
```

- Both y pulses are windowed against **x1's time**, not each other (case `tol_y_diff`: a y1
  3200 from x1 kept, 3201 skipped though the pair is consistent).
- `|y1 − y2| < 3400` and `|x1 + x2 − y1 − y2| < 400` are **strict** and do bind (cases
  `tol_y_diff`, `tol_sum`). `x1 + x2` is the raw sum (`x1`, `x2` are the stored first-candidate
  values).
- The **first valid pair** in nested order (y1 by offset, then y2 by offset) is kept. After
  it, the y2 loop keeps scanning (a further valid y2 sets `how_many_y = 2` and breaks the y2
  loop) and the y1 loop **goes on** (more y1 candidates only increment `how_many_y` and break
  their y2 loops). None of that changes the output (case `ambiguous_y`).
- On success the four pulses' channels become NaN **at once**, inside the search; later
  checks in this same search then don't see them.
- No retry: if the stored x2 (the first candidate) has no valid y pair, the hit is dropped and
  the other x2 is never tried (case `ambiguous_x2` B: a retry would have recovered it).
- 2023 adds, inside the success branch: `rows_mcp = max(count+dummy3-search_no,1):min(...)`
  (unused), `if true; … else how_many_y = how_many_y - 1; end` (the else never runs), and
  `dld_pulses_used(which_row,:) = [count, x2_index, count+dummy2, count+dummy3]` (grows, never
  returned). No effect on the output.

### 5.6 After the y search (L574–576)

`if how_many_y == 0: which_row = which_row - 1` — the row is given back to the next x1 and
will be overwritten. Its x columns (2, 3) stay as written, and column 1 stays whatever it was.
The x2 of a failed x1 was not NaN'd, so a later x1 can use it (case `used_pulses`).

## 6. Output assembly (L580–592; 2023 L642–654), combine (L1525–1530)

### 6.1 The phantom row (a quirk not in the findings)

The prealloc is `NaN(floor(N/4), 5)`. When `which_row` exceeds it, MATLAB **grows the matrix
and fills new cells with 0, not NaN** (probed: `A = NaN(1,5); A(2,2) = 7` → row 2 is
`[0 7 0 0 0]`). Each success uses 4 distinct rows, so successes ≤ floor(N/4); `which_row`
reaches floor(N/4) + 1 only when an x1 finds an x2 after the last success has filled the
prealloc. If that x1 then finds no y, the grown row keeps column 1 = **0**, survives the
`~isnan(col 1)` filter, and becomes a hit at **T = 0**, X = (x1 − x2)·v·25 ps, **Y = 0**
(2019: columns 2, 3 hold x1 − tx, x2 − tx; 2023: x1, x2; same X).

- Needs N mod 4 ≥ 2 and every prealloc row used by a success: small files only. Cases
  `phantom_lone_pair` (trigger + x1 + x2: N = 3, prealloc 0 → one phantom),
  `phantom_after_hit`, `phantom_multi_cut`; `phantom_none` (lone pair before the hit: its row
  is reused) and `phantom_multi` (N = 16: the row is preallocated NaN) have none.
- At most one phantom per file (the grown row is the last one, index successes + 1).
- A port with a list that only appends on success, or a NaN-filled growable array, misses it.

### 6.2 Filter, T/X/Y

- L580–581: keep rows whose column 1 is not NaN (order kept: generation order = x1 sorted
  order).
- L583–584: drop NaN-channel rows from `dld_output_sorted` (unused afterwards).
- L590 `T = col1 * bin_time`, with `bin_time = 25e-12` (L39).
- L591 `X = (col2 − col3) * v_perp_x * bin_time`, evaluated left to right:
  `((col2 − col3) * 5.2632e+005) * 25e-12`. In 2019 `col2 − col3 = (x1 − tx) − (x2 − tx)`;
  in 2023 `x1 − x2`. (Equal for integer times below 2^52; a port should still compute it the
  same way.)
- L592 `Y = (col4 − col5) * v_perp_y * bin_time`, likewise.
- `t = (tx + ty)/2` with `tx = 0.5*(x1 + x2 − T_sum)`: quarter-bin values, exact in double.

### 6.3 Combine and final sort (L1525–1530)

`cat(1, zeros(0,3), zeros(0,3), [], three_channel_output_4corners, [])` is just the 4-corner
output (the 3-corner flag is 0, so L1206 and L1522 set those to `[]`). L1528 sorts by T,
**stable** (equal T keep generation order; case `equal_times` has two hits with equal T, and
two hits whose generation order is not their T order). NaN can't reach this sort.

## 7. Writing (the wrappers)

- **2019** `dld_raw_to_txy_counts.m` L15–27: `counts = size(hits_sorted,1)`; **only if
  `~isempty(hits_sorted)`** it writes `[filename_raw, '_txy_forc', file_no, '.txt']` with
  `dlmwrite(…, hits_sorted, 'precision', 8)`. **An empty result writes no file** (cases
  `trigger_only`, `no_hits`, `garbage_mid`, `tzero_nan`).
- **2023** `dld_raw_to_txy.m` L16–20: writes unconditionally; an empty result gives a **0-byte
  file**.
- `dlmwrite` with `'precision', 8`: each value as C `%.8g`, `,` between values, `\n` after each
  row, **LF even on Windows** (the reference `_txy_forc` files from the lab PC have no CR).
  Probed: `-0` → `-0`, `0` → `0`, `1e-05`, `1.2345679e-05`, `1.2345679e+08`, `1e+100` (exponent
  at least 2 digits, sign always), `NaN`, `Inf`, `-Inf` (capitalised, unlike Python's `%g`).
  Python's `"%.8g" % v` gives the same bytes for every finite value probed; NaN/Inf can't reach
  the output (§6.3), and −0 can't either (X, Y, T are sums or differences of finite values,
  which round to +0).
- Rounding at the 8th digit: the samples' and cases' outputs agree with Python's correctly
  rounded `%.8g`; no tie case seen.

## 8. Running MATLAB on the cases

`tools/run_matlab_cases.m` (one MATLAB session per variant, since both define the same
function name):

```bash
cd .ai/sessions/2026-10-29-claude-txy-reference/crosscheck/tools
matlab -nodisplay -batch "run_matlab_cases('2019', '<abs>/crosscheck/cases', '<abs>/.ai/temp/crosscheck/run')"
matlab -nodisplay -batch "run_matlab_cases('2023', '<abs>/crosscheck/cases', '<abs>/.ai/temp/crosscheck/run')"
python3 -I compare_oracle.py ../cases      # oracle vs MATLAB: "mismatches: 0"
```

It copies each `d1.txt` to `.ai/temp/crosscheck/run/<variant>/<case>/`, converts there, and
copies the output back unchanged.

## 9. Quirks to reproduce (checklist for the port)

Numbered so findings can cite them. ✱ = not in the brief's list.

1. Sorted row 1 is never an x1, whatever its channel; it can be an x2/y partner. (§5.2)
2. `t_zero` is the file's first row's time (unsorted), any channel. (§2)
3. 0 rows → MATLAB errors (no output); the port must not write a TXY. (§2) ✱
4. Stable sort, NaN last, for the pulses (L58) and for T (L1528). (§2, §6.3) ✱
5. Search offsets −1, +1, …, −18, +18, all from the x1 row, for x2, y1 **and** y2. (§5.3, §5.5)
6. Window `|t − x1| > 3200` → `continue` (inclusive keep, relative to x1, for every partner). (§5.3)
7. x2's `< 3400` never binds; effective `|x1 − x2| ≤ 3200`. (§5.3) ✱
8. `how_many_x == ~1`: the first x2 candidate is kept when there are two. (§5.4)
9. y: `|y1 − y2| < 3400` and `|x1 + x2 − y1 − y2| < 400`, strict; first valid pair in nested
   order; `break` leaves only the y2 loop. (§5.5)
10. No retry of the other x2 (or y pair). (§5.5)
11. Used pulses NaN'd immediately on success (inside the search); a failed x1's x2 stays
    free. (§5.5, §5.6)
12. The phantom row: the prealloc `NaN(floor(N/4),5)` grows with zeros. (§6.1) ✱
13. T = ((tx + ty)/2)·25e-12; X = ((x1 − tx) − (x2 − tx))·5.2632e5·25e-12 in that order
    (2023: (x1 − x2)·…). (§6.2)
14. 2023: x1 `uniquetol` cut (first of each ≤ 20000-bin group, not chained, ties → first row),
    dropped x1 rows stay in the matrix; `T_sum_x` 3390 / `T_sum_y` 3275 in tx/ty only. (§4)
15. 2019 writes no file for an empty result; 2023 writes a 0-byte file. (§7) ✱
16. `%.8g`, `,`, LF; the reader's textscan behaviour (§1), especially: truncated last line →
    NaN time or a shorter number, a non-numeric line stops reading, BOM → 0 rows. ✱
17. N (and so the prealloc and the window) counts every row read: triggers, MCP, other
    channels, NaN-time rows, 2023-dropped x1 rows. ✱
