# I/O track notes (2026-10-20)

Branch `agent/refactor-io` from `agent/refactor-prep` (`9cf8782`), worktree
`/home/user/wt/io`. Slices F and G done.
Plan and decisions: [readiness](readiness.md), [common brief](brief-common.md).

## Slice F: `helab/io_helper.py` as the dispatcher over `helab/io_ops/`

`helab/io_helper.py` (3209 lines) is now 140 lines: the process entry
(`main`, the if/elif dispatch, `CACHE_ONLY`, `SOURCE_OPERATIONS`, the inline
`drives`, `resolve` and `invalidate`). Every other top-level definition moved,
unchanged and in its original order, to one module of `helab/io_ops/`:

| Module | Lines | What (originally) |
|---|---:|---|
| `infra` | 396 | `Emit`, read gate and source guard seams, the I/O trace (`TRACE`, `_trace_fd`, `_trace_request`, `_start_trace`, …), traced calls (`_stat` … `_read_txy_file`, `_mounts`), `_volume_id_cache`, `emit`, `Pause`, `Heartbeat` |
| `stores` | 175 | `_cache_info`, `_data_root`, `_open_store`, `_store_or_off`, `_cache_store`, plus `_deadline`, `_usage`, `_removed_event` |
| `markers` | 375 | `_discover_root`, `verify_volumes`, `verify_known_roots`, `_marker_temporary`, `_marker_hint`, `reassign_root`, `_location_path`, `_root_rows`, `create_root`, `remove_root`, `_hide` |
| `metadata` | 165 | `_saved_folders`, `_read_saved`, `_listed_sizes`, `_dataset_flags`, `_send_saved`, `_send_constants`, `_send_guard` |
| `summary` | 83 | `_shots`, `_classify`, `SUMMARY_STATUSES`, `_valid_summary`, `_summary`, `_valid_subtree`, `_save_summary` |
| `fingerprints` | 132 | `SETTLE_SECONDS`, `_settled`, fingerprint/signature helpers, raw shot times (`_raw_mtime`, `_raw_list`, …), `DEFAULT_CHECK_LEVEL`, `_sample_indices`, `_samples_unchanged`, `_cached_signature` |
| `identity` | 53 | `_folder_identity`, `_location_identity` |
| `browse` | 144 | `_mount_fingerprint`, `list_folder` |
| `scanning` | 224 | `scan`, `save_subtrees`, `save_scan_history`, `_scan`, `_check_cached_shots` |
| `loading` | 697 | `read_cached`, `_unchanged_since_*`, `load`, `_load`, `_write_dataset`, `_save_failed`, `NOT_CACHED_REASON`, `_too_large`, `_with_sizes`, `_pending_event` |
| `save_held` | 192 | `save_held` |
| `live` | 308 | `RACY_SECONDS`, `live_check` |
| `icons` | 38 | `folder_icons` |
| `admin` | 253 | `NO_ROOT_CONSTANTS`, `UNVERIFIED_CONSTANTS`, `ADMIN_ACTIONS`, `cache_admin`, `cache_move_job`, `_cache_move_step` |
| `trace_check` | 48 | `trace_check` |

