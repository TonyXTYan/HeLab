# Docs audit: AGENTS.md, `.ai/architecture/` and README setup (2026-10-28)

This audit was read-only: only this report was written. Ground is `dev/v0.0.7` at `7b82c9d`
(main `9c477c2` plus Q6.4 and the release-draft fix). It was done before the TXY converter port
starts. Method:
- every backticked name in AGENTS.md and the 11 area files was checked against the code with an
  AST script: class attributes, module top-level names and dotted names;
- paths, test files, env vars, links and anchors were checked;
- defaults and numbers were read from the code;
- `helab/**/*.py` was compared with the docs.

The [earlier audit](../2026-10-28-claude-v0.0.6-checks/audit.md) and the
[instructions audit](../2026-10-28-claude-v0.0.6-checks/instructions-audit.md) predate the
AGENTS.md cut. Items they listed that are now fixed aren't repeated (see the end). Items still
open are marked **(still open)**.

Size: AGENTS.md is **15,898 B** (limit 30 KB). The area files are 2.3–17.8 KB.

Name accuracy is high. Of several hundred names, none is missing from the code: the AST check
found no unknown class attribute or module name. The findings below are about wrong or stale
behaviour, contradictions and gaps.

## Findings

1. **dld-analyses.md:1, :11 and architecture/README.md:19 still call the legacy MATLAB folders
   "submodules".** After `7b82c9d` (Q6.4) only `legacy/tdc_autoconverter` is one. `.gitmodules`
   lists only it, and `.gitignore:114-115` ignores `legacy/DLD_front_panel/` and
   `legacy/Momentum_Bells_test/`. AGENTS.md:76/215 and README.md:126-134 are already right.
   The paragraph also doesn't give the pinned commits (README:130/132) or say these two are
   cloned by hand. For the converter, the converter's own reference is described only as "a
   MATLAB TDC data auto-converter kept for reference/compatibility". It doesn't name the files
   that matter: `legacy/tdc_autoconverter/tdc_auto_convert.m`,
   `lib/dld_raw_to_txy_counts.m`, `lib/dld_read_5channels_reconst_multi_imp.m` and
   `lib/txy_importer.m`. Fix:
   - retitle the section "Legacy MATLAB references";
   - say which folder is a submodule and which are cloned by hand at the pinned commits;
   - name the converter files. [AI]

2. **AGENTS.md:175 overstates the headless rule.** It says "The script contract and the analysis
   core (`helab/analysis/`) import no Qt…", which reads as all of `helab/analysis/`. But
   `tests/test_headless_imports.py:34` lists 10 `helab.analysis` modules as Qt:
   - `backends`, `budget`, `empty`, `live_feed`, `overlay`;
   - `panes`, `parameter_tree`, `plot_axes`, `plot_text`, `runner`.

   Its `PURE` list also includes `helab.utils.ram_buffers` and excludes
   `helab.utils.constants` (which imports `PyQt6.QtCore`, `constants.py:11`). The code map
   (AGENTS.md:209) also calls `helab/analysis/` a "Qt-free core". plots-and-scripts.md:9 has
   it right ("lists each … module as Qt-free or Qt"). Fix: "The script contract
   (`helab/scripts/base.py`) and the Qt-free analysis modules (`PURE` in
   `tests/test_headless_imports.py`; a new `helab/analysis` module must be listed there as
   pure or Qt) import no Qt, plotting library or `helab.utils.constants`." This matters for a
   headless converter (Q6.3.2). [AI]

