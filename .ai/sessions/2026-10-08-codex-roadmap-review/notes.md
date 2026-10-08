# Roadmap review notes

2026-10-08. Tony approved promoting the cross-tab status fix, adding cache-failure
feedback and specifying sample-data fixtures. Keep ROADMAP.md concise. Tony
clarified that ongoing manual work belongs in `.ai/MANUAL_TODO.md`; session notes
hold implementation details and validation evidence. This session changes
documentation only.

## TXY validity assumption

Tony confirmed: once written, TXY files should never be touched again, except
potentially to recover an interrupted original write. Keep the existing write-once
assumption and cache-first policy; no general overwrite-detection feature was
requested.

The one-folder-stat cache check relies on this assumption. A temporary local
helper reproduction overwrote an already cached file: its file mtime changed,
its directory mtime did not, and the helper returned `unchanged` with zero reads.
This demonstrates the assumption's boundary, rather than a failure in the normal
write-once workflow. Interrupted-write recovery is included in manual validation.

## Status messages

The status/toolbar/Refresh changes are committed in `c1d14ea`; the prior roadmap
wording "once the fixes are committed" is obsolete. Verify the remaining
`merged`/`updated` load-phase labels against actual reads and cache writes before
closing the audit. Source reviews:

- [Original audit](../2026-10-08-codex-status-message-review/review.md).
- [Implementation and validation](../2026-10-08-codex-status-message-fixes/results.md).

## Cross-tab status results

While a tab refreshes, it ignores other tabs' finished checks. Visible rows can
catch up when Refresh relists their parent; off-screen rows keep old counts until
listed again. Applying results through `request_scan(automatic=True)` is blocked
by Refresh. A naive replay after Refresh can request source I/O if the result is
older than the ten-second snapshot freshness window.

Separate applying an existing in-memory result from requesting source I/O. This
fix is independently useful and should not wait for full cache-only browsing.
Retain the source-I/O suppression during Refresh. Two strict `xfail` tests in
`tests/test_two_step_browse.py`, marked `SHARED_RESULTS_DURING_REFRESH`, describe
the desired behavior; remove their markers when fixed and verify that applying
the result submits no source operation, including for old snapshots.

## Cache-failure feedback

When the disk cache cannot be opened, automatic status checks are silently
skipped. Show why the check did not run and provide the existing manual checking
action where appropriate. Agree concise UI wording during implementation.

## Sample data

Refine the old sample-experiment-data item into a small anonymized fixture with
known shot counts and expected loaded arrays. Include valid, malformed and
interrupted writes, with expected outcomes for each. Exercise the real loading
path and existing settling policy; synthetic fixtures can cover edge cases where
real data is unnecessary. Do not add large lab datasets to the repository.

## Cache-only browsing

Current feature scope and dependencies now live in
[roadmaps/cache-only-browsing.md](../../../roadmaps/cache-only-browsing.md).
The notes below retain the original review's ideas as historical context.

Working name remains undecided (offline mode, cached view). Browse and view data
using only local cache, without source-folder I/O or network queries, for off-site
use or an unmounted data volume. Implementation ideas, not settled requirements:

- Persist folder listings (subfolder names per folder); today summaries, history
  and datasets persist, while listings are session-only.
- Use `FolderCache.submit` as a source-operation gate, retaining local-lane reads
  and in-memory result application. Audit entry points before claiming no I/O.
- Reuse the independent in-memory result path from the cross-tab fix.
- Show cached dates rather than "Checking for changes…"; disable or relabel
  Refresh, Retry and Check folder status; retain generic folder icons.
- Consider switching automatically when the volume is unreachable, without
  blocking the GUI to establish reachability.

## Deferred tree-lock idea

The old README asked whether to lock the tree during recursive status checks.
The roadmap retains this as an unchosen idea. Reconsider only with a concrete
usability problem; current navigation is intended to remain available during I/O.
