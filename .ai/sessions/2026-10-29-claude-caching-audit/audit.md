# Caching in HeLab after the built-in converter: audit and options

2026-10-29, Side's subagent (claude), read-only on `dev/v0.0.7` at `977120e`. Asked by Tony (Q14.5):
"now we have converter built into helab... we might need to rethink how all caching works, can you
run an audit and suggestions". Every claim cites the code; numbers marked *measured* were measured
here on Tony's Mac against `~/HeLab-samples/txy-v1/` (read-only, 309 shots, 217.5 MB raw; script
in this session's scratchpad, not committed). Proposals carry provisional IDs (`Q~n`, `A~n`) for
the Assistant or Coordinator to number.

## Summary

- HeLab keeps **four copies** of a converted shot's data: the raw file (the source), HeLab's TXY
  text in `<cache>/converted-txy/` (or temp), a Blosc dataset in `store-v3`, and float64 arrays in
  RAM. Only the store copy is in the 8 GB budget; the TXY copy is **3× larger than the store copy**
  and outside it (Q12.3), and the copy in the temp folder isn't even shown in Settings.
- The store keeps **one dataset per folder** (`datasets.path` is the primary key), so only the
  default TXY source is disk cached; the other three sources are RAM only (Q14.5), and the default's
  content follows the conversion-profile setting, so switching profile rewrites the row.
- A HeLab shot's identity is its **TXY file's (size, mtime)**. Converting the same raw file again
  (after Clear, or into another folder) gives byte-identical TXY with a new mtime, which makes the
  store re-read it and saved results show "outdated". Since every backend is byte-identical by
  contract, **(raw size, raw mtime, profile hash)** is a complete, stable key that needs no TXY.
- Writing TXY text and parsing it back costs more than it saves for HeLab's own use: format+write
  is ~36 % of a NumPy conversion, and the parse runs at ~250 MB/s of text, against ~3.5 GB/s for
  decompressing the store's dataset.
- **Recommendation:** first make what exists visible and consistent (stage 0, small). Next, store
  datasets as **layers**: one per (folder, kind of TXY), with HeLab's keyed by the raw file plus the
  profile tag. That caches every source with no duplication (stage 1). Then **convert on read**
  (Q6.9) in loads and Live, so HeLab writes TXY files only beside the raw files or on export
  (stage 2). None of these needs a change to "never removes cached datasets without asking"; only
  option (b) with automatic eviction would. Eight questions for Tony are at the end.

## 1. Inventory: every cache and stored copy

### Data (the shots themselves)

