# Parallel development and refactoring design notes

2026-10-14. Planning only; no implementation or agent pilot has started.
Product priority and completion remain in [the roadmap](../../../roadmaps/_readme.md);
the concise refactoring direction is in
[refactoring.md](../../../roadmaps/refactoring.md). This note holds the working
design and evidence, not a second priority checklist.

## Tony's intended outcome

Tony wants to bring a new idea to a coordinator while other agents are already
working. The coordinator should review the roadmap and active branches, suggest
independent assignments, and ask Tony before spawning workers, committing,
pushing, merging or other consequential steps. Workers can use separate
worktrees; a reviewer and integrator check their work. The architecture should
make different features genuinely independent. File size matters mainly for
reading and token use. Refactoring must preserve current user-visible
behaviour. The first real lab analysis can be chosen later.

The development-agent workflow is separate from the proposed HeLab analysis
job runner, where agents and GUI users submit scientific analyses at runtime.

## Evidence and current coupling

The current Python files are large (line counts checked 2026-10-14):

| File | Lines | Responsibilities seen in code and project notes |
|---|---:|---|
| `helab/views/FolderExplorer.py` | 2112 | Tab selection, load state and dwell timer, cached display, scan controls, status text and navigation |
| `helab/utils/folder_cache.py` | 1824 | Shared job subscriptions and events, RAM datasets, metadata, disk-cache state, mismatch and budget policy |
| `helab/io_helper.py` | 1442 | Process dispatcher plus browsing, loading, icons and cache operations |
| `helab/utils/cache_store.py` | 1353 | SQLite connection/transactions, records, datasets, guards, budgets and maintenance |
| `helab/views/HelabMainWindow.py` | 1283 | Docks and menus plus cross-tab activity and browser wiring |
| `helab/models/SnapshotFileSystemModel.py` | 1088 | Tree-node state, Qt model rendering, requests and event application |

`FolderExplorer` holds both selected-folder state and widget state, then
updates it from I/O events. `FolderCache` owns many Qt signals and applies
helper events to shared jobs, memory datasets and persisted-state hints.
`SnapshotFileSystemModel` renders from memory, but also submits scans and
applies results. `HelabMainWindow` wires tabs, activity and settings. These
links make a new feature likely to edit several of the same files. Existing
tests also patch methods and module globals directly, so moving code can
silently change test hooks.

This is a planning survey, not an audited dependency graph. CodeGraph reported
the affected files as changed since its last index sync, so the source survey
used current file outlines and the architecture in `AGENTS.md`. Before a code
slice, inspect the actual call and signal paths for that slice, including calls
through attributes that CodeGraph can miss.

## Architectural target

Each area owns its mutable state and exposes a small typed contract. An
interface should say who creates and releases an object, what an event means,
which operation is cancellable, and which component is authoritative after
errors or reconnects. Contracts should be tested by both producer and
consumer. Avoid a new generic event bus or framework until a real boundary
requires one.

| Area and owner | Public boundary to design | Must remain internal |
|---|---|---|
| Source I/O coordinator | Bounded requests, cancellation, progress and terminal outcomes | Lane selection, helper slots, pause/resume and reaper state |
| Cache and dataset provider | Dataset-view lookup, retention/release, freshness and cache-admin outcomes | SQLite transactions, save guards, pending saves, eviction and move recovery |
| Dataset view | Stable input identity, shot map, provenance, warnings and read-only arrays already in RAM when possible | Mutable tab selection, display-only sampled data and automatic disk copies |
| Analysis runner | Validated versioned request; job ID, events, results and artifacts | Adapter process details and scientific implementation |
| Browser and analysis UI | User actions and presentation models/signals | Store rows, helper events and another panel's widget state |
| Main window | Compose tabs, panels, menus and shared services | Per-feature state machines |

The dataset view is the important bridge between browser/cache and analysis.
Its identity must represent the actual included TXY shots and fingerprints,
not just a path or cache hit. A quick analysis can reuse read-only arrays in
RAM; an active job retains the input view when the selected tab changes. Only
expensive or Live work that needs stronger retention should materialize a
durable input snapshot. Define the lifetime of arrays and RAM-only results.
This is a proposed shape; do not freeze a schema before testing a real
consumer against known TXY fixtures.

The source-I/O and cache boundary must keep existing invariants: no GUI source
I/O or disk-cache opens; bounded foreground/background/local lanes; slots held
until helper exit; cancellation and pause semantics; cache-first display;
settled-file and missing-shot checks; save guards, budgets and cache-move
recovery. The refactor should move ownership, not duplicate those policies in
new layers. GUI wording and timing remain observable behaviour.

