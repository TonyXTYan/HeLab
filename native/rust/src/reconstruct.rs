//! MATLAB's 4-corner reconstruction (`dld_read_5channels_reconst_multi_imp`), as
//! `helab/convert/backends/reference.py` ports it, byte for byte. Line numbers `L…` are the 2019
//! file's, `L2023:…` the front panel's 2023 copy; the reference's docstring lists the quirks.
//!
//! Two things differ in form from the reference, not in output:
//!
//! - The output matrix isn't kept. MATLAB writes row `which_row` for each x1 whose x2 matched and
//!   steps back when its y doesn't, so rows 1..R end up as the R hits and row R + 1 holds the last
//!   failed attempt after the last hit, if there was one. That row survives only when MATLAB grew
//!   the matrix to reach it (R + 1 > floor(N/4)): the phantom row, T = 0 and Y = 0. Here the hits
//!   are a list and the last failed attempt is remembered (`Piece::trailing`).
//! - The search stops at the first x2 and the first y pair. MATLAB goes on looking, but a second
//!   candidate only ends its loop and writes nothing.
//!
//! **Within one shot** the sorted rows can be cut into pieces matched apart (`cut_points`). A cut
//! goes only between two finite times more than the search window apart. Every row an x1 looks at
//! across the cut is then further than the window from it (subtraction rounds monotonically, so
//! `|t[j] − t[i]| ≥ t[k] − t[k−1] > window` holds in floating point too), and MATLAB skips such a
//! row before reading its channel (L465, L515, L538), whatever its distance in rows within the 36
//! searched; so no match, and no mark of a used pulse, crosses a cut. NaN and infinite times
//! never match anything, and no cut goes next to one. What stays global: `t_zero` and the sort
//! (done first), the dead-time cut (done before cutting), the first-row skip (global row 0, in
//! the first piece), floor(N/4) for the phantom row (the whole file's N; the trailing attempt is
//! taken across pieces in order), and the final stable sort by T over all pieces' hits in order.

use std::cmp::Ordering;
use std::sync::atomic::{AtomicUsize, Ordering as AtomicOrdering};
use std::sync::Mutex;

/// The profile, as the Python side unpacks it (`backends/rust.py`).
#[derive(Clone, Debug)]
pub struct Params {
    pub channel_x1: f64,
    pub channel_x2: f64,
    pub channel_y1: f64,
    pub channel_y2: f64,
    pub subtract_time_zero: bool,
    pub skip_first_sorted_row: bool,
    /// Per corner (x1, x2, y1, y2): `dead_time / bin_time` in bins, or None for no cut.
    pub dead_time_bins: [Option<f64>; 4],
    pub search_depth: usize,
    /// T_sum (L465).
    pub search_window: f64,
    /// T_sum_tol_throw (L440): `match_time_sum_x + match_tolerance_x`.
    pub x_limit: f64,
    /// T_sum_tol_keep (L441): `match_time_sum_y + match_tolerance_y`.
    pub y_limit: f64,
    /// two_tolerance_keep (L442).
    pub xy_limit: f64,
    pub time_sum_t_x: f64,
    pub time_sum_t_y: f64,
    pub bin_time: f64,
    pub v_perp_x: f64,
    pub v_perp_y: f64,
    /// "centred" (2019) or "raw" (2023) columns.
    pub centred: bool,
    pub matlab_overflow_row: bool,
}

/// MATLAB's `sort`: ascending, NaN last; equal values (−0 and 0 among them) keep their order
/// when the sort is stable.
#[inline]
fn nan_last(a: f64, b: f64) -> Ordering {
    match (a.is_nan(), b.is_nan()) {
        (false, false) => a.partial_cmp(&b).unwrap_or(Ordering::Equal),
        (false, true) => Ordering::Less,
        (true, false) => Ordering::Greater,
        (true, true) => Ordering::Equal,
    }
}

/// The rows searched around x1 (L456–457): −1, +1, −2, +2, …
pub fn offsets(depth: usize) -> Vec<isize> {
    let mut out = Vec::with_capacity(depth);
    let mut dummy: isize = 0;
    for count2 in 1..=depth as isize {
        dummy += if count2 % 2 == 0 { count2 } else { -count2 };
        out.push(dummy);
    }
    out
}

/// The rows of a shot after the sort, time zero and the dead-time cut: what the matching reads.
pub struct Sorted {
    pub ch: Vec<f64>,
    pub t: Vec<f64>,
}

