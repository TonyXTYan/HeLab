# Decisions for Tony

The ongoing list of open questions only Tony can answer. Any agent may raise one. It is one of
three living lists shared by every agent:

- this file: decisions, `Q` IDs;
- [MANUAL_TODO](MANUAL_TODO.md): checks that need Tony at a screen or the lab, `M` IDs;
- [AI_TODO](AI_TODO.md): work agents may do without asking, `A` IDs.

**IDs** are `<letter><block>.<item>[.<sub>]`, e.g. `Q1.2` or `Q2.2.1`. The block says where an
item came from (date, agent, session, branch), in [ID_BLOCKS](ID_BLOCKS.md). An ID never changes
and is never reused. Floors and cloud agents number their proposals provisionally in their own
handoff (`Q~1`, `A~1`, `M~1`). The Coordinator or the Assistant merges them in here under the
next block, and records the mapping in ID_BLOCKS. Use IDs in commits, briefs and Chat ("Q1.2:
yes").

How to use this list:

- Each question has its context in a few lines, the options and a **Proposed** answer, under
  the heading for when it's needed.
- Tony answers under it or in Chat, and the Assistant writes the answer in.
- Once answered, the decision goes where it lives:
  - `.ai/memory/results/` for settled design;
  - the roadmap or a plan for priorities;
  - AGENTS.md or `.ai/architecture/` for rules.

  Then the question moves to **Recently decided** as one line with its ID, cleared at each
  release's tidy-up.
- Features stay in `roadmaps/_readme.md` and bugs in `roadmaps/known-issues.md`; only the
  question goes here.

## Recently decided

Tony's answers in Chat, 2026-10-28:

- **Q1.1 yes:** the release gate is the smoke pass (M1.1–M1.8) on a Mac and a lab PC, plus CI
  green with no RERUN. The other native checks are lab validation after the release. Recorded
  in the roadmap's Now and in MANUAL_TODO.
- **Q1.2 yes:** the version is `0.0.6a1` (A1.5).
- **Q1.3 yes:** the `v0.0.5a1` draft stays unpublished (roadmap).
- **Q1.4 yes:** release repos as proposed (`roadmaps/app-updates.md`, roadmap).
  **Q1.4.1 no:** v0.0.6a1 isn't lab-ready, so HeBECANU isn't fast-forwarded yet.
- **Q1.5 yes:** move `store-v2` to the Trash when upgrading a lab PC (MANUAL_TODO, A1.1).

Applied as proposed on 2026-10-28, after "proper fix AGENTS.md and Maestri roles setup"; each
needs Tony's confirmation:

- **Q3.2, Q3.1, Q2.8:** AGENTS.md went from 92 KB to 15.5 KB of rules and a map. Its detail moved
  word for word to `.ai/architecture/` (10 area files and an index), so Codex reads all of it.
- **Q2.3:** CodeGraph is optional, in AGENTS.md, the Cursor rule and the setup guide.
- **Q3.3:** the "nothing removed without asking" wording, with its housekeeping list, is in
  AGENTS.md (Codebase rules, The disk cache).
- **Q3.4:** agents offer roadmap and known-issues items, and do AI_TODO items without asking.
- **Q3.6.3:** "🎓Tony" is used in direct answers only.
- **Q2.2.1:** agent branches are never deleted (AGENTS.md, workflow, setup guide §7).
- **Q2.2.2:** the Quick Fixer pushes once when its jobs are done, or earlier when the
  Coordinator asks.
- **Q4.1:** short IDs `<letter><block>.<item>[.<sub>]`, given at merge; provisional `Q~1` on
  floors and in cloud sessions; `Q` for questions so they don't clash with the DLD port's
  D-numbers (Tony, 2026-10-28).

## Before the v0.0.6 release

Q1.1–Q1.5 were answered on 2026-10-28; see Recently decided.

## From the audit (block 2)

These come from the [audit](sessions/2026-10-28-claude-v0.0.6-checks/audit.md), whose finding
numbers are given as #N. They are quick yes/no answers.

- **Q2.1 Clean-ups that delete or stop things (#17, #26).**
  - Q2.1.1: kill the pytest process orphaned since Oct 23 (pid 15027)?
  - Q2.1.2: delete `.ai/temp/pytest-land` (386 MB)?

  Proposed: yes to both.
- **Q2.2 Branches and pushing (#1, #2, #6).** Q2.2.1 and Q2.2.2 are applied (Recently decided).
  - Q2.2.3: push the six local agent branches whose handoff commits aren't on GitHub yet?

  Proposed: yes.
- **Q2.4 `.ai/coding-workspace.md` (#4).** It's a symlink into your `ai-common` folder, broken
  everywhere else. Commit a real copy here, or keep the link and say it's Mac-only? Proposed: a
  copy.
- **Q2.5 GUI on floors (#5).** Have each floor run HeLab with its own settings file
  (`HELAB_TEST_SETTINGS_FILE` in `floor-env.sh`), so workers can check on screen? Proposed: yes.
  They'd use their own empty cache folders too.
- **Q2.6 Windows CI time (#24).** The Windows test step uses 13–15 of its 20 min. Raise its limit to
  30 min now, and look for the slow tests later? Proposed: yes.
- **Q2.7 Dependabot alerts on `main` (#25).** They clear when v0.0.6 lands, since its lock has
  Pillow 13. Wait for that, or bump `main`'s `requirements-pip.txt` now? Proposed: wait, if the
  release is days away.

## From the instructions audit (block 3)

Finding numbers refer to the
[instructions audit](sessions/2026-10-28-claude-v0.0.6-checks/instructions-audit.md).

- **Q3.5 Decisions out of AGENTS.md (#6).** Half done: the "(Tony, date)" notes now sit in
  `.ai/architecture/` files, not AGENTS.md. Proposed: also record each in
  `.ai/memory/results/`, where settled decisions live, and have the architecture files link
  there.
- **Q3.6 Smaller rules (#11, #21).** Q3.6.3 is applied (Recently decided).
  - Q3.6.1: commit subjects in the log's "Area: summary" style?
  - Q3.6.2: do floors need the two large submodules (Momentum_Bells_test, DLD_front_panel)?
    Proposed: no; only `legacy/tdc_autoconverter`.

## Automating the smoke pass (block 5)

- **Q5.1 Which model drives the smoke pass** ([runbook](sessions/2026-10-28-claude-smoke-automation/plan.md))?
  Proposed: Haiku 5.5. Use Sonnet 5.5 if Haiku misreads the screen in the dry run (A5.1).
  Also: which computer-use tool runs it on each machine (the Claude desktop app's computer use
  on the Mac; check a lab PC can run it)?

## After the release (not blocking)

### Q1.6 Lab numbers only Tony can give
- Q1.6.1: the detector QE (0.1 proposed), the trap frequencies and the trap's axial axis. They are
  used by BEC properties' QE checks and are amber "unconfirmed" in Settings → Lab parameters.
- Q1.6.2: the hot spots of the current detector, which become the "current detector" mask
  preset. Find them with Find hot spots on a flat field or an atom-free T window.
- Q1.6.3: how auto detection should find orders 0, ±1, ±2 in Transfer fractions (roadmap: "Tony
  to describe").

### Q1.7 Windows 3D scatter window flicker
On the Mac, the hidden QQuickWidget stops the main window from closing and reopening when the
first 3D scatter opens. Before turning the same fix on for the lab PCs, check (M1.8):
- whether the flicker happens there;
- whether the fix is safe on PCs that can't paint QtWebEngine.

### Q1.8 The tray / menu-bar icon for notifications
Shot trends' Notify during Live shows a system notification through a tray icon. Is the icon
acceptable, or should notifications use the status bar only?

### Q1.9 After the release (agreed order, still to confirm)
1. Export with provenance, together with the analysis worker in the activity panel.
2. The `folder_cache.py` split (it should run alone).
3. The headless runner and CLI.
4. The TXY converter port (needs sample raw and `_txy_forc` files from Tony).
5. The DLD port's D13 (halo centring per shot).
6. The `--upgrade` lock refresh (python-dateutil 3.0), in its own CI run.
