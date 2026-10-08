# Cache-only browsing

Horizon: medium term; may move earlier if off-site use is frequent.
Added: 2026-10-08. Direction agreed; detailed design is draft.
Priority and completion: [overview](_readme.md).

## Purpose and current foundation

Browse folders and analyse retained data when the lab volume is unmounted or
unreachable. Summaries, scan history and datasets persist today; folder listings
are session-only. A folder's presence in a saved listing does not guarantee its
dataset is still cached.

## Scope

- Persist sufficient folder listings to navigate the cached hierarchy across
  restarts, with bounded retention and saved observation dates.
- Apply results already in memory without requesting source I/O. The near-term
  cross-tab Refresh fix should establish this independently of offline mode.
- Gate source operations at the shared request boundary, retaining memory
  replays and local-cache reads. Audit all entry points before claiming no
  source-folder or network access.
- Show cached observation dates and distinguish available data, missing data
  and unknown current validity. Keep analyses bound to retained dataset identity.
- Define Refresh, Retry, Check folder status and generic-icon behavior in this
  mode; freshness indicators must not initiate source checks.

## Dependencies and acceptance

Requires persisted listings, the separate no-I/O result-application path and
cache-only dataset access. Analysis uses the [common workflow](analysis-workflow.md).

A user can restart without the source mounted, navigate saved folders and run
analysis on retained data. Tests deny source access and verify that navigation,
rendering, loading and analysis setup submit no source operations. Cache eviction
or missing data produces an honest unavailable state rather than an implicit
source load. Returning online has an explicit validation path.

## Open decisions

- User-facing name and entry/exit controls.
- Listing schema, retention policy and source-root identity across machines.
- Treatment of source jobs already running when entering the mode.
- Explicit-only switching versus automatic switching after an asynchronous
  reachability failure; automatic switching remains an idea, not a requirement.

Historical context: [roadmap review](../.ai/sessions/2026-10-08-codex-roadmap-review/notes.md#cache-only-browsing).
