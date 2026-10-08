# Review of the uncommitted changes

2026-10-08. Review only; application code was not edited during this review.

## Confirmed findings

1. **P2: Manual Retry during a listing-only Refresh loses the status-update intent.**
   `SnapshotFileSystemModel.request_scan()` joins an existing `list` job and
   only lifts its timeout; it does not change the existing subscription's
   `listing_only` flag or arrange a normal browse afterward. Refresh completion
   therefore skips status updates, details and statusReady. Reproduced with two
   existing TXY shots, adding a third, starting Refresh, then requesting the same
   no-timeout Retry used by the context menu: the count stays at two.
   Fix must preserve independent subscribers' intents and avoid another helper
   racing the listing it replaces. Add a permanent regression test for this.

2. **P2: Refresh and status-check jobs share one child-pruning accumulator.**
   `FolderNode.seen` is cleared at request submission and populated by all
   listing/scan entry deliveries. Overlapping requests can therefore combine
   two different snapshots. Reproduced by queuing a status check and Refresh,
   delivering the status check's old entries, deleting a child directory, then
   completing the refresh listing: the removed directory stays in the model.
   The underlying shared-state problem may predate these changes, but remains
   exposed by the supported Refresh-during-check flow. Keep seen entries per
   request or reconcile children from the completed request's own snapshot.
   Test both completion orders and changes in child entries.

3. **P2: Live progress omits files already known to be settling.**
   `io_helper.load()` filters `young` shots out of `files`, then emits progress
   with `total_files=len(files)` and `unsettled_files=len(late)` only. With one
   settled and one young shot, progress says one total and zero unsettled; the
   completed event correctly says two total and one unsettled. Tests cover the
   final young-file result and live progress for files growing during reading,
   but not live progress for files already young before reading. Keep total and
   unsettled counts consistent while retaining the existing five-second policy.

4. **P3: Some UI guidance still assumes Refresh checks/reloads data.**
   The Live tooltip says to use Refresh to check for new files, and the load
   helper's changed-during-load error says `Refresh to retry`. Toolbar Refresh
   now updates folder names only. Use Check folder status for status changes
   and the existing load Retry action for load errors.

## Validation and remaining gaps

- Full suite: **334 passed, 1 skipped**, one existing logging.warn deprecation
  warning. Command: `venv/bin/pytest -q --basetemp=.ai/temp/pytest-full-review`.
- Browser/cache/toolbar/I/O subset: **224 passed, 1 skipped**.
- Strict mypy: clean, 90 source files. Pyright: 0 errors, 0 warnings.
- `git diff --check`: clean.
- Three additional failing reproductions are kept in gitignored scratch:
  `.ai/temp/test_review_refresh_edges.py`. Run with
  `venv/bin/pytest -q tests/test_hover_menu_button.py .ai/temp/test_review_refresh_edges.py --basetemp=.ai/temp/pytest-review-edges-final`.
  Result: **3 failed, 5 passed** (the five passing tests are existing hover tests).
- Existing tests exercise independent toolbar click targets, scope/cancel/tab
  switching, preserving shared subscriptions, hover-open delay, one-second
  dismissal, staying over the menu, and reentry cancelling/restarting dismissal.
- New hover tests use offscreen Qt. Native macOS/Windows popup mouse handling
  and painting remain a manual validation gap; keyboard opening/Escape and
  clicking the main scan icon while the hover popup is open also lack dedicated
  regressions. This review does not claim bugs in those unverified cases.
- No frozen executable was built during this review. Earlier wheel packaging
  verification covered inclusion of the new SVG; native bundled rendering is
  not established by that check.

Recommendation: resolve the three reproduced cases and update the stale
guidance before committing this change set.

## Implementation follow-up

Tony accepted a different resolution for finding 1: disable folder-listing
Retry during a refresh of the same folder, then enable it after success,
failure or cancellation. Load Retry and other folders' retries remain separate.
The old scratch reproduction's expectation of upgrading a running refresh is
therefore superseded; the permanent tests now assert disabled/guarded Retry
and a fresh normal retry after the refresh ends.

Refresh now cancels this tab's automatic scan/details/revalidation subscriptions
and prevents new automatic checks until all refresh paths have completed.
Manual subscriptions, including an automatic scan explicitly adopted by a
manual check, and other tabs' subscriptions survive. Optional checks cancelled
by Refresh return to idle without showing an error. Foreground priority and
cooperative pausing remain unchanged; manual checks may pause for listings.

Finding 2 is addressed with per-request child sets and ownership of the tree
by the newest request. Shared snapshots also retain the newest listing's names
when an older check finishes, and that older check does not cancel delivery of
the newer listing. Permanent tests cover both completion orders, completion
during refresh replay, and a tab opened afterward.

Finding 3 and the stale guidance are fixed. Live and cached progress include
known unsettled files in total/checked/unsettled counts. The exclusion policy
is unchanged. Load errors now direct users to Retry; the Live tooltip points
to Check folder status. Folder-listing Retry targets one folder, including
the root when the root listing failed while a child is selected.

Additional regressions cover sharing another tab's listing, adopting automatic
work with either queued or idle row state, superseding a cached replay, and
abandoning a backpressured refresh batch after navigation. The old synthetic
GUI event helper now emits the request's queued event before its entries,
matching the real I/O protocol.

Final validation after implementation:

- `venv/bin/pytest -q --basetemp=.ai/temp/pytest-refresh-policy-complete`:
  **346 passed, 1 skipped**, one existing logging.warn deprecation warning.
- Full suite includes the strict mypy and explicit-path Pyright checks; both
  also passed independently during the implementation.
- `git diff --check`: clean. Changes remain uncommitted.
- GUI coverage remains offscreen; native popup validation remains the manual
  gap described above. This follow-up did not change the hover-menu behavior.
