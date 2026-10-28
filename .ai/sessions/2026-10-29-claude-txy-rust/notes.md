# Notes: TXY converter stage 2, backend rust (Ferrous, 2026-10-29)

Branch `agent/txy-rust` from `372f2ac`. Brief: [brief.md](brief.md). Results: [results.md](results.md).
Handoff: [handoff.md](handoff.md).

## Files

| Path | What |
|---|---|
| `native/rust/Cargo.toml`, `Cargo.lock` | the crate `helab-convert-rs` (lib `helab_convert_rs`, cdylib + rlib): `pyo3 0.30` (`abi3-py311`), `numpy 0.30`; release profile `lto = "fat"`, `codegen-units = 1`, `panic = "abort"`, `strip = true` |
| `native/rust/pyproject.toml` | maturin build backend (`maturin develop --release` / `maturin build --release`), `pyo3/extension-module` feature passed by maturin only, so `cargo test` links |
| `native/rust/.gitignore` | `target/`, `*.so`, `*.pyd` |
| `native/rust/src/reconstruct.rs` | the matching (no PyO3): `prepare` (sort, t_zero, dead time), `match_piece`, `cut_points`, `reconstruct` (pieces on `std::thread::scope` threads, phantom row, final sort); the module doc holds the split proof |
| `native/rust/src/rawio.rs` | report only: `parse_strict` (raw.py's fast path) and `format_txy` (`%.8g`) |
| `native/rust/src/lib.rs` | the PyO3 module: `reconstruct`, `cut_points`, `parse_strict`, `format_txy`, `__version__`; inputs copied under the GIL, work in `py.detach` (PyO3 0.30's name for `allow_threads`) |
| `helab/convert/backends/rust.py` | the backend: typed `Native` Protocol over the lazily imported module (`_import_native`, the test seam; loaded once under a lock, so threads asking first all get it: tested with 32 threads on a slowed import, one import), `unavailable`, `reconstruct_rust(pulses, profile, threads, piece_rows)`, registers `rust` with `releases_gil=True` |
| `helab/convert/reconstruct.py` | one `_MODULES` line (`"rust": "helab.convert.backends.rust"`); the dict is now one entry per line so the five floors' lines merge |
| `tests/test_convert_backend_rust.py` | 197 tests; without the module 195 skip with "rust extension not built (stage 4 packaging): helab_convert_rs; …" and 2 run (registration, the unavailable path) |
| `compare_samples.py`, `bench_rust.py` (this folder) | the sample comparison and the extra timings |

Build: `source venv/bin/activate && cd native/rust && maturin develop --release` (≈10 s warm, ≈1 min
cold; Homebrew `rustc 1.99.1`, untouched). `cargo test --release` needs
`PYO3_PYTHON=<abs path>/venv/bin/python`.

## How the port differs in form (not in output)

The reference keeps MATLAB's `five_channel_output_4corners` matrix and its `which_row` counter.
The Rust port doesn't: rows 1..R of that matrix always end as the R hits in order (an attempt whose
y fails writes row `which_row` and steps back, so the next attempt overwrites it), and only row
R + 1 can hold anything else: the last failed attempt after the last hit. MATLAB's matrix holds
`floor(N/4)` NaN rows and grows with zeros, so row R + 1 survives (T = 0, Y = 0) exactly when
R + 1 > floor(N/4) and `matlab_overflow_row`. The port keeps a list of hit rows and the last
failed attempt (`Piece::trailing`) and adds that row at the end under the same condition. Rows
whose T is NaN are still counted in R and dropped at the end, as the reference does (they can't
occur with finite inputs, but the rule is the same).

The x2 search stops at the first x2, the y search at the first pair: in MATLAB a second candidate
only ends its loop (L479, L546) and writes nothing; marks of used pulses happen only for the first
pair. Everything else is line for line, with the reference's line numbers.

f64 semantics: comparisons are IEEE in both (NaN compares false, so a NaN time is never skipped
by the window test but never matches; the same in Rust). The sorts are stable with NaN last and
`partial_cmp`, so −0 and 0 keep their order (`total_cmp` would not). Arithmetic is written in the
reference's order (`0.5 * (x1 + x2 - t_sum)`, `(tx + ty) / 2.0`, `(a - b) * v * bin_time`). No
`mul_add` anywhere, and rustc never contracts `a * b + c` to an FMA by itself (LLVM's
fp-contract is off for Rust; the Cython floor needed `-ffp-contract=off` for the same bits). `dead_time / bin_time` and the two limit sums are computed
in Python, as the reference does, and passed in.

## Within-shot split: how the cut is chosen and why it can't change the output

`cut_points(t, window, piece_rows)`: walking the sorted, t_zero-subtracted times, a cut before
row k is allowed only when `t[k−1]` and `t[k]` are both finite and `t[k] − t[k−1] > search_window`
(3200). The pieces aim at `piece_rows` rows: from each piece's start + `piece_rows`, the first
allowed gap. `threads > 1` with `piece_rows = 0` means about four pieces per thread.

Proof sketch (also the module doc of `reconstruct.rs`):

1. For x1 at row i < k and any row j ≥ k: `t[j] ≥ t[k]`, `t[i] ≤ t[k−1]`, and rounding is
   monotonic, so `fl(t[j] − t[i]) ≥ fl(t[k] − t[k−1]) > window` (and `fl(a − b) = −fl(b − a)` for
   the other side). Every candidate test (x2 L465, y1 L515, y2 L538) checks the window **before**
   the channel and skips such a row. This holds whatever the row distance, so the 36-row search
   (±18 rows) never reaches across: a row beyond the cut is skipped in MATLAB too, and the piece's
   bounds only make that explicit.
2. Infinite and NaN times never match (every comparison with NaN, or `Inf − Inf`, is false), and
   no cut goes next to one.
3. So no match and no NaN mark of a used pulse crosses a cut; each piece's sequence of attempts
   (hit or failed) is what the whole run does over those rows, in the same order.
4. Global state stays global: the sort and `t_zero` (the first **raw** row) come first; the
   dead-time cut (uniquetol over a whole channel, groups up to 20,000 bins, wider than the window)
   runs on the whole shot before cutting; the first-row skip is global row 0, which only the first
   piece holds; the phantom row uses the whole shot's N and R, and the trailing attempt is taken
   across pieces (walking back from the last piece: the first piece with a trailing attempt gives
   it, unless a piece with hits comes first); one stable sort by T over all pieces' rows in order.

Tested: every case and both profiles split at every allowed gap (`piece_rows=1`) on 1 and 3
threads and automatically on 4; 320 random shots (dense ones with phantom rows, gaps at, just
over and far over the window and the dead time, near-sorted file order, NaN times, t_zero not the
trigger) under seven splits; a hand-built shot whose phantom comes from an earlier piece; and the
309 sample shots under both profiles, every-gap on 1 and 8 threads and automatic on 8
(`compare_samples.py`: up to 741,370 pieces in one shot), all bit-identical to the reference.

## Speed: the sort was the cost

First build: 286 MB/s serial reconstruct, and splitting a shot on threads barely helped.
`examples/phases.rs` on the largest sample (2019-halos d2227, 1,590,770 rows, 20 hits, 79,524
descents in file order) showed why: `prepare` 31–36 ms of a 31–34 ms call; matching ≈ 1 ms. Sort
variants on that file (one-off experiment, removed): pairs `sort_by` 23 ms, `(u64 key, index)`
stable + gather 22 ms, unstable 22 ms, `(u64 key, channel)` stable 20 ms, **insertion sort 3.4–3.8 ms**
(1,228,185 moves: under one per row). On a momentum-bells shot: 0.85 ms vs 0.27 ms.
`sort_rows` now runs the insertion sort with a budget of 16 moves per row and hands the rest to
`sort_by` (stable) past it; because insertion never swaps equal keys, equal times are still in file
order at the hand-over, so the result is the stable sort's either way (tested: nearly sorted,
reversed, scrambled, ties, −0 beside 0, NaN; and reversed/shuffled shots against the reference).
The rows are now built once, under the GIL, from the NumPy arrays. The same shot: 5.5 ms;
serial reconstruct 969 MB/s.

## Byte-identity results

- `tests/data/convert/cases/`: 39 × 2 variants identical to MATLAB's output and outcome.
- `tests_sample_data/`: all lab pairs reproduced, every split.
- `dev/txy/check_samples.py --positions all --backend rust` (matlab-2019): 303 identical, cut 1,
  variant 2, empty 3, differ 0; every proof held again (exit 0).
- `compare_samples.py --positions all`, both profiles: 309 shots × 4 rust variants, 0 differ
  against the reference. For `matlab-2023-lab-edit` the reference is the bar (it matched MATLAB's
  own 2023 output on 184 shots in stage 1; that MATLAB output isn't on this floor).

## Packages (floor venv only)

`maturin==1.15.0` (`requirements-bench.txt`), and the crate itself as `helab-convert-rs 0.1.0`
(editable, `maturin develop`). Rust crates come from crates.io through Cargo (`Cargo.lock`).
