# I/O track notes (2026-10-20)

Branch `agent/refactor-io` from `agent/refactor-prep` (`9cf8782`), worktree
`/home/user/wt/io`. Slice F done; slice G (typed helper events) not started.
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

## Open points

- Slice G (typed helper events) not started, as asked.
- A PyInstaller build would confirm the bundle picks up `helab.io_ops`
  (expected: static imports from the hidden-imported `helab.io_helper`).
- Proposal: `admin.py`'s `cache_admin` (150 lines) and `loading._load`
  (365 lines) are the largest single functions left; splitting them is a
  separate, behaviour-sensitive step, not part of this move.
