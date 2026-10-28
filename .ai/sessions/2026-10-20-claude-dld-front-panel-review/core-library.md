# Core_BEC_Analysis (in DLD_front_panel), module by module

This is a subagent's read of `legacy/DLD_front_panel/lib/Core_BEC_Analysis` (`b8907f5`,
2019-07-08), compared with HeLab's loader. Paths are relative to that folder unless
they start with `helab/` or `legacy/`. The overview and plan are in [notes.md](notes.md).

## Import (`lib/import_mcp_tdc_data/`)

| File | Role |
|---|---|
| `import_mcp_tdc_data.m` | Wraps the core in `function_cache` (1–54). Per shot, the core (56–198) checks the file exists, checks it is done writing, converts raw → TXY if needed, reads it, rotates it, masks it and counts it. |
| `dld_read_5channels_reconst_multi_imp.m` | 1660 lines: raw 5-channel TDC → N×3 (t, x, y). |
| `dld_raw_to_txy.m` | Calls the reconstruction with `(1,0,1,0)`, then writes `d_txy_forcN.txt` with `dlmwrite` precision 8 (16–20). |
| `txy_importer.m` | Reads the comma-separated `%f64%f64%f64` TXY file (25–34). |
| `find_data_files.m` | Finds the `d<digits>.txt` shot numbers, leaving out `txy_forc` files. The one-character prefix is hard-coded (`name(2:end-4)`, 27). |
| `is_dld_done_writing.m` | The mtime must be older than `wait_for_mod` **and** the last character must be `\n` (19–34). |
| `data_tcreate.m` | Returns the file's [creation, write] times as POSIX times. Creation time is available only on Windows (`GetFileTime`). |

**Options** (`import_mcp_tdc_data_core`, 111–127):

| Option | Default | Notes |
|---|---|---|
| `dir` | required | |
| `file_name` | `'d'` | |
| `shot_num` | all shots | Any list of shots; missing shots give NaN |
| `dld_xy_rot` | 0.61 rad | `txy·[1 0 0; 0 cos α −sin α; 0 sin α cos α]` with α = −rot (181–182) |
| `txylim` | `[[0,10];[-30e-3,30e-3];[-30e-3,30e-3]]` | Applied after the rotation (184) |
| `mod_wait` | 1 s | |
| `force_forc` | off | |
| `force_reimport` | off | |
| `force_load_save` | off | |
| `cache_save_dir` / `save_cache_in_data_dir` | none | |
| `mat_save` | | Unused |

Two more behaviours:
- **Re-conversion:** a shot is converted again when its `_txy_forc` file is missing or older than its raw file (162–170).
- **Outputs:**
  - `counts_txy{ii}`.
  - `num_counts(ii)`, counted **inside `txylim`**.
  - `shot_num`.
  - `time_create_write(ii,:)`, taken from the **raw** file.

## Raw reconstruction

The input is `channel,time_bin` rows. Bins are 25 ps (`bin_time = 25e-12`, 39). Channels 0–3 are x1, x2, y1 and y2 (the delay-line ends), 7 is the MCP, and the first row is the trigger.

1. **Sort and normalise.** Sort the rows by time. With `normalise_time_flag`, subtract `t_zero = raw(1,2)` (58–66).
2. **Constants:**
   - `tsum = 3200` bins, tolerance 200.
   - `max_group_time = 3400`, `dead_time = 400`.
   - `v_perp_x = v_perp_y = 5.2632e5` m/s.
   - Cubic tsum corrections, used only by the 3-corner mode (72–80).
3. **Production mode, 4-corner without the MCP (424–599).** For each x1, search up to `search_no = 36` rows in each direction:
   - **x2:** take the **unique** x2 with |x1−x2| < tsum+200. More than one candidate is a multi-hit and is dropped.
   - **y1 and y2:** take the **unique** y1, y2 with |y1−y2| < tsum+200 and |x1+x2−y1−y2| < 400. All of them must be within tsum of x1.
   - **Times:** `tx = (x1+x2−tsum)/2`, `ty = (y1+y2−tsum)/2`, `t = (tx+ty)/2`.
   - **Output:** **T = t·25 ps**, **X = (x1−x2)·v_perp·25 ps**, **Y = (y1−y2)·v_perp·25 ps**. Used hits become NaN.
   - **Quirk:** `how_many_x == ~1` (513) means `== 0`.
