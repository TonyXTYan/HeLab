# Live monitoring

Horizon: medium term. Added: 2026-10-08. Direction agreed; detailed design is draft.
Priority and completion: [overview](_readme.md).

## Purpose and current foundation

Monitor the selected experiment folder as shots arrive, then update chosen
analyses without repeated manual checking. Live L1 and L2 are implemented
(2026-10-19): the selected folder's new settled shots join its data in RAM, saved
every N shots, when Live stops and before quitting. Existing incremental loading and unsettled-file
handling provide a foundation; automatic visible-folder status checks are not
continuous monitoring.

## Scope

- Explicitly enable/disable monitoring for the chosen folder and expose its state.
- Discover new shots through isolated I/O with bounded work and cancellation.
  Do not query source folders from rendering or GUI callbacks.
- Load only settled shots, reuse unchanged data and avoid duplicate ingestion.
- Update selected analyses at a controlled cadence. Keep plot interactions
  usable and identify which dataset revision a displayed result represents.
- Keep last usable data/results when the source becomes unavailable; provide
  clear recovery controls rather than accumulating unchecked retries.

Deliver Live updates for **local use first**. Then add remote connections for
metadata and result access; remote Live revision notifications/push follow once
those connections work. The local runner and result records must not depend on
the remote stages.

TXY is write-once after completion. Interrupted original writes are the relevant
recovery case; this feature does not require general tracking of arbitrary
edits to settled files.

## Dataset-cache writes while monitoring

This section is the one home for how Live writes the **TXY dataset cache**.
Analysis results during Live follow [result caching](result-caching.md)
(rules 7 and 8), a separate store.

Decided by Tony 2026-10-13; periodic saves decided 2026-10-15:

- New shots never clear the cache, and monitoring doesn't write the disk cache
  for each arriving shot.
- Each check keeps every unchanged shot from RAM, reads only new settled files
  and merges them, as loads do today (`memory_shots`, load source `updated`).
- New shots stay in RAM while Live is on. Every load that read new files
  recompresses and rewrites the folder's **whole** dataset file; doing that per
  shot of a large folder would mean rewriting ~1 GB each time.
- **Auto-save every N shots** (configurable; Settings → Cache, default to be
  chosen): once N unsaved shots have arrived, the folder's dataset is saved in
  the background, so a crash or quit re-reads at most N shots. Saves never
  overlap: shots arriving during a save count towards the next one.
- The disk cache is also written when monitoring of that folder stops: a
  different folder is selected, Live is turned off, or the tab closes.
- Quitting HeLab first saves the unsaved shots, then shuts down. The window
  says what it is saving and offers **Quit now**, which skips the save; a save
  with no progress for the usual timeout stops by itself. Nothing is lost
  either way: the source files remain, so the next check reads only the shots
  that weren't saved. A crash is the same. The same quit save applies to an
  ordinary finished load's background save (`disk_cache_pending`), today
  cancelled at quit ([known issue](known-issues.md)).
- Auto-saves obey the disk budget, the folder's Don't cache flag and the
  pending-save questions like any load's save.

## Live scope and polling (decided by Tony 2026-10-19)

- **Polling**, not filesystem notifications: the next check starts a cooldown
  after the previous one finished (default **3 s**, a setting), so checks never
  overlap or queue up however slow the volume is.
- Live applies to the **selected folder of the current tab**. Turning Live on
  greys out that tab's folder explorer (tree, path bar, navigation), so the
  window focuses on the plots in the middle and the parameters on the right;
  turning Live off gives it back.
- **Switching tabs turns Live off**, and so does quitting: Live is always off
  after a restart.
- Auto-save default: **every 10 shots** (L2).

## Acquisition machine