The [Live acquisition-machine scenario](remote-headless.md#live-acquisition-machine-proposed-near-term-scenario)
is a useful boundary test: one machine watches raw files, converts them,
runs QC and quick analyses, publishes completed result revisions, and serves
other HeLabs plus a phone view. The refactor should let those roles share
versioned contracts without making all clients depend on GUI widget state.

## Candidate implementation slices

The order is provisional. Start by mapping one representative change path in
each area, then choose the smallest boundary that removes a real conflict.

1. **Characterize interfaces.** Trace a selected folder from model request to
   helper result, cache update and UI display; trace dataset retention across
   tabs; trace one analysis button. Record direct imports, signals, test patches
   and packaged entry points. Add focused tests only where a move would otherwise
   leave behaviour unguarded.
2. **Make data and event contracts explicit.** Define typed request/result and
   lightweight dataset-view objects where consumers currently depend on loose
   event dictionaries or widget attributes. Keep adapters from current APIs while
   callers migrate. Verify path identity, stale events, cancellation, cached
   versus checked data, and array ownership.
3. **Separate helper operations.** Keep `helab/io_helper.py` as the frozen
   process entry/dispatcher. Place browsing, loading, icons, cache admin and
   cache move behind it. Do not introduce GUI imports or eager numpy/pandas
   imports into scans. Check packaged helper discovery and a real load.
4. **Separate cache responsibilities.** Keep one SQLite transaction/connection
   owner while extracting record, dataset and maintenance operations. In
   `FolderCache`, keep a single job/subscription coordinator and delegate RAM
   retention, metadata and disk-cache policy behind explicit interfaces.
   Split `_on_event` by operation only after event ordering and stale-result
   guards are characterized.
5. **Separate tab state from presentation.** Move load/scan state machines and
   summary formatting out of `FolderExplorer` where they can be tested without
   widgets. Keep the widget's public actions/signals or adapters until
   `HelabMainWindow`, `FolderDetailsPanel` and tests migrate. Keep the main
   window as composition; extract `SnapshotFileSystemModel` node state only if
   it gives an independent ownership boundary.
6. **Attach analysis behind the seam.** A small fixture-backed analysis
   consumer exercises dataset-view and runner contracts without selecting the
   definitive daily-use analysis. Scientific definitions and first product
   workflow stay in their own roadmap decision.

One slice should be reviewable on its own. Internal APIs may change; current
behaviour should not. A move and a feature change should not be combined merely
to save commits. Exact package names and class shapes are implementation
decisions after the change-path map.

## Human-supervised parallel work

The coordinator is a planning and integration role, not an autonomous merge
bot. It can read the roadmap and all active branches/worktrees, inspect diffs,
check dependency and file overlap, and propose a brief for each worker. Before
starting a worker it presents the scope and asks Tony. It also asks before each
commit, push and merge; those approvals are separate. Review-only inspection
does not require a worker.

A worker brief should contain: objective and acceptance criteria; base commit;
owned paths and forbidden shared paths; contracts consumed or changed; tests
and build checks; expected handoff; and the person/agent integrating it. Each
worker uses a separate worktree and branch. Workers report changed paths,
behaviour, test evidence, open risks and interface changes. A reviewer inspects
the actual diff and reproduces critical checks. The integrator checks the
combined tree, resolves contracts, and reruns the relevant gates before asking
Tony about merging. Parallel test runs use separate pytest scratch directories.

The coordinator may assign truly independent areas at once, such as build-size
work beside an isolated analysis contract. It should not assign two workers to
the same `FolderCache` state or a shared UI wiring file unless one contract
owner first publishes an agreed interface. If a new idea overlaps active work,
offer Tony a dependency choice: wait for the boundary, give one worker the
shared change, or revise the tasks. Separate worktrees prevent accidental edits
to another worker's files; they do not remove semantic merge conflicts.

## Pilot and acceptance evidence

With Tony's later approval, try one refactor slice and one independent feature
in separate worktrees. The coordinator records overlap before starting them.
The reviewer checks each branch; the integrator tests the combined result.
Measure files touched in common, contract changes, conflict resolution, test
reruns and time spent integrating. If the pilot still requires both workers to
edit the same state machine, revise the boundary rather than declare success
because the files became shorter.

For each integrated code slice: focused tests, full pytest with xdist/reruns,
strict mypy for app and tests, Pyright and `git diff --check`. Report any
`RERUN`. For moved helper modules, verify PyInstaller discovery and a packaged
browse/load; check cache move where touched. Native GUI and real-volume checks
remain in `.ai/MANUAL_TODO.md`, with results recorded in session notes.

## Decisions still open

- Start after `v0.0.5a1` merges, or sooner for an isolated preparatory slice?
- Exact ownership and typed contracts after the change-path map.
- Which independent feature to use for the pilot; the first real lab analysis
  can be selected separately later.
- Where to keep an active worktree/branch register without duplicating roadmap
  priorities, and how the coordinator reads its current state.
