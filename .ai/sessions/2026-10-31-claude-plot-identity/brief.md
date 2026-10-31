# Brief: plot identity, the area review's plots fixes (`agent/plot-identity`)

Coordinator: CoCo, 2026-10-31. Tony (Chat, via Side): the area review's plots fixes can start now. The
findings, with scenarios, scratch scripts and fix directions, are in the area review's
`plots.md` (branch `agent/area-review`, `573361f`: `git show 573361f:.ai/sessions/2026-10-31-claude-area-review/plots.md`).
One Worker; one Reviewer at landing. Hybrid floor (`roadmaps/agent-workflow.md`, "Feature floors with named areas").

**Areas:** `plots` (owner). Boundary with `io`/`convert` (they make a dataset's signature): read, don't change.

## Read first

`AGENTS.md`; `.ai/architecture/plots-and-scripts.md`, `dld-analyses.md`, `live.md` (plots follow Live);
the area review's `plots.md` and `io.md` (io-5 is the signature's other side, fixed on the I/O floor).

## Base and branch

Base `0571ff2` (`dev/v0.0.8`). Branch `agent/plot-identity`. Running beside you: the I/O Fixes floor
(`io`) and the Caching v2 floor (`cache`); neither owns your paths. Merge `dev/v0.0.8` when CoCo says,
before your final push.

## Objective (in this order; commit each separately)

1. **plots-1 (High): each view chain gets its own identity.** A folder's datasets share one signature
   (the folder's MATLAB-TXY signature, `sha256("[]")` for a raw-only folder), so `ViewIdentity` and
   `ViewKey` collide across a fresh load, another TXY choice or another profile, and `follow.newer`
   never offers the new chain. Give the chain its own token (the review proposes one carried by
   `with_shots`), keep the reuse key's fields as they are, and make the plot's source label
   (`workspace._update_plot_source_label`) and `shot_trends.newer_than_drawn` compare what the view
   covers, not the MATLAB signature. Tests with two datasets of one raw-only folder (equal
   signatures): a fresh load and a profile change are both offered; the label says "previously loaded"
   when the folder moved on. Fix `tests/test_live_plots.py`'s fake signatures so the suite sees one
   identity across chains.
2. **plots-3: Velocity distributions' Live-kept t_r and crop box keyed by the data**: `kept_key` takes
   the view's source, TXY choice and profile hashes (or plots-1's chain token); Correlations' kept box
   and detection the same for consistency. A test: another profile's next Live run detects again.
3. **plots-4 (Low): the Dash server on macOS** must not share port 8050 with another program (see the
   finding); a test.
4. **The review's plots nits**, where each is a line or two in your paths.
5. **Docs proposals** in the handoff (`plots-and-scripts.md`, `live.md`, known-issues), provisional
   `Q~`/`A~`/`M~`.

**Not in scope:** plots-2 (two HeLabs share "plots open at quit"): Tony chose one running HeLab per
computer (Q39.1), built as A39.3 on Quick Fixes 8, which makes it moot. Don't change how signatures are computed (`io_ops/loading.py`, `helab_txy.py`): that's
`io`/`convert`.

## Rules

Owned paths: `helab/analysis/**`, `helab/scripts/**`, `helab/views/plots/**`, `helab/utils/dash_server.py`,
their tests. Ask CoCo before any other file. Every control you add has an accessible name and ID.
Strict typing (incl. `--platform win32`, `pyright --pythonplatform Windows`); tests never touch real
data; the full suite (`-n` with `--reruns 5 --reruns-delay 1`) before the handoff, every RERUN reported
with its reason. Docs only in `.ai/sessions/2026-10-31-claude-plot-identity/`. Push at checkpoints
only; before reporting a CI run, read every Tests and Converter backends job's log for RERUN
(`.ai/memory/feedback_ci_reruns_in_logs.md`). The landing needs the Reviewer with no open findings and
CI green on 3 OSes by run ID. No version bump, release, tag or PR.

When done: `maestri ask "CoCo" "Plot Identity: done at <hash>, suite <N> passed, RERUNs <…>, CI <run>"`.
