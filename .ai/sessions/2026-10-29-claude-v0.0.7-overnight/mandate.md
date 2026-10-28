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

- ~01:30, stage 1 started (CoCo): floor "TXY Reference" on `agent/txy-reference` from `29e7e19`;
  Forge (builder) and Lens (cross-checker), Claude Code, Opus 5.5 high, Worker role. Builder
  develops on even sample positions, Lens checks odd ones first.
- ~01:30, **decided:** the final Reviewer is the Codex preset (another model than the author);
  if Codex stalls on approval prompts on the floor (untrusted project), CoCo replaces it in place
  with a Claude Code Reviewer rather than anyone answering its prompts. Why: the rule asks for a
  different model, and nobody answers prompts for Tony. Reverse: re-review with Codex later.
- ~01:35, stage 1: Forge's port (`2b49629`) is byte-identical on all 39 synthetic cases × 2
  variants and on 154 of 157 held-in `matlab-2019` shots. The other 3 are faults in the reference
  files, each proven: 2019 halos d3667 (MATLAB converted a half-written raw, its TXY a prefix of
  ours); 2022-07 He3/He4 d3 (re-converted 2023-02-08 by a third MATLAB variant: `matlab-2019` plus
  a 2 µs x1 dead time, reproduced byte for byte); 2022-11 d5 (trigger-only raw, 0 hits; the 2023
  wrapper wrote a 0-byte TXY, the 2019 wrapper writes none).
- ~01:35, **decided:** the checker keeps known reference exceptions in one list keyed by set, shot
  and the reference's SHA-256, each with an automatic proof; any other mismatch, or a proof that
  stops holding, fails. Lens verifies the proofs independently. The third variant stays a
  dev-script finding (Q~ for Tony: make it a built-in profile?). For stage 4: a 0-hit conversion
  still writes an empty HeLab TXY ("converted, empty" ≠ "not converted"); case 1 is the evidence
  for the settle checks. Why: the bar "every sample shot" can't hold against faulty references.
  Reverse: drop the list and re-pick samples.
- ~01:45, stage 1: port and harness done at `d14f0cb` (not pushed). `matlab-2019` on all 309
  sample shots: 303 identical, 6 proven exceptions (cut d3667; variant 2022-07 He3/He4 d2, d3;
  empty 2020 halos d400, 2022-11 d5, 2023-02 d187); `matlab-2023-lab-edit` 32/32 identical to
  MATLAB's own output; 39 synthetic cases × 2 variants and `tests_sample_data` 17/17 identical.
  Full suite 4653 passed, 2 skipped, no RERUN; types clean. Reference ~10.7 MB/s serial (busy
  machine). Lens's findings round and the Codex Reviewer (Kestrel) run in parallel.
- ~01:50, stage 1: the Codex Reviewer (Kestrel) stalled on its first approval prompt (it needed
  approval just to run `maestri list` / `maestri floor status`). Nobody answered it; CoCo
  replaced it in place with a Claude Code Reviewer, Heron (Opus 5.5 high), reviewing `d14f0cb`.
  **For Tony:** Codex in "Ask for approval" mode can't work unattended on floors; it needs Codex
  trust/approval settings for the floors folder (the setup guide's open "(check)").
- 01:52, heartbeat: CI for `1afaf35` passed (the Windows 30-min limit works; `1ab4ec0`'s run was
  cancelled by the newer push). CoCo's status line shows "5h:99%" (earlier 95 %, then 82 %,
  so probably the share left in the 5-hour window, not used); if the account's limit is hit,
  agents stall until it resets.
- ~02:00, stage 1 reviews: Lens's cross-check round 1 is byte-identical everywhere MATLAB has
  spoken (its own MATLAB 2023 run on the 152 odd shots: 152/152; a 10,000-file fuzz against its
  oracle: 0 differences; all 6 exceptions confirmed with MATLAB); 5 low findings (mixed line
  endings vs textscan, TXY written 0600, the x2-retry gain overstated: ~0.1–0.7 % not ~15 %, two
  wordings). Heron: no findings on faithfulness; 1 blocker (`tests_sample_data` TXY lack
  `-text`, so Windows autocrlf breaks 17 tests; reproduced), 1 medium (profile hash and schema
  not extensible), 5 minor. Forge fixes all 12, then pushes `agent/txy-reference` for a Windows
  CI run.
- ~02:00, CoCo's call (technical, reversible): the profile schema is extensible now; fields at
  their neutral default stay out of the content hash, `from_dict` fills missing fields through a
  per-schema migration, and `matlab-2019`'s hash is pinned in a test. Side added: any field that
  can change the TXY must be in the hash (MCP channel counts once MCP matching is on), checked
  by a test.
- 02:04, stage 1: `agent/txy-reference` pushed at `785f6dc` (first push; all 12 findings fixed,
  including the hash caveat: fields leave the hash only at their neutral default, the MCP and
  trigger channels are listed as not used by the output, and a perturbation test covers every
  field). Forge: 5155 passed, 4 skipped, no RERUN; types clean; samples 303 + 6 proven; 2023
  32/32. CI run 40712192572; Lens and Heron re-checking.
- 02:14, stage 1 CI (run 40712192572, `785f6dc`): macOS and Ubuntu build and tests green;
  both Windows jobs failed at checkout on a Windows-reserved file name (a textscan probe named
  `nul.txt`; Heron caught it). Fixed in `dd6b314` with a guard test over `git ls-files`. Round 2:
  Heron one minor (umask read at import isn't thread-safe; use `os.open` with `O_EXCL`, 0o666),
  Lens one low (textscan's line-ending rule for files that start with line endings; fix checked
  on 1,367 MATLAB-judged inputs). Forge applies both, then one push.
- 02:32, stage 1 CI (run 40713926667, `09a0711`): all six jobs green; Windows ran the
  converter tests for the first time. One RERUN, Windows Tests:
  `tests/test_preset_folder_live.py::test_offline_a_folder_never_listed_is_named_as_such`
  (pytestqt waitUntil timed out after 30 s at line 82), passed on rerun; outside the converter,
  filed in known-issues at landing (cause not hunted tonight). Lens round 3: no open findings;
  Heron round 3 pending.
