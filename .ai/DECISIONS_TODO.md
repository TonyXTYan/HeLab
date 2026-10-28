# Decisions for Tony

The ongoing list of open questions only Tony can answer. Any agent may add one. It is one of
three living lists, shared by every agent:

- this file: decisions;
- [MANUAL_TODO](MANUAL_TODO.md): checks that need Tony at a screen or the lab;
- [AI_TODO](AI_TODO.md): work agents may do without asking.

How to use it:

- Add a question with the date, its context in a few lines, the options and a **Proposed** answer,
  under the heading for when it's needed.
- Tony answers under it, or in Chat, and the Assistant writes the answer in.
- Once answered, carry the decision to where it lives: `.ai/memory/results/` for settled
  design, the roadmap or a plan for priorities, AGENTS.md for codebase or workflow rules. Then
  delete it from this file, leaving one line in **Recently decided** with a link (cleared at
  each release's tidy-up).
- Product features stay in `roadmaps/_readme.md` and bugs in `roadmaps/known-issues.md`; only
  the question goes here.

Added 2026-10-28 (Assistant, Ground, `dev/v0.0.6` at `927de44`).

## Recently decided

Tony said "proper fix AGENTS.md and Maestri roles setup" on 2026-10-28. These were applied as
the proposals stood, so each needs his confirmation; say if one should change.

- **R, S, Q:** AGENTS.md was cut from 92 KB to 15.5 KB of rules and a map. Its detail moved word
  for word to `.ai/architecture/` (10 area files and an index), so Codex now reads all of it.
- **L:** CodeGraph is optional, in AGENTS.md, the Cursor rule and the setup guide.
- **T:** the "nothing removed without asking" wording, with its housekeeping list, is in
  AGENTS.md (Codebase rules, The disk cache).
- **U:** agents offer roadmap and known-issues items, and do AI_TODO items without asking
  (AGENTS.md).
- **W, part:** "🎓Tony" in direct answers only (AGENTS.md).
- **K, part:** agent branches are never deleted (AGENTS.md, workflow, setup guide §7). The Quick
  Fixer pushes once when its jobs are done, or earlier when the Coordinator asks (role and guide).
  Still open: pushing the six local branches (J/K).

## Before the v0.0.6 release

### A. Release gate
What has to pass before `dev/v0.0.6` goes to `main`?

- **Proposed:** the [smoke pass](MANUAL_TODO.md#release-smoke-pass), once on a Mac and once on a lab PC
  (about 45 min each), plus CI green with no RERUN on the release commit.
  The physics checks, rare edge cases and the long DLD list become lab validation after
  the release: they are listed in MANUAL_TODO and don't block it.
- The alternative is all of MANUAL_TODO first. That's about 120 items, so the lab would
  wait weeks for presets, saved results and Work Offline.

Answer:

### B. Version number
`helab/_version.py` is still `0.0.5a1`.

- **Proposed:** `0.0.6a1`. An alpha is a pre-release on GitHub, as `0.0.5a1` was. A plain
  `0.0.6` would be the first final version, and the lab update check would treat it as
  stable ([versioning](../roadmaps/app-versioning.md)).

Answer:

### C. The unpublished v0.0.5a1 draft
The `v0.0.5a1` draft release was never published (its native checks are part of this list).

- **Proposed:** leave it as a draft and publish v0.0.6a1 instead, since nothing on the lab
  PCs depends on 0.0.5a1. The other choice is to publish it now, as a record.

Answer:

### D. Release repos
This was proposed on 2026-10-13 and never confirmed
([plan](../roadmaps/app-updates.md#release-repos-proposed-2026-10-13-tony-to-confirm)):
develop and release on `TonyXTYan/HeLab`; fast-forward `HeBECANU/HeLab` `main` only for
lab-ready versions, which drafts the same release there; stop pushing dev branches to
`HeBECANU`.

- **Proposed:** confirm. Then the first lab-ready version is the one fast-forwarded to
  HeBECANU.
- Also decide: is v0.0.6a1 lab-ready (fast-forward HeBECANU now), or wait for a later one?

Answer:

### E. The old cache on lab PCs
Each machine that ran v0.0.5 or older keeps `store-v2` next to the new `store-v3`, unused.
HeLab never deletes it.

- **Proposed:** when upgrading a lab PC, move its `store-v2` to the Trash / Recycle Bin by
  hand. HeLab works either way; this only frees disk.
- The alternative is to keep it until v0.0.6 has run a week in the lab.

Answer:

## From the audit

These come from the [audit](sessions/2026-10-28-claude-v0.0.6-checks/audit.md); each number refers to its finding there. They are
quick yes/no answers.

- **J. Clean-ups that delete or stop things (17, 26).** Kill the pytest process orphaned since
  Oct 23 (pid 15027)? Delete `.ai/temp/pytest-land` (386 MB)? Proposed: yes to both.
- **K. Branches and pushing (1, 2, 6).**
  - Keep every agent branch on GitHub, as the memory rule says, and drop `maestri-setup.md:459`'s
    "remove the branch once merged"?
  - May the Quick Fixer push once when done, like other workers?
  - Push the six local branches whose handoff commits aren't on GitHub yet?

  Proposed: yes to all three. The keep rule then goes into AGENTS.md.
- **M. `.ai/coding-workspace.md` (4).** It's a symlink into your `ai-common` folder, broken
  everywhere else. Commit a real copy here, or keep the link and say it's Mac-only? Proposed: a
  copy.
- **N. GUI on floors (5).** Have each floor run HeLab with its own settings file
  (`HELAB_TEST_SETTINGS_FILE` in `floor-env.sh`), so workers can check on screen? Proposed:
  yes. They'd use their own empty cache folders too.
- **O. Windows CI time (24).** The Windows test step uses 13–15 of its 20 min. Raise its limit to
  30 min now, and look for the slow tests later? Proposed: yes.
- **P. Dependabot alerts on `main` (25).** They clear when v0.0.6 lands, since its lock has
  Pillow 13. Wait for that, or bump `main`'s `requirements-pip.txt` now? Proposed: wait, if the
  release is days away.

## From the instructions audit

Numbers refer to the [instructions audit](sessions/2026-10-28-claude-v0.0.6-checks/instructions-audit.md)
(2026-10-28).

- **T. "Nothing is removed without asking" (4).** Today's automatic housekeeping (the sweep,
  expiry after 1 h, old logs, eviction) contradicts it. Proposed wording: "HeLab never removes
  the user's data, records, flags, constants or presets without asking. Housekeeping removes
  only what is listed here: …".
- **U. Offer vs do (5).** Proposed: agents offer roadmap and known-issues items and start
  them after Tony agrees, and do AI_TODO items without asking.
- **V. Decisions out of AGENTS.md (6).** Half done: the "(Tony, date)" notes now sit in `.ai/architecture/` files, not AGENTS.md. Proposed: also copy each into `.ai/memory/results/`, where settled decisions live,
  `.ai/memory/results/`. AGENTS.md keeps the rule an agent must follow and a link, without
  "(Tony, date)".
- **W. Smaller rules (11, 21).** (🎓Tony in direct answers applied: see Recently decided.)
  - Commit subjects in the log's "Area: summary" style?
  - Do floors need the two large submodules?
  - Use 🎓Tony in direct Chat answers only, not in progress lines or messages between agents?

## After the release (not blocking)

### F. Lab numbers only Tony can give
- The detector QE (0.1 proposed), the trap frequencies and the trap's axial axis. They are used
  by BEC properties' QE checks and are amber "unconfirmed" in Settings → Lab parameters.
- The hot spots of the current detector, which become the "current detector" mask preset: use
  Find hot spots on a flat field or an atom-free T window.
- How auto detection should find orders 0, ±1, ±2 in Transfer fractions (roadmap: "Tony to
  describe").

### G. Windows 3D scatter window flicker
On the Mac, the hidden QQuickWidget stops the main window from closing and reopening when
the first 3D scatter opens. Check whether the same happens on a lab PC, and whether that
fix is safe on PCs that can't paint QtWebEngine, before turning it on there (smoke pass,
lab PC step).

### H. The tray / menu-bar icon for notifications
Shot trends' Notify during Live shows a system notification through a tray icon. Is the icon
acceptable, or should notifications use the status bar only?

### I. After the release (agreed order, still to confirm)
1. Export with provenance, together with the analysis worker in the activity panel.
2. The `folder_cache.py` split (it should run alone).
3. The headless runner and CLI.
4. The TXY converter port (needs sample raw and `_txy_forc` files from Tony).
5. D13 halo centring.
6. The `--upgrade` lock refresh (python-dateutil 3.0), in its own CI run.
