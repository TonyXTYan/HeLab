# Handoff: TXY converter stage 2, backend rust (Ferrous, 2026-10-29)

Branch `agent/txy-rust` from `372f2ac`. Brief: [brief.md](brief.md). Detail: [notes.md](notes.md).
Timings: [results.md](results.md).

## Summary

A `rust` backend (PyO3 0.30 + numpy 0.30, abi3-py311, built with maturin) that gives the
reference's output **bit for bit**: 39 cases × 2 profiles against MATLAB, `tests_sample_data`,
every sample shot through `check_samples.py --backend rust` (303 identical + the 6 listed
exceptions, each proof held again), and all 309 shots under both built-ins in four variants
(whole; cut at every allowed gap on 1 and 8 threads; automatic pieces on 8 threads), compared as
array bytes against the reference. It releases the GIL, imports lazily, and HeLab and the tests
run without it: 195 of its 197 tests skip with "rust extension not built (stage 4 packaging): helab_convert_rs; …".

Speed (machine busy, load ~8, four other backend floors running; see results.md):
reconstruction **969 MB/s serial** (1.6 GB/s on large shots), about 75× the reference's 12.8 in
the same run; whole pipeline 47 MB/s per core, 136 / 226 / 258 MB/s on 4 / 8 / 16 processes,
bound by the shared Python read (≈ 70 MB/s) and write (≈ 160 MB/s), not the backend. The Rust
raw parser and formatter (report only) run at 1,910 and 596 MB/s: with fast I/O one core would
reach ≈ 320 MB/s. Threads stay at ≈ 47 MB/s (Python I/O holds the GIL); splitting one shot gains
≤ 1.3×. No JIT: first call 0.1 ms after a 0.7 ms import. Adds ≈ 0.44 MB to a PyInstaller build
(estimated from the wheel).