4. **Off in production:**
   - 5-hit events with the MCP (a channel product of 42, 97–200);
   - multi-hit with the MCP (213–390);
   - 3- and 2-corner reconstructions, which rebuild the missing corner as `2(t_mcp − 3404) + tsum + poly3 − known` (612–1523).
5. **Concatenate and sort by T** (1525–1530). TXY files are therefore sorted by T.

**The autoconverter.** `legacy/tdc_autoconverter/lib/dld_read_5channels_reconst_multi_imp.m` is byte-identical to this file. `tdc_auto_convert.m` also:
- waits until a file is 1 s old;
- calls `dld_raw_to_txy_counts`, which returns counts and the last T;
- beeps when `counts/max_time < min_counts_hz`;
- plots a moving mean ± std of counts over `mov_mean_len` shots (230–251).

## HeLab compared

**HeLab's loader:**
- `helab/io_helper.py` `_read_txy_file` uses `pandas.read_csv` (t, x, y as float64).
- Rows with NaN are dropped, and the shot is flagged.
- `helab/utils/file_kinds.py` sorts files by name:
  - `d(\d+).txt` is RAW: counted, never loaded;
  - `d_txy_forc(\d+).txt` is TXY: loaded.

**Where HeLab is ahead:** settle rules, fingerprints, incremental merges, the Blosc cache, pausing and raw/TXY status classification.

**Where HeLab lacks something:**
- raw → TXY conversion;
- the XY rotation (declined);
- an import-time window, so counts per shot are totals;
- shot timestamps;
- circle masks;
- the trailing-newline check (not used, by choice).

## Other modules

### `txy_tools/`
- **`masktxy_square`:** a box with strict inequalities (12–15).
- **`masktxy_2d_circle`:** ANDs several circles; polarity 1 keeps the inside, 0 cuts it out (23–43). Used to cut hot spots and select halos.
- **`centre_BEC`:** per axis, the median of the bin centres whose counts are above a threshold (12–20). It is robust to saturation.
- **`centre_BEC_COM`:** the centre of mass within a box, with `vz = 9.8·tof` (11–34). It needs a `boxcull` that isn't in the library, and has dead code after its `end`.

### `txy_to_vel/`
- **Fall time:** `t_f = T − out_time`.
- **v_z (folder copy, 41):** `h/t_f − ½|g|t_f`.
- **v_z (top-level `lib/txy_to_vel.m`, 41):** `−h/t_f + ½|g|t_f`. **The sign is opposite.** The test (19–20) says early arrival means v₀ > 0, so the folder copy is right.
- **v_x and v_y:** `X/t_f`, `Y/t_f`, a TOF correction per count.
- **Approximation:** `v_z ≈ g·t − √(2gh)`.
- **Constants:** the library sets no fall distance; the test uses t = 0.417 s with h = ½·9.81·t².

### `fft_tx/`
**`fft_tx(t, x, window, win_param, padding, f_lim)`** (1–199) returns `[freq; complex amplitude]`:
- **Uneven samples:** if `range(diff t) > 10·eps`, it spline-resamples onto `2^nextpow2(n·(10+10·std(dt)/mean(dt)))` points (120–134).
- **Windows:** hamming, gauss, blackman, hanning, kaiser, chebyshev, bohman and blackmanharris. Each is normalised to sum = length (162–165).
- **Padding:** zero padding.
- **Amplitudes:** `fft/len` before padding, with non-DC bins ×2 (176–188).

**`dominant_freq_components`** (9–63):
- **Method:** removes the mean, then uses a Chebyshev(300) window with padding `clip(1e7/n, 1, 100)`.
- **Peaks:** keeps those above `1e-4·std(x)` and at least `5/T_span` apart.
- **Output:** amplitude, frequency and phase+π/2.

### `sewm/`
The standard error of a weighted mean (Cochran 1977, 25–39):

`SE = sqrt(n/((n−1)(Σw)²)·(Σw²x² − 2Mw·Σw²x + Mw²·Σw²))`

