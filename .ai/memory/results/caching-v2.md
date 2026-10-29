---
date: 2026-10-29
status: planning
name: caching-v2
description: "Caching v2, decisions so far (planning only, no cache code until Tony's explicit go): a fresh store-v4 with a one-time store-v3 choice (keep/clear/ignore); cache the raw d files as a raw-pulse layer plus TXY layers keyed by profile hash (tags as names); filled by a background raw_fill wherever HeLab caches today; global raw default + per-folder source priority; overwritten raw files re-read with a big warning; raw layer ≈1.8× a TXY layer"
metadata:
  node_type: memory
  type: result
---
Planned with Tony in Maestri Chat on 2026-10-29, after the converter landed (Q14.5 asked to
rethink caching). Plan: `roadmaps/caching-v2.md`; evidence: the caching audit and the store-v4
design note in `.ai/sessions/2026-10-29-claude-caching-audit/`. Open questions: Q19.1–Q19.3,
Q19.5–Q19.8 and Q22.7 in `.ai/DECISIONS_TODO.md`.

## The rule for now

- **No cache code until Tony gives an explicit go**, "A19.1 and A19.2 included" (2026-10-29). Keep
  planning.

## Decided (Tony, 2026-10-29)

- **A fresh store-v4** (Q19.4), not a migrated store-v3, with a compatibility option: keep using
  store-v3 (read for what v4 lacks), clear it (asked), or ignore it. Until the choice is made,
  behave as Keep, read only (Q22.3); the user's own v3 state (flags, converter flags, constants,
  presets, data-root answers, mount hints, the budget) is imported once whatever the choice (Q22.4).
- **Cache the raw d files** (Q19.9): "plan to move on to caching the raw d files". Why, in Tony's
  words: each plot may prefer a different converter, and a calibration script needs raw pulses;
  keep both options open, and once the converter is robust go back to caching a selected tag.
- **Where the raw layer is filled** (Q19.10): wherever HeLab caches a folder today: loads of the
  selected folder (Load, or auto-load), Live's saves, loads for presets and reopened plots,
  auto-convert; not listings, Don't-cache folders, folders without a data root, or offline. By a
  background `raw_fill` job after the folder shows, so loads keep today's speed (Q22.1).
- **Layers** (Q22.2): HeLab layers keyed by profile hash, with tags as names (`m19v1` and the
  uncalibrated plate tags hold identical data, stored once).
- **Policy** (Q22.11): cache the raw layer and the selected TXY versions at the same time; a global
  default to cache raw files; a per-folder override choosing the source priority (MATLAB's TXY, or
  any HeLab profile tag), whose TXY layer is then cached too.
- **An overwritten raw file** (Q22.5): only happens when the TDC is misconfigured; HeLab reads it
  again, re-converts its HeLab shots and replaces its layer row, never stops Live, **and shows a big
  warning**. The TDC may also skip numbers on pause/resume, so per-shot plots offer a time axis or
  a shot-index axis (A22.1).
- As proposed (Q22.6, Q22.8–Q22.10): raw layers whose file is gone or from an older parser are kept
  and labelled (Make room lists them last); offline, HeLab may make a HeLab layer from the raw
  layer; no "clear this tag" action for now; full-precision tags written as `%.17g` text.

## Sizes (measured on the 309-shot sample set)

- Raw text 217.5 MB; today's store keeps 16.2 MB (MATLAB's TXY); an `m19v1` TXY layer is 15.5 MB at
  today's settings (zstd 9, no shuffle).
- Raw layer (int8 channels, int64 time deltas, byte shuffle): 29.5 MB at zstd 5, 27.5 MB at zstd 9
  (2.0 B/pulse, the floor for generic compression; proposed in Q22.7). So a raw layer is ≈ 1.8× a
  TXY layer (1.9× at zstd 5), and raw + one tag ≈ 2.7× today's store (2.8×). The audit's first
  "about the same" compared different settings. Whether to raise the 8 GB budget is Q22.7.
