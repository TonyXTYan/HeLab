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

Quick analyses consume the Live RAM view and keep intermediate results in RAM.
HeLab tracks loaded TXY shot identities and each script reports which shots it
has analysed; the runner sends missing shots through the script's Live-update
method. Scripts separately declare ordinary one-off caching, Live updates and
Live cache updates. Only scripts with all three can offer **Auto-update cache**
to advance an older cached result during Live. Cache writes must be coalesced
and bounded, not one large write per shot; save the latest completed revision
at Live stop when enabled. A Live script without Live-cache support updates in
RAM and may save a final one-off result only if ordinary caching is supported
and enabled. This result policy is separate from the TXY dataset-cache
write. The first local deployment can watch settled raw files, convert to TXY,
and run QC and fast analyses. Remote notification/push follows the remote
connection stage. See the
[working design](../.ai/sessions/2026-10-14-codex-planning-for-future/remote-headless.md#live-acquisition-machine-proposed-near-term-scenario).

## Dependencies and acceptance

Depends on the [analysis workflow](analysis-workflow.md) for managed reruns and
result identity, plus the existing incremental loader and settling policy.
Sharing completed Live result revisions with other machines belongs to the
[network extension](network-runners-and-web.md#cross-machine-result-sharing).
The proposed [runner result policy](analysis-job-runner.md#result-retention-and-caching)
keeps intermediate Live analysis results in RAM by default; it is separate from
the TXY dataset cache write policy above.

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