The split was made by a script (AST segments with their leading comments,
imports computed from each definition's free names), and checked by comparing
each moved definition's AST with the original: all identical except the two
intended changes below. Module-level imports stay stdlib, `typing`,
`helab.utils.file_kinds`/`large_folder` and other `io_ops` modules; every
lazy import (numpy, pandas, PyQt, `cache_store`, `cache_paths`, `data_roots`,
`scan_history`) is still inside its function. Importing `helab.io_helper`
loads only `helab`, `helab.utils`, `file_kinds`, `large_folder` and the
`io_ops` modules (no numpy, pandas, Blosc, PyQt6, Dash, Plotly). No cycles:
`infra` ← `stores` ← `markers`/`metadata`/`fingerprints`… ← families ←
`io_helper`.

### Decisions

- **Module names differ from the proposal where a module is reached as
  `module.name`:** `store` → `stores`, `shots` → `fingerprints`, `saved` →
  `metadata`, `roots` → `markers`. `store`, `shots`, `saved` and `roots` are
  local variable names in the moved code (and `markers` would not be), so a
  qualified call such as `store._cache_store(...)` inside a function with a
  local `store` would break. `scan` → `scanning` and `load` → `loading`, since
  tests import the `scan`/`load` functions and also need the scanning module
  (to patch `_scan`); a module named like its function makes
  `helab.io_ops.scan` ambiguous. `save_held`, `trace_check`, `identity`,
  `summary` keep the proposed names (nothing reaches them qualified).
- **Patched names are looked up through their defining module at call time**
  from every other module: `stores._cache_store` (autouse in conftest, and
  `test_ram_only_status`), `infra._volume_id_cache`, `infra._read_txy_file`,
  `metadata._send_saved`, `fingerprints._raw_mtime`,
  `markers._discover_root`. No module binds them with `from … import`
  (checked with grep). Names patched and read only in their own module stay
  bare there: `SETTLE_SECONDS` (only `fingerprints` reads it), `_scan` (only
  `scan`), `_mount_fingerprint` (moved into `browse`, its only caller, so the
  test patches `browse._mount_fingerprint`), the trace globals (`infra`),
  `Heartbeat.INTERVAL` (class attribute), `time.time` (one module object;
  the test string now names `helab.io_ops.scanning.time.time`, the clock
  `scan` reads).
- **Mutable state lives in `infra` only** (`TRACE`, `_trace_fd`,
  `_trace_request`, `_volume_id_cache`, `Pause`, `_TracedListing.current`,
  `_guard_rules`' cache). Nothing in `helab/io_ops/` imports
  `helab.io_helper`, which runs as `__main__` under `-m helab.io_helper`.
- **`RACY_SECONDS` went to `live`** (its only user), not `identity`.
  `_deadline`, `_usage` and `_removed_event` went to `stores` (used by
  `loading`, `admin` and `main`'s `invalidate`).
- **`invalidate`, `drives` and `resolve` stay inline in `main`**, as the
  proposal said; `invalidate` calls `stores._cache_store` (the seeded store
  in tests).
- **One intended code change in a moved line:** `_guard_rules` finds this
  checkout from `__file__`, one folder deeper now
  (`dirname(dirname(dirname(abspath(__file__))))`); checked:
  `infra._guard_rules()` still allows `/tmp` and the worktree root.
  Otherwise only `io_helper.py`'s docstring gained a sentence.
- **HeLab.spec unchanged:** it lists `helab.io_helper` as a hidden import, and
  `io_helper` imports every `io_ops` module statically at module level, so
  PyInstaller's analysis follows them. `helab/main.py`'s frozen entry
  (`from helab.io_helper import main` before any Qt import) is unchanged.
  A PyInstaller build wasn't run here.
- **No re-export shims:** every test import and patch target points at the
  new home. `from helab.io_helper import x` became
  `from helab.io_ops.<module> import x`; `io_helper.f(...)` calls of public
  operations became plain calls with a from-import; private names, constants
  and patch targets became `<module>.name`. Subprocess tests keep running
  `python -m helab.io_helper`. Two test files have a local variable named like
  an imported module (`markers` in `test_root_discovery`, in another test
  function than the module's use; harmless). In `test_io_trace` (local
  `identity`) and `test_store_migration` (a fixture named `admin`) the names
  are imported directly instead (`_folder_identity`, `NO_ROOT_CONSTANTS`,
  `UNVERIFIED_CONSTANTS`). `test_helper_imports` now imports `list_folder` and
  `scan` from their modules, same intent.
- **Docs:** `AGENTS.md` (the test-seam paragraph now names
  `helab/io_ops/infra.py`; Responsive filesystem I/O describes the package and
  the patch rule; `io_ops.fingerprints._raw_mtime`, `io_ops.live.live_check`,
  `io_ops.save_held.save_held`, Data loading names `helab/io_ops/loading.py`),
  `.ai/memory/results/{basic-scan-defaults-and-failures,data-roots,folder-io-queue,subfolder-derived-status}.md`,
  and code comments in `FolderExplorer`, `folder_cache`, `io_service`,
  `MissingShotsWindow`, `RootDuplicatesWindow`, `stats` (which named a
  non-existent `io_helper.read_txy`; now `io_ops.infra._read_txy_file`) and
  `subfolder-derived-status.md` (named a non-existent `_subtree_info`; now
  just `io_ops.scanning.save_subtrees`). Left as they are: mentions of
  "`io_helper` processes/requests" (still true) in `AGENTS.md` Threading,
  `roadmaps/app-updates.md` and `roadmaps/build-size.md`, and a past plan in
  `roadmaps/cache-storage-and-settings.md`. `roadmaps/refactoring.md` names
  no moved file.

## Validation

- Strict mypy (`helab`: 135 files, `tests`: 94) and pyright (`helab tests`):
  clean.
- Same test count collected before and after (2172).
- Targeted (the 32 test files that referenced `io_helper`, `-n 2 --reruns 2`):
  814 passed, 5 skipped, 2 xfailed, 1 rerun:
  `test_analysis_gui.py::test_scatter_from_the_panel` (a Dash/web-view plot
  test, no helper code; passed alone, see below).
- `python -m helab.io_helper` end to end: a `list` request streams entries,
  status and `done`; an unknown operation reports `error`. The subprocess
  tests (`test_cache_switch`, `test_cache_admin`, `test_io_trace`,
  `test_folder_icons`, `test_real_data_guard`, `test_folder_cache`) pass.
- Full suite (`-n 2 --reruns 5 --reruns-delay 1`): 2183 passed, 9 skipped,
  2 xfailed in 6 min 22 s, **no reruns**. The 2 warnings are pyqtgraph's
  NumPy 2.5 deprecation in `test_t_spectrum` (unrelated).
- `test_scatter_from_the_panel`'s targeted-run rerun: passed alone (1.7 s)
  and in the full suite; a Dash/web-view timing flake under parallel load.

## Review of a05d135 (coordinator)

No correctness bugs found. Fixed on top in their own commit:

- `tests/test_helper_imports.py`'s script also imports `helab.io_helper`, so a
  module-level numpy/pandas/Qt import in any `io_ops` module (all imported
  when a helper starts) fails the check, not just one in `browse` or
  `scanning`.
- `AGENTS.md` states the rule precisely: a name tests patch is called as
  `module.name` from other modules (the six names above); other shared
  helpers are imported by value.
- Known, no change: `io_helper.py` imports `SOURCE_GUARD` by value. It is read
  from the environment at import and only in the helper process, never
  patched, so the copy can't go stale.
- **PyInstaller:** the coordinator built the app from `a05d135` on Linux
  (`HeLab.spec --clean`): all 15 `helab.io_ops` modules are in the PYZ, and
  the frozen helper (`HeLab --helab-io-helper req resp`) ran `list`,
  `details` and a 3-shot TXY load through to `loaded`/`done`.

## Open points

- Proposal: `admin.py`'s `cache_admin` (150 lines) and `loading._load`
  (365 lines) are the largest single functions left; splitting them is a
  separate, behaviour-sensitive step, not part of this move.

## Slice G: typed helper events (static contract, no runtime change)

**Contract module: `helab/io_ops/events.py`** (705 lines, standard library and
`typing` only). It lives beside the code that sends the events, and
`helab/io_ops/__init__.py` imports nothing, so the app can import the
contract without loading helper code; a `helab/utils/io_events.py` would put
the protocol away from its producers, where new operations wouldn't see it.
It declares 72 `TypedDict` shapes for 66 kinds, their union `HelperEvent`,
and `KINDS`, plus the field groups spread into events (`UsageFields`,
`DataRootField`, `DatasetFlags`, `LiveState`, `AdminResultFields`,
`MoveCheckFields`, …).

- **Shapes per sender, not per kind, where senders differ.** Strict mypy
  (`--extra-checks`) requires every non-required key of a `TypedDict` literal
  that uses `**` to come from a `**` item, so one shape with many optional
  keys doesn't type-check at senders that spread `_data_root` or `_usage`.
  So `loaded` has six shapes (cached read, unchanged since cache, unchanged
  since RAM, load, save from RAM, Live) over a shared `_LoadedBase`; `status`
  two (listing, scan; `FolderSummary` is the scan's base and `scan_summary`'s
  payload); `admin_result` two (`cache_admin`, `invalidate`); `swept` two
  (read-only store or not); `root_changed` two (`RootFoundEvent`, marker found
  with another UUID, shared with `root_found`; `RootChangedEvent`, a location
  forgotten). `cache_full`/`cache_approval` and `root_created`/`root_adopted`
  are one shape each, since one expression picks between them.
- **Helper side:** `infra.Emit = Callable[[HelperEvent], None]` and
  `infra.emit(event: HelperEvent)`, so every `send`/`emit` is checked. The
  spread helpers return their field groups (`_data_root`, `_usage`,
  `_dataset_flags`, `_removed_event`, `_pending_event`, `_summary`, Live's
  `state` and `progress`, `_scan`); `_save_summary` takes a `Mapping`.
- **Code changes for typing only** (no emitted key, value or order changes;
  each was checked to have no side effects or ordering effects):
  - Four conditional spreads became annotated locals spread in the same
    place: a shot's `raw_mtime` (`loading`, `live`, `save_held`:
    `known_time: RawMtimeField`), the load's `disk_cached`
    (`known_cached: DiskCachedField`), `error`'s `unverified`
    (`io_helper`), and a scan's no-cache flags (`uncached: DatasetFlags`).
    Neither checker types `**({...} if c else {})`.
  - A listing's `saved_root`, added after the literal, is now an annotated
    local spread last (`saved_root: SavedRootField`): the same last key.
  - `cache_admin`'s `result.update(a=…, b=…)` became `result.update({"a": …,
    "b": …})`: mypy doesn't accept keyword `update` on a `TypedDict`.
  - Three casts, only where an untyped `dict[str, Any]` crosses into the
    contract: `_usage` (`CacheStore`'s usage `event()`), `_dataset_flags`
    (a comprehension over two fixed keys) and `move_check`
    (`cache_move.check_target`). No event literal is cast.
- **Tests:** test sinks passed to helper functions are `list[Any]` (was
  `list[dict[str, Any]]`), and test callbacks that receive helper events take
  `Any`: a `TypedDict` isn't a `dict[str, Any]`, so `events.append` of a
  `list[dict[str, Any]]` can't be an `Emit`. That's 29 test files, annotations
  only (mypy listed each one).
- **`tests/test_helper_events.py`:** `KINDS` equals the union's kinds; the
  kinds the helper sends (an AST scan of `helab/io_ops` and `io_helper.py`:
  dict literals with `"kind"`, conditionals between kinds, `dict(kind=…)`,
  `x["kind"] = …`) equal `KINDS`, with two dicts that aren't events listed
  (`scanning`'s scan outcome `success`, `loading`'s dataset `info`); every
  kind the app matches on (`==`, `!=`, `in`, `not in` on `x["kind"]`,
  `x.get("kind")` or a name assigned from them, in `helab/main.py`,
  `helab/utils`, `helab/views`, `helab/models`; `scan_history.py`'s outcome
  kinds left out) is declared or one of the app's own `GUI_KINDS`
  (`queued`, `started`, `cancelled`, `exit`: `IOService`'s), which the app
  makes and no helper sends. Checked by hand that a misspelt field
  (`mounts_seen`'s `mount`) fails mypy and a misspelt matched kind
  (`CacheTab`'s `inventorry`) fails the test.
- `AGENTS.md`'s Responsive filesystem I/O has a sentence on the contract.

### Later (GUI side, not in this slice)

`FolderCache._on_event` and the other handlers still take `dict[str, Any]`.
A later step would type `IOService.resultReady`'s payload as
`HelperEvent | GuiEvent` (a small union for `queued`/`started`/`cancelled`/
`exit`, declared beside it), narrow by `event["kind"]` in each handler
branch (mypy narrows a `TypedDict` union by a literal `kind` check), and
handle the per-sender shapes of `loaded`/`status` by their common base. Done
handler by handler, it would surface fields the GUI reads that no sender
sets. Some GUI code also builds helper-kind events itself (`FolderCache`
replays `loaded`, `entries`, `status`…), which would need the same shapes.

### Validation (slice G)

- Strict mypy (`helab` 136 files, `tests` 94) and pyright (`helab tests`):
  clean.
- Targeted (29 changed test files plus the contract, import, Live and
  cache-move tests, `-n 2 --reruns 2`): 838 passed, 5 skipped, 2 xfailed, no
  reruns.
- Full suite (`-n 2 --reruns 5 --reruns-delay 1`): 2187 passed, 9 skipped,
  2 xfailed in 5 min 42 s, **no reruns** (the same 2 pyqtgraph warnings).

## Reviews (coordinator, 2026-10-20)

Separate reviewer subagents read each slice's commits.

- **F (`a05d135`):** no correctness findings. 101 definitions are AST-identical;
  13 differ only by a bare name becoming `module.name`, plus `_guard_rules`'s
  extra `dirname`. Ruff finds no undefined names on any platform branch. All
  mutable state lives once, in `infra`. Patch targets all go through their
  defining module. Three low items: the import guard covered only browse/scan
  (fixed in `a7029f1`); the AGENTS.md patch rule was too broad (fixed in
  `a7029f1`); `SOURCE_GUARD` is imported by value (harmless, see above).
- **G (`a7029f1`, `8ae9173`):** no runtime change. The trees are compared with
  annotations and casts removed. Every conditional spread moved to a local
  reads only plain variables, `saved_root` overrides nothing else, and
  `result.update` keeps key and evaluation order. The AST-scan test is sound
  for today's code, with three known blind spots: kinds built outside `io_ops`,
  comparisons against named sets or `match`, and GUI code outside
  views/utils/models/main. A nit (the `GUI_KINDS` comment named only
  `IOService`) is fixed by the coordinator. Low: the three casts let mypy trust
  `MoveCheckFields`, which must be kept in step with
  `cache_move.check_target` by hand.
