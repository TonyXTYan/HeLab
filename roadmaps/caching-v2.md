# Caching v2: raw files as the cached source

Horizon: after v0.0.7's converter. Added: 2026-10-29, planned with Tony in Chat. **Planning
only: no cache code until Tony's explicit go** (block 19). Evidence and options:
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
    variants and at the floor for generic compression; proposed in Q22.7);
  - so **the raw layer is ≈ 1.8× an `m19v1` TXY layer** with the proposed zstd 9 (1.9× at zstd
    5), and raw plus one tag ≈ 2.7× today's store per folder (2.8× at zstd 5). An earlier "about
    the same" compared TXY at other settings.
- **Key:** the data root key and relative path (as datasets), plus the raw file's fingerprint
  (size and mtime, read once settled). A raw file overwritten in place is a new version: read
  again, re-converted, and **a big warning** shown, since it only happens when the TDC is
  misconfigured (Q22.5).
- **Exactness:** converting from the layer must equal converting from the file, byte for byte;
  stage 1's checker proves it on every sample shot and the fuzz set.
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
  hash** (`helab:<hash>`), with the tags (`m19v1`, `p22v1`, …) kept as its names (Q22.2): the
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
  today (Make room offers TXY layers first, since they can be rebuilt).
- **Identity:** HeLab shots are identified by the raw file's fingerprint + the profile hash, so a
  re-conversion is the same data and saved results stay valid.
- **Precision (proposed, Q19.6 open):** binary always; text TXY only beside the raw files and on
  export. `m19v1` rounds to 8 significant figures so it matches its text exactly; newer tags keep
  full float64, written as `%.17g` text so a beside or exported TXY equals its layer (Q22.10,
  decided).
- **No "clear this tag's data and its saved results" action** for now (Q22.9).

## Store v4 (Q19.4: a fresh store, Tony 2026-10-29)

Caching v2 lives in a new `DIR_CACHES/store-v4`, not a migration of store-v3. The
[design note](../.ai/sessions/2026-10-29-claude-caching-audit/store-v4-design.md) (`37c0a83`) has the
schema, keys, read and write paths, budget, tests and build order; in short:

- **Tables:** the record tables carried over from store-v3 (listings, status, subtrees, data
  roots' records, results, presets' references, flags), plus `raw_layers` (one row per raw file:
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

## Stages (each needs Tony's go)

0. Small fixes from the audit (A19.1 temp-folder TXY shown and cleared; A19.2 Clear vs a running
   conversion; both on hold for Tony's go) and the Q18.4 tags (built, `c718c71`).
1. The raw layer: parser output as stored pulses; the checker proves layer = file.
2. TXY layers per profile hash and the loading order above; identity by raw fingerprint +
   profile hash; every source mode disk cached.
3. Convert on read: loads and Live convert from the raw layer; HeLab writes TXY text only beside
   the raw files or on export; `converted-txy/` becomes legacy (read while present, cleared by
   the user) and the temp output setting goes (Q19.1, Q19.7).
4. The policy UI (per folder and global) and Make room's order.
5. After MATLAB is retired (converter stage 5): raw files drive status, counts and signatures
   (Q14.4).

## Open decisions

In [DECISIONS_TODO](../.ai/DECISIONS_TODO.md):

- Q19.1 (keep HeLab's own TXY files once loads convert on read), Q19.2 (= Q12.3, does
  `converted-txy` count toward the budget), Q19.3 (disk-cache every TXY source), Q19.5 (Don't
  cache and HeLab's TXY), Q19.6 (precision, above), Q19.7 (drop the temp output setting), Q19.8
  (temp-folder TXY without a data root).
- Q22.7: the disk budget (keep 8 GB, or raise it) and the raw codec.

Decided: Q19.4, Q19.9, Q19.10, Q22.1–Q22.6 and Q22.8–Q22.11 (above, and Recently decided).
