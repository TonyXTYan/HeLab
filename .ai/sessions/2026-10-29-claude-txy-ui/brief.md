# Brief: TXY converter stage 4, TXY source choice and profile manager (`agent/txy-ui`)

Coordinator: CoCo, 2026-10-29 (overnight build; Side approves on Tony's behalf within the
[mandate](../2026-10-29-claude-v0.0.7-overnight/mandate.md)). One Worker, then a Reviewer. Runs
beside `agent/txy-live` and `agent/txy-packaging`, all from helab-core landed + docs (01776d6).

## Read first

1. `AGENTS.md`, `roadmaps/agent-workflow.md`; `roadmaps/txy-converter.md` (Decided: which TXY a
   folder uses, profiles; Stage 4).
2. `.ai/architecture/converter.md` (profiles: schema, hash policy, built-ins; helab-core's output
   locations and provenance), `.ai/architecture/plots-and-scripts.md`, `.ai/architecture/cache-store.md`
   (datasets, saved results), `.ai/architecture/settings.md`.
3. helab-core's handoff (`.ai/sessions/2026-10-29-claude-txy-helab-core/handoff.md`).
4. `.ai/DECISIONS_TODO.md` Q6.6, Q6.10, Q6.11, Q10.1; `.ai/AI_TODO.md` A10.3.

## Base and branch

Base `01776d6` (helab-core landed). Branch `agent/txy-ui`.

## Objective

The user chooses which TXY a folder's plots use, and manages detector profiles.

## Scope

1. **TXY source choice** (Q6.6), in the plot settings: (a) MATLAB's `d_txy_forc`, with HeLab's
   filling shots MATLAB lacks (the default); (b) HeLab's wherever they exist; (c) both, as two
   datasets for comparing. HeLab's TXY come from wherever helab-core put them (cache, temp or
   beside the raw files). **Every dataset and saved result records its source** (and for HeLab's,
   the profile name/version/hash), so caches and saved results never mix sources: extend the
   dataset identity and the result key accordingly, with the store migration rule in AGENTS.md
   (`cache_store._migrate`) if a column is added. Test that switching source never reuses the
   other source's cached dataset or result.
2. **Profile manager** (Q6.11), a Settings tab: list the built-ins (read-only:
   `matlab-2019`, the default; `matlab-2023-lab-edit`; and the plate profiles `plates-2017`,
   `plates-2022`, `plates-2025`, which start equal to `matlab-2019` in output; `plates-2025` marked
   **uncalibrated**, Q6.11); user profiles as JSON files (in the app folder, not the repo): import,
   export, duplicate (from any profile) and edit (a form over `DetectorProfile`'s fields, with its
   validation; the content hash shown); which profile and backend conversion uses (settings rows).
   Built-in profiles ship as JSON in the package and load equal to the Python definitions
   (A10.3). Deleting a user profile asks first (AGENTS.md: nothing removed without asking).
3. **Converted TXY in Settings → Cache** (helab-core's Q~3, decided by Side for Tony to confirm):
   show the size of HeLab's converted TXY under the cache folder (`converted-txy/`), with a Clear
   that asks first. Also: Clear folder preferences now clears the per-folder `write_beside`
   flag too (helab-core); its confirmation (`CacheTab.py` ~433) and enabling (~609) must name it. They stay outside the disk budget for now, and nothing removes them without
   asking.
4. Plate swap dates (2017-03-17; ~2022, 2022-11-03 for now; 2025-06-18) can suggest the plate
   profile for a folder's date, but the default stays `matlab-2019` (Q6.10): show the suggestion,
   don't apply it.

## Rules

- Owned paths: plot settings panel parts in `helab/views/plots/`, a new Settings tab in
  `helab/views/`, the converted-TXY row in `helab/views/CacheTab.py` (its Clear goes through a
  helper, as every store and cache-folder change does), dataset/result identity where the source must enter it (`helab/analysis/identity.py`,
  `result_cache`, `folder_cache.py` only for that), `helab/convert/profile.py` and new profile
  JSON files (the plate built-ins, JSON loading), new tests. Not the helper operation, Live, or
  packaging. A store schema change: tell CoCo first (others may touch the store).
- GUI checks only with `floor-env.sh` sourced, on synthetic folders; never real data.
- Everything else as in AGENTS.md: strict typing, the full suite and three type checks, RERUNs
  reported, docs only in your session folder with `Q~`/`A~`/`M~`, push once, report to CoCo.
