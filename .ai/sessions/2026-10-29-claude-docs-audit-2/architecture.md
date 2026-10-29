# Docs audit 2: AGENTS.md, `.ai/architecture/` and README setup (2026-10-29)

This audit was read-only: only this report was written. Ground is `dev/v0.0.7` at `36e3d6c`, after
the converter day (`helab/convert/`, `native/`, `io_ops/convert`, `io_ops/helab_txy`,
`convert_cli`, TXY sources, profiles, Live auto-convert, packaging, CI test groups).

Method:
- every backticked name in AGENTS.md, README.md and the 12 area files was grepped against
  `helab/`, `tests/`, `native/`, `dev/`, `.github/`, `setup.py` and `HeLab.spec`;
- dotted names (`module.name`, `Class.attr`) were checked with an AST pass;
- every relative link and anchor, every `HELAB_*` env var (both directions) and every event kind
  named were checked;
- constants, payload fields, event fields, CLI options, CI jobs and fixture counts were read from
  the code;
- `git ls-files helab native` was compared with the docs.

Size: AGENTS.md is **18,370 B** (limit 30 KB). converter.md is 31 KB, the largest area file.

Name accuracy is still high: no backticked name is missing from the code. The findings are about
stale converter behaviour, contradictions and gaps.

Of [yesterday's audit](../2026-10-28-claude-docs-audit/architecture.md), items 1–9, 11–14 and
16–18 are fixed (`synchronised_dict.py` is gone). Items 10 and 15 are partly open (finding 22).

## Findings

1. **converter.md:219-227: the events table no longer matches `helab/io_ops/events.py`.**
   - `shot_unconvertible` (:222) says "same fields; `reason` `no_rows` or `failed`". The code's
     reasons are `damaged` (Q18.5, with the extra field `problem`: `no_final_newline`,
     `not_trigger_first` or `no_rows`), `failed`, and `no_rows` from a `NoRowsError` at compute
     time. Evidence: `events.py:943-958` (`ShotUnconvertibleEvent`, `problem: NotRequired[str]`)
     and `io_ops/convert.py:579-582`. converter.md:207-211 itself describes `damaged`, so the file
     contradicts itself.
   - `shot_waiting` (:221) lists `settling`, `future`, `changed`, `no_final_newline`,
     `not_trigger_first` and `read_failed`, but leaves out `no_rows`. It now waits like the
     others (Q23.3; `raw.py:158` `WAITING` and `events.py:928-931`).
   - `partial_removed` (:226): the "When" column says "beside" and the fields are
     `file, size, age`. The code also sends `folder` (`events.py:1004-1011`). It also sends the
     event for leftovers in HeLab's own folder on any conversion, not only beside
     (`convert.py:737`; see finding 3).
   - `convert_plan`'s `profile` (:219) is `{name, version, hash, calibrated}`. `ConvertProfile`
     also has `tag` (`events.py:867-873`).

   Fix: update the four rows. Better still, have the table point at the `TypedDict`s
   (`ShotWaitingEvent`, …) for the field lists and keep only the "When" column, so it can't
   drift again. [AI]

2. **converter.md:255-257: the provenance record is described as `"version": 1` without the tag.**
   `helab/convert/provenance.py:32-34` has `VERSION = 2`, with the comment "2: tagged names (Q18.4)
   and `profile_tag`. A version-1 record belongs to an untagged name". The record also holds
   `profile_tag` (`convert.py:592`). converter.md:31 has the same gap. Fix: write "version 2", add
   "tag" to the profile fields, and say that a version-1 record belongs to an untagged
   `d_txy_helab_<N>.txy`. [AI]

3. **AGENTS.md:171-175 (the housekeeping list) and converter.md:244-251 tie the removal of
   leftovers in HeLab's own folder to a beside conversion. The code removes them on every
   conversion that has work.** `convert.py:558-562`: `if todo: … _remove_own_partials(path,
   places["folder"], send)` runs whatever the output is (cache, temp or beside). `places["folder"]`
   is under the temp folder when the output falls back to temp (`folder_for(base, …)`, :166-169).
   So "HeLab's own `converted-txy/` folder" means either of two folders.
   - AGENTS.md:171 reads "a beside conversion deletes its own leftover … in that source folder,
     … and the same leftovers in HeLab's own `converted-txy/` folder", so it reads as beside
     only.
   - converter.md:249 says "The same rules remove its own leftovers in HeLab's `converted-txy/`
     folder", and one of those rules (:248) is "only in a folder it is writing beside".

   AGENTS.md's list is meant to be exhaustive, so this wording matters. Fix: split the item into
   two.
   - "A beside conversion deletes its own leftover temporary TXY in that source folder (…)."
   - "Every conversion deletes its own leftovers in HeLab's `converted-txy/` folder (under the
     cache or temp folder): `io_ops.convert.own_partial()`."

   Make the same split in converter.md. [AI] (The behaviour itself is Q12.7/Q18.6 as built; only
   the wording is off.)

