# Brief: converter follow-ups from Tony (`agent/txy-followups`)

Coordinator: CoCo, 2026-10-29. Tony's decisions in `.ai/DECISIONS_TODO.md` block 18 (Q18.2-Q18.6) and
Q10.3/A17.1 (commits `1e6de51`, `376a081` and the QF6 docs commit). One Worker, then a Reviewer. The
TXY ship floor runs beside you (lock, `HeLab.spec`, CI workflows, and one edit in `io_ops/convert.py`
for numba's cache folder); stay off its files and ask CoCo before touching a shared one.

## Read first

`AGENTS.md` (all of it: the source-folder write rule, I/O, UI rules); `.ai/DECISIONS_TODO.md` block 18
and Q10.3; `.ai/architecture/{converter,live,io-and-browsing,cache-store,plots-and-scripts}.md`; the
helab-core, UI and Live floors' handoffs (`.ai/sessions/2026-10-29-claude-txy-{helab-core,ui,live}/`).

## Base and branch

Base `6fcf012` (`dev/v0.0.7`). Branch `agent/txy-followups`.

## Scope (in this order; commit each separately)

1. **Q18.4 Profile tag in the file name.** HeLab's TXY are `d_txy_helab_<tag>_<N>.txt` (`.txt`, like
   MATLAB's `d_txy_forc<N>.txt`), beside the raw files and in HeLab's folders. Tags are short and
   frozen once used: `m19v1` (matlab-2019), `p22v1` (plates-2022 v1), `p25t1` (plates-2025, testing);
   prefixes `a`/`b`/`t` for alpha, beta, testing; app-tweaked (user) profiles tagged from their
   hash (`u<hash>`, say how many hex digits and why). A tag is a profile field (built-ins fixed in
   their JSON; tests that a built-in's tag never changes). No metadata beside the raw files;
   per-shot provenance stays in HeLab's folders; freshness of a beside TXY is "TXY newer than raw".
   Update the file kind (`file_kinds.HELAB_TXY`), finding HeLab's TXY (`io_ops.helab_txy`), the
   helper and CLI (`helab/io_ops/convert.py`, `convert_cli.py`), the `.partial` patterns (Q18.6: keep
   the temporary name and rename, and the exact-pattern cleanup), AGENTS.md's write rule wording (a
   proposal in your handoff). Existing untagged `d_txy_helab_<N>.txy` from tonight's builds: say how
   they're treated (proposed: ignored, never deleted; a converted folder converts again under the
   new name).
2. **Q18.2 Four TXY source modes**: helab-priority (the default: HeLab's current TXY where they exist,
   MATLAB's for the rest), matlab-priority (today's default), helab-only, matlab-only; the profile
   chosen by its tag. Update `helab/utils/txy_sources.py`, the plot settings' TXY row, the tab/Live
   default, the identity and reuse rules (MATLAB-only data keeps its identity; caches never mix). A
   setting for the tab/Live default if one isn't there.
3. **Q18.3 One Live folder, one launch folder.** Live runs in one folder only; there is one launch
   folder (the setting becomes a single folder; migrate a list by keeping its first); an instance set
   to launch Live and auto-convert opens no other folder tabs; turning Live on collapses the file
   explorer panel (and turning it off restores it).
4. **Q18.5 Damaged raw files**: a raw file unchanged for **20 s** that still fails the format checks
   (no final newline, off the trigger channel, no rows) is marked damaged: a notification (once per
   file), a status in the Live line and Folder details, no TXY, never holding up later shots.
5. **A17.1 No-hit shots**: the Live line and Folder details' Auto-convert row name shots whose
   conversion found no hits (amber, numbers in the tooltip; a 0-byte TXY); a folder loaded later shows
   the same from the dataset's empty HeLab shots. Memory only at render time.

## Rules

Strict typing (incl. `--platform win32`, `pyright --pythonplatform Windows`); tests never touch real data;
the full suite inside and once outside the checkout basetemp; GUI only with `floor-env.sh` sourced on
synthetic folders. Docs only in `.ai/sessions/2026-10-29-claude-txy-followups/` (proposed changes to
converter.md, live.md, AGENTS.md's write rule and code map; provisional `Q~`/`A~`/`M~`). Push when done
(and earlier if a CI run is worth it); the landing needs a Reviewer with no open findings and CI green
on 3 OSes by run ID.