3. **(still open, instructions audit #7) cache-store.md:15 contradicts io-and-browsing.md:17-18.**
   cache-store.md says "Online browsing still lists every folder: saved listings are read only
   offline". io-and-browsing.md says "Selecting a folder with saved counts and a disk cache does
   not list it" (:17) and "selecting a RAM-held leaf folder doesn't list it" (:18). Fix: "Online,
   saved listings are never read (a folder is listed when expanded; selection may skip the
   listing, see io-and-browsing)". [AI]

4. **(still open, instructions audit #7) Lanes and "settle" wording in io-and-browsing.md.**
   - :12 says "One app-wide queue with two source-I/O lanes", then "the **background** lanes".
   - :15 says "A third, **local** lane".
   - The code has three lane kinds (`FOREGROUND`, `BACKGROUND`, `LOCAL`; `io_service.py:125`,
     `FOREGROUND_CAP = 3`, `LOCAL_CAP = 2`), with N background slots
     (`simultaneous_folder_io_operations`, default 1).
   - :15's local-lane list also omits `saved_list`, which is in `LOCAL_OPERATIONS`
     (`io_service.py:157`). It is mentioned only in the Work Offline bullet.
   - Three different "settles" still have no glossary: `SETTLE_SECONDS` (files being written),
     `FolderExplorer.settle_seconds`/`SETTLE_MAX` (the selection) and Live's "settled by age".

   Fix: state the three lanes once, with their caps, add `saved_list`, and add a one-line
   glossary of the three settles. [AI]

5. **cache-store.md:9 keeps the unscoped "**Nothing is removed without the user asking.**"** It
   comes right after describing the sweep deleting retired files and orphans and expiring pending
   saves. AGENTS.md:157-165 now scopes this rule and lists the housekeeping exceptions (Q3.3,
   instructions audit #4). The verbatim copy wasn't updated. Fix: replace the sentence with
   "Apart from the housekeeping AGENTS.md lists, nothing is removed without the user asking."
   [AI]

6. **The "never import a patched name by value" exception list is incomplete
   (io-and-browsing.md:9).** It says `folder_cache.store_options` is called as a module attribute
   "except in `helab/views/plots/arrangement.py` and `instance.py`". But
   `helab/views/HelabMainWindow.py:10` imports it by value
   (`from helab.utils.folder_cache import … store_options`) and calls it at `:702`, while 7 tests
   patch `helab.utils.folder_cache.store_options` (e.g. `tests/test_root_discovery.py:631`).
   Also, the "today …" list omits `stores._mounts`: tests patch it at
   `tests/test_saved_listings.py:312-324`, and it is imported by value from `infra` into
   `stores`, `browse`, `identity` and `markers`. Patching `stores`' copy is deliberate, since it
   is read only in `stores`, so it belongs in the "patched and read only in their own module"
   group. Fix:
   - change HelabMainWindow to `folder_cache.store_options()`, or list it as an exception;
   - add `stores._mounts` to the own-module group. [AI]

7. **data-roots.md:19 says "Live tab rebinding and offline roots are future roadmap work".**
   Offline roots were built as cache-only browsing (C0–C3, `9bb1ff7`). That covers Work Offline
   and mount hints for unmounted paths, which data-roots.md:11 itself describes
   (`stores._offline_mounts`); see `roadmaps/cache-only-browsing.md:7-12`. Fix: drop "and
   offline roots", or point at its listed follow-ups. [AI]

8. **(still open, audit #14) README.md:74 says compatibility checks run "3.10–3.12".** CI runs
   3.11, 3.12 and 3.14 (`.github/workflows/dev-cicd.yml:116,134`). README:136 already says
   3.11/3.12/3.14. [AI]

9. **release-and-ci.md has no line for the new dependency-graph workflow (`7b82c9d`).** It
   is `.github/workflows/dependency-graph.yml`: weekly and on lock changes on `main`, it sends
   `requirements.lock` through `helab/dependency_snapshot.py`. Neither file is named in any doc.
   The build-stamp env vars `HELAB_BUILD_BRANCH` / `HELAB_BUILD_REF`
   (`helab/build_info.py:104-105`, `ci-build.yml:46`) are also unnamed; :16 only says "CI
   stamps record the explicit source branch/build ref". Fix: one sentence for each. [AI]

10. **Modules no doc names (not in AGENTS.md's code map or any area file).** From
    `git ls-files 'helab/*.py'`, excluding `legacy_plotly`:
    - `helab/analysis/results.py`: `AnalysisContext`, `AnalysisResult`, `RamResults`, coverage.
      These are central to the script contract; the classes are named in the docs, the file
      isn't.
    - `helab/analysis/stats.py`: auto-crop, sampling, histograms; Basic plots v1's numerics.
    - `helab/analysis/identity.py`: `AnalysisIdentity`.
    - `helab/analysis/parameter_tree.py`: `UnitSpinBox` is named, its file isn't.
    - `helab/analysis/panes.py`: `PlotlyPane`.
    - `helab/utils/`: `cache_setting.py` (helpers' `settings_spec`/`open_settings`, named in
      settings.md without a file), `cache_freshness.py`, `number_format.py` and
      `time_format.py`.
    - `helab/views/SettingsDialog.py`, which hosts the Settings tabs; also `FolderTabWidget.py`,
      `explorer_text.py`, `ElidedLabel.py`, `HoverMenuToolButton.py`, `MemoryUsageWindow.py`
      and `DebugIconsWindow.py`.
    - `helab/models/StatusReport.py`: a folder's status as the browser shows it.
    - `helab/dependency_snapshot.py` (see 9).
    - The AGENTS.md:202 io_ops list omits `summary` and `identity`, which io-and-browsing.md:9
      lists.
    - `helab/utils/file_kinds.py` (`FILE_KINDS`: `RAW` `^d(\d+)\.txt$`, `TXY`
      `^d_txy_forc(\d+)\.txt$`) and `helab/utils/constants.py` appear only deep in
      cache-store.md. Both are first stops for the converter.

    Fix:
    - name `results.py`, `stats.py`, `identity.py`, `parameter_tree.py` and `panes.py` in
      plots-and-scripts.md;
    - name `SettingsDialog`, `FolderTabWidget`, `StatusReport` and the format helpers in
      app-runtime-and-ui.md, and `cache_setting.py` in settings.md;
    - give `file_kinds.py` its own code-map line. [AI]

11. **`helab/utils/synchronised_dict.py` (`SynchronisedDict`, 79 lines) is referenced nowhere**
    in `helab/` or `tests/`: dead code. Should it be removed, or kept and documented?
    [Tony]

12. **`tests_sample_data/` is in no doc.** It is tracked, 12 MB, 43 files, with folders `bad/`,
    `bad_txy/` and `goodish/` that hold raw `d*.txt` and `d_txy_forc*.txt` pairs. It is inside
    the checkout, so the guard allows it (`tests/test_real_data_guard.py:69`). It is also listed
    in `constants.DEV_POTENTIAL_DATA_PATHS` (`constants.py:469-470`). It is the natural fixture
    source for converter tests. Fix: a testing.md line on what it holds, that it's allowed
    under the guard, and that its files are small, real lab shots. [AI]

13. **testing.md:11 misstates the scope of `tests/test_helper_events.py`.** It says the test
    "reads every module under `helab/views`". It reads `helab/views` (recursively),
    `helab/utils`, `helab/models` and `main.py`, and checks both sides (`GUI`, `HELPER`,
    `NOT_GUI`, `NOT_EVENTS`, `RECEIPTS`; `test_helper_events.py:1-8,19-24`). The opt-in test
    env vars `HELAB_TEST_NATIVE_ICONS` (`tests/test_folder_icons.py:187`) and
    `HELAB_TEST_REAL_VOLUME` (`tests/test_data_roots.py:224`) are undocumented. Fix: correct
    the scope and add both env vars. [AI]

14. **architecture/README.md:7-9 points to "git history before that commit" for the 92 KB
    AGENTS.md.** On `main` the cut is inside the squash `9c477c2`, so the previous main commit
    (`5a8ae6f`) has a 39 KB v0.0.5 file. The 92 KB text is `55c9ca1^:AGENTS.md` on
    `dev/v0.0.6` (91,655 B; the branch is on origin). Fix: name that ref. [AI]

15. **Stale pointers to AGENTS.md sections that moved, outside the scope files but read by
    agents:**
    - `roadmaps/analysis-workflow.md:23` ("AGENTS.md › Script system");
    - `roadmaps/cache-storage-and-settings.md:597,630` ("AGENTS.md › Caching");
    - `roadmaps/cache-only-browsing.md:12` ("AGENTS.md › Work Offline");
    - `roadmaps/live-monitoring.md:99` ("the architecture summary is in AGENTS.md").

    The area files have no `##` headings: each is one or two very long paragraphs with bold
    labels. So nothing can link to e.g. "Work Offline" or "Cache first". Fix:
    - give each bold label in the area files a `###` heading (no text change);
    - re-point these five references to `.ai/architecture/<file>.md#<anchor>`. [AI]

16. **AGENTS.md:169 says "open QSettings only through `app_settings()`" without the helper
    exception.** settings.md:9 says "helpers aside, which reopen it from `settings_spec`".
    `tests/test_settings_store.py:16` allows `helab/utils/cache_setting.py`, which builds
    `QSettings` at `:31-32`. Fix: add "(helpers: `cache_setting.open_settings`)". [AI]

17. **(still open in code, audit #19) GUIWatchdog stall stacks go to `sys.__stderr__`, not the
    log** (`helab/utils/gui_watchdog.py:39-40`). io-and-browsing.md:9 ("dumps thread stacks")
    and app-runtime-and-ui.md:11 don't say where the stacks go, so an agent reading a
    `helab-<pid>.log` stall line will look for stacks that aren't there. Fix: say "to stderr,
    not the log" until the code changes (AI_TODO). [AI]

18. **README.md:69 says "Development branch: … TonyXTYan/HeLab"**, which is a repo. AGENTS.md:7
    was fixed this way ("is where HeLab is developed"). Fix: "Development repo". [AI]

## Where the converter port would be documented

The port turns raw `d*.txt` into `d_txy_forc*.txt`. It touches rules that today assume HeLab
only reads data:

- **New area file `.ai/architecture/converter.md`**, plus an index row in
  architecture/README.md and one code-map line in AGENTS.md. It would hold:
  - the numerics module (4-corner match, `bin_time`, `tsum`, tolerances, the `how_many_x`
    quirk from `.ai/sessions/2026-10-28-claude-txy-converter-plan/findings.md`);
  - the MATLAB reference files (finding 1);
  - the output format and byte-exactness (`dlmwrite`, precision 8);
  - detector profiles (Q6.10/Q6.11);
  - the headless CLI (Q6.3.2).
- **io-and-browsing.md:** a converter helper operation is source I/O. It needs:
  - a lane;
  - `SOURCE_OPERATIONS` (`io_helper.py:41`), so Work Offline refuses it (`OFFLINE_REFUSED`);
  - `IOService.LABELS`/`NOUNS`;
  - pausing and heartbeats;
  - new event kinds in `helab/io_ops/events.py`, which `test_helper_events.py` checks.

  "Files still being written" and `SETTLE_SECONDS` apply to its raw input. live.md:9 already
  names "the converter writing to a temporary name and renaming it" as the real fix for paused
  writers: the port should do that, and the doc should say so.
- **AGENTS.md invariants:**
  - Today the only writes into source folders are `.helab-root` markers (`MARKER_OPERATIONS`,
    `folder_cache.py:44`). Writing TXY beside the raw files, or only into the cache, is Q6.9 and
    Q6.6 (`d_txy_helab_*.txy`). Whichever Tony picks needs a one-line invariant: "HeLab writes
    into source folders only …" [Tony, already Q6.9]
  - The test guard (`infra._guard`) is applied on reads through `infra`. A converter's writes
    must go through it too, and testing.md should say so. [AI once designed]
- **cache-store.md / file kinds:** a new output kind is "a new entry" in `FILE_KINDS`
  (`file_kinds.py:3-4` says so). The shot-time rule (io-and-browsing.md:20: "a TXY's mtime is
  when it was converted") holds for HeLab's own conversions too.
- **live.md:** the Live auto-convert toggle (Q6.8) belongs in live.md when built.
- **testing.md:** `tests_sample_data/` as the fixture source (finding 12). Real raw files on X
  are reachable only by hand, never from tests (AGENTS.md:97).

## Verified OK (no finding)

- **settings.md:** keys, defaults, org/app, the plist name and `RETIRED`, checked against
  `settings_defaults.py` and `~/Library/Preferences`.
- **live.md:** `LIVE_REREAD_SECONDS` = 300, `RACY_SECONDS` = 2, interval 3 s, autosave 10, and
  every class and function named.
- **app-runtime-and-ui.md:** log rotation (1 MB, 10 backups), 300 kept, 50/20 MB, the RAM
  budget shares (50/75/70/80 %), `RELOAD_GRACE` 10 s, snapshot bounds 256/100,000, icons 4096
  and batch 64 with a 5 s timeout, `FRESH_SECONDS` 10, the clock-skew threshold 2 s, and the
  thread names.
- **plots-and-scripts.md:** all names and files, minimum sizes 200×200, 240×360 and 240×400,
  Dash port 8050, bootstrap 1000.
- **cache-store.md:** names, the `_migrate` tables, `PENDING_MAX_AGE`, the admin actions,
  `VERIFY_WAIT` 15 / `SAVE_VERIFY_WAIT` 120 (apart from 3 and 5).
- **data-roots.md:** names (apart from 7).
- **release-and-ci.md:** the matrices, `upload`, `-n 4`, `--timeout=120`, the 20-minute test job
  and `faulthandler_timeout` 100 (apart from 9).
- **io-and-browsing.md:** timeouts 60 s and 15/20/30 s, resume 0.5 s, stalled listing 3 s,
  `SETTLE_MAX` 1 s, `MAX_MISMATCHED` 8192, `OFFLINE_OPERATIONS`, the stderr tail of 2 KB, and
  `trace_check` 10 s.
- **Links:** every relative markdown link and anchor in AGENTS.md, README.md and the area files
  resolves.
- **AGENTS.md commands:**
  - the `helab` entry point (`setup.py:61`);
  - the bundle ID (`HeLab.spec:71`);
  - `legacy_plotly` excluded (`mypy.ini:4`, `pyrightconfig.json`);
  - `test_typing.py` runs mypy soft and strict and pyright on `helab` and `tests`;
  - the frozen helper is dispatched first (`main.py:3`).
- **README.md setup:** consistent with AGENTS.md and `.gitmodules` (apart from 8 and 18).

**Fixed since the earlier audits (not repeated):**
- AGENTS.md size and the Codex 32 KiB cut.
- The housekeeping exceptions in AGENTS.md.
- CodeGraph is now optional.
- The routing table, floor rule and definition of done.
- `.ai/coding-workspace.md` and `session-export` are marked as possibly missing.
- README's submodule count.
- `CacheTab.confirm` is valid again: an instance attribute set to `_confirm` at
  `CacheTab.py:118`.
