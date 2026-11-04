# Brief, round 2: PR #11's second Codex review (C-4)

Coordinator: CoCo, 2026-11-04. Tony (Chat) sent
[review 5754636077](https://github.com/TonyXTYan/HeLab/pull/11#pullrequestreview-5754636077) to be addressed, as in
round 1 ("please address codex reviewer and reply to @codex once your fixes are pushed"). Codex reviewed `6585cba`
(the PR's head with C-1 to C-3) and left one finding. Same floor, Worker and Reviewer; the rules of `brief.md`
apply except the owned paths below. CoCo replies on the PR, not you.

## The finding (verbatim)

**C-4 (P1), `helab/views/plots/script_tree.py`: "Recheck in-flight runs after the asynchronous script probe".**
> If a user opens a new plot from the folder while Reload is displaying "Reload (checking)", `run_analysis()` starts
> that plot without holding it for the pending reload. The earlier `_busy()` check has already passed, and this
> callback calls `_load_folder()` without checking again, so `load_directory()` can unload and replace helper modules
> while the new plot's `compute()` is running. This can mix old script code with newly imported helpers or reset
> module state during an experiment. Hold newly opened plots throughout the probe, or recheck and wait for in-flight
> runs before performing the real import. This violates the repository's explicit reload exclusion rule.

The rule (AGENTS.md): "A reload of the user's scripts never runs while a `compute` of them is queued or running
(`AnalysisRunner.in_flight`)". CoCo's read: the window is real. `_try_reload` checks `_busy` before the probe round
(up to `PROBE_START_SECONDS` + `PROBE_SECONDS`), and `_probe_then`'s `answered` → `_finish_reload` → `_load_folder`
imports without checking again. A plot opened meanwhile (`run_analysis`, `reopen_plot`, a preset or arrangement
restore, Live's catch-up) or a held plot's rerun can be computing then.

## What to do

1. **A failing test first**, as in round 1: a probe round in progress (a slow probe stub, or `FolderProbes` faked),
   a plot of that folder opened meanwhile with a `compute` still running when the probe answers; the real import must
   not happen until that run has ended.
2. **Fix it.** Either of Codex's options, or both; say which and why in the handoff. Whatever you choose:
   - the real import never runs while a run of those folders' scripts is queued or computing, on any runner;
   - the GUI thread never waits (the reload waits on `finished`, as "Reload (waiting)" does now);
   - the probe's answers are kept, so waiting doesn't start a second probe round;
   - a plot opened during the round gets the new code after the import, as held plots do (`_adopt`), or says
     why it kept the old;
   - the initial restore (`restore_folders` → `_restored`) gets the same treatment if it has the same window;
   - a reload asked meanwhile still follows in its own round.
3. **One commit** for the fix with its test (two if the restore path needs its own).

## Base and branch

`agent/pr11-codex`, fast-forwarded to `dev/v0.0.8` first (`git merge --ff-only dev/v0.0.8`: dev has your branch
merged at `79dae49`, plus the landing's docs and this brief).

## Owned paths

- `helab/views/plots/script_tree.py`; `helab/views/plots/instance.py` only if holding a plot needs it;
- their tests (`tests/test_script_*`, `tests/test_live_scripts*` or wherever the reload tests are).

Ask CoCo before any other file.

## Handoff

Append a "Round 2 (C-4)" section to `handoff.md`: confirmed or not, the cause, the fix and its commit, the test, a
doc proposal for `plots-and-scripts.md` if the reload's mechanics change, and a short reply text for the Codex
comment. Before it: the full suite (`-n` with `--reruns 5 --reruns-delay 1`) and the five type checks, every RERUN
reported. Push, read every CI job's log for RERUN.

When done: `maestri ask "CoCo" "C-4: done at <hash>, <fix>, suite <N>, RERUNs <…>, CI <run>"`.
