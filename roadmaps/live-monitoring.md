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

TXY is write-once after completion. Interrupted original writes are the relevant
recovery case; this feature does not require general tracking of arbitrary
edits to settled files.

## Cache writes while monitoring (decided 2026-10-13)

Tony's decision: new shots never clear the cache, and monitoring doesn't write
the disk cache for each arriving shot.

- Each check keeps every unchanged shot from RAM, reads only new settled files
  and merges them, as loads do today (`memory_shots`, load source `updated`).
- New shots stay in RAM only while Live is on. Today every load that read new
  files recompresses and rewrites the folder's **whole** dataset file in the
  background; for each shot of a large folder, that would mean rewriting
  ~1 GB.
- The disk cache is written once, when monitoring of that folder stops: a
  different folder is selected, Live is turned off, or the tab closes.
- Quitting HeLab first saves the unsaved shots, then shuts down. The window
  says what it is saving and offers **Quit now**, which skips the save; a save
  with no progress for the usual timeout stops by itself. Nothing is lost
  either way: the source files remain, so the next check reads only the shots
  that weren't saved. A crash is the same.
- To decide while designing: whether a long session also saves periodically,
  or when the unsaved part grows large, so a later check doesn't re-read many
  shots.

## Dependencies and acceptance

Depends on the [analysis workflow](analysis-workflow.md) for managed reruns and
result identity, plus the existing incremental loader and settling policy.

New settled shots enter once, while incomplete shots remain excluded and
reported. Expensive analysis never blocks navigation. Repeated arrivals do not
create an unbounded backlog of obsolete reruns. Stopping Live stops further
monitoring; disconnecting and reconnecting the source preserves usable data and
has a defined recovery path.

## Open decisions

- Polling versus filesystem notifications on the actual lab volume.
- Monitoring scope after switching tabs and behavior on app restart.
- Update cadence, manual versus automatic reruns and handling busy analyses.
- Whether a displayed result follows arrivals or remains a fixed snapshot.

Use real-volume/manual checks from [.ai/MANUAL_TODO.md](../.ai/MANUAL_TODO.md);
record execution evidence in sessions rather than in this feature plan.