/// Sorts `(time, channel)` rows by time, stably, NaN last. The TDC writes nearly in time order (a
/// raw file's rows move about one place each on average), so an insertion sort goes first; past a
/// budget of moves it hands over to the merge sort. Insertion never swaps equal times, so equal
/// times are still in file order when it hands over, and the stable merge sort ends in the same
/// order as on the file's rows.
pub fn sort_rows(rows: &mut [(f64, f64)]) {
    let mut budget = rows.len().saturating_mul(16);
    for i in 1..rows.len() {
        let mut j = i;
        while j > 0 && nan_last(rows[j - 1].0, rows[j].0) == Ordering::Greater {
            rows.swap(j - 1, j);
            j -= 1;
            budget = budget.saturating_sub(1);
        }
        if budget == 0 {
            rows.sort_by(|a, b| nan_last(a.0, b.0));
            return;
        }
    }
}

/// The file's `(time, channel)` rows in file order, as `prepare` and `reconstruct_rows` take them.
pub fn file_rows(channels: &[f64], times: &[f64]) -> Vec<(f64, f64)> {
    times.iter().copied().zip(channels.iter().copied()).collect()
}

/// L58–66 and L2023:429–458: sort the file's rows by time (stable, NaN last), subtract the first
/// raw row's time, then drop all but the first pulse of each dead-time group per corner.
pub fn prepare(mut rows: Vec<(f64, f64)>, p: &Params) -> Sorted {
    let n = rows.len();
    let t_zero = rows.first().map(|row| row.0);
    sort_rows(&mut rows);
    let mut ch: Vec<f64> = rows.iter().map(|row| row.1).collect();
    let t: Vec<f64> = match t_zero {
        Some(zero) if p.subtract_time_zero => rows.iter().map(|row| row.0 - zero).collect(),
        _ => rows.iter().map(|row| row.0).collect(),
    };
    drop(rows);

    if p.dead_time_bins.iter().any(Option::is_some) {
        let snapshot = ch.clone();
        let corners = [p.channel_x1, p.channel_x2, p.channel_y1, p.channel_y2];
        for (corner, tol) in corners.iter().zip(p.dead_time_bins.iter()) {
            let Some(tol) = *tol else { continue };
            // uniquetol(…, tol, 'DataScale', 1): the first of each group within tol (≤) of the
            // group's first value, not chained; every NaN its own group.
            let mut first = f64::NAN;
            for k in 0..n {
                if snapshot[k] != *corner {
                    continue;
                }
                let value = t[k];
                // `!(… <= tol)`, not `> tol`: as the reference writes it (equal for these
                // non-NaN values, and kept so it reads alike).
                #[allow(clippy::neg_cmp_op_on_partial_ord)]
                let outside = !((value - first).abs() <= tol);
                if value.is_nan() || first.is_nan() || outside {
                    first = value;
                } else {
                    ch[k] = f64::NAN;
                }
            }
        }
    }
    Sorted { ch, t }
}

/// One piece's matches: rows `[t, x1′, x2′, y1′, y2′]` in order, and the columns of the last x1
/// whose x2 matched but whose y didn't, after the piece's last hit.
pub struct Piece {
    pub rows: Vec<[f64; 5]>,
    pub trailing: Option<(f64, f64)>,
}