| Copy | Where | Keyed by | Invalidated / replaced by | Budget, housekeeping | Written / read by |
|---|---|---|---|---|---|
| Source: raw `d<N>.txt`, MATLAB `d_txy_forc<N>.txt` | source folder (share, disk) | file name | never changed by HeLab (AGENTS.md, I/O rules) | none; never removed | MATLAB/acquisition write; helpers read |
| HeLab TXY **beside** (`d_txy_helab_<N>.txy`) | source folder, per-folder flag `write_beside` (`convert_prefs`) | file name (no profile in the name yet; Q18.4 adds the tag) | never replaced: a later conversion is `shot_kept` (`io_ops/convert.py:563-576`) | none; never removed; its `.partial` leftovers removed after 1 h (AGENTS.md housekeeping, Q12.7) | `convert` helper / `helab convert`; loads read |
| HeLab TXY in HeLab's folder + per-shot provenance JSON | `<cache>/converted-txy/<sha256(key)[:24]>/` (output `cache`, default) or `<temps>/converted-txy/…` (output `temp`, no data root, cache off) (`io_ops/convert.py:154-157, 224-263`) | `root://` key, else `path:<abs>`; file name `d_txy_helab_<N>.txy` | profile change: **overwritten** in place (`convert.py:580`, `write_atomic` replaces by default, `convert/txy.py:81`); stale when raw or TXY size changes or another profile hash (`convert/provenance.py:105-119`) | **outside the budget** (Q12.3); shown and cleared in Settings → Cache for the cache folder only (`io_ops/admin.py:75, 190-195`, `helab_txy.py:260-323`); the temp folder's copy is neither shown nor cleared | `convert` helper writes; `load`/Live find them via `helab_txy.find` (`helab_txy.py:79`) |
| Store dataset | `<cache>/store-v3/datasets/<file>` (Blosc zstd-9 pickle, `cache_store.py:34, 459-465`) + `datasets` row | **one row per folder**: `path` = `root://<uuid>/<rel>` primary key (`cache_store.py:130-134`); per-shot fingerprint = the *chosen* TXY file's (size, mtime) (`io_ops/loading.py:376-381`); origins in `info.txy` | per shot: fingerprint or origin kind changed (`loading.py:490-541`); folder/root epochs (Clear); profile setting changed (`_helab_unchanged`, `loading.py:116-127`) | 8 GB disk budget (SI), 80 % pause, Make room / Save update asked; replaced files retired and swept after 600 s (`RETIRE_GRACE`, `cache_store.py:44`); pending saves expire after 1 h | helpers only (load, `save_held`, `cached`) |
| Store dataset, **non-default TXY source** | none: RAM only (`views/plots/instance.py:863` sends `no_cache: True`) | — | — | — | — |
| RAM datasets | GUI `FolderCache.datasets` (`folder_cache.py:346`) and `pins` | (folder, signature + `|txy=<source>` suffix, epoch) (`folder_cache.py:819-833`) | folder changed, invalidate, `removed`, a newer dataset of the same source (`_drop_superseded`, `folder_cache.py:2500`) | RAM budget (default 16/128 of RAM; LRU of datasets no tab shows, `_evict`, `folder_cache.py:1986`); shared buffers counted once (`utils/ram_buffers.py`) | helpers send arrays (`.npy` artifacts); GUI holds |
| Plot data and released pictures | GUI, per plot | the plot's view | Live revisions, Reload | same RAM budget: warn 50 %, window 75 %, release 80 % (`analysis/budget_core.py`) | GUI / analysis thread |

### Records and other stored state (store-v3 tables unless said)

| What | Keyed by | Removed by | In budget? |
|---|---|---|---|
| `folder_summaries`, `scan_histories`, `subtrees`, `listings` | root key | Clear by kind / all, purges, a root's Clear cached data | yes (records DB size, `_live`, `cache_store.py:2247-2256`) |
| Saved results (`results` + `results/<uuid>.npz`) | root key + exact lookup key (script, env, parameters, coverage with per-shot fingerprints **and origins**, `analysis/result_cache.py:57-62`, `analysis/results.py:54-76`) | Clear cached analysis, purge by `last_used`, Make room (asked, results only) | yes |
| `folder_prefs`, `convert_prefs`, `folder_constants`, `presets` | root key (presets: none) | only the user's specific Clear; never by Clear all, purges, making room | yes (rows), negligible |
| `roots`, `root_volumes`, `mount_hints`, `folder_epochs`, `meta` | location / mount path | Forget, Delete .helab-root | yes (rows) |
| Numba's compiled-code cache | `<cache>/numba` (`io_ops/convert.py:386-393`); Q18.1 moved it to temp, **not built yet** | nothing | no |
| User detector profiles | `<app folder>/profiles` (`convert/user_profiles.py`) | the user | no (settings-like) |
| Helper private folders | system temp `helab_data_*` / `helab_io_*` (`utils/io_service.py:796-800`) | removed when the helper ends (`io_service.py:963`) | no |
| I/O trace | `<temps>/io-traces` | — | no |
| Logs | `<app folder>/logs`, 300 files kept (`log_files_keep`, `settings_defaults.py:97`) | startup tidy | no |

### Sizes and speeds per shot (measured unless cited)

