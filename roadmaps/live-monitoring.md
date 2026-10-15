# Live monitoring

Horizon: medium term. Added: 2026-10-08. Direction agreed; detailed design is draft.
Priority and completion: [overview](_readme.md).

## Purpose and current foundation

Monitor the selected experiment folder as shots arrive, then update chosen
analyses without repeated manual checking. The active browser's Live action is
currently a disabled placeholder. Existing incremental loading and unsettled-file
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
  cancelled at quit ([known issue](_readme.md#known-issues)).
- Auto-saves obey the disk budget, the folder's Don't cache flag and the
  pending-save questions like any load's save.

## Acquisition machine

The first local deployment can watch settled raw files, convert them to TXY,
and run QC and fast analyses on the machine that acquires the data. Remote
notification/push follows the remote connection stage. See the
[working design](../.ai/sessions/2026-10-14-codex-planning-for-future/remote-headless.md#live-acquisition-machine-proposed-near-term-scenario).

## Stages

| Stage | Delivers | Needs |
|---|---|---|
| L1 | Live on/off for the selected folder: new shots found by isolated I/O, settled shots merged into RAM, cache written at stop and quit (with Quit now) | Existing incremental loader |
| L2 | Auto-save every N shots, with its setting | L1 |
| L3 | Chosen analyses follow Live at a controlled cadence; unpinned views show revisions, pinned keep theirs | L1, [result caching](result-caching.md#stages) R3 |
| L4 | Acquisition machine: raw → TXY conversion and QC as shots settle | L3, [QC](quality-control-and-repair.md) |
| L5 | Remote Live revision notifications | [Network extension](network-runners-and-web.md), result caching R5 |

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

- Polling versus filesystem notifications on the actual lab volume.
- Monitoring scope after switching tabs and behavior on app restart.
- Update cadence, manual versus automatic reruns and handling busy analyses.
- How a Live-following unpinned view presents revisions while a pinned view
  keeps its chosen fixed result.

Use real-volume/manual checks from [.ai/MANUAL_TODO.md](../.ai/MANUAL_TODO.md);
record execution evidence in sessions rather than in this feature plan.
