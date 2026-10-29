# Caching v2: raw files as the cached source

Horizon: after v0.0.7's converter. Added: 2026-10-29, planned with Tony in Chat. **Planning
only: no cache code until Tony's explicit go** (block 19). Evidence and options:
[caching audit](../.ai/sessions/2026-10-29-claude-caching-audit/audit.md); decisions Q19.x in
[DECISIONS_TODO](../.ai/DECISIONS_TODO.md). Priority and completion: [overview](_readme.md).

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
- **Size:** on the 309-shot sample set, raw text 217.5 MB compresses to 29.5 MB as pulses. At
  today's dataset settings (zstd-9, no shuffle) the same shots' TXY layer is 15.5 MB (`m19v1`) or
  17.0 MB (full float64), so the raw layer is about 1.9× a TXY layer, and raw + one tag about 2.8×
  what today's store keeps per folder (an earlier "about the same" compared different settings).
  Best raw codec of ten measured: int64 time deltas + int8 channels, zstd 9 with byte shuffle,
  27.5 MB (2.0 B/pulse, 7.9× the text), at the floor for generic compression (Q22.7).
- **Key:** the data root key and relative path (as datasets), plus the raw file's fingerprint
  (size and mtime, read once settled). A raw file overwritten in place (free-run) is a new key.
- **Exactness:** converting from the layer must equal converting from the file, byte for byte;
  stage 1's checker proves it on every sample shot and the fuzz set.
- **Filled** wherever HeLab caches a folder today (Q19.10, Tony 2026-10-29): a load of the
  selected folder (Load, or auto-load when it is on), Live's saves (every 10 shots and on stop),
  loads for presets and reopened plots, and auto-convert. Not for listings or scans (status only),
  folders marked Don't cache, folders without a data root (RAM only) or while working offline.
  Only helpers open the store (AGENTS.md).
- **Uses:** any profile tag can be made from the layer without touching the share (Work Offline
  too); calibration and D11's raw-pulse diagnostics read it directly (MCP pulses, ringing, time
  sums: information a TXY loses).

## TXY layers and the policy

- **TXY layers:** one stored dataset per (folder, source tag): MATLAB's TXY, and HeLab's per
  profile tag (`m19v1`, `p22v1`, …). A TXY layer can always be rebuilt from the raw layer, so it
  is a speed-up, not the only copy.
- **Loading a (folder, tag):** its TXY layer if present; else convert from the raw layer (no text
  parsing: ~280 MB/s NumPy, ~1 GB/s Cython per core); else read the share.
- **Policy** (per folder, with a global default): *raw only* (convert on load); *raw + a selected
  tag* (fast loads; the default once the converter is robust); *TXY only* (archives without raw
  files, or where raw isn't wanted). Switching policy needs no migration.
- **Budget:** both layers count in the one disk budget; nothing is removed without asking, as
  today (Make room offers TXY layers first, since they can be rebuilt).
- **Identity:** HeLab shots are identified by raw fingerprint + profile tag, so a re-conversion is
  the same data and saved results stay valid.
- **Precision:** binary always; text TXY only beside the raw files and on export. `m19v1`
  rounds to 8 significant figures so it matches its text exactly; newer tags keep full float64
  (Q19.6).

## Store v4 (Q19.4: a fresh store, Tony 2026-10-29)

Caching v2 lives in a new `DIR_CACHES/store-v4`, not a migration of store-v3. Design to write
before stage 1 (a design note, then this section):

- **Tables:** the record tables carried over from store-v3 (listings, status, subtrees, data
  roots' records, results, presets' references, flags), plus `raw_layers` (one row per raw file:
  key, fingerprint, parser version, pulse count, file) and `txy_layers` (one row per folder and
  source tag, per-shot fingerprints as `datasets` has now). Dataset files per layer, Blosc.
- **Saved results:** keyed by the layer they ran on (raw fingerprint + tag), so they survive a
  re-conversion.
- **Compatibility with store-v3** (Tony: an option to keep using it, clear it or ignore it):
  shown once, when HeLab first opens a cache folder that has a store-v3 and no store-v4:
  - *Keep using store-v3 for now:* store-v4 is created and filled as folders load; store-v3 is
    read (never written) for what store-v4 doesn't have yet: its datasets as MATLAB-TXY layers,
    its saved results, presets and records.
  - *Clear store-v3:* after asking, with its size shown; store-v4 starts empty.
  - *Ignore store-v3:* left on disk, unused; Settings › Cache shows it with a Clear.
  The choice can be changed later in Settings › Cache. HeLab never deletes store-v3 without
  asking (AGENTS.md).
- **Budget:** one budget across store-v4 (and store-v3 while kept); Make room offers TXY layers
  before raw layers, since they can be rebuilt.

## Stages (each needs Tony's go)

0. Small fixes from the audit (A19.1 temp-folder TXY shown and cleared; A19.2 Clear vs a running
   conversion) and the Q18.4 tags (being built).
1. The raw layer: parser output as stored pulses; the checker proves layer = file.
2. TXY layers per tag and the loading order above; identity by raw fingerprint + tag; every source
   mode disk cached.
3. Convert on read: loads and Live convert from the raw layer; HeLab writes TXY text only beside
   the raw files or on export; `converted-txy/` becomes legacy (read while present, cleared by
   the user) and the temp output setting goes (Q19.1, Q19.7).
4. The policy UI (per folder and global) and Make room's order.
5. After MATLAB is retired (converter stage 5): raw files drive status, counts and signatures
   (Q14.4).

## Open decisions

- Q19.1–Q19.3 and Q19.5–Q19.8 (block 19).
- The [store-v4 design note](../.ai/sessions/2026-10-29-claude-caching-audit/store-v4-design.md)
  (schema, keys, read/write paths, the store-v3 choice, budget, tests, build order) and its
  questions, Q22.1–Q22.10.
