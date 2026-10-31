# Caching v2: raw files as the cached source

Horizon: v0.0.8 (Q28.2, Tony 2026-10-29), after v0.0.7's converter. Added: 2026-10-29, planned with Tony in Chat. **Tony's
go came on 2026-10-31 (Q28.1): stages 0 and 1 in v0.0.8, stage 2 later**, on one area floor (Caching v2,
`agent/caching-v2`); stage 0 and stage 1's checkpoint 2 landed `ad86bd3` with store-v4 behind its switch,
off (Q28.3; [stages](#stages-each-needs-tonys-go)). Readiness for an unattended build: block 28; stage 1's
design: the [addendum](../.ai/sessions/2026-10-31-claude-caching-v2/design-stage1.md). Evidence and options:
[caching audit](../.ai/sessions/2026-10-29-claude-caching-audit/audit.md); the design:
[store-v4 design note](../.ai/sessions/2026-10-29-claude-caching-audit/store-v4-design.md);
decisions Q19.x and Q22.x in [DECISIONS_TODO](../.ai/DECISIONS_TODO.md), with Tony's answers so far
in the [caching memory](../.ai/memory/results/caching-v2.md). Priority and completion:
[overview](_readme.md).

## Why

With the converter in HeLab, the raw `d<N>.txt` files are the true source and every TXY is
derived and reproducible (byte-identical across backends). Today a converted shot exists four
times (raw file, HeLab's TXY text, the store's dataset, RAM), only the default source is disk
cached, and a re-converted shot looks new (its TXY file's mtime changes). Tony (2026-10-29): each
plot may prefer a different converter, a calibration script needs raw pulses, so cache the raw
files; keep both options open, and once the converter is robust, cache a selected tag again.

## The raw layer

Per shot, the raw file parsed into binary arrays and kept in the store, beside the datasets:

- **Content:** the pulses as `channel` (int8) and `time` (int64, 25 ps bins), stably sorted by
  time as the converter needs them, time delta-encoded, Blosc-compressed; plus what the converter
  and the checks need from the text: the trigger time (`t_zero`, the first unsorted row), the
  first line's channel, the row count, whether the file ended with a newline, and the parse
  diagnostics. The parser's version is part of the key, so a parsing fix re-reads.
- **Size** (measured on the 309-shot sample set, 217.5 MB of raw text; design note §5, Q22.7):
  - a TXY layer at today's dataset settings (Blosc zstd 9, no shuffle): 15.5 MB for `m19v1`
    (8 significant figures), 17.0 MB at full float64; today's store keeps 16.2 MB (MATLAB's TXY);
  - the raw layer (int8 channels, int64 time deltas, byte shuffle): 29.5 MB at zstd 5 (the design
    note's codec), 27.5 MB at zstd 9 (2.0 B/pulse, 7.9× smaller than the text; the best of ten
    variants and at the floor for generic compression; chosen in Q22.7);
  - so **the raw layer is ≈ 1.8× an `m19v1` TXY layer** with zstd 9 (Q22.7) (1.9× at zstd
    5), and raw plus one tag ≈ 2.7× today's store per folder (2.8× at zstd 5). An earlier "about
    the same" compared TXY at other settings.
- **Key:** the data root key and relative path (as datasets), plus the raw file's fingerprint
  (size and mtime, read once settled). A raw file overwritten in place is a new version: read
  again, re-converted, and **a big warning** shown, since it only happens when the TDC is
  misconfigured (Q22.5).
- **Exactness:** converting from the layer must equal converting from the file, byte for byte;
  stage 1's checker proves it on every sample shot and the fuzz set. As built (`helab/convert/raw_layer.py`,
  `b3945f1`): the compact encoding (int8 channels, int64 time deltas, row 0 first) holds when the strict
  parser read the file, channels ≤ 127 and times < 2^62 (exact, since every strict value is an integer
  float64), else float64 in file order; `tests/test_raw_layer.py` proves layer = file on every case, the
  textscan probes, `tests_sample_data/` and a 57-file fuzz set with every backend (cython in CI's Converter
  backends job), and the sample set via the layer gives 303 identical and the same 6 proved exceptions as
  the file path (`check_samples.py --via-layer`, in memory).
- **Filled** by a background `raw_fill` job after the folder shows, so loads keep today's speed
  (Q22.1; raw files are 2.4–3.6× the TXY bytes over the share), wherever HeLab caches a folder
  today (Q19.10, Tony 2026-10-29): a load of the
  selected folder (Load, or auto-load when it is on), Live's saves (every 10 shots and on stop),
  loads for presets and reopened plots, and auto-convert. Not for listings or scans (status only),
  folders marked Don't cache, folders without a data root (RAM only) or while working offline.
  Only helpers open the store (AGENTS.md).
- **Uses:** any profile tag can be made from the layer without touching the share; offline,
  HeLab may make and save a HeLab layer from it (local work only, Q22.8). Calibration and D11's
  raw-pulse diagnostics read it directly (MCP pulses, ringing, time sums: information a TXY loses).
- **Raw layers whose raw file is gone** (the only copy) **or from an older parser** are kept and
  used, labelled; Make room lists them last and names them; never removed automatically (Q22.6).

## TXY layers and the policy

- **TXY layers:** per folder, one `matlab` layer (MATLAB's TXY) and one HeLab layer per **profile
  hash** (`helab:<hash>`), with the tags (`m19v1`, `p22v1`, …) kept as its names (Q22.2), each
  cached as a plot uses it (Q19.3): the
  uncalibrated plate profiles have `matlab-2019`'s hash, so `m19v1` and `p22v1` hold identical
  data and are stored once. A HeLab layer can always be rebuilt from the raw layer, so it is a
  speed-up, not the only copy.
- **Loading a (folder, tag):** its TXY layer if present; else convert from the raw layer (no text
  parsing: ~280 MB/s NumPy, ~1 GB/s Cython per core); else read the share.
- **Policy (Tony, 2026-10-29, Q22.11):** cache the raw layer and the selected TXY versions at the
  same time; a global default caches raw files; a per-folder override picks the source priority
  (MATLAB's TXY or a HeLab profile tag), whose TXY layer is cached as well. Variants: *raw only* (convert on load); *raw + a selected
  tag* (fast loads; the default once the converter is robust); *TXY only* (archives without raw
  files, or where raw isn't wanted). Switching policy needs no migration.
- **Budget:** both layers count in the one disk budget; nothing is removed without asking, as
  today (Make room offers TXY layers first, since they can be rebuilt; MATLAB's TXY layers and
  layers cached without raw files are not rebuildable, Q28.5).
- **HeLab's text TXY in `converted-txy/`** (while the cache output is used) have their own budget,
  separate from the dataset budget; beside TXY have none (Q12.3 = Q19.2, Tony 2026-10-29).
- **Identity:** HeLab shots are identified by the raw file's fingerprint + the profile hash, so a
  re-conversion is the same data and saved results stay valid.
- **Precision (Q19.6, Tony 2026-10-29):** binary always; text TXY only beside the raw files and on
  export. `m19v1` rounds to 8 significant figures so it matches its text exactly; newer tags keep
  full float64, written as `%.17g` text so a beside or exported TXY equals its layer (Q22.10,
  decided).
- **No "clear this tag's data and its saved results" action** for now (Q22.9).

## Store v4 (Q19.4: a fresh store, Tony 2026-10-29)

Caching v2 lives in a new `DIR_CACHES/store-v4`, not a migration of store-v3. The
[design note](../.ai/sessions/2026-10-29-claude-caching-audit/store-v4-design.md) (`37c0a83`) has the
schema, keys, read and write paths, budget, tests and build order; in short:

- **Tables:** the record tables carried over from store-v3 (listings, status, subtrees, data
  roots' records, results, presets' references, flags; and `datasets` through stage 1, Q42.3, so a v4
  store caches datasets until stage 2's TXY layers replace it), plus `raw_layers` (one row per raw file:
  key, fingerprint, parser version, pulse count, file) and `txy_layers` (one row per folder and
  layer, per-shot fingerprints as `datasets` has now).
- **Files:** pickle-free `.hlb` containers (a magic, a JSON header, Blosc chunks of at most 64 MB),
  replacing today's Blosc pickles; this also fixes the 2.1 GB limit on one save
  ([known issues](known-issues.md#app)).
- **Saved results:** keyed by the layer they ran on (raw fingerprint + profile hash), so they
  survive a re-conversion.
- **Compatibility with store-v3** (Tony: an option to keep using it, clear it or ignore it):
  shown once, when HeLab first opens a cache folder that has a store-v3 and no store-v4:
  - *Keep using store-v3 for now:* store-v4 is created and filled as folders load; store-v3 is
    read (never written) for what store-v4 doesn't have yet: its datasets as MATLAB-TXY layers,
    its saved results, presets and records.
  - *Clear store-v3:* after asking, with its size shown; store-v4 starts empty.
  - *Ignore store-v3:* left on disk, unused; Settings › Cache shows it with a Clear.
  The choice can be changed later in Settings › Cache. HeLab never deletes store-v3 without
  asking (AGENTS.md). Until the user has chosen, HeLab behaves as Keep, reading only (Q22.3).
- **The user's own state** in store-v3 (flags, converter flags, constants, presets, data-root
  answers, mount hints, the budget) is imported into store-v4 once, whatever the choice (Q22.4).
- **Budget:** one budget across store-v4 (and store-v3 while kept); Make room offers TXY layers
  before raw layers, since they can be rebuilt.

## Versioning

Tony (2026-10-29, Q27.2): make versioning more robust with this store and cache upgrade, ready for
distributed analysis (results computed on other machines, other versions). To settle in the
design:

- **Dev builds say so** (proposed, Q27.3): the dev branch carries `X.Y.Z.devN` from its first
  commit (PEP 440) and the PR sets the release version, so a source build never looks like a
  released one. This changes AGENTS.md's bump rule and [app versioning](app-versioning.md)'s
  workflow.
- **Everything stored says who made it:** each raw layer, TXY layer and saved result records
  HeLab's version, commit and modified flag, the machine, and the environment (Python, NumPy,
  SciPy), so a result from another machine or version can be traced and judged. As a `makers` table
  (Q28.4, Tony 2026-10-31): one row per HeLab session, each stored row keeping its id; HeLab's TXY
  files need none, being named by their frozen profile tag and recorded in `converted-txy/index.sqlite`.
- **Saved results:** reuse needs the same release, or for a source build the same clean commit; a
  modified checkout neither reuses nor saves (or keeps its results apart). `reuse_saved_results` turns
  back on with this (Q27.1).
- **Formats:** every file format and record HeLab writes (store, `.hlb`, the converted-TXY index,
  markers, profiles, exported results) carries a format version, with one rule: an additive change
  keeps the version (older HeLab ignores unknown fields); only a breaking change bumps it, and an
  older HeLab then reads read-only or ignores, never rewrites. A compatibility test reads fixtures
  written by each older format.
- **Distributed analysis:** a result made elsewhere is accepted only with this provenance, and
  shown with it.

## Stages (each needs Tony's go)

0. Small fixes from the audit (A19.1 temp-folder TXY shown and cleared; A19.2 Clear vs a running
   conversion; both on hold for Tony's go) and the Q18.4 tags (built, `c718c71`).
   **Done** (landed `ad86bd3`): A19.2's fence (A19.1 earlier, with the converted-TXY index), cache-4,
   cache-5, cache-6.
1. The raw layer: parser output as stored pulses; the checker proves layer = file. Steps (the brief's):
   - [x] the design addendum (T~1–T~3 decided as Q42.1–Q42.3);
   - [x] the `.hlb` container and the raw layer's codec, layer = file proved (`b3945f1`);
   - [x] store-v4's core behind the switch: the carried-over tables, `makers`, `LegacyStore`, the import,
     Keep's read-through, cache moves with two stores (`cbf6e16`, `627d1ab`; checkpoint 2, landed `ad86bd3`);
   - [x] step 5's store side: raw layers, save units and guards, Make room's order, the sweep's orphan rule
     over `raw/`, v3's bytes in the usage (`d207b61`, inert);
   - [ ] step 5's rest: `raw_fill` (passing `RawEntry.read_at`; each `.hlb` published just before its batch's
     save), raw rows from `convert`, the maker id in each `.hlb` header, Q28.6's notice, cache-1;
   - [ ] step 6: the store-v3 question and Settings › Cache rows (raw pulses; Clear all includes `raw`); Make
     room's dialog names only copies (Q42.4);
   - [ ] step 7: the integration check with the switch on, in temp stores;
   - [ ] **cache export and the `.hlb` format documented** (Q42.5, Tony 2026-10-31): the format written up
     with sample code (`helab.utils.hlb.read`), `helab cache dump FILE` and `helab cache export FILE|--folder
     FOLDER --to npz|mat|csv`; read only, no new dependency.
2. TXY layers per profile hash and the loading order above; identity by raw fingerprint +
   profile hash; every source mode disk cached.
3. Convert on read: loads and Live convert from the raw layer; HeLab writes TXY text only beside
   the raw files or on export by default; `converted-txy/` and the cache and temp outputs stay as
   options (Q19.1: "default no", keep options open; Q19.7: temp kept for scratch and new
   features).
4. The policy UI (per folder and global) and Make room's order.
5. After MATLAB is retired (converter stage 5): raw files drive status, counts and signatures
   (Q14.4).

## Open decisions

In [DECISIONS_TODO](../.ai/DECISIONS_TODO.md):

- Q19.1 (keep HeLab's own TXY files once loads convert on read: Tony "default no", keeping
  beside writing and the options open; to confirm as written).
- Block 28 is decided (Tony, 2026-10-31): stages 0 and 1 (Q28.1), store-v4 behind a switch until stage
  2 (Q28.3), the `makers` table (Q28.4), Make room's "Clear old stores…" (Q28.5), the overwrite
  warning (Q28.6).
- Block 42 (the floor, 2026-10-31): Q42.1 a raw batch over the budget isn't saved and never asks; Q42.2
  zstd 9 stays unless M42.1 finds it too slow; Q42.3 `datasets` through stage 1; Q42.4 Don't cache's
  removal takes seen raw layers, keeps only copies; Q42.5 cache export (all decided). Open: Q42.6
  (AGENTS.md's wording). Follow-ups: A42.1, A42.2, A40.3.

Decided: Q19.2 (under Q12.3), Q19.3–Q19.10, Q22.1–Q22.11 (Q22.7: keep 8 GB and zstd 9 + byte
shuffle), Q26.1 (byte units by OS), Q26.2 (one `converted-txy/index.sqlite` instead of a JSON
per TXY, before v0.0.7's release) (above, and Recently decided).