| Quantity | Value |
|---|---|
| MATLAB TXY / raw | 0.23 over the sample set (0.09 for the sparse 2019 halos, 0.38–0.43 elsewhere); 0.27–0.41 on X (Q6.9) |
| RAM float64 / TXY | 0.69 (0.67–0.71 per set; matches the memory note) |
| Store Blosc (zstd-9, no shuffle) / TXY | **0.32** (0.29–0.35); zstd-9 with shuffle 0.58, lz4 0.63: the current format is the right one |
| So per GB of raw (X ratios) | TXY 270–410 MB, store 86–131 MB, RAM 186–283 MB |
| Convert, NumPy, one core, end to end | 119 MB/s of raw; of which parse raw 0.40 s, reconstruct 0.79 s, format+write 0.68 s for 217 MB (bench `results.md:108-120`) |
| Parse TXY text (`pandas.read_csv`, as `infra._read_txy_file`) | 253 MB/s of text (≈ 620–940 MB/s of raw equivalent) |
| Blosc decompress / compress (zstd-9) | 3.5 GB/s / 57 MB/s of float64 |

Illustration: one shot every 30 s at the sample's mean of 0.7 MB raw is ~2 GB of raw a day, so
Live auto-convert (output `cache`) adds ~0.5–0.8 GB a day to `converted-txy/`, unbounded, plus
~0.2 GB a day of store datasets inside the budget.

## 2. What the converter changes

**New facts.** Raw files become the true source; every TXY is derived and reproducible
byte for byte (every backend matches the reference, `converter.md` "Backends"); a shot can have
several TXY (MATLAB's, HeLab's per profile; Q18.4 puts the tag in the file name); conversion is fast
(one core beats gigabit delivery); MATLAB TXY are 27–41 % of raw on X.

### Redundancies

- **R1. TXY text and the store dataset hold the same shot.** For an auto-converted folder the
  derived bytes on disk are TXY 1.00 + store 0.32, so the TXY copy is ~76 % of them and the only
  part outside the budget. Its one use after the first load is to rebuild the store dataset if the
  user clears it (parse at ~250 MB/s instead of converting at ~120 MB/s raw).
- **R2. Round trip through text.** The converter has float64 hits in memory, formats them
  (`%.8g`), writes, fsyncs and renames; then Live's next check lists the folder, stats, reads and
  parses the text back to float64 (`AutoConvert` → `LiveSession.check_soon`, `live.md`). Format+write
  is 36 % of NumPy's conversion time and 80 %+ for compiled backends.
- **R3. Two helpers per Live tick** (a background `convert` and a foreground Live check) where one
  could convert and hand over the arrays.
- **R4. Same MATLAB shots twice in RAM** when a plot uses `matlab-only` beside the tab's default:
  each source loads separately with no shared base (`folder_cache.py:910`, same source only), so the
  arrays exist twice and count twice.

### Inconsistencies

- **I1. One store copy per folder, four source modes.** Only the default source is stored
  (`instance.py:863`); `matlab-only`, `helab`, `helab-only` are RAM only, and their Reload after a
  release reads the source folder again (`instance.py:1250-1256`), so they don't work offline. Yet
  their **saved results are disk cached** (`result_cache_off` ignores the source,
  `folder_cache.py:2842-2851`).
- **I2. The default's content depends on a setting.** The stored row is "MATLAB + HeLab's fill of
  the *current* conversion profile"; changing the profile drops the old profile's shots from it
  (`_helab_unchanged`, `loading.py:125`), and switching back converts and re-reads again, because
  HeLab's folder keeps one profile per shot (overwritten, `convert.py:580`). Q18.2 (helab-priority
  default) makes this the common case.
