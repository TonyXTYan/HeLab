# Brief: TXY converter stage 1, the reference and harness (`agent/txy-reference`)

Coordinator: CoCo, 2026-10-29 (overnight build; Side approves on Tony's behalf within the
[mandate](../2026-10-29-claude-v0.0.7-overnight/mandate.md)). Two Workers share this floor: the
**builder** and the **cross-checker**. A Reviewer comes at the end.

## Read first

1. `AGENTS.md`, `roadmaps/agent-workflow.md`.
2. [`roadmaps/txy-converter.md`](../../../roadmaps/txy-converter.md): Decided, Design (proposed),
   Stage 1. This brief does stage 1 only.
3. [Findings](../2026-10-28-claude-txy-converter-plan/findings.md): the match step by step, the
   2023 lab edit, the quirks, the samples.
4. `.ai/DECISIONS_TODO.md` Q6.5, Q6.10, Q8.5, Q8.6, Q9.x.
5. The MATLAB sources:
   - 2019 reference (the default, `matlab-2019`):
     `legacy/tdc_autoconverter/lib/dld_read_5channels_reconst_multi_imp.m`, called by
     `dld_raw_to_txy_counts` with flags `1,0,1,0`;
   - 2023 lab edit (`matlab-2023-lab-edit`):
     `legacy/DLD_front_panel/lib/Core_BEC_Analysis/lib/import_mcp_tdc_data/dld_read_5channels_reconst_multi_imp.m`
     (its `dld_raw_to_txy.m` calls it with the same flags).

## Base and branch

Base `29e7e19` (`dev/v0.0.7`). Branch `agent/txy-reference` (this floor). Both Workers commit
here; push only when the stage is done or the Coordinator asks.

## Objective

A plain-Python reference port of the running path of MATLAB's raw → TXY converter, byte for byte,
plus the harness stage 2's backends are measured with.

## Design (from the plan; refine, don't redesign)

A Qt-free package **`helab/convert/`**, every module added to `PURE` in
`tests/test_headless_imports.py` (no Qt, plotting, Dash, `helab.utils.constants`; standard
library and NumPy only):

- `raw`: parse a raw `d<N>.txt` into channel and time arrays exactly as MATLAB reads it
  (including what MATLAB does with a truncated last line, blank lines, an empty file). The
  done-writing checks (settled, newline at end, trigger channel first) are stage 4's; leave a
  clear place for them.
- `profile`: `DetectorProfile` (frozen dataclass) with every constant the MATLAB code hard-codes
  as a field: bin time, time sum per axis for matching and for T separately, match tolerances,
  the x−y sum tolerance, v⊥ per axis, search depth, channel map (corners, MCP, trigger), x1/x2/y1/y2
  dead times (the 2023 edit's `uniquetol` cut), x2/y handling (`"matlab"` = keep the first
  candidate; leave room for a retry option, not implemented), `calibrated`, `name`, `version`.
  JSON to and from, a stable content hash for provenance. Built-ins in stage 1: `matlab-2019`
  (the default) and `matlab-2023-lab-edit`. The plate profiles (`plates-2017/2022/2025`) come in
  stage 4, so make sure the schema has what they need (`calibrated: false`, version, notes).
- `reconstruct`: `reconstruct(pulses, profile, backend="reference") -> txy` behind one backend
  interface (a small registry: name → callable, with a capability/availability check so stage 2
  can add `numpy`, `numba`, `cython`, `rust`, `mlx` without touching callers). `backends/reference.py`
  holds the plain-Python port: loops mirroring MATLAB's, readable, with comments mapping to the
  MATLAB line numbers. Not optimised.
- `txy`: write TXY exactly as `dlmwrite(…, 'precision', 8)` does (format, separator, line
  endings, exponents, `-0`, NaN/Inf if reachable, empty output), to a temporary name, then rename.
- **Quirks to reproduce** in `matlab-2019` (from the findings): `how_many_x == ~1` (only "no x2"
  skips; the nearest of two candidates is kept), the first sorted row skipped as "the trigger",
  `t_zero` from the **unsorted** first row, the search order −1, +1, −2, +2 … within 36 rows, the
  `T_sum` skip, used pulses set to NaN, no retry of the other x2. Any further quirk you find:
  reproduce it and list it in your notes.
