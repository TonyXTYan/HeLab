# v0.0.7 overnight build: mandate (2026-10-29)

Tony, in Chat (orange), 2026-10-29 ~01:20: "check everything in the plans, can you supervise CoCo
to build all v0.0.7 without my input? I need to sleep." Side (the Assistant) supervises; CoCo
(the Coordinator) runs the floors. The plan is [roadmaps/txy-converter.md](../../../roadmaps/txy-converter.md);
its decisions are Q6.x, Q8.x and Q9.x in [DECISIONS_TODO](../../DECISIONS_TODO.md).

## Scope

v0.0.7 ships with stages 1, 2 and 4 and the smoke pass (Q9.9). Tonight: stages 1, 2 and 4.
Not tonight: stage 3 (calibration) and stage 5 (replacing MATLAB), the smoke pass (needs Tony),
the version bump and PR.

## What Side approves on Tony's behalf, tonight only

- CoCo creates floors (`agent/<task>` from the current `dev/v0.0.7`) and recruits Workers and
  Reviewers, on the presets' default models (no Fable).
- A floor lands into `dev/v0.0.7` when: the Reviewer has no open findings; the full suite
  (`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=…`) and mypy --strict (helab, tests) and
  pyright pass; every RERUN is explained or filed in known-issues. CoCo applies the handoff's
  doc changes when landing, as usual, and tells Side before and after each landing.
- Pushes only at checkpoints (a landing, or a CI run worth having).
- Gaps the plan doesn't cover: CoCo asks Side (`maestri ask "Side" …`); Side decides from the
  proposals already written and logs each below as "decided by Side overnight, for Tony to
  confirm". Only reversible choices.

## Never tonight (stop that piece and leave it for Tony)

- A PR to `main`, a version bump, a release or tag; touching a published release.
- Deleting branches (`maestri floor delete` only with `--keep-branch`; never `floor land
  --delete-branch`), user data, caches or settings.
- Writing to the X share (`/Volumes/192.168.137.1-4`) or `~/HeLab-samples` (read-only copies;
  floors read only those). MATLAB runs only on local copies under the floor's `.ai/temp`.
- Machine-wide installs (Rust is already installed via Homebrew); packages go only into a
  floor's own venv (`uv pip install --python venv/bin/python …`, after checking `sys.prefix`).
- Answering any agent's permission prompt on Tony's behalf.
- A test that keeps failing after a cause hunt: file it and stop that piece.

## Stage split (defaults for the floors)

- **Stage 1, `agent/txy-reference`:** one floor, a builder Worker and a cross-checker Worker (the
  cross-checker never edits the port; it writes and commits only its own session folder and
  scratch under `.ai/temp`), then a Reviewer. Done-when as in the plan.
- **Stage 2:** one floor per backend from stage 1's landed commit: `agent/txy-numpy`,
  `agent/txy-numba`, `agent/txy-cython` (Cython or C), `agent/txy-rust` (PyO3 + maturin),
  `agent/txy-mlx`. The stage 1 cross-checker is connected to all. Each passes stage 1's checker
  byte for byte and measures the three parallelism levels. Final timings: one agent, serially,
  machine otherwise idle (Tony's HeLab is quit), after the backend floors are done. Results
  table and recommendation in a session note, checked by a Reviewer.
- **Stage 4**, after stage 2's recommendation, in this order:
  - `agent/txy-helab-core` first: the helper operation (settle checks for raw files: unchanged
    5 s, size stable between checks, newline at the end, trigger channel first), new event
    kinds, the `d_txy_helab_<N>.txy` file kind, the output-location setting (temp / cache,
    default cache per Q9.3, and beside the raw files as a per-folder option per Q9.7, with the
    AGENTS.md write rule), provenance, `helab convert --watch <folder>`, and
    `.ai/architecture/converter.md`.
  - then in parallel: `agent/txy-live` (Live's auto-convert toggle shown once Live is on, folders
    that start Live and auto-convert at launch, low-count alerts through the existing system
    notification path); `agent/txy-ui` (the TXY source choice in plot settings, Q6.6; the
    detector-profile manager: built-ins read-only, user profiles as JSON with import, export,
    duplicate and edit, `plates-2025` marked uncalibrated); `agent/txy-packaging` (every
    backend in the build per Q9.2: lazy imports so NumPy alone always works, platform markers,
    compiled extensions built in CI on all three OSes, `HeLab.spec`; A9.1 note to remove unused
    ones later).

## Decisions log (decided by Side overnight, for Tony to confirm)

Each entry: time, question, decision, why, how to reverse.
