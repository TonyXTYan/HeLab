# Brief: Quick Fixes 8 (Rivet, Quick Fixer on Ground, `dev/v0.0.8`)

Coordinator: CoCo, 2026-10-31. Tony's go (Chat, via Side) for the area review's small fixes; A39.x are
AI_TODO items (block 39). Findings with scenarios and fix directions: the area review's `app.md` and
`convert.md` (`git show 573361f:.ai/sessions/2026-10-31-claude-area-review/<area>.md`).

**Running beside you on floors** (don't touch their paths): Plot Identity (`helab/analysis/**`,
`helab/scripts/**`, `helab/views/plots/**`, `dash_server.py`), I/O Fixes (`folder_cache.py`,
`io_service.py`, `io_helper.py`, `helab/io_ops/` except `convert.py`/`helab_txy.py`/`stores.py`/`admin.py`,
`explorer_live.py`), Caching v2 (`cache_store.py`, `cache_paths.py`, `cache_move.py`, `cache_setting.py`,
`data_roots.py`, `io_ops/{stores,admin,helab_txy,convert,events}.py`, `CacheTab.py`, `CacheDialogs.py`,
`settings_defaults.py` rows). If a fix needs one of those, stop and ask CoCo.

## Now (one commit each, on Ground's `dev/v0.0.8`; commit freely, Tony's go)

1. **convert-1:** `helab convert --watch F --again` converts each shot once more (`convert_cli.py`); a
   `--watch --again` test.
2. **app-1:** Settings › Reset all settings resets the TXY converter tab too, and Save doesn't put the old
   values back (`SettingsDialog.py`, `ConverterTab.py`); a test.
3. **app-2:** split widths saved on a wider screen never collapse the plot area to 0 px, and quitting
   doesn't save squeezed widths (`HelabMainWindow.py`); a test.
4. **A39.3 one running HeLab per computer** (Q39.1): a second HeLab (source or build) says one is running
   and stops before opening anything (no store, no helpers, no settings writes); the lock in the app folder,
   so `HELAB_APP_DIR_OVERRIDE` (agents, tests) has its own; a stale lock (dead pid) doesn't block. Owned:
   `helab/main.py`, `helab/utils/cache_locks.py` (the lock only), tests. What else only served several
   instances (cache-3, plots-2, `cache_locks`' "N windows"): list it in your handoff, don't remove it.
5. **A39.1 the archive check on PR builds** (`.github/workflows/`, `helab/release_draft.py` if needed): each
   PR's three builds run the stamp check against the build commit, without a tag or draft.

## Later (CoCo says when I/O Fixes has landed)

6. **convert-2:** the path-too-long advice can be acted on this session (its caller is in `folder_cache.py`).
7. **A39.4:** Folder details' "N left out (TXY source)" and TXY counts per converter tag (`load_counts` is
   in `io_ops/`).

## Rules

AGENTS.md throughout; every control named with an ID; strict typing (incl. `--platform win32`, `pyright
--pythonplatform Windows`); tests never touch real data. Before your handoff: the full suite (`-n` with
`--reruns 5 --reruns-delay 1`) and the three type checks, every RERUN reported. Push once when "Now" is
done (one CI run); read every Tests and Converter backends job's log for RERUN before reporting
(`.ai/memory/feedback_ci_reruns_in_logs.md`). Handoff and doc proposals in this folder (provisional
`Q~`/`A~`/`M~`). Ground stays shared: commit each fix before starting the next, never stash or reset
anyone's changes. No version bump, release, tag or PR.

When done: `maestri ask "CoCo" "QF8: done at <hash>, suite <N> passed, RERUNs <…>, CI <run>"`.
