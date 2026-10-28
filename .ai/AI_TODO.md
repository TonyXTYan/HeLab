# AI to-do

This is the ongoing list of work agents may do without asking Tony: docs upkeep, release
preparation, repo hygiene, verification jobs and small fixes already agreed. Any agent may add
to it. It is one of three living lists, shared by every agent:

- [DECISIONS_TODO](DECISIONS_TODO.md): decisions for Tony;
- [MANUAL_TODO](MANUAL_TODO.md): checks that need Tony at a screen or the lab;
- this file: work agents do.

How to use it:

- Add an item with the date, where it runs (Ground, a floor or CI) and links to its evidence.
- An item that needs a decision first goes to DECISIONS_TODO, and comes back here once Tony
  has answered.
- Features stay in `roadmaps/_readme.md` and bugs in `roadmaps/known-issues.md`; an item here
  may point to them.
- Tick a done item with its commit, and drop ticked items at each release's tidy-up.

The usual rules still apply:

- ask before committing on Ground;
- floors work on their own branches;
- **tests never touch real data**: real-share items only prepare tools and fixtures, and
  running them on the share stays with Tony.

Added 2026-10-28 (Assistant, Ground, `dev/v0.0.6` at `927de44`).

## Before the v0.0.6 release

1. **Tidy MANUAL_TODO** (Ground, docs only). Tick or merge items that later work replaced:
   the store-v2 / account-independent SMB-key instructions (superseded by `store-v3`, now one
   item in [decision E](DECISIONS_TODO.md#e-the-old-cache-on-lab-pcs)) and duplicates between the
   v0.0.5a lists and the later ones. Link the smoke pass from each item it covers, and group
   what's left by where it is checked: Mac, lab PC, lab share, real-data physics.
2. **Build the macOS app locally** (Ground). Run `pyinstaller HeLab.spec --clean -y` on the release
   commit, then check:
   - the zip is ~300 MB and holds only `HeLab.app`;
   - launched from outside the checkout, Help › About matches the version, commit and build stamp;
   - helpers run in the packaged app;
   - the SVG triangle and Qt's SVG icon plugin render.

   This covers the packaged-app part of MANUAL_TODO's "native UI and packaged application"
   and "release evidence", for macOS. The Windows build is checked on the lab PC with the
   smoke pass.
3. **Picture sheet of every plot** (Ground or a floor). Render each Basic plots v1 and DLD port
   plot natively on macOS (not offscreen) in a 560 px dock, from a synthetic dataset with
   Tony's units, into one sheet. Tony looks at one image instead of opening each plot. It
   covers the look of "ms/mm everywhere", "titles wrap" and "the ħ glyph" (DLD port, macOS);
   behaviour stays in the smoke pass.
4. **Edge cases with disposable fixtures** (a floor). Under pytest with the real window
   (`HELAB_SHOW_GUI=1` where it helps), check each case and add a test where none exists:
   - a TXY written halfway, then finished or repaired;
   - switching and closing tabs during shared listings and loads;
   - cancel and retry during active I/O (never beside a helper still stopping);
   - a source folder removed mid-load.

   Most of these have offscreen tests already, so first list which are covered.
5. **Release record** (Ground, after decisions A and B). Covers MANUAL_TODO's "Record the
   required Python 3.13 suite/type-check and build results":
   - the version bump on `dev/v0.0.6`;
   - the full suite at `-n 12` and the three type checks on the release commit, any RERUN with
     its reasons;
   - CI's run, OS durations and RERUNs;
   - the PR text to `main` (changes since v0.0.5a1 from the "v0.0.6 changes" note).
6. **Hover-menu timing tests** (CI watch). Read each release CI run's logs for
   hover-menu reruns (≈200 ms slack). A failure that reproduces goes to known-issues
   with logs.

## After the pass

7. **Summarise Tony's I/O trace**, if he recorded one. Run
   `.ai/sessions/2026-10-19-claude-smb-io-audit/trace_summary.py <folder> --under <share> --minutes`:
   no `roots_verify` bursts, about 0 ops/min idle, one `load: shot time` per raw file of an
   uncached load and none on a cached reload. Compare it with the 2026-10-19 audit
   (`compare_traces.py`). This covers the trace items in MANUAL_TODO (Live, D7).
8. **Carry results into the docs.** Tick the MANUAL_TODO items the smoke pass covered,
   linking [2-smoke-pass.md](MANUAL_TODO.md#release-smoke-pass). Move problems found to known-issues, and
   Tony's decisions into the roadmap and `.ai/memory/results/`.

## From the audit

Numbers refer to the [audit](sessions/2026-10-28-claude-v0.0.6-checks/audit.md) findings.

9. **Docs refresh** (Ground, docs only, one commit). Bring the docs up to date with what landed,
   and record Tony's decisions where the docs contradict them:
   - the roadmap and plan status lines (8);
   - the documents that contradict his decisions (9, 10);
   - stale memory (11), known-issues (12), MANUAL_TODO (13) and the README (14);
   - `CacheTab._confirm` in AGENTS.md (15);
   - lost handoff follow-ups into known-issues, `refactoring.md` and the DLD plan (16);
   - the Quick Fixer role text in the setup guide (1);
   - the Maestri-note decisions in `_readme.md`, and the "v0.0.6 changes" note (7).
10. **Small app fixes** (a Quick Fixes floor, after the release or before it if Tony wants):
    - set werkzeug's logger to WARNING (20);
    - write the watchdog's stall stacks into the log (19);
    - name the cause in "Disk cache unavailable" (21);
    - retire the old `diskcache.*` settings keys (22);
    - lower the back button's log line to DEBUG (22).
11. **Idle CPU** (the same floor): find what repaints ~35 % CPU in an idle window (18).
12. **Unclosed SQLite connections in tests** (the same floor): `-W error::ResourceWarning` with
    tracemalloc to find what opens them (23). They may explain the Windows file-lock failures.
13. **Known-issues entry** for the macOS rerun of
    `test_a_floating_plot_runs_and_follows_with_its_settings_in_its_window` (23), with item 9.

## From the instructions audit

Numbers refer to the [instructions audit](sessions/2026-10-28-claude-v0.0.6-checks/instructions-audit.md)
(2026-10-28).

14. [x] (2026-10-28, uncommitted, with the AGENTS.md restructure) **AGENTS.md fixes that need no decision** (Ground, with item 9):
    - the listing contradiction, the three "settle"s and the lane count (7);
    - the floor rule, a routing table and a definition of done (8);
    - "if present" for session exports (10);
    - "development repo" and `CacheTab._confirm` (11).
15. [x] (2026-10-28, live roles edited; guide synced) **Role prompts** (Ground, `maestri role edit`, mirrored in `.ai/maestri-setup.md` §2):
    - the Assistant's "current dev branch" and "this guide" (19, 20);
    - the Quick Fixer's text added to the guide (16);
    - the new lists' rules for each role (17).
16. [x] Not needed: AGENTS.md is now 15.5 KB, within what Codex reads (23).

## Not AI work (stays in MANUAL_TODO)
These items need a real share, lab hardware or a lab person:
- remounts and two mounts of one folder;
- read-only shares and mapped-drive spellings on Windows;
- the converter and lab MATLAB scripts ignoring `.helab-root`;
- the physics checks on real data (temperatures, condensate fits, g², release time, the
  QE calibration);
- release recovery in a disposable release;
- the self-update questions for ANU IT.