- **I3. Different rules for MATLAB's and HeLab's TXY.** MATLAB's feed the mismatch rule, the folder
  signature, status counts and the large-folder estimate; HeLab's feed none
  (`helab_txy.matlab_signature`, `helab_txy.py:216`; `file_kinds.py:32` `sized=False`;
  `large_estimate` reads `files.txy.bytes`, `folder_cache.py:1908-1923`). Deliberate for now (Q6.6,
  Q14.4), but for a **raw-only folder** the signature is SHA-256 of `[]` whatever it holds
  (`summary.py:63`) and the tab's large-folder estimate is 0 (the helper re-checks with real sizes,
  `loading.py:432`, so this is a UI gap, not a safety hole).
- **I4. "No data root, no disk cache" holds for datasets but not for TXY.** A folder without a root
  (or with the cache off) still gets HeLab TXY on disk, in the temp folder keyed by path
  (`convert.py:249-261`, Q12.1), where nothing shows or removes them.
- **I5. Don't cache isn't honoured by the converter.** `convert` never reads `folder_prefs`
  (no `no_cache` in `io_ops/convert.py`), so a folder the user chose not to cache still gets TXY
  written into the cache folder.
- **I6. Budgets.** In: store datasets, results, records. Shown but out: `<cache>/converted-txy`.
  Not shown: `<temps>/converted-txy`, `<cache>/numba`.

### Risks

- **K1. Unbounded growth outside the budget** (R1, I6): Live auto-convert on the acquisition PC or
  a bulk re-conversion fills the cache disk with nothing to stop or warn; the 80 % pause and Make
  room don't see it.
- **K2. Regenerated TXY look like new data.** HeLab shots are fingerprinted by their TXY file's
  (size, mtime) (`loading.py:378-381`); after Clear converted TXY and a re-conversion, the bytes are
  identical but the mtime is new, so the store re-reads and rewrites the folder, and saved results
  covering those shots show outdated (`Coverage.diff`, `results.py:69-76`) until rerun.
- **K3. Beside TXY depend on this machine's cache folder.** Their provenance lives only in HeLab's
  folder (Q12.2), so another computer, a recreated store, or a refused cache folder makes them "not
  current" and they aren't loaded. Q18.4 ("TXY newer than raw", tag in the name) is the fix.
- **K4. No fence between Clear converted TXY and a running conversion**: store writes have save
  guards, `clear_converted` (`helab_txy.py:286`) doesn't, so a conversion running during the clear
  leaves files behind. Low impact: the user clears again.
- **K5. Profile switch churn** (I2) on archives: every switch re-converts whole folders and
  rewrites store rows, about 120 MB/s of raw per core.