/// L449–576 for the x1 rows in `[lo, hi)`, looking only at rows in `[lo, hi)`. `ch` is the
/// piece's own slice of channels (used pulses become NaN); `t` and the indices are global.
fn match_piece(ch: &mut [f64], t: &[f64], lo: usize, hi: usize, search: &[isize], p: &Params) -> Piece {
    let mut rows: Vec<[f64; 5]> = Vec::with_capacity((hi - lo) / 4);
    let mut trailing: Option<(f64, f64)> = None;
    let window = p.search_window;
    let first = if p.skip_first_sorted_row { 1 } else { 0 };
    let at = |j: isize| -> Option<usize> {
        if j < lo as isize || j >= hi as isize { None } else { Some(j as usize) }
    };
    for i in lo.max(first)..hi {
        if ch[i - lo] != p.channel_x1 {                                  // L450
            continue;
        }
        let x1 = t[i];                                                   // L451
        // L456–490: the first x2 in search order; a second only ends the search (L479).
        let mut found_x2: Option<(usize, f64)> = None;
        for &dummy in search {
            let Some(j) = at(i as isize + dummy) else { continue };     // L459–464
            if (t[j] - x1).abs() > window {                              // L465
                continue;
            }
            if ch[j - lo] == p.channel_x2 && (x1 - t[j]).abs() < p.x_limit {  // L474, L477
                found_x2 = Some((j, t[j]));
                break;
            }
        }
        let Some((x2_index, x2)) = found_x2 else { continue };          // L498: how_many_x == ~1
        let tx = 0.5 * (x1 + x2 - p.time_sum_t_x);                       // L485 (L2023:519)
        let (x1c, x2c) = if p.centred { (x1 - tx, x2 - tx) } else { (x1, x2) };  // L486–487

        // L505–555: the first y pair in search order, both around x1; a second pair writes
        // nothing (L546).
        let mut hit: Option<[f64; 5]> = None;
        'y1: for &dummy2 in search {
            let Some(j2) = at(i as isize + dummy2) else { continue };   // L509–514
            if (t[j2] - x1).abs() > window || ch[j2 - lo] != p.channel_y1 {  // L515, L524
                continue;
            }
            let y1 = t[j2];
            for &dummy3 in search {
                let Some(j3) = at(i as isize + dummy3) else { continue };  // L532–537
                if (t[j3] - x1).abs() > window || ch[j3 - lo] != p.channel_y2 {  // L538, L542
                    continue;
                }
                let y2 = t[j3];
                if (y1 - y2).abs() < p.y_limit && (x1 + x2 - y1 - y2).abs() < p.xy_limit {  // L544
                    let ty = 0.5 * (y1 + y2 - p.time_sum_t_y);           // L551 (L2023:585)
                    let hit_t = (tx + ty) / 2.0;                         // L552
                    let (y1c, y2c) = if p.centred { (y1 - ty, y2 - ty) } else { (y1, y2) };
                    hit = Some([hit_t, x1c, x2c, y1c, y2c]);             // L553–555
                    ch[i - lo] = f64::NAN;                               // L557–560
                    ch[x2_index - lo] = f64::NAN;
                    ch[j2 - lo] = f64::NAN;
                    ch[j3 - lo] = f64::NAN;
                    break 'y1;
                }
            }
        }
        match hit {
            Some(row) => {
                rows.push(row);
                trailing = None;
            }
            None => trailing = Some((x1c, x2c)),                         // L574–576
        }
    }
    Piece { rows, trailing }
}

/// Where to cut `t` (sorted) into pieces of about `piece_rows` rows: each cut index `k` starts a
/// piece and has finite `t[k−1]`, `t[k]` with `t[k] − t[k−1] > window`. `piece_rows` 0: no cut;
/// 1: every gap that allows one. Returns the piece bounds, `[0, …, n]`.
pub fn cut_points(t: &[f64], window: f64, piece_rows: usize) -> Vec<usize> {
    let n = t.len();
    let mut bounds = vec![0];
    if piece_rows > 0 {
        let mut k = piece_rows.max(1);
        while k < n {
            if t[k - 1].is_finite() && t[k].is_finite() && t[k] - t[k - 1] > window {
                bounds.push(k);
                k = k.saturating_add(piece_rows);
            } else {
                k += 1;
            }
        }
    }
    bounds.push(n);
    bounds
}

/// More threads than this are asked for as this many (and never more than there are pieces).
pub const MAX_THREADS: usize = 256;

/// A piece's bounds and its own channels.
type Slice<'a> = (usize, usize, &'a mut [f64]);

/// The hits, `n × 3` row-major (T s, X m, Y m), sorted by T; and the number of pieces matched.
/// `threads` > 1 matches pieces on that many threads (at most `MAX_THREADS`, and the piece
/// count); `piece_rows` 0 with `threads` > 1 picks about four pieces per thread.
pub fn reconstruct(channels: &[f64], times: &[f64], p: &Params, threads: usize, piece_rows: usize) -> (Vec<f64>, usize) {
    reconstruct_rows(file_rows(channels, times), p, threads, piece_rows)
}

