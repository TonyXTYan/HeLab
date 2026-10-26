# Cache-only browsing (brief, CoCo, 2026-10-26)

Floor "Cache Only", branch `agent/cache-only`, base `0840acb` (dev/v0.0.6 = origin). Coordinator:
CoCo. Tony asked for this (Chat, 2026-10-26: "parallel floors, work on fixes and cache-only mode").

## Objective

Browse and analyse cached data when the lab volume is unmounted or unreachable, with no source I/O
and no network request. The plan is `roadmaps/cache-only-browsing.md`; read it, with its links (the
2026-10-08 roadmap review's "Cross-tab status results" and "Cache-only browsing" sections, and
`.ai/sessions/2026-10-14-codex-planning-for-future/remote-headless.md#offlinecache-only-interaction`).

Its acceptance: a user can restart without the source mounted, navigate saved folders and run
analysis on retained data. Tests deny source access and show that navigation, rendering, loading
and analysis setup submit no source operation. Evicted or missing data gives an honest
unavailable state, never an implicit source load. Returning online has an explicit validation
path.

## Stages

Each stage is one or a few commits. Report to CoCo after each, then go on, except at the
checkpoint after C0.

**C0. Design note (checkpoint: report, then wait for CoCo's go before C3).** Write `design.md` in
this folder. For each open decision in the plan, give your recommendation and the alternatives,
in plain words; CoCo takes them to Tony. Defaults I'd expect, which you can argue against:

- **Name and control:** explicit switching only, e.g. a "Work offline" toggle (File menu and/or
  toolbar), with a status-bar line while it's on. Tony names it.
- **Running source work when entering:** Live turns off first (its save runs, or is offered).
  Running loads, scans and listings are cancelled; local-lane work (cached reads, cache writes,
  the sweep) goes on.
- **Listings:**
  - **What a saved listing holds:** subfolder names per folder, plus enough to show counts.
  - **Key and scope:** the `root://` key, saved only below data roots, since RAM-only folders have
    no store.
  - **When a listing is written:** by the helper of a `list`, like the other records, under the same
    save guards. Propose the table, columns and retention: purge by age with the folder records?
    which Clear-by-kind row removes them?
  - **Size:** measure it on a large tree (`tests/` fixtures, or a generated tree of 10k folders).
- **Leaving offline:** what is checked on the way back (the next selection's normal cache-first
  check, or more), and what the tree shows meanwhile.
- **The gate:**
  - **Where it sits:** `FolderCache.submit` and the `IOService` request boundary.
  - **Which operations pass:** local-lane `cached`, `cache_admin`, `subtree_save`, presets,
    results, etc.
  - **Which are refused:** everything that touches a source folder (`list`, `resolve`, `details`,
    loads, Live, icons, marker writes, `roots_verify`, `volumes_verify`?).
  - **What a refused one tells the user.**
- **Audit:** list every entry point that can submit source I/O (grep `submit(`, `request_scan`,
  `cache.load`, Live, icons, Retry/Refresh, Place .helab-root, Settings → Data roots, Folder
  constants), and say how each is gated.

**C1. Cross-tab status results during Refresh without source I/O** (`roadmaps/_readme.md`, near
term; useful on its own). While a tab refreshes, it ignores other tabs' finished checks. The two
strict `xfail` tests marked `SHARED_RESULTS_DURING_REFRESH` in `tests/test_two_step_browse.py`
describe the behaviour wanted. Make them pass, remove the markers, and show that applying a result
submits no source operation, old snapshots included. This is the "no-I/O result-application path"
the plan depends on.

**C2. Persisted listings,** behind the design you proposed in C0: written by `list` helpers,
read by the local lane, in `store-v3` (a new table added to older stores by `cache_store._migrate`,
as for `folder_constants`; never only in `SCHEMA`). Normal browsing behaves as today: it still
lists the folder. Using saved listings to skip a scandir online ("Cache folder listings", unchosen
idea) is out of scope. Tests: written, read back, guarded, migrated, purged/cleared as decided.

**C3. The mode (after CoCo's go on C0's decisions):**
- the control;
- the gate;
- tabs navigating saved listings;
- selection showing cached data via `cached` reads only;
- plots running on it (reopened plots and saved analysis results included);
- honest states for missing and evicted data and for folders never listed;
- disabled or relabelled Refresh / Retry / Check folder status / Live / Place .helab-root;
- generic icons;
- the way back online.

Tests run with source access denied (an `IOService` or helper seam that fails any source operation
in offline mode). They cover navigation, rendering, loading, plots, Settings tabs, and a restart
with the source path missing.

## Scope

- **Owned paths:**
  - `helab/utils/folder_cache.py`, `helab/utils/io_service.py` (the gate), `helab/io_ops/browse.py`
    and the local-lane reads you add;
  - `helab/utils/cache_store.py` (the listings table and `_migrate`);
  - `helab/models/SnapshotFileSystemModel.py`;
  - `helab/views/FolderExplorer*` and the explorer modules;
  - `HelabMainWindow` (only the control and the status line), `CacheTab` (a listings row, if
    decided);
  - `settings_defaults.py` rows;
  - tests.
- **Coordinate:** the "Quick Fixes 2" floor runs beside you, with small changes in `cache_move.py`,
  `io_helper.CACHE_ONLY` and a forgotten root's RAM state in `folder_cache.py`. It lands first;
  merge `dev/v0.0.6` when CoCo tells you it has landed.
- **Ask CoCo before:** changing what users see outside the mode; touching the cache-first,
  Live, presets or result-cache rules; or anything in `tests/conftest.py` beyond a small fixture.

## Checks and handoff

- **Before each report:** the full suite (`pytest -n 4 --reruns 5 --reruns-delay 1
  --basetemp=.ai/temp/pytest`), `mypy helab/ --strict`, `mypy tests --strict` and
  `pyright helab tests`. Report each RERUN with its reason.
- **Notes and handoff:**
  - `notes.md` for measurements and evidence.
  - `handoff.md` at the end, with:
    - what it does;
    - Tony's decisions;
    - proposed doc edits for AGENTS.md, `roadmaps/cache-only-browsing.md`,
      `roadmaps/cache-storage-and-settings.md`, known-issues and MANUAL_TODO;
    - the on-screen checks.
- **Push the branch once, when C3 is done.**
- **Reporting:** keep `maestri floor status` current. Report each stage with
  `maestri ask "CoCo" "<stage, what it does, commits, checks with RERUNs, questions>"`. A reviewer
  may be added after C3.
