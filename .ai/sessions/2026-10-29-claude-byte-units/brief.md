# Brief: byte units by OS (`agent/byte-units`)

Coordinator: CoCo, 2026-10-29. Tony's decision **Q26.1** and item **A26.1** (block 26 in
`.ai/DECISIONS_TODO.md` and `.ai/AI_TODO.md`): disk sizes in SI on macOS and Linux, powers of 1024
labelled KiB/MiB/GiB on Windows; RAM in GiB on every OS; the budget defaults follow. Not cache code
(no store or caching v2 change). One Worker, then a Reviewer.

## Read first

`AGENTS.md` (the units rule under "The disk cache", Tony 2026-10-26, which this replaces; UI rules:
one-line status rows, details in tooltips); `.ai/DECISIONS_TODO.md` Q26.1 (a)–(d), Q22.7 (keep 8 GB);
`.ai/AI_TODO.md` A26.1; `.ai/architecture/{settings,cache-store,app-runtime-and-ui}.md`.

## Base and branch

Base `1d3bbb9` (`dev/v0.0.7`; Q27.1: saved-result reuse is off by default, tests that need it use the
`reuse_on` fixture). Branch `agent/byte-units`.

## Today (where to look)

- `helab/utils/number_format.py` `byte_size(num)` (SI, B…TB) and `helab/utils/time_format.py`
  `byte_rate(per_second)` (SI, B/s…GB/s); about 67 calls in 15 modules (`grep -rn 'byte_size\|byte_rate'
  helab`), among them `folder_cache.py`, `cache_move.py`, `result_cache.py`, the snapshot model,
  `CacheTab`, `CacheDialogs`, `CacheMover`, `DataRootsTab`, `LargeFolderDialog`, `explorer_text.py`,
  `FolderExplorer`, the main window, and the plots' `instance.py`, `workspace.py`, `cached_results.py`.
- The budgets: `settings_defaults.py` (disk budget `8 * 10**9`), `constants.py` `MIN_DISK_BUDGET` and
  `MIN_RAM_BUDGET` (`10**9`); the RAM budget's 1/128 steps of total RAM.

## Objective

1. **One helper**: `byte_size(num, kind="disk" | "ram")` (and `byte_rate` as disk): disk is SI on
   macOS/Linux and 1024-based `KiB`/`MiB`/`GiB`/`TiB` on Windows; RAM is 1024-based `GiB` (`MiB`…) on
   every OS. Same significant figures as today. The platform is a parameter the tests can set (both
   platforms tested on every OS); say how it's chosen at run time. Keep `number_format` free of Qt.
2. **Sort every call into disk or RAM**, explicitly (no default left to guess: say whether you made
   `kind` required). RAM: the RAM budget, In use, "in RAM when loaded", plots' memory, and whatever
   else measures memory; disk: the store, budgets on disk, folders, files, converted TXY, rates.
   List the sorting in your handoff (module, line, kind) so the Reviewer can check it.
3. **Defaults and minimums follow** (Q26.1 (c)): the disk budget's default 8 GB on macOS/Linux and
   8 GiB on Windows (Q22.7 keeps 8), the minimum 1 GB / 1 GiB; the RAM minimum 1 GiB. A stored budget
   keeps its byte value (no rewrite of anyone's setting); the settings' spin boxes and steps show the
   platform's unit. `settings_defaults.py` stays the one place for the default (say how a
   platform-dependent default is expressed there; tests for both).
4. Tooltips and dialogs that say "GB" in text (not through the helper) use the same units: grep
   for hard-coded `kB`/`MB`/`GB` in strings.
5. Docs proposals: AGENTS.md's units rule (one line), `settings.md`, `cache-store.md`, and anything in
   `.ai/architecture/` that quotes SI.

## Rules

Owned paths: `number_format.py`, `time_format.py`, `settings_defaults.py` and `constants.py` (the
budget rows), the `byte_size`/`byte_rate` call sites, their tests. Change only the units at a call
site, nothing else there. The TXY Index floor (Q26.2 with Q27.4 and Q27.5, `agent/txy-index`) runs beside you and owns the
converted-TXY rows of `CacheTab.py` (it adds the temp folder's), `helab/io_ops/convert.py`,
`helab/io_ops/helab_txy.py`, `helab/convert/` and `FolderCache.convert`: there, change only the units
of a `byte_size` call (expect a small merge), and ask CoCo before anything more. Strict typing (incl. `--platform win32`, `pyright --pythonplatform
Windows`); tests never touch real data; the full suite inside and once outside the checkout basetemp,
every RERUN reported; GUI checks only with `floor-env.sh` sourced on synthetic folders. Docs only in
`.ai/sessions/2026-10-29-claude-byte-units/` (proposals; provisional `Q~`/`A~`/`M~`). Push when done;
the landing needs a Reviewer with no open findings and CI green on 3 OSes by run ID. No version
bump, release, tag or PR.
