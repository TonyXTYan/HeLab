# Brief: TXY converter stage 4, Live auto-convert (`agent/txy-live`)

Coordinator: CoCo, 2026-10-29 (overnight build; Side approves on Tony's behalf within the
[mandate](../2026-10-29-claude-v0.0.7-overnight/mandate.md)). One Worker, then a Reviewer. Runs
beside `agent/txy-ui` and `agent/txy-packaging`, all from helab-core landed + docs (01776d6).

## Read first

1. `AGENTS.md`, `roadmaps/agent-workflow.md`; `roadmaps/txy-converter.md` (Decided, Stage 4);
   `roadmaps/live-monitoring.md` (L4).
2. `.ai/architecture/live.md`, `.ai/architecture/converter.md` (with helab-core's sections: the
   helper operation, settle checks, events, output locations, provenance), `.ai/architecture/io-and-browsing.md`.
3. helab-core's handoff (`.ai/sessions/2026-10-29-claude-txy-helab-core/handoff.md`): the
   interfaces you build on.
4. `.ai/DECISIONS_TODO.md` Q6.8, Q9.4, Q9.6, Q9.7; `.ai/memory/results/live-monitoring.md`.

## Base and branch

Base `01776d6` (helab-core landed). Branch `agent/txy-live`.

## Objective

Live converts new raw shots as they arrive, when the user turns it on; folders can be set to
start Live and auto-convert when HeLab launches; low-count shots raise a system notification.

## Scope

1. **Auto-convert toggle, shown once Live is on** (Q6.8): in the Live controls of the tab; off by
   default and reset each session (Q9.6), except in folders set to start at launch (3). With it
   on, each Live check also submits the helper's convert operation for settled raw files with no
   current HeLab TXY (through `FolderCache`/`IOService` as Live's checks are; bounded, deduplicated,
   never waiting on the GUI thread; Work Offline refuses it). Converted shots then load like any
   new TXY, through the existing Live path, so plots follow them.
2. **Status**: the Live line and Folder details say what auto-convert is doing (converting N,
   last converted shot, unconvertible shots with the reason in the tooltip), one line, details in
   tooltips (UI rules in AGENTS.md).
3. **Start at launch** (Q9.6): a per-folder setting "start Live and auto-convert when HeLab
   launches" (stored like the existing per-folder flags; a settings row if global); at launch,
   such folders open (a tab each) and start Live with auto-convert. A folder that's missing or
   unreachable at launch: a notification, no retry loop. Writing beside raw files stays the
   per-folder option from helab-core (Q9.7), shown here where the user turns on auto-convert.
4. **Low-count alerts** (Q9.4): a converted shot whose hit count is below a threshold raises a
   system notification through the existing path only (`helab/utils/events.py`, `events.notify`,
   once per shot), never sounds, plots or email. The threshold: reuse Shot trends' Notify during
   Live if it fits; else a setting with a sensible default (propose it as a `Q~`).
5. **From helab-core** (its handoff lists the interfaces): ALWAYS send a `seen` list (the
   settle rule's two checks depend on it); send each `convert_summary`'s lists back as
   `seen`/`done`/`skip` so done shots aren't checked again and unfinished ones aren't
   read again (its A~5). A settled raw file that never gets a final newline (or starts off the
   trigger channel) waits for good, re-checked only when it changes; show it as waiting with the
   reason (Q~5, decided by Side as proposed). A manual "Convert anyway" is only an idea for Tony;
   don't build it.
6. Tests with synthetic folders: a raw file arriving while Live runs is converted once settled,
   not before (a half-written file stays unconverted until settled); toggling off stops new
   conversions; start-at-launch opens and starts; Work Offline refuses; a low-count shot notifies
   once.

## Rules

- Owned paths: `helab/views/explorer_live.py`, Live parts of `helab/views/FolderExplorer.py` and
  `FolderDetailsPanel.py`, `helab/utils/folder_cache.py` (only what auto-convert needs), new
  settings rows, `tests/test_live_*`/new test files. Not the converter package, the helper
  operation or the plot settings (other floors); ask CoCo if you need a change there.
- GUI checks: launch HeLab only with `floor-env.sh` sourced (its own settings and folders), on
  synthetic folders under `.ai/temp`; never the X share or real data.
- Everything else as in AGENTS.md: strict typing, the full suite and three type checks, RERUNs
  reported, docs only in your session folder with `Q~`/`A~`/`M~`, push once, report to CoCo.