4. **cache-store.md:9 says "**Only helpers open it**". AGENTS.md:155 says "Only helpers (and
   `helab convert`, a headless process without the GUI) open the store".** `convert_cli.py:68-98`
   (`_start_cache` → `store_root(cache_dir())`) and `:208-222` run `convert_folder` in the CLI's
   own process, so that process opens the store and does source I/O there. AGENTS.md:127-129 also
   still says "Source-folder and store work runs in isolated `helab/io_helper.py` processes" with
   no CLI exception. Fix:
   - copy AGENTS.md:155's parenthesis into cache-store.md:9;
   - add "(or the headless `helab convert` process)" to AGENTS.md:128;
   - re-wrap AGENTS.md:155, which is 144 characters.

   [AI]

5. **converter.md:176 says the convert operation runs in the "Background lane unless
   `FolderCache` makes it foreground". It never runs in the foreground.**
   `folder_cache.py:45`: `FOREGROUND_OPERATIONS = ("list", "resolve", "load", "root_create", …)`
   has no `convert`, and `_is_foreground` (:526-530) requires it. live.md:11 and
   io-and-browsing.md:9 correctly say background. Fix: "Background lane (never foreground:
   `FOREGROUND_OPERATIONS`)". [AI]

6. **live.md:11 says the launch folder opens "from the main window 40 ms in". The code does it at
   10 ms.** `HelabMainWindow.py:170`: `QTimer.singleShot(10, self._open_first_tab)`, which calls
   `live_launch.start` (:1504-1505). Fix: "10 ms in (`_open_first_tab`)", or drop the number. [AI]

7. **converter.md:72 says "449 + 1,367 MATLAB-judged probes". The total is 1,367.** Round 1 is 449
   probes (`ts` 24, `ts2` 17, `ts3` 8, `fuzzts` 400) and round 2 is 918 (`ts4` 18, `fuzzeol` 500,
   `fuzzlead` 400). These counts come from the files in `tests/data/convert/textscan/*/`, less
   `list.txt` and `matlab.txt`. `.ai/sessions/2026-10-29-claude-txy-reference/crosscheck/handoff.md:174`
   says "all **1,367** MATLAB-judged inputs agree (ts 24, ts2 17, ts3 8, …". Fix: "1,367
   MATLAB-judged probes (449 in round 1, 918 in round 2)". [AI]

