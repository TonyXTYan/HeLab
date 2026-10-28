# Audit of agents, roles, docs and logs (2026-10-28)

This audit is read-only. Nothing was changed while it ran. It was asked for by Tony in Chat, on
Ground at `dev/v0.0.6` `927de44`. Three agents worked in parallel: roles and workflow,
documentation, and logs and CI. The Assistant merged their findings and checked the first
claims (the stray pytest process, the symlink, the branch-deletion line).

Each finding is tagged:
- **[Tony]**: a decision, now also listed in [1-decisions.md](../../DECISIONS_TODO.md#from-the-audit).
- **[AI]**: mechanical work, now also listed in [3-ai-tasks.md](../../AI_TODO.md#from-the-audit).

## Agents and Maestri roles

1. **The Quick Fixer role is documented nowhere.** Its live prompt (`maestri role show "Quick
   Fixer"`) isn't in `.ai/maestri-setup.md` §2 or `agent-workflow.md`. Two of its rules differ
   from the others:
   - it says "don't push unless told", where AGENTS.md says push once when done;
   - its session folder name hardcodes `claude`.

   The other four live prompts match the guide word for word. [Tony: the push rule; AI: the docs]
2. **Branch rule conflict.** `maestri-setup.md:459` says "Remove the branch on GitHub too once it's
   merged". The memory rule `feedback_keep_branches_on_github.md` says never delete, and it lives
   only in memory. [Tony: one rule, then AI writes it into AGENTS.md]
3. **CodeGraph is required but not set up here.**
   - AGENTS.md and `.cursor/rules/codegraph.mdc` (alwaysApply) tell agents to use `codegraph_*`.
   - Ground has no `.codegraph/`, and Claude Code has no codegraph MCP server registered.
   - `maestri-setup.md` §0 step 8 points to a `~/.claude/CLAUDE.md` that doesn't exist.

   [Tony: set it up, or mark it optional]
4. **`.ai/coding-workspace.md` is a tracked symlink to `/Users/tonyyan/Documents/GitHub/ai-common/…`**
   (mode 120000). It is broken on lab PCs, CI and cloud agents. Its memory-format rules have also
   drifted from what the memory files use. [Tony: commit a copy, or note it's Mac-only]
5. **Floors could run the GUI now.** `maestri-setup.md:284,400,463` say QSettings isn't isolated,
   but `app_settings()` honours `HELAB_TEST_SETTINGS_FILE`. One `floor-env.sh` line would isolate
   each floor's settings. [Tony]
6. **Local agent branches are one commit ahead of GitHub.** Six branches:
   - cache-only, codebase-review-2, presets-reopen;
   - quick-fixes-2, quick-fixes-3, windows-store-test.

   Each has its handoff commit unpushed. Those commits are already on the pushed dev/v0.0.6, so
   nothing is lost. [AI, with Tony's OK to push]
7. **Decisions kept only in the Maestri note** (the folder_cache split after the release, the
   unapproved Export floor, the version bump and PR) aren't in `roadmaps/_readme.md`. The "v0.0.6
   changes" note stops at `450b6ec` and still lists the store-identity test as open. [AI]

## Documentation

8. **Roadmap status drift.** [AI]
   - `_readme.md:24` says "Priorities for v0.0.6 are still to choose".
   - The DLD port is described as "on agent/dld-front-panel-port" (`_readme.md:140`,
     `dld-front-panel-port.md:159`), though it landed as #6 (`43aa3de`).
   - `live-monitoring.md:9` stops at L2, and its line 149 says presets and R2 are "later".
   - `cache-only-browsing.md:58-63` still lists open decisions that D1–D10 settled.
   - `_readme.md:206` lists "Cache folder listings" as unchosen, but it is partly done (C2).
   - `agent-workflow.md:3,60,90` and `maestri-setup.md:8-9,115` describe the floor pilot as future.
9. **Contradicting Tony's decisions.** [AI]
   - Live notifications are "once per shot, no time limit" (Tony, 2026-10-26), but
     `dld-front-panel-port.md:354` and MANUAL_TODO still say once a minute.
   - Byte sizes are SI (Tony, 2026-10-26), but `cache-storage-and-settings.md:869` says binary.
   - `store-v2` is named as current in `cache-storage-and-settings.md:76,709` and
     `app-updates.md:183`.
10. **Basic plots v1 units.** `_readme.md:137` says "T in ms and X/Y in mm since 2026-10-20". The
    code and AGENTS.md say Basic plots v1 keeps s and m, and only the DLD port uses ms/mm. [AI:
    take the code as the truth, unless Tony says otherwise]
11. **Stale memory.** [AI]
    - `project_v0.0.5a-folder-browser.md`: threads from 10-08.
    - `results/folder-io-queue.md:112`: "Live not implemented".
    - `results/live-monitoring.md:18`: the "whole last row" check, against Tony's metadata-only
      decision.
    - `results/disk-cache-and-budgets.md:5,18` and `basic-scan-defaults-and-failures.md:27`: store-v2.
    - `results/analysis-plots.md:17,24,30`: the units and the RAM budget listed as open.
    - The lab-PC caveat files say `requirements.txt` instead of `.lock`.
12. **Stale known-issues.** [AI]
    - The temp folder "used by nothing" (`:18`): I/O traces use it now.
    - "Once plotting exists" (`:31`).
    - "Over 100,000 entries records a scan failure" (`:17`): no such limit found; re-verify.
13. **Obsolete MANUAL_TODO items.** [AI]
    - The store-v2 / SMB-key build (`:198-217`).
    - "New issues go in _readme" (`:9`): they go in known-issues now.
    - "Download the macOS CI artifact" (`:469`): CI keeps builds only on release.
14. **README.** [AI]
    - It says the compatibility runs cover 3.10–3.12; CI runs 3.11, 3.12 and 3.14.
    - Only one submodule is named, though there are three; `--recurse-submodules` pulls ~440 MB more.
15. **AGENTS.md checked against the code.** Of ~230 names, one is wrong: `CacheTab.confirm` is
    `CacheTab._confirm`. AGENTS.md is 92 KB (~23k tokens, loaded into every agent). These
    paragraphs repeat their roadmap docs, and cutting them to a code map with links would save
    35–40 KB:
    - Script system 12 KB;
    - Caching 8.5 KB;
    - DLD 7 KB;
    - Live 5 KB;
    - Cache first 4 KB.

    [Tony: trim or not]
16. **Handoff follow-ups never carried over.** [AI]
    - `test_analysis_gui.py::test_scatter_from_the_panel` needed a RERUN twice (dld-d7) and isn't
      in known-issues.
    - `AnalysisRunner.stop()` is never called on quit (refactor-prep).
    - The plot RAM budget's open 80–100 % decision, and what the budget doesn't count.
    - Tests still prefer port 8050.
    - Two-port correlations, and other libraries for the DLD port.
    - `test_typing.py` calls a bare `mypy`.

## Logs and CI

17. **A pytest process orphaned since Oct 23** (pid 15027, 151 MB). It is
    `test_presets_window.py` from the removed Result Cache floor, and the Assistant confirmed it's
    still running. [Tony: OK to kill]
18. **The idle HeLab (pid 77000, started Oct 27) uses ~35 % CPU.** That's 107 CPU-min in 18.5 h,
    with the main thread repainting from QTimer callbacks and no helpers running. Likely culprits
    are a status-bar timer or the Dash poll; medium confidence. [AI: investigate]
19. **Stall stacks don't reach the log.** `helab-77000.log:32` logged a 4.12 s GUI stall, but
    `gui_watchdog.py:40` writes the stacks to `sys.__stderr__`, so they never reach the log. [AI]
20. **Dash's werkzeug logs every request at INFO.** That was 1,300 of 1,338 lines in one 22-min
    Live session, so the 1 MB log rotates about hourly and pushes out its own start lines. Set
    werkzeug to WARNING. [AI]
21. **Vague warning.** `loading.py:43` turns every store-open failure into "Disk cache
    unavailable", with no cause. [AI]
22. **Leftovers.** [AI]
    - 33 empty `helab_io_*` folders in the system temp folder.
    - 70 old `diskcache.*` keys in the settings plist, not in `RETIRED`.
    - The back button logs each click at INFO.
23. **CI.**
    - The last 10 test jobs were clean.
    - One rerun not in known-issues: `test_live_plots.py::test_a_floating_plot_runs_and_follows…`
      on macOS, run 40260284152, `'completed' == 'cancelled'`. [AI]
    - About 56 `ResourceWarning: unclosed database` per job, which fits the Windows file-lock
      (WinError 32) failures; find what opens them. [AI]
24. **The Windows test step runs 13–15 min of its 20-min limit.** One run was cancelled at
    18.4 min after 10 reruns. [Tony: raise the limit, or speed up Windows]
25. **Dependabot on `main`.**
    - There are 41 alerts on `main:requirements-pip.txt` (5 critical, 23 high).
    - Pillow is pinned at 12.3.0 and the fix needs 13.0.0, so the security update fails.
    - dev/v0.0.6's lock already has 13.0.0, so releasing v0.0.6 clears them, or bump or remove
      that file on main. [Tony]
26. **`.ai/temp/` is 386 MB**, mostly `pytest-land` from Oct 22. [Tony: OK to delete]

**Clean:**
- The app logs: no unexpected errors, tracebacks, clock skew or helper deaths.
- No new crash reports since the fixed web-view crash (Oct 22).
- Codecov uploads all succeeded.
- No floors or worktrees left over.
- The memory symlink and index are consistent.
- The recent handoffs' AGENTS.md edits were all applied.
