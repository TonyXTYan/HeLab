# Brief: Live L3, plots following Live

Floor "Live L3", branch agent/live-l3, base d0b8fbe (dev/v0.0.6, after Settings panel hardening). Worker: Claude Code (Opus 5.5, xhigh), Worker role. Review: Codex. Rules: your role, AGENTS.md (Live, Script system), roadmaps/agent-workflow.md.

## Decisions to build (Tony, 2026-10-19; roadmaps/live-monitoring.md › "Plots following Live: L3", commit 3fe2b19)

1. **Follow Live.** A plot run on the Live folder follows it by default. Turning Follow Live off pins the plot at its revision. Plots of other folders stay put.
2. **Cadence.**
   - By default a plot reruns on every new shot.
   - A script may declare a Live policy: rerun every N shots, and/or a minimum delay after its previous run finishes.
   - The plot's settings show the policy, with the script's values as defaults.
3. **Hold and coalesce.**
   - A running analysis is never cancelled for new data.
   - New revisions accumulate. When the run finishes, one rerun takes the newest revision.
   - No backlog: at most one pending rerun per plot.
   - A failed rerun keeps the last good plot, shows an amber error, and keeps following.
4. **Coverage** (result-caching rule 8).
   - Every result records the TXY shot numbers it ran on, with fingerprints, so HeLab can diff against the dataset.
   - The default is a full rerun on the newest revision. Updating with only the missing shots comes later (R3).
5. **Scripts never do I/O.** They only get the in-memory `DatasetView` (`with_shots()` gives revisions). Live stays HeLab's, never a plot's.
6. **Live can start on an empty folder,** before the first shot. This is Live's open question 1, now decided.
   - The dataset view and every bundled plot must handle "no events yet" by showing a clear empty state, not an error.
   - The first shots then arrive as revisions.
7. **Ready for later, not built now:**
   - No new storage.
   - Each result keeps the reuse-key parts: analysis ID, version and file hash; input root key and signature; effective parameters; covered shots and fingerprints.
   - Parameters stay JSON-serializable, for presets and R2.
8. **Source line:** the state, e.g. "rev N · following Live · 3 new shots waiting". Auto-detected settings (Transfer fractions' orders) are found again on each rerun; manual mode fixes them.

## Hooks that exist (Live handoff, `.ai/sessions/2026-10-19-claude-live-l1/handoff.md`)

- `FolderExplorer.live` (a `LiveSession` or None), `watching(path)`, `liveChanged`, and `session.dataset` (the newest revision).
- Each Live revision replaces `displayed_dataset` and emits `dataLoaded`.
- `DatasetView.with_shots(added, fingerprints)`.
- `AnalysisRunner` (one worker thread, FIFO, cooperative cancellation) and `RamResults`.

## Tests

- **Synthetic Live:** shots arriving faster than an analysis runs. Show:
  - one coalesced rerun at the newest revision
  - no cancelled runs
  - no backlog
- **Policy:** every N shots, and a minimum delay.
- **Pin and unpin.**
- **Failed rerun:** keeps the last plot.
- **Empty folder:** Live starts on it, then the first shot arrives.
- **Coverage records** on every result.
- **Tab switch:** Live off, plots keep their last revision.
- **Two plots on one Live folder** with different policies.
- **Live I/O tests:** keep them on all three OSes, using `HELAB_TEST_READ_GATE`.

## Ownership

- You own:
  - `helab/analysis/`
  - `helab/scripts/base.py`, `helab/scripts/standard/`
  - `helab/models/ScriptTreeSelector.py`, and the plot-dock code in `HelabMainWindow`
  - what Live needs for item 6: `FolderExplorer` start_live / LiveSession, the `io_helper.live_check` empty case, and `folder_cache`
  - tests for all of these
- The SMB I/O audit floor may be in `io_helper` / `folder_cache` / `FolderExplorer` at the same time.
  - Part 1 only adds an opt-in trace.
  - Ask Maestro before changing anything there beyond item 6.

## Coordination

- The SMB I/O audit floor is fixing I/O in parallel (Part 2): , ,  and . Its work includes Live saves (a dedicated save path) and Live checks.
- Keep your changes there to item 6 (Live on an empty folder), and tell me before you touch them, so I can sequence the two.
- Tony may soon ask for plot settings that move into a floating plot's window. If he does, it comes to you as a later round; don't build it now.

## Checks and handoff

- The usual checks:
  - the full suite with `--reruns`; report any RERUN by name
  - `mypy --strict`, also `--platform win32` on tests
  - pyright, also `--pythonplatform Windows`
  - `git diff --check`
- Windows matters, because the lab PCs run Windows: Maestro will run the suite on RSPE.
- Commit freely; push when Maestro says. The handoff gives Tony an on-screen checklist: Live on a real run folder with plots following.

## Change from Maestro (2026-10-19, during the work)

Floating plot settings will be their own floor after this one lands, not a later round here: ignore that line in Coordination, and leave the floating-window behaviour as it is.