- **The 2023 lab edit**: the x1 `uniquetol(x1, 0.5e-6/bin_time, 'DataScale', 1)` cut (confirm its
  grouping by running MATLAB, don't assume), `T_sum_x = 3390`, `T_sum_y = 3275` in T only, the
  raw-columns change; byte-identical to MATLAB's own output of that variant.

**Harness** (in `helab/convert/` where it is pure logic, with thin scripts in `dev/txy/` that
read the sample set; tests must never import a path to the sample set):

- the sample manifest reader (`~/HeLab-samples/txy-v1/manifest.json`, SHA-256 checked on read);
- a checker: our output vs the reference TXY, byte-identical, and on mismatch the first differing
  line (line number, both lines, and the hit count of each side);
- a timing harness: per shot, reading, reconstruction and writing timed separately; raw MB/s and
  latency; across all shots, small and large. Stage 2 calls it per backend and per parallelism
  level (across shots in processes; threads; within one shot), so give it that shape now, even if
  stage 1 runs only the reference serially;
- `python -m helab convert`-style entry points are **not** in scope (stage 4).

## Split between the two Workers

**Builder** (owns the code): `helab/convert/**`, `dev/txy/**`, `tests/test_convert_*.py`,
`tests/data/convert/**` (synthetic fixtures), `tests/test_headless_imports.py` (adding to
`PURE` only). Writes `notes.md` and `handoff.md` in this folder.

**Cross-checker** (never edits the port or the tests; writes only
`.ai/sessions/2026-10-29-claude-txy-reference/crosscheck/**` and scratch under
`.ai/temp/crosscheck/`):

1. Read both MATLAB variants independently of the builder and write down, line by line, what the
   running path does (`crosscheck/matlab-walkthrough.md`), so the port can be checked against it.
2. Build **synthetic edge cases** as raw files (small, made up, safe to commit): ambiguous x2 and
   y pairs, pulses exactly at a tolerance (±200, 3400, the x−y 400) and at the dead time, an
   empty file, a trigger-only file, a truncated last line, no trailing newline, hits at the
   file's start and end, unsorted input, equal times, a pulse more than `T_sum` away inside the
   36-row window, channel 4 present and absent. Run both MATLAB variants on copies and keep the
   outputs: `crosscheck/cases/<case>/d1.txt` plus `expected-2019.txt` and `expected-2023.txt`.
   Commit them and tell CoCo, who tells the builder to copy them into `tests/data/convert/`.
3. When the builder says the port is done: check the port line by line against your walkthrough,
   run it on every case and on the **held-out shots** (below), and report findings to the builder
   and the Coordinator, most severe first, with file and line. Repeat until none are open.

**Both** measure the x2 handling: how often a second x2 (or y pair) candidate exists, and how many
hits retrying the other candidate would recover, per sample set. A report (`x2-handling.md` by the
builder, cross-checked); the default never changes.

**Held-out samples.** In each set of `manifest.json`, the builder develops on the shots at even
positions in that set's `shots` list (0, 2, 4, …). The cross-checker checks the odd positions
first, then everything. At the end every shot must pass.

## Rules for tonight

- **Samples:** `~/HeLab-samples/txy-v1/` is read-only: read it, never write, move or chmod it.
  Never read the X share (`/Volumes/192.168.137.1-4`) or any other real data folder.
- **MATLAB:** `/Applications/MATLAB_R2025b.app/bin/matlab -nodisplay -batch "…"` (starts in ~5 s).
  Only on copies under this floor's `.ai/temp/` (`dld_raw_to_txy_counts` writes beside its
  input). `addpath` the variant's folder plus what it needs; never write into `legacy/`. If two
  MATLAB runs collide (licence), run them one at a time.
- **Tests** use synthetic raw files and `tests_sample_data/` only (`bad/`, `goodish/`, `bad_txy/`
  hold raw and `_txy_forc` pairs; check whether the 2019 port reproduces them and test that if
  so). Never the sample set. Never import `helab` outside pytest without `source
  .ai/local/floor-env.sh` first.
- **Packages:** none beyond `requirements.lock` should be needed. If one is, it goes only into
  this floor's venv (check `venv/bin/python -c "import sys; print(sys.prefix)"` is under the
  floor, then `uv pip install --python venv/bin/python <pkg>`), listed in your notes, and you ask
  the Coordinator first.
- **Commits on a shared branch:** stage only your own paths (`git add <paths>`, `git commit`), never
  `git add -A`; if `index.lock` exists, wait and retry. Don't rewrite history.
- Strict typing (mypy --strict on helab and tests, pyright `helab tests`).
- Docs: only this session folder. Proposed doc changes (a new `.ai/architecture/converter.md`
  outline, the roadmap's stage 1 status, known-issues lines) and provisional items (`Q~1`, `A~1`,
  `M~1`) go in the builder's `handoff.md`; the cross-checker's in `crosscheck/handoff.md`.
- A question the brief doesn't answer: `maestri ask "CoCo" "…"`. Don't guess Tony's choices.
- A test that keeps failing after a cause hunt: write it up, tell CoCo, carry on with the rest.

## Done when (from the plan)

- Byte-identical on every synthetic case and every sample shot for `matlab-2019`, and for
  `matlab-2023-lab-edit` on MATLAB's own output (cases, plus at least two shots per sample set run
  through the 2023 variant under `.ai/temp`).
- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`, `mypy helab/ --strict`,
  `mypy tests --strict`, `pyright helab tests` pass; every RERUN reported with its reason.
- The cross-checker has no open findings; then the Reviewer's review.
- Handoff: what was built, the checker's results table (set × shots × identical, for both
  variants), timings of the reference, the x2 report, quirks found, proposed doc changes,
  provisional items.

## Reporting

- Keep `maestri floor status` current (one line; `--state review` when done).
- Builder → CoCo: when the port first passes the held-in shots, when the stage is done.
- Cross-checker → CoCo: when the cases are ready, each findings round, and "no open findings".
- Builder (Forge) and cross-checker (Lens) aren't connected to each other: send messages for the
  other to CoCo, who relays them. Shared files (the cases, the walkthrough, the port) are on this
  floor, so a message can just name the path and commit.
- Every report to CoCo is an ask back: `maestri ask "CoCo" "<report>"`, then carry on.
