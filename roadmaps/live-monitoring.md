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
