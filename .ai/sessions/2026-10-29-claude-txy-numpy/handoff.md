# Handoff: TXY converter stage 2, the NumPy backend (Worker Abacus, 2026-10-29)

Branch `agent/txy-numpy` from `372f2ac`. Brief: [brief.md](brief.md). Design and proofs:
[notes.md](notes.md). Timings: [results.md](results.md).

## Summary

- **`numpy` backend** (`helab/convert/backends/numpy_backend.py`, one `_MODULES` line):
  byte-identical to the reference on every case (both profiles, against MATLAB),
  `tests_sample_data/`, and all 309 sample shots × 2 profiles. `check_samples.py` gives the
  reference's table (303 + 6 proved exceptions); 2023 is 32/32 against MATLAB's own output.
  How it is built:
  - vectorised: the sorts, the uniquetol cut, the candidate windows (exact runs of rows), the
    first x2, the nested y-pair search and T/X/Y;
  - sequential and exact: only the x1s an earlier match could interfere with.
- **Speed.** Reconstruction runs at 258 MB/s serial (reference 13), 109 MB/s end to end on one
  core, and 332 / 558 MB/s wall on 4 / 8 processes. Latency is 4.6 ms median and 61 ms max. All
  of this was measured at load 16–19, beside four other floors.
- **Shared fast I/O** (`helab/convert/fastio.py`, used by every backend through `raw`/`txy`):
  - parse 72 → 608 MB/s (SWAR digits, GIL-free, 1,081 MB/s on 8 threads);
  - format 179 → 374 MB/s (Python's `%.8g` over padded columns, distinct X/Y values once;
    470 MB/s on 8 threads, the `%` holds the GIL);
  - tested equal to the general paths on every case and probe, and on random inputs.
- **Within-shot split** (`helab/convert/split.py`, `timing`'s `WITHIN_SHOT`):
  - it cuts at gaps wider than the window and every dead time;
  - pieces run with any backend, keeping the global t_zero, the first-row skip in piece 0 only,
    and the phantom row from a rerun of the tail;
  - one stable sort merges them;
  - identical on every case at every gap (both backends) and on all 618 sample conversions;
  - a 25 MB dense shot is 2× faster on 8 processes (the reference 4.3×).
- **Packages:** none installed (`requirements-bench.txt`: NumPy from the lock). Build files: none.

## Checks

- **Full suite:** `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`, see
  below.
- **Types:** `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests` are clean.
- **Converter tests alone:** 3,366 passed, 2 skipped (the perturbation test's single-value
  fields, as on stage 1).

Full suite at `b9b2285`: **7,848 passed, 4 skipped, no RERUN** (219 s at load ~16). Two warnings,
outside the converter: pyqtgraph setting `arr.shape` (deprecated in NumPy 2.5), from
`tests/test_t_spectrum.py::test_drawn_with_its_peak_list_and_updated_in_place`.

## Paths touched outside the brief's backend paths

The brief's own list covers `raw.py`, `txy.py`, `fastio.py`, `split.py`, `pipeline.py` (not
changed) and `timing.py`. Beyond those:

- `tests/test_convert_raw.py`: one test called stage 1's `_parse_strict`, which the fast path
  replaced; it now compares `fastio.parse_strict`.
- `tests/test_convert_harness.py`: `WITHIN_SHOT` no longer raises `NotImplementedError`. The
  timing test now runs every `Parallelism`.
- `tests/test_headless_imports.py`: `PURE` lists `backends.numpy_backend`, `fastio` and `split`
  (AGENTS.md: every converter module is pure). The other backend floors will add their modules to
  the same tuple, so a landing merges one line per floor.
- `tests/test_convert_fastio.py`, `tests/test_convert_split.py`: new, beside the brief's
  `test_convert_backend_numpy.py`.

## Notes for the landing (other floors)

- Every floor's pipeline goes through `raw.parse_raw`/`txy.format_txy`, so each gains the fast
  I/O on merge with no change of its own. The figures Anvil and Ferrous quoted for "Python"
  (69–72 MB/s parse, 153–184 format) are stage 1's paths.
- `timing.time_shot` gained optional `split`/`pieces` arguments (positional order unchanged).
  `time_shots(WITHIN_SHOT)` uses threads for a backend with `releases_gil`, processes otherwise.
- `reconstruct._MODULES`: my line is `"numpy": "helab.convert.backends.numpy_backend"` (Ferrous
  reformatted the dict one entry per line; keep every line).

## Proposed doc changes (for the Coordinator)

- **`.ai/architecture/converter.md`**:
  - **Module table:** add `fastio` ("the fast strict parse (SWAR digits) and the TXY formatter;
    `raw` and `txy` use them"), `split` ("within-shot pieces at safe gaps, any backend, merged
    byte for byte") and `backends/numpy_backend` ("vectorised match; exact pass for interfering
    x1s").
  - **`raw` row:** the fast path is `fastio.parse_strict`; fields over 16 digits take the
    general reader.
  - **`txy` row:** `format_txy` goes through `fastio`; `format_txy_by_value` is the general path.
  - **`timing` row:** within-shot is implemented (processes, or threads for `releases_gil`).
  - **Backends section, add the split rule:** cut only where `t[g+1] − t[g] >` max(window, dead
    times in bins); pieces get their rows pre-sorted and shifted (`subtract_time_zero` off), the
    skip in piece 0 only, the phantom row off. When hits + 1 > N//4, the tail from the piece with
    the last hit is rerun with the phantom row on (its floor(n/4) is then its hit count). One
    stable sort by T. The proof is in this folder's notes.md.
  - **Backends section, add the backend's principle:** "marks only remove candidates: an
    optimistic failure is final, an optimistic choice is final when its pulses are free; only x1s
    whose chosen rows an earlier x1 has as candidates need the sequential pass".
  - **Line-ending note:** the strict fast path's acceptance is tested equal to `_STRICT_CRLF` and
    `_STRICT_LF` (the regexes stay in `raw` as its definition).
- **`roadmaps/txy-converter.md`**, Stage 2: the NumPy row of the results table (from
  results.md) and its recommendation as the everywhere default; the fast I/O and the split as
  done for every backend.
- **AGENTS.md:** no new rule needed. (Optional: "a converter backend's pieces are merged by
  `split.reconstruct_split`; never split a shot another way".)

## Provisional items

- **A~1** (stage 2 final timing run): time the shared I/O and the split serially on an idle
  machine, including `time_large.py` (large dense shot) for every backend. The within-shot gain
  depends on load, and these runs were at load 16–19.
- **A~2** (stage 4): HeLab's helper should parallelise across shots with processes (as here: 4–8
  processes give 3–5×). Use within-shot only for a single large shot (Live latency) or a slow
  backend.
- **A~3** (optional, if threads ever matter): a vectorised exact `%.8g` (float scaling with a
  fallback near ties) would make formatting GIL-free. The prototype was ~1.5× slower per value
  than `%` serially, so it is not worth it while conversions run in processes.
- **Q~1** (for Tony, low stakes): keep `releases_gil=False` for numpy (threads give 1.5× on 4,
  processes 3×)? Proposed: yes; HeLab converts in helper processes.
