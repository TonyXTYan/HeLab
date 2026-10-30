# Brief: TXY converter stage 4, HeLab core (`agent/txy-helab-core`)

Coordinator: CoCo, 2026-10-29 (overnight build; Side approves on Tony's behalf within the
[mandate](../2026-10-29-claude-v0.0.7-overnight/mandate.md)). One Worker, then a Reviewer. The
Live, UI and packaging floors start from this floor's landed commit, so its interfaces are theirs.

## Read first

1. `AGENTS.md` (all of it: the I/O, cache, settings and source-folder rules apply here in full),
   `roadmaps/agent-workflow.md`.
2. `roadmaps/txy-converter.md` (Decided; Stage 4), the mandate's stage 4 split.
3. `.ai/architecture/converter.md`, `.ai/architecture/io-and-browsing.md`,
   `.ai/architecture/cache-store.md`, `.ai/architecture/data-roots.md`, `.ai/architecture/settings.md`,
   `.ai/architecture/live.md` (its settle and notification parts).
4. `.ai/DECISIONS_TODO.md` Q8.2, Q9.1–Q9.9, Q10.2, Q10.3; `.ai/AI_TODO.md` A10.1, A10.3–A10.5,
   and the stage 2 handoffs' stage 4 items (`.ai/sessions/2026-10-29-claude-txy-*/handoff.md`):
   the lock in `reconstruct._load`, the numba cache seam wired to `cache_dir()` (Side's decision;
   restart helpers after a cache move or accept a stray folder), backends as optional behind the
   switch.

## Base and branch

Base `ed35099` (stage 2 landed on `dev/v0.0.7`). Branch `agent/txy-helab-core` (this floor).

## Objective

HeLab converts settled raw files to TXY in its I/O helpers, safely, with provenance, and a
headless `helab convert --watch <folder>` does the same without the GUI. No GUI controls yet
(the Live and UI floors add them on top of what you build).

## Scope

1. **The helper operation** (`helab/io_ops/convert.py`, dispatched by `helab/io_helper.py`):
   convert the given shots of a folder with a profile and backend, writing each TXY atomically
   (`txy.write_atomic`, A10.4), with heartbeats, cancellation and the usual slot rules
   (`IOService`). It is source I/O: **Work Offline refuses it** (not in `OFFLINE_OPERATIONS`),
   and every source path goes through the source guard in tests.
2. **Settle checks for raw files** (A10.1; evidence 2019-halos d3667, which MATLAB read
   half-written): a raw file is converted only when unchanged for `SETTLE_SECONDS` (5 s, as
   `fingerprints`), its size stable between two checks, ending with a newline, and its first
   line on the profile's trigger channel. Not settled: skip and retry later, never read twice in
   a row as if done. A file with no rows (Q10.2, proposed): refused while it may still be
   written; once settled, reported as unconvertible (an event, no TXY), never silently skipped.
   Test each check with synthetic files, including a half-written one.
3. **Event kinds** in `helab/io_ops/events.py` (TypedDicts, `KINDS`, both sides checked by
   `tests/test_helper_events.py`): at least a converted shot (shot, output path, hit count,
   profile name/version/hash, backend, raw fingerprint, timings), an unconvertible shot (reason),
   and progress. Name them for what the Live floor will need (a low-count shot is detected from
   the hit count there, not here).
4. **The file kind** `d_txy_helab_<N>.txy` in `helab/utils/file_kinds.py`: matched and counted
   (`loaded=False` for now). Which TXY a dataset loads (MATLAB's, HeLab's, or both, Q6.6) is the
   UI floor's job; don't change what loads today.
5. **Where the TXY go** (Q9.3, Q9.7): a setting (a row in `settings_defaults.py`, read with
   `read_setting`), values `temp` and `cache`, default `cache`; plus a per-folder option to write
   beside the raw files (stored like the existing per-folder flags; off by default). In the cache:
   under `cache_dir()` (never `DIR_CACHES`), keyed by the folder's data root like the store
   (`root://<uuid>/<relative>`); a folder with no data root goes to the temp folder instead, and
   say so in the event (propose this as a `Q~` for Tony; it follows the "no data root, no disk
   cache" rule). Beside the raw files: only `d_txy_helab_<N>.txy`, temporary name then rename;
   never touch raw `d*.txt` or any existing TXY. **AGENTS.md's write rule** (already in AGENTS.md:
   "HeLab writes nothing into source folders except the user's `.helab-root` markers and, where
   the user turns it on per folder, converted `d_txy_helab_<N>.txy`") must hold: a test proves no
   other write reaches a source folder.
6. **Provenance** (plan, Design): every HeLab TXY records the raw file's fingerprint and the
   profile's name, version and hash, and the backend. Keep the TXY bytes identical to MATLAB's
   format (no header in the file): store provenance beside it (a small JSON sidecar per shot, or
   a per-folder manifest, written atomically; your choice, say why), so a shot can be converted
   again when a profile improves and a stale TXY is recognisable.
7. **0 hits** (Q10.3, A10.5): HeLab's own output is a 0-byte TXY, so "converted, empty" differs
   from "not converted yet".
8. **`helab convert --watch <folder>`** (Q9.5): a console command (in `helab/main.py`'s dispatch,
   before any GUI import, like the frozen helper entry), headless: watches a folder, converts
   settled raw files as they arrive, logs, and stops cleanly on Ctrl-C. Options at least:
   `--profile`, `--backend`, `--output temp|cache|beside`, `--once` (convert what's there and
   exit). Works in the frozen app too (`HeLab --convert …` or the same subcommand; say which). It
   uses the same code path as the helper operation, never a second converter.
9. **Shared converter fixes** from stage 2's handoffs: a lock in `reconstruct._load` (with a
   many-threads first-load test in a fresh process, as the mlx floor's); the numba backend's cache
   folder set with `numba_backend.set_cache_folder(<cache_dir()>/numba)` (absolute) in the helper
   before its first use (convert stays pure); after a cache-folder move, restart or replace
   helpers that loaded the kernels, or accept a stray old folder (say which, in the handoff).
   Parallelism: convert across shots in processes (4–8 give 3–5×, the NumPy floor measured);
   within-shot only for a single large shot (Live latency); the default backend is `numpy`
   (the bench's recommendation: `.ai/sessions/2026-10-29-claude-txy-bench/results.md` on
   `agent/txy-bench`, under review), the others stay optional behind the switch.
10. **Docs**: proposed `.ai/architecture/converter.md` sections (the helper operation, settle
    checks, events, output locations, provenance, the CLI) and `io-and-browsing.md` lines, in your
    handoff.

## Not in scope

Live's auto-convert toggle and low-count alerts (`agent/txy-live`), the TXY source choice and the
profile manager (`agent/txy-ui`), packaging and CI builds (`agent/txy-packaging`). Leave clear
seams for them and list the interfaces in the handoff.

## Rules

- Strict typing; tests never touch real data (synthetic folders under `tmp_path`; the source
  guard on); never import helab outside pytest without `source .ai/local/floor-env.sh`.
- Samples (`~/HeLab-samples/txy-v1/`) read-only, for manual checks only.
- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`, `mypy helab/ --strict`,
  `mypy tests --strict`, `pyright helab tests` before the handoff; report every RERUN.
- Docs only in `.ai/sessions/2026-10-29-claude-txy-helab-core/`; provisional items `Q~`, `A~`, `M~`.
- Push once, when done. Report to CoCo (`maestri ask "CoCo" "…"`) when done, blocked, or when a
  choice here is Tony's (then propose, carry on with what doesn't depend on it).