8. **converter.md:24, the `profile` row, lists only the two stage-1 built-ins** ("built-ins
   `matlab-2019` (default, Q6.10) and `matlab-2023-lab-edit`"). There are five
   (`profile.py:296-297` `BUILTIN_PROFILES`: plus `plates-2017`, `plates-2022`, `plates-2025`).
   The "uncalibrated" mark is `UNCALIBRATED = frozenset({"plates-2025"})` (`profile.py:295`), and
   every built-in has `calibrated=False`. So the event and provenance field `calibrated` is false
   for all five, and converter.md:310's "`plates-2025` marked uncalibrated" means the UI mark.
   Fix:
   - list the five built-ins in the row (or point to "Profiles in the app");
   - name `UNCALIBRATED` at :310.

   [AI]

9. **AGENTS.md:199 says "`helab/convert/` is Qt-free (`PURE`)", and converter.md:19 says "every
   module in `PURE`". Neither is quite true, and nothing enforces it.**
   - `tests/test_headless_imports.py:25-28` lists 18 `helab.convert` modules. It leaves out
     `backends.numba_kernels`, which imports numba only when numba loads (its docstring), and the
     package `__init__`s.
   - `test_every_analysis_module_is_listed_as_pure_or_qt` (:47-51) walks only `helab.analysis`.
     So a new `helab/convert` module that imports Qt or `helab.utils.constants` would pass CI.

   Fix: extend that test to `helab.convert` (walk it with `pkgutil.walk_packages`, with an explicit
   `OPTIONAL_ONLY = {"backends.numba_kernels"}`), or soften both docs to "the modules listed in
   `PURE`". [AI]

10. **converter.md:330 says "exit 0, 1 when the conversion fails, 2 for usage". Exit 1 happens only
    with `--once`.** `convert_cli.py:226-233`: with `--watch` alone, a failed pass is logged and
    the loop goes on; Ctrl-C then returns `status` 0. Fix: "exit 0; 1 when `--once`'s conversion
    fails (`--watch` logs a failed pass and goes on); 2 for usage". [AI]

11. **`multiprocessing.freeze_support()` at the top of `helab/main.py:3-6` is in no doc.** It runs
    in frozen builds before the helper dispatch, so the converter's worker pool
    (`ProcessPoolExecutor`, `io_ops/convert.py:365-374`) can spawn. The main.py ordering rule in
    AGENTS.md:150-151 and in release-and-ci.md covers only "before imports that start GUI
    services…". The CLI dispatch (`main.py:17-21`) appears only in converter.md:323. A12.1 depends
    on this. Fix: one sentence in release-and-ci.md (and in converter.md's "Frozen builds") giving
    main.py's order: `freeze_support` (frozen), then the I/O helper, then `convert`, then
    `--version`, then the GUI. [AI]

12. **architecture/README.md:14-24: the index rows don't cover the converter day.**
    - The converter.md row (:21) lists only stage 1–2 content ("raw parsing …, backends, TXY
      writing, the sample harness and proved reference faults"). It leaves out stage 4: the helper
      operation and its events, settle and damaged rules, where files go, provenance, tags, TXY
      sources, profiles in the app and `helab convert`.
    - The live.md row (:17) leaves out auto-convert and the launch folder.
    - The settings.md row (:22) leaves out the converter rows.
    - The io-and-browsing.md row (:14) leaves out `convert` and `helab_txy`.

    Fix: update the four rows. [AI]

13. **AGENTS.md's code map has routing gaps for the converter.**
    - :227, the `helab/views/` row, names `ConverterTab.py` but points its detail at
      app-runtime-and-ui and live. app-runtime-and-ui.md never mentions it; it is described in
      converter.md:313-318.
    - `helab/utils/txy_sources.py` (the four modes) and `helab/views/plots/txy_source.py` (the
      plots' TXY row) are in no code-map row.
    - :230 lists `backends/ (reference, numpy, cython, rust, numba, mlx)` without saying which
      ship. A reader of the map alone can take numba, mlx and rust to be shipping.

    Fix:
    - add converter.md to the views row's Detail column;
    - add `txy_sources.py` to a row (e.g. the `helab/convert/` row: "TXY sources
      `helab/utils/txy_sources.py`");
    - write "(numpy default; cython ships; rust, numba, mlx for developers only, A9.1)". [AI]

14. **Neither README.md nor AGENTS.md's command block shows how to run the headless converter.**
    README.md:118-124 ("Run") and AGENTS.md:83-90 give `helab` and `python -m helab` only.
    `helab convert --watch FOLDER [--once]` (Q9.5, built; `main.py:17-21`, `convert_cli.py:41-52`)
    is in the code map (AGENTS.md:221) and converter.md:321 only. The packaged form `HeLab convert …`
    logs only on Windows (A12.2). Fix: one line in each command block, e.g.
    `helab convert --watch FOLDER [--once] [--output temp|cache|beside]   # headless TXY converter`.
    [AI]

15. **testing.md:11 gives `tests/test_helper_events.py`'s app side as "`helab/views` with its
    `plots` package, `helab/utils`, `helab/models` and `main.py`, less `NOT_GUI`". That list
    leaves out `helab/convert_cli.py`**, which the test includes (`test_helper_events.py:7-8,23`).
    converter.md:230 has it right. Fix: add "and `convert_cli.py`". [AI]

16. **converter.md:153-156 lists the hand-picked "Converter backends" tests as
    "`test_convert_backend_*`, `test_convert_helab` or `test_convert_split`".** CI also runs
    `tests/test_convert_required_backends.py` (`ci-test.yml:107-108`). The same job is described
    again in release-and-ci.md:31-42, so the two copies will drift. Fix:
    - add the fourth file;
    - keep the job's description in release-and-ci.md only, with converter.md keeping just the
      rule ("a new converter test that runs every available backend must be added to
      `ci-test.yml`'s list") and a link. [AI]

17. **plots-and-scripts.md:9's list of the `helab/views/plots/` package** ("`dock`, `pictures`,
    `instance`, `script_tree`, `settings_panel`, `workspace`, `arrangement`, `presets`,
    `cached_results`") leaves out `txy_source`, which exists (`helab/views/plots/txy_source.py`).
    Fix: add it. [AI]

18. **Some text is duplicated and will drift.** Each item below has two or more copies:
    - The temporary-name patterns are typed out in AGENTS.md:172-174
      (`.d_txy_helab_<tag>_<N>.txt.<16 hex>.partial`, the `.json` and `.folder.json` ones), in
      converter.md:240, :246 and :251, and in `events.py:1002`. The code's single source is
      `io_ops.convert.partial()`/`own_partial()` over `provenance.BARE_NAME`. Fix: in AGENTS.md
      name the functions and keep one illustrative pattern.
    - The `.gitattributes` `* -text` rule is in AGENTS.md:201-202, converter.md:363-364 and
      testing.md:25. `test_windows_paths` is in converter.md:364-366 and testing.md:25. Fix: keep
      them in testing.md, with AGENTS.md's rule and a link.
    - converter.md:284-300 says twice in one paragraph that data of MATLAB's TXY alone keeps its
      identity and saved results (:285-287 and :298-300). Fix: drop the second.
    - The converter settings rows are in settings.md:11, converter.md:313-316 and live.md:11. Fix:
      settings.md lists the keys and the others link to it.

    [AI]

19. **converter.md:132-134's "Recommendation (Q11.2): … drop numba (+145 MB) and mlx" reads as
    current.** What was built is that numba, mlx and rust aren't shipped but their code stays
    (Q11.3, converter.md:140-144; `tests/test_shipped_backends.py:83`
    `test_the_unshipped_backends_code_stays`). Fix: "Decided (Q11.2, Q11.3): numpy default,
    cython ships; numba, mlx and rust kept for developers, not shipped". [AI]

20. **cache-store.md:9's list of `FolderCache.cache_admin` actions** leaves out `convert_prefs`,
    `clear_converted_txy` and `clear_root_results`. They are in `ADMIN_ACTIONS`
    (`io_ops/admin.py:21-24`); the first two are mentioned later in the same paragraph, and the
    third in :11. Fix: complete the list, or say "(`ADMIN_ACTIONS` in `io_ops/admin.py`)" and drop
    the copy. [AI]

21. **AGENTS.md's converter edits broke its line wrap.** :155 is 144 characters, :172 is 115 and
    :183 is 117; the rest of the file wraps at about 100. This is cosmetic, but Codex and terminal
    readers see it. Fix: re-wrap them. [AI]

22. **Still open from yesterday (items 10 and 15, partly fixed).**
    - Modules no doc names: `helab/analysis/panes.py` (`PlotlyPane`, `MatplotlibPane` are named,
      the file isn't), `helab/views/ElidedLabel.py`, `HoverMenuToolButton.py`,
      `MemoryUsageWindow.py` and `DebugIconsWindow.py`. Also the individual plot modules in
      `helab/scripts/dld/` and `helab/scripts/standard/` (`basic_plots`, `density_images`,
      `mean_position`, `scatter_3d`, `shot_trends`, `t_spectrum`, `velocity_distributions`; the
      groups are named) and `native/cython/build.py` (converter.md names only `native/build.py`,
      which calls it).
    - Headings: converter.md now has `##` headings (19), but the other 9 area files still have
      one heading each, with bold labels inside long paragraphs. cache-store.md:9 is one 11 KB
      line, so nothing can link to "Caching", "Cache first" or "Work Offline".

    Fix as yesterday: name the files in plots-and-scripts.md and app-runtime-and-ui.md, and give
    each bold label a `###` heading with no text change. [AI]

23. **Outside scope, noticed in passing:** `.ai/DECISIONS_TODO.md:146` (Q12.2) still uses the
    old name `d_txy_helab_<N>.txy`. Today's beside name is `d_txy_helab_<tag>_<N>.txt` (Q18.4).
    The store-v4 decision (Q19.4, `roadmaps/caching-v2.md`) is correctly absent from the area
    files, which describe the code as it is (`STORE_DIRNAME = "store-v3"`,
    `cache_store.py:31`). A one-line "planned: store-v4" pointer in cache-store.md would help
    readers. [AI]

## Verified OK (no finding)

- **Names:** every backticked identifier in the 14 files exists in the code or tests, apart from
  hashes, branch names and MATLAB file names. The dotted names (`fingerprints.SETTLE_SECONDS`,
  `infra._read_txy_file`, `stores._mounts`, `convert._read_raw`, …) are defined where the docs
  say.
- **Patch-by-value list (io-and-browsing.md:9):** it matches the code. `infra._mounts` is imported
  by value into `browse`, `stores`, `markers` and `identity`, and only `stores._mounts` is
  patched. `pipeline.convert_shot`, which tests patch, is imported at call time inside
  `io_ops/convert.py:354,389`, so the patch holds.
- **Links:** every relative markdown link and anchor in AGENTS.md, README.md and the area files
  resolves. Every repo path in backticks exists, apart from gitignored `.ai/local/`,
  `.ai/temp/txy/` and branch names. The session paths cited exist, among them
  `crosscheck/matlab-walkthrough.md` and `2026-10-29-claude-txy-bench/results.md`.
- **Env vars:** every `HELAB_*` named in the docs exists. The only ones the code has and the docs
  don't name are `HELAB_DIR_TEMPS_OVERRIDE` (covered by `HELAB_DIR_*_OVERRIDE`),
  `HELAB_IO_TRACE` (test-internal) and constants that happen to start with `HELAB_`
  (`txy_sources.HELAB_ONLY`, …).
- **Event kinds:** every kind named (79 literals in `events.py`) exists. The `ConvertRequest`
  fields and the `destination`/`output` note match `io_ops/convert.py:114-143` and
  `io_service.py:803`.
- **Converter constants:**
  - `ONCE_SETTLE_SECONDS` 60, `DAMAGED_SECONDS` 20, `PARTIAL_MAX_AGE` 1 h;
  - `SPLIT_BYTES` 20 MB, `READ_BLOCK` 8 MB;
  - `compute_budget` 60 s + 1 s/MB, progress every 0.25 s;
  - `DEFAULT_WORKERS` min(4, cores/2) and 1 when frozen;
  - `FUTURE_SECONDS` 2, `APP_BACKEND` `numpy`;
  - `folder_for` (`sha256[:24]`), `folder.json`'s fields;
  - the built-in tags `m19v1`/`m23v1`/`p17v1`/`p22v1`/`p25t1`, `BARE_NAME`, `FILE_KINDS`'s three
    patterns;
  - `_MODULES`, `UNSHIPPED_BACKEND_PACKAGES`, the spec's hiddenimports and datas, `setup.py`'s
    `package_data`;
  - the CLI options (`convert_cli.py:41-52`).
- **Settings:** the converter rows, their defaults (`cache`, `matlab-2019`, `numpy`,
  `helab-priority`, `""`, 100), the `read_convert_*`/`read_txy_source` readers and the
  `live_launch_folders` migration.
- **Live:** `AutoConvert`, `check_soon`, `convert_reasons`, `auto_convert`, `key_asked`,
  `LOW_COUNTS` with `source="convert"`, the "no hits" and damaged texts, Folder details'
  Auto-convert row, and the left panel collapsing.
- **I/O:** `convert` is in `SOURCE_OPERATIONS` (`io_helper.py:43`), `PAUSABLE`, `LABELS`/`NOUNS`
  and `uses_cache`. `LOCAL_OPERATIONS`, `OFFLINE_OPERATIONS`, `FOREGROUND_CAP` 3 and `LOCAL_CAP` 2
  match io-and-browsing.md. No new GUI-side worker threads or pools.
- **Store:** `_migrate` adds `convert_prefs` (cache-store.md's list matches;
  `pending_results` is grouped with results). `inventory.converted_txy` and
  `clear_converted_txy` sending `removed` kind `converted_txy` match.
- **CI:**
  - "Converter backends" has a 20 min timeout and the 4 files; Tests has groups `1/2`, `2/2`
    with a 20 min timeout (30 on Windows), the `pip list` guard and macOS coverage uploads;
  - the build job's timeout is 25 min;
  - `native/build.py --ci`/`--only rust` (maturin `--locked`) and
    `native/check_build.py --frozen`;
  - `SLOW_FIRST_MODULES`, `slow_first_positions`, `ALL_TESTS`, `crc32` grouping and
    `tests/test_test_groups.py`.
- **Fixtures:** `tests/data/convert/cases` holds 39 cases. `tests_sample_data/` is 12 MB, with 43
  data files plus `.gitattributes`. Both `.gitattributes` files say `* -text`. The `dev/txy/`
  scripts exist, and so does `~/HeLab-samples/txy-v1/`.
- **AGENTS.md:** under the size limit. Its setup, commands, rules and code-map paths exist. Its
  write rule matches `write_atomic(replace=False)` and the hard-link no-replace rename. Its
  headless and analysis rule matches `test_headless_imports.py`.
- **README.md setup and build:** consistent with AGENTS.md, `.gitmodules`, `requirements.txt`
  (Cython as a build tool) and the shipping rule (numba, mlx and rust never ship), apart from
  finding 14.
- **Commit refs** cited in converter.md, live.md and architecture/README.md (`d26e196`, `7cb168e`,
  `134e2ec`, `775fb1d`, `c718c71`, `475c6a6`, `6454b4a`, `55c9ca1`, `9c477c2`) all exist.
- **Unchanged since yesterday and spot-checked:** settings.md, data-roots.md, dld-analyses.md,
  release-and-ci.md (apart from 11 and 16) and app-runtime-and-ui.md (apart from 13 and 22).