### `bootstrap_error/bootstrap_se.m` (490 lines)
The standard error of any estimator, by resampling. In practice the data is one cell per shot.
- **Defaults:** replace = true, `num_samp_frac` = 10, `num_samp_rep` = 10, `samp_frac_lims` = 0.1.
- **Method:**
  - SE = σ_subset·√(n_s/N).
  - Without replacement, it applies the finite-population correction (N−n)/(N−1).
  - The SE of the SE comes from the c4 factor (assuming normal data) or from the 4th moment (any distribution).
  - These are combined as a weighted mean over the subset fractions.
  - A linear fit of the estimator's mean against sample size checks for bias.

### `fast_search_histogram/` and `fast_sorted_mask/`
Histogram counts and index ranges for sorted data by binary search (O(m log n)). `hist_adaptive_method` picks a method by size, and `fast_sorted_mask` returns the range `[i0, i1]` between two bounds.
- **Python:** these are just `np.searchsorted` / `np.diff(np.searchsorted(sorted_t, edges))`.

### `smooth_hist.m`
- **Method:** a histogram (by default bin width = σ/5, capped at 2e6 bins), smoothed with `gaussfilt`. Returns counts and rates, including under- and overflow.
- **Bugs:**
  - `bin_width` is undefined in the `bin_width` branch.
  - `sigma~=0 || ~isnan(sigma)` is always true.

### `matlab_function_cache/`
`function_cache(opts, @fun, {args})` saves results to `cache__<fun>__<MD5 of args>.mat`.
- **Paths:** `mock_working_dir` makes path arguments relative.
- **Recomputing:** `recalc_if_older_than`, `force_recalc` and `force_cache_load` control it. When loading would be slower than recomputing, it saves a dummy file that says "recompute".
- **Cleaning:** it deletes files on its own, FIFO, by count (10000), size (30 GB) and age (30 days).
- **Compared with HeLab:** the MATLAB key covers neither the function's code nor the data's content. HeLab's exact-match rules (`roadmaps/result-caching.md`) and its `root://` keys go further.
- **Worth keeping:** a "load slower than recompute" hint, shown to the user rather than acted on.

### Small utilities
- `cell_manipulation`, `col_row_fun_mat`, `taylor_series`, `stfig`, `cli_*`: trivial or MATLAB-only.
- `custom_gaussian_function_2d`: a rotated 2D Gaussian kernel.
- `string_value_with_unc(v, u, 's'|'b')`: formats a value with its uncertainty as `50.12±0.15` or `8.5479(10)` (41–60). Worth porting.
- `hebec_constants.m`:
  - `mhe = 4.002·1.66e-27`;
  - `g0 = 9.7960207 − 78e-8` (Canberra, 29);
  - `b_freq = 2.802e10 Hz/T`;
  - He scattering length 15 nm (`TC_and_below` uses 7.512 nm).
- `freq_to_recoil_vel_he(f)`: `v = h·f/(c·m_He)`.
- `getlims`: indexes rows, not columns as its docstring says.

## `bin/` (third-party)

numpy, scipy or pyqtgraph replaces all of these:

| Package | Python replacement |
|---|---|
| `gaussfilt` | `gaussian_filter1d` |
| `nanconv` | normalised convolution |
| `ndhist` / `histcn` | `histogram2d` / `histogramdd` |
| Colormaps | built in |
| `export_fig` | savefig and exporters |
| `wmean` | `np.average` |
| `errorbarxy` | `ErrorBarItem` |
| `FileTime` | `os.stat`, with `st_birthtime` on macOS |
| `isalmost` | `np.isclose` |
| `closest_value` | `searchsorted` |
| `colorspace` | `matplotlib.colors` |
| `sfigure`, `genpath_exclude` | not needed |

## Ranked by the subagent

1. Counts in a window, with box and circle masks.
2. Shot timestamps and time-axis plots: moving mean ± std, and a low-count alert.
3. TXY → velocity, after settling the sign.
4. XY rotation as a view transform: ask Tony first; it has been declined.
5. Bootstrap standard error and `sewm`.
6. Value ± uncertainty formatting.
7. Smoothed histograms and BEC centre finding.
8. FFT and dominant frequencies.
9. Raw → TXY (4-corner) as a helper-side repair, validated against existing `_txy_forc` files.