/// `reconstruct` of the file's rows (`file_rows`).
pub fn reconstruct_rows(rows: Vec<(f64, f64)>, p: &Params, threads: usize, piece_rows: usize) -> (Vec<f64>, usize) {
    let n = rows.len();
    if n == 0 {
        return (Vec::new(), 0);
    }
    let Sorted { mut ch, t } = prepare(rows, p);
    // Offsets past ±N never land on a row, so a deeper search than 2N + 2 is the same search.
    let search = offsets(p.search_depth.min(n.saturating_mul(2).saturating_add(2)));
    let threads = threads.clamp(1, MAX_THREADS);
    let piece_rows = if piece_rows == 0 && threads > 1 { n.div_ceil(threads.saturating_mul(4)) } else { piece_rows };
    let bounds = cut_points(&t, p.search_window, piece_rows);

    // Each piece gets its own slice of ch: pieces never touch each other's rows.
    let mut slices: Vec<Slice> = Vec::with_capacity(bounds.len() - 1);
    let mut rest: &mut [f64] = &mut ch;
    for w in bounds.windows(2) {
        let (head, tail) = rest.split_at_mut(w[1] - w[0]);
        slices.push((w[0], w[1], head));
        rest = tail;
    }
    let count = slices.len();
    let pieces: Vec<Piece> = if threads == 1 || count == 1 {
        slices.into_iter().map(|(lo, hi, c)| match_piece(c, &t, lo, hi, &search, p)).collect()
    } else {
        let jobs: Vec<Mutex<Option<Slice>>> = slices.into_iter().map(|s| Mutex::new(Some(s))).collect();
        let done: Vec<Mutex<Option<Piece>>> = (0..count).map(|_| Mutex::new(None)).collect();
        let next = AtomicUsize::new(0);
        std::thread::scope(|scope| {
            for _ in 0..threads.min(count) {
                scope.spawn(|| loop {
                    let k = next.fetch_add(1, AtomicOrdering::Relaxed);
                    if k >= count {
                        break;
                    }
                    let (lo, hi, c) = jobs[k].lock().unwrap().take().unwrap();
                    let piece = match_piece(c, &t, lo, hi, &search, p);
                    *done[k].lock().unwrap() = Some(piece);
                });
            }
        });
        done.into_iter().map(|m| m.into_inner().unwrap().unwrap()).collect()
    };

    // L444 and the zeros MATLAB grows the matrix with: row R + 1 survives only past floor(N/4).
    let total: usize = pieces.iter().map(|piece| piece.rows.len()).sum();
    let mut phantom: Option<(f64, f64)> = None;
    for piece in pieces.iter().rev() {
        if piece.trailing.is_some() {
            phantom = piece.trailing;
            break;
        }
        if !piece.rows.is_empty() {
            break;
        }
    }
    let mut kept: Vec<[f64; 3]> = Vec::with_capacity(total + 1);
    let (b, vx, vy) = (p.bin_time, p.v_perp_x, p.v_perp_y);
    let mut emit = |row: &[f64; 5]| {
        // L580–581: keep the rows with a T; L590–592: scale, in MATLAB's order.
        if !row[0].is_nan() {
            kept.push([row[0] * b, (row[1] - row[2]) * vx * b, (row[3] - row[4]) * vy * b]);
        }
    };
    for piece in &pieces {
        piece.rows.iter().for_each(&mut emit);
    }
    if let Some((x1c, x2c)) = phantom {
        if p.matlab_overflow_row && total + 1 > n / 4 {
            emit(&[0.0, x1c, x2c, 0.0, 0.0]);
        }
    }
    // L1525–1530: sort by T, stably.
    kept.sort_by(|a, b| nan_last(a[0], b[0]));
    (kept.into_iter().flatten().collect(), count)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn offsets_alternate() {
        assert_eq!(offsets(6), vec![-1, 1, -2, 2, -3, 3]);
    }

    #[test]
    fn sort_rows_is_the_stable_sort_whichever_way_it_goes() {
        // Nearly sorted (insertion), reversed and scrambled (over budget: merge sort), with ties,
        // −0 beside 0 and NaN; the channel numbers the rows, so stability shows.
        let mut seed: u64 = 7;
        let mut next = || { seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407); seed >> 33 };
        for case in 0..3 {
            let rows: Vec<(f64, f64)> = (0..5000)
                .map(|k| {
                    let r = next();
                    let time = match case {
                        0 => (k / 3) as f64 + (r % 3) as f64,
                        1 => (5000 - k) as f64 / 4.0,
                        _ => (r % 50) as f64,
                    };
                    let time = if r % 97 == 0 { f64::NAN } else if r % 89 == 0 { -0.0 } else if r % 83 == 0 { 0.0 } else { time };
                    (time, k as f64)
                })
                .collect();
            let mut expected = rows.clone();
            expected.sort_by(|a, b| nan_last(a.0, b.0));
            let mut got = rows.clone();
            sort_rows(&mut got);
            assert!(got.iter().zip(&expected).all(|(a, b)| a.0.to_bits() == b.0.to_bits() && a.1 == b.1), "case {case}");
        }
    }

    #[test]
    fn cuts_only_at_wide_finite_gaps() {
        let t = [0.0, 1.0, 5000.0, 5001.0, f64::INFINITY, f64::NAN];
        assert_eq!(cut_points(&t, 3200.0, 1), vec![0, 2, 6]);
        assert_eq!(cut_points(&t, 3200.0, 0), vec![0, 6]);
    }
}