The first local deployment can watch settled raw files, convert them to TXY,
and run QC and fast analyses on the machine that acquires the data. Remote
notification/push follows the remote connection stage. See the
[working design](../.ai/sessions/2026-10-14-codex-planning-for-future/remote-headless.md#live-acquisition-machine-proposed-near-term-scenario).

## Stages

| Stage | Delivers | Needs |
|---|---|---|
| L1 (done 2026-10-19) | Live on/off for the selected folder: new shots found by isolated I/O, settled shots merged into RAM, cache written at stop and quit (with Quit now) | Existing incremental loader |
| L2 (done 2026-10-19) | Auto-save every N shots, with its setting | L1 |
| L3 (done 2026-10-19) | Chosen analyses follow Live at a controlled cadence; unpinned views show revisions, pinned keep theirs | L1, [result caching](result-caching.md#stages) R3 |
| L4 | Acquisition machine: raw → TXY conversion and QC as shots settle | L3, [QC](quality-control-and-repair.md) |
| L5 | Remote Live revision notifications | [Network extension](network-runners-and-web.md), result caching R5 |

## Decided in L1/L2 (2026-10-19)

From the Live floor (`.ai/sessions/2026-10-19-claude-live-l1/`, handoff and
Codex review); the architecture summary is in AGENTS.md.

- A check is one folder stat while the folder is unchanged, a names-only listing
  when it changed, while files are still being written, within 2 s of its mtime,
  or at least once a minute.
- On a listing, held shots are reused only after the data-root identity and the
  check level's sample of held fingerprints match; otherwise Live stops and the
  folder is listed as mismatched. A single shot rewritten in place outside the
  sample stays under the write-once assumption, as for ordinary loads.
- A new file is read only when settled by age and unchanged since the previous
  check (metadata only, by Tony's decision: its content isn't checked). A writer
  paused longer than the settle age is read unfinished; a shot Live read in the
  last 5 minutes that then changes is read again (by checks and by saves), with a
  note for a minute and a WARNING. The converter's temp-name rename remains the
  real fix (planned).
- A Live check pauses background work only while it reads a file (measured: 15 %
  of a background load paused otherwise).
- Live greys out the tab's explorer; switching tabs turns Live off and saves.
  Errors keep Live on with the data and a Retry; nothing retries by itself.
- Quit waits for every save a subscriber asked for, with Quit now.

## Plots following Live: L3 (decided by Tony 2026-10-19)

- **Cadence:** a following plot reruns on every new shot by default. A script
  may declare its own Live policy (rerun every N shots, and/or a minimum delay
  after its previous run finishes) for long, heavy analyses; the plot's settings
  show it with the script's values as defaults.
- **Follow Live is on by default** for plots run on the Live folder; plots of
  other folders stay put. Turning it off keeps the plot's revision (the pin).
- **Hold and coalesce:** a running analysis is never cancelled for new data. New
  shots accumulate; when the run finishes, one rerun takes the newest revision
  with everything that arrived. No backlog of obsolete reruns. A failed rerun
  keeps the last good plot with an amber error and keeps following.
- **Coverage:** every result records the TXY shot numbers (with fingerprints) it
  ran on, so HeLab can diff against the dataset and decide which shots to send
  ([result caching](result-caching.md) rule 8). Full reruns on the newest
  revision are the default; scripts that can update with only the missing
  shots declare it later (R3).
- **Scripts never do I/O:** they only get the in-memory dataset view; HeLab's
  helpers do every read. Live itself is HeLab's, never a plot's.
- **Live is toggled by hand each session** (it never survives a restart) and may
  start on an empty folder, before the first shot: needed for L3's "start Live,
  then run the experiment" and for bringing the converter
  (`legacy/tdc_autoconverter`) into HeLab (L4).
- **Ready for later stages, not built now:** plot parameter presets and the
  disk result cache (R2) come later. L3 keeps results keyed by what reuse needs
  (analysis ID, version and file hash, input root key and signature, effective
  parameters, covered shots and fingerprints), with JSON-serializable
  parameters, and adds no storage.
- The plot's source line shows the state, e.g. "rev N · following Live · 3 new
  shots waiting". Auto-detected settings (Transfer fractions' orders) are found
  again on each rerun; manual mode fixes them.

## Dependencies and acceptance

Depends on the [analysis workflow](analysis-workflow.md) for managed reruns and
result identity, plus the existing incremental loader and settling policy.
Sharing completed Live result revisions with other machines belongs to the
[network extension](network-runners-and-web.md#cross-machine-result-sharing).
Live analysis results follow [result caching](result-caching.md), separate
from the dataset-cache writes above.

New settled shots enter once, while incomplete shots remain excluded and
reported. Expensive analysis never blocks navigation. Repeated arrivals do not
create an unbounded backlog of obsolete reruns. Stopping Live stops further
monitoring; disconnecting and reconnecting the source preserves usable data and
has a defined recovery path.

## Open decisions

- Built in L3 (2026-10-19, `.ai/sessions/2026-10-19-claude-live-l3/`): Live may start on any folder (its own files only, never subfolders) before the first shot; Live off catches held plots up once (Tony); the scatter keeps its 5 s wait and its camera across reruns; "Highlight the newest shot" in the scatter and histograms, the histograms' newest shot on its own right axis (Tony). By design: with Live off, a pending delay timer may still finish one rerun.
- Live with settle age only: a writer stalled longer than 5 s mid-file leaves a partial shot held; when it completes, Live sees the shot changed and stops as mismatched. Keep, or re-read recently changed shots in Live? (Tony to decide, 2026-10-19.)
- Live's data grows in RAM without the large-folder limits: warn, and stop Live
  at 30 % of RAM? (with plots counting toward the RAM budget)
- Add Cancel to the quit window (back to HeLab, saves carry on)?
- Should an error turn Live off (tree unlocked) instead of keeping it on?

- Analysis cadence, automatic reruns and busy analyses: decided (L3 above).

Use real-volume/manual checks from [.ai/MANUAL_TODO.md](../.ai/MANUAL_TODO.md);
record execution evidence in sessions rather than in this feature plan.
