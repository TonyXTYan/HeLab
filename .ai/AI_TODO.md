# AI to-do

This is the ongoing list of work agents may do without asking Tony: docs upkeep, release
preparation, repo hygiene, verification jobs and small fixes already agreed. Any agent may
raise an item. It is one of three living lists shared by every agent:

- [DECISIONS_TODO](DECISIONS_TODO.md): decisions for Tony, `Q` IDs;
- [MANUAL_TODO](MANUAL_TODO.md): checks that need Tony at a screen or the lab, `M` IDs;
- this file: work agents do, `A` IDs.

**IDs** are `<letter><block>.<item>[.<sub>]`. Blocks are listed in [ID_BLOCKS](ID_BLOCKS.md),
and the ID rules are in [DECISIONS_TODO](DECISIONS_TODO.md). Floors and cloud agents propose
`A~1`, `A~2`… in their handoff, and the Coordinator or the Assistant gives them final IDs when
merging.

How to use this list:

- Each item says where it runs (Ground, a floor or CI) and links to its evidence.
- An item that needs a decision first goes to DECISIONS_TODO, and comes back here once Tony has
  answered.
- Features stay in `roadmaps/_readme.md` and bugs in `roadmaps/known-issues.md`; an item here may
  point to them.
- Tick a done item with its commit, and drop ticked items at each release's tidy-up.

The usual rules still apply:

- ask before committing on Ground;
- floors work on their own branches;
- **tests never touch real data**: real-share items only prepare tools and fixtures, and running
  them on the share stays with Tony.

## Before the v0.0.6 release (block 1)

- **A1.1 Tidy MANUAL_TODO** (Ground, docs only). Tick or merge the items later work replaced:
  the store-v2 / account-independent SMB-key instructions (now Q1.5), and duplicates between the
  v0.0.5a lists and the later ones. Link the smoke pass from each item it covers. Group what's
  left by where it's checked: Mac, lab PC, lab share, real-data physics. Give the older items
  M IDs as they're touched.
- **A1.2 Build the macOS app locally** (Ground). On the release commit, run
  `pyinstaller HeLab.spec --clean -y`, then check:
  - the zip is ~300 MB and holds only `HeLab.app`;
  - launched from outside the checkout, Help › About matches the version, commit and build stamp;
  - helpers run in the packaged app;
  - the SVG triangle and Qt's SVG icon plugin render.

  This is the macOS half of MANUAL_TODO's "native UI and packaged application" and "release
  evidence". The Windows build is checked on the lab PC with the smoke pass.
- **A1.3 A picture sheet of every plot** (Ground or a floor). Render each Basic plots v1 and DLD
  port plot natively on macOS (not offscreen) in a 560 px dock, from a synthetic dataset in
  Tony's units, into one sheet that Tony can check in one look. It covers how "ms/mm
  everywhere", "titles wrap" and "the ħ glyph" look; behaviour stays in the smoke pass.
- **A1.4 Edge cases with disposable fixtures** (a floor). Under pytest with the real window
  (`HELAB_SHOW_GUI=1` where it helps), check each case and add a test where none exists:
  - a TXY file written halfway, then finished or repaired;
  - tabs switched and closed during shared listings and loads;
  - cancel and retry during I/O, never beside a helper that is still stopping;
  - a source folder removed mid-load.

  Most of these already have offscreen tests, so first list which ones.
- **A1.5 Release record** (Ground, after Q1.1 and Q1.2). It covers MANUAL_TODO's "Record the
  required Python 3.13 suite/type-check and build results":
  - the version bump;
  - the full suite at `-n 12` and the three type checks on the release commit, with any RERUN
    and its reasons;
  - CI's run, its OS durations and RERUNs;
  - the PR text for `main`, from the "v0.0.6 changes" note.
- **A1.6 Hover-menu timing tests** (CI watch). Read each release CI run's logs for hover-menu
  reruns (≈200 ms slack). One that reproduces goes to known-issues with its logs.

### After the smoke pass