- **K6. Rule pressure.** Any fix of K1 that deletes TXY automatically is a removal not on AGENTS.md's
  housekeeping list (cache-store.md: "whether they join the budget later, and so AGENTS.md's
  housekeeping list, is Tony's").

## 3. Options

Each option says what changes, what it costs, what could go wrong, how existing data migrates, and
which AGENTS.md rules or decisions it touches. **T** marks a choice that is Tony's.

**(a) Keep as is.** Cost: nothing. Risk: K1–K6 stay. Q12.3, Q14.5 stay open. Reasonable only
until Q18.2/Q18.4 land, since those make HeLab TXY the default and multiply them per tag.

**(b) Converted TXY are a cache: counted in the budget, evictable, made again on demand.**
- Changes: `converted_usage` joins the store's live usage (the store needs a table of those files,
  or helpers measure the folder each time); Make room may pick TXY folders, least recently used
  first; a load finding a shot whose current TXY is missing converts it (that is (d)'s machinery).
- Cost: medium (budget accounting outside SQLite, a `last_used` per converted folder, eviction
  under the same guards as datasets).
- Risk: K2 gets worse (eviction then re-conversion makes shots look new) unless identity changes
  first (stage 1). Eviction of the only copy of a shot whose raw file has gone (raw deleted or
  moved after conversion) loses data: it must check the raw file is still there.
- Migration: none.
- Rules (**T**): with Make room **asking**, no rule changes (it's the existing dialog). With
  **automatic** eviction, AGENTS.md's housekeeping list gains "converted TXY under the cache folder,
  least recently used first, to stay within the budget".

**(c) Store parsed datasets keyed by (raw fingerprint, profile tag); keep TXY files only beside.**
- Changes: a HeLab shot's fingerprint becomes the raw file's (size, mtime) with the tag in its
  origin; provenance (raw SHA-256, backend, hits, converted_at) moves into the dataset row's info;
  `converted-txy/` becomes legacy (read while present, cleared when the user asks).
- Cost: medium-high; touches `loading.py`, `save_held.py`, `live.py`, `helab_txy.py`, result
  coverage.
- Risk: identity change makes saved results of HeLab shots outdated once (they exist only since
  2026-10-29). Something must still produce the arrays when there's no TXY: (d).
- Migration: old rows reuse MATLAB shots as now; HeLab shots are read once more.
- Rules: none. Q12.3 becomes moot.

**(d) Convert on read (Q6.9): no TXY stored by HeLab for its own use, only parsed arrays.**
- Changes: `load` and the Live check convert settled raw files lacking a usable TXY in the helper
  (workers as in `convert`) and send arrays; Live auto-convert without beside is folded into the
  Live check (R2, R3); the `convert` operation stays for beside output and `helab convert --watch`
  (the acquisition PC publishing TXY for others).
- Cost: medium. The settle rule for raw files needs two sightings (`seen`), so a one-off load
  leaves out shots first seen in it until the next check (as Live does today). Precision: arrays
  straight from the reconstruction have full float64 precision, while TXY text has 8 significant
  figures; to keep data identical whichever way it was read, round as the text does (format and
  parse in memory, still ~30 % of a NumPy conversion, but no disk write, fsync, listing or
  re-read), or prove a vectorised rounding equal to it (**T**: see Q~6).
- Risk: first loads over the network read raw files, 2.4–3.6× the bytes of TXY (Q6.9). The fix:
  prefer a current TXY that exists on the share (MATLAB's or a beside one) and convert only shots
  without one.
- Migration: existing `converted-txy/` still read while present.
- Rules: none; the converter output setting (`converted_txy_output`, cache/temp) loses its purpose
  (**T**).

**(e) Cache every source (no RAM-only datasets).**
- Simple form: `datasets` keyed (folder, source). Cost low-medium, but a folder viewed in two
  modes stores the MATLAB shots they share twice, and the budget fills twice as fast.
- Layer form (recommended): store one dataset per **(folder, layer)**, where a layer is one kind
  of TXY, `matlab` (`d_txy_forc`) or `helab:<tag>`; a source mode is a per-shot choice between
  layers made at load time (`txy_sources.choose` and `helab_txy.compose` already do this per
  shot). Nothing is duplicated on disk; in RAM a shot's array is shared across modes; changing the
  conversion profile or the default (Q18.2) changes the composition, not the cache.
- Cost: medium-high. A new table or primary key (SQLite can't change a primary key in place: a new
  `dataset_layers` table via `_migrate`, or a fresh store-v4, **T**); pending saves, Make room and
  `clear_root` per layer; `read_cached` composes layers.
- Risk: more rows per folder, so more paths through the save guards; the identity of the default
  source (`identity_source` returns "" for the default, `txy_sources.py:93`) needs one definition
  that survives Q18.2's flip.
- Migration: a v3 row reads as layer `matlab` plus HeLab fills (by its `info.txy.origins`) until the
  next save splits it; or start empty in store-v4 (lab caches then re-read from the shares once).
- Rules: none; cache-store.md's "one dataset file per folder" and Q14.5's answer change.

| | Fixes | Cost | Rule change | Tony |
|---|---|---|---|---|
| (a) | — | none | none | — |
| (b) asked | K1, I6 | medium | none | Q~2 |
| (b) automatic | K1, I6 | medium | housekeeping list | Q~2 |
| (c) | K2, K3 (with Q18.4), R1 | medium-high | none | Q~1 |
| (d) | R1–R3, K1 (nothing new written), I4 | medium | none | Q~1, Q~6, Q~7 |
| (e) simple | I1 | low-medium | none | Q~3 |
| (e) layers | I1, I2, K5, R4 | medium-high | none | Q~3, Q~4 |

## 4. Recommendation: a staged path

**Stage 0, now on `dev/v0.0.7` (small; Ground or a Quick Fixes floor):**
- A~1: Settings → Cache shows and clears HeLab's TXY in the **temp** folder too (I4, I6): `converted_usage`
  and `clear_converted` over both bases.
- A~2: build Q18.1 (numba's cache in temp), already decided.
- A~3: `clear_converted` takes a fence that a conversion checks before each write (K4), or the
  docs say a running conversion may write after it.
- Build Q18.4 (tags in file names) **before** any change below: the tag is the layer's name, and
  per-tag file names end the overwrite churn in HeLab's folder (I2, K5).
- Q~2 and Q~5 below decide whether `converted-txy/` joins the budget and honours Don't cache now.

**Stage 1, with or right after Q18.2 (helab-priority default):** content identity and layers.
- HeLab shots fingerprinted by the raw file plus the tag (option (c)'s key), so a re-conversion
  is the same data (K2).
- The store holds one dataset per (folder, layer); every source mode is disk cached, and the
  default flip and profile changes cost no re-reads (option (e), layer form; I1, I2, R4).
- Saved results of HeLab shots are outdated once; MATLAB-only data keeps its identity and results.

**Stage 2:** convert on read (option (d)).
- Loads and Live convert raw files that have no usable TXY straight into arrays; Live auto-convert
  writes TXY only when the folder writes beside.
- `converted-txy/` is legacy, read while present and cleared by the user, and the
  `converted_txy_output` setting goes. Everything HeLab keeps that it can make again is then in the
  one budget, with no new removal rule.

**Stage 3, after stage 5 (MATLAB retired on the acquisition PC):** raw files drive status, counts,
signature and the large-folder estimate (Q14.4, I3); MATLAB's TXY become one more layer.

If Tony prefers to keep TXY files in the cache (Q~1 "no"), use option (b) with asked Make room
instead of stage 2, after stage 1 (else eviction triggers K2).

## Open questions for Tony

- **Q~1 Should HeLab keep its own TXY files once loads can convert on read?** Options: (a) no:
  only beside TXY and an explicit export; (b) yes, as a cache in the budget (option (b)); (c) yes,
  as now, outside the budget. Proposed: (a), at stage 2.
- **Q~2 Until then, does `<cache>/converted-txy` count toward the 8 GB budget (Q12.3)?** Proposed:
  yes, counted and shown with the store's usage; Make room may offer it, always asked (no change
  to AGENTS.md's list). Alternative: automatic eviction, which adds a housekeeping line.
- **Q~3 Disk cache datasets of every TXY source (Q14.5)?** Proposed: yes, as layers (no
  duplication), at stage 1.
- **Q~4 Layers in store-v3 (a new table, migrated) or a fresh store-v4 (lab caches re-read from
  the shares once)?** Proposed: store-v3 with a migrated table, since lab PCs now hold real caches.
- **Q~5 Does Don't cache this folder also stop HeLab's TXY going to the cache folder?** Proposed:
  yes; such folders convert to the temp folder, as folders without a data root do (I5).
- **Q~6 Precision of data converted on read:** round as the TXY text does (8 significant figures,
  identical to data read from any TXY), or keep full float64? 8 figures of T ≈ 0.4 s is 10 ns,
  coarser than the 25 ps bin but far finer than the detector resolves in position. Proposed: round
  as the text does (one rule for every path); full precision later as a profile option.
- **Q~7 The temp output (`converted_txy_output = temp`):** keep it after stage 2? Proposed: drop
  it with the setting.
- **Q~8 Temp-folder TXY of folders without a data root:** shown and cleared by the user only
  (proposed), or deleted after N days at startup (a new housekeeping line)?