One speed-up beyond the port: raw rows are nearly in time order, so the stable sort starts with
an insertion pass (budget 16 moves per row, then the stable merge sort; equal keys never swap, so
the order is the stable sort's either way): 31 → 5.5 ms on the 1.6 M-row shot.

## What was built (owned paths)

- `native/rust/` (new): `Cargo.toml`, `Cargo.lock`, `pyproject.toml` (maturin), `.gitignore`
  (`target/`, `*.so`, `*.pyd`), `src/reconstruct.rs` (the matching, no PyO3), `src/rawio.rs`
  (report-only raw parser and `%.8g` formatter), `src/lib.rs` (PyO3 module `helab_convert_rs`),
  `examples/phases.rs` (dev phase timings).
- `helab/convert/backends/rust.py` (new): typed `Native` Protocol over the lazily imported
  module, `unavailable`, `reconstruct_rust(pulses, profile, threads=1, piece_rows=0)`, registers
  `rust` with `releases_gil=True`.
- `helab/convert/reconstruct.py`: the one `_MODULES` line. I wrote the dict one entry per line so
  each floor's line merges as its own hunk; a landing that meets another floor's one-line edit
  keeps every entry.
- `tests/test_convert_backend_rust.py` (new).
- This folder: brief, notes, results, handoff, `compare_samples.py`, `bench_rust.py`,
  `requirements-bench.txt`.

Nothing in `pyproject.toml` (there is none at the root), `setup.py`, `HeLab.spec`,
`requirements*.txt` or the shared converter modules beyond the `_MODULES` line.

## Within-shot split (how the cut is chosen, why it's safe)

Cut only between two finite sorted times more than `search_window` (3200 bins) apart; pieces of
about `piece_rows` rows (or four per thread). Every candidate test checks the window before the
channel, and float subtraction is monotonic, so nothing across a cut is ever looked at, whatever
its row distance (the 36-row search included). Global: t_zero, the sort and the dead-time cut
(before cutting), the first-row skip (global row 0), floor(N/4) and the phantom row (the trailing
failed attempt taken across pieces), one final stable sort. Proof in notes.md and the module doc
of `reconstruct.rs`; tested on every case, random shots with phantom rows, a hand-built
cross-piece phantom, and all 309 samples (up to 741,370 pieces in one shot).

## Checks

On the final build (load ≈ 12, four other floors running):

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: **6276 passed, 4 skipped**
  (the 4 are stage 1's, none of mine), no RERUN, 161 s.
- `mypy helab/ --strict` (174 files), `mypy tests --strict` (145 files), `pyright helab tests`: clean.
- `cargo test --release` 5 passed; `cargo clippy --release --all-targets` no warnings.
- Without the module (uninstalled): `tests/test_convert_backend_rust.py` 2 passed, 195 skipped with
  "rust extension not built (stage 4 packaging): helab_convert_rs; `maturin develop --release` in
  native/rust"; reinstalled after.
- `check_samples.py --positions all --backend rust`: 303 identical + 6 listed (proofs held), differ 0.
- `compare_samples.py --positions all`, both built-ins: 309 × 4 variants, 0 differ.
- Loader: 32 threads asking for the module at once on a slowed import get it, with one import
  (Anvil's race note); no FMA (`mul_add` unused, rustc doesn't contract).

## CI wheels and packaging (for the packaging floor, stage 4)

- **Build**: `PyO3/maturin-action@v1`, `command: build`, `args: --release --out dist -m
  native/rust/Cargo.toml`, one job per target: macOS arm64 (`macos-14`) and x86_64 (`macos-13`),
  or one `--target universal2-apple-darwin` wheel; Windows x64 (`windows-latest`, MSVC is on the
  runner); Linux x86_64 with `manylinux: auto` (manylinux2014 or 2_28 container). Cache with
  `Swatinem/rust-cache` (cold compile ≈ 1 min here, warm ≈ 10 s).
- **abi3**: the crate builds `abi3-py311`, so one wheel per OS and architecture serves CPython
  3.11–3.14 (CI's compat matrix). Free-threaded builds (3.13t/3.14t) can't load abi3 wheels; not
  needed today.
- **Runtime**: only NumPy (rust-numpy reaches the C API through NumPy's capsule at run time, so the
  build needs no NumPy headers; 1.x and 2.x both load). No Rust needed where it runs.
- **CPU**: don't set `target-cpu=native` in CI. The default x86_64 target needs no AVX, so the
  wheel runs on the Lab Side PC (Sandy Bridge).
- **PyInstaller**: the backend imports `helab_convert_rs` through `importlib`, so `HeLab.spec`
  needs `hiddenimports=[…, "helab_convert_rs"]`; the abi3 `.so`/`.pyd` is collected as a binary and
  must be signed with the app on macOS. maturin's wheel is a package (`helab_convert_rs/__init__.py`
plus `helab_convert_rs.abi3.so`), so list `helab_convert_rs.helab_convert_rs` too if PyInstaller
misses it. Size added: ≈ 0.44 MB (the `.so`, 440,864 B; wheel 223,549 B; estimated from the
wheel, not a scratch build).
- **Tests in CI**: they skip today (nothing builds the module). To run them, a job step
  `pip install maturin && maturin develop --release -m native/rust/Cargo.toml` (or install the
  built wheel) before pytest.

## Proposed doc changes (for the Coordinator)

- `.ai/architecture/converter.md`, module table: a row for `backends/rust` ("the matching in Rust,
  `native/rust/` (PyO3, maturin); typed wrapper, lazy import; `reconstruct_rust(threads,
  piece_rows)` splits one shot"). Under "Backends (stage 2)": the cut rule (only between finite
  times more than `search_window` apart, because every candidate test checks the window before the
  channel) and the phantom-row rule for pieces (row R + 1 survives when R + 1 > floor(N/4); the
  trailing failed attempt is taken across pieces). A line that a stable sort may start with an
  insertion pass, since raw files are nearly in time order (≈ 1 move per row), as long as it hands
  over to a stable sort (equal keys never swapped).
- `tests/test_headless_imports.py` `PURE`: add `"backends.rust"` to the `helab.convert` list (it
  imports only the standard library, NumPy and the compiled module).
- AGENTS.md code map row for `helab/convert/`: mention `native/rust/` (or a `native/` row once
  other floors add theirs).

## Provisional items

- **Q~1** (Tony / CoCo): ship the rust backend? Proposed: as an optional fast backend built in CI
  wheels for the three OSes, with the NumPy (or reference) backend as the default that works
  everywhere; decide with the other floors' results.
- **A~1** (stage 4 packaging, Side): build the rust extension in CI on macOS, Windows and Linux
  (maturin, above) before pytest, and turn the skips into required tests there: in that job,
  "rust extension not built (stage 4 packaging)" must not appear (fail if `helab_convert_rs`
  doesn't import), so all 197 tests of `tests/test_convert_backend_rust.py` run on every OS. Plus
  the wheel jobs and the `hiddenimports` line.
- **A~2** (stage 2 final timings): time `rust` with the shared fast I/O (fastio) once it lands; the
  backend is no longer the bottleneck. The Rust `parse_strict`/`format_txy` numbers in results.md
  are the comparison point.
- **M~1** (Tony, once a CI wheel exists): install it on a lab PC (Windows, Sandy Bridge) and convert
  one shot with `backend="rust"`, to see the wheel load there.

## RERUNs

None: no test needed a rerun in any run on this floor (two full suites, 6275 and 6276 passed).