- **A1.7 Summarise Tony's I/O trace**, if he recorded one. Run
  `.ai/sessions/2026-10-19-claude-smb-io-audit/trace_summary.py <folder> --under <share> --minutes`.
  Expect:
  - no `roots_verify` bursts;
  - about 0 ops/min while idle;
  - one `load: shot time` per raw file of an uncached load, and none on a cached reload.

  Compare it with the 2026-10-19 audit (`compare_traces.py`). This covers MANUAL_TODO's trace
  items (Live, the DLD port's D7).
- **A1.8 Carry the results into the docs.**
  - Tick the MANUAL_TODO items the [smoke pass](MANUAL_TODO.md#release-smoke-pass) covered.
  - Move the problems it found to known-issues.
  - Move Tony's decisions into the roadmap and `.ai/memory/results/`.

## From the audit (block 2)

Finding numbers (#N) refer to the [audit](sessions/2026-10-28-claude-v0.0.6-checks/audit.md).

- **A2.1 Docs refresh** (Ground, docs only, one commit). Bring the docs up to date with what has
  landed, and in line with Tony's decisions where they contradict them:
  - the roadmap and plans' status lines (#8);
  - documents that contradict his decisions (#9, #10);
  - stale memory (#11), known-issues (#12), MANUAL_TODO (#13) and the README (#14);
  - handoff follow-ups that were never carried over, into known-issues, `refactoring.md` and the
    DLD plan (#16);
  - the Maestri note's decisions into `_readme.md`, and the "v0.0.6 changes" note (#7).
- **A2.2 Small app fixes** (a Quick Fixes floor, after the release, or before it if Tony wants):
  - set werkzeug's logger to WARNING (#20);
  - write the watchdog's stall stacks into the log (#19);
  - name the cause in "Disk cache unavailable" (#21);
  - retire the old `diskcache.*` settings keys (#22);
  - lower the back button's log line to DEBUG (#22).
- **A2.3 Idle CPU** (with A2.2): find what repaints at ~35 % CPU in an idle window (#18).
- **A2.4 Unclosed SQLite connections in tests** (with A2.2): run with `-W error::ResourceWarning`
  and tracemalloc to find what opens them (#23). They may explain the Windows file-lock
  failures.
- **A2.5 Known-issues entry** for the macOS rerun of
  `test_a_floating_plot_runs_and_follows_with_its_settings_in_its_window` (#23), with A2.1.

## From the instructions audit (block 3)

Finding numbers refer to the
[instructions audit](sessions/2026-10-28-claude-v0.0.6-checks/instructions-audit.md).

- [x] **A3.1 AGENTS.md fixes that need no decision** (`55c9ca1`). Fixed:
  - the listing contradiction, the three "settle"s, the lane count (#7);
  - the floor rule, the routing table, the definition of done (#8);
  - "if present" (#10);
  - "development repo" and `CacheTab._confirm` (#11).
- [x] **A3.2 Role prompts** (live roles, guide §2 synced, `55c9ca1`). Fixed:
  - the Assistant's "current dev branch" and its guide (#19, #20);
  - the Quick Fixer in the guide (#16);
  - the new lists in each role (#17).
- [x] **A3.3 Stopgap for Codex reviewers**: not needed, since AGENTS.md is now 15.5 KB, within
  what Codex reads (#23).

## Automating the smoke pass (block 5)

- [x] **A5.1 Dry run of the computer-use runbook** (done 2026-10-28, Tony's Mac, Sonnet 5.5; results in
  `sessions/2026-10-28-claude-smoke-mac/`, fixes applied to the runbook). Run the
  [runbook](sessions/2026-10-28-claude-smoke-automation/plan.md) once and fix its wording where
  the screen differs. Then hand it to a small model (Q5.1) on the other machines. Each run
  writes `sessions/<date>-<tool>-smoke-<machine>/results.md`, which A1.8 carries into the docs.

## Not AI work (stays in MANUAL_TODO)

These need a real share, lab hardware or a person in the lab:
- remounts, and two mounts of one folder;
- read-only shares, and mapped-drive spellings on Windows;
- the converter and the lab's MATLAB scripts ignoring `.helab-root`;
- the physics checks on real data: temperatures, condensate fits, g², release time, the QE
  calibration;
- release recovery in a disposable release;
- the self-update questions for ANU IT.
