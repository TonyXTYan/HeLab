# Brief: caching v2, stages 0 and 1, store-v4 behind a switch (`agent/caching-v2`)

Coordinator: CoCo, 2026-10-31. **Tony's go (Chat, via Side; Q28.1):** stages 0 and 1 in v0.0.8, stage 2
later; store-v4 behind a switch that stays off until stage 2 and his go (Q28.3); Make room's "Clear old
stores…" for every older store version (Q28.5); an overwritten raw file warned by a notification once per
shot per session, a Folder details line and a log line (Q28.6); the area review's cache findings fold in
here; the I/O fixes land before stage 1 reaches `folder_cache.py`. **Q28.4 (Tony, 2026-10-31): a `makers`
table**, one row per HeLab session (version, commit, modified, machine, environment), and each stored row
keeps its maker's id; not per TXY file. **Block 28 is fully decided** (recorded on Ground at `d9d647f`,
after your base: you get it with your first merge of `dev/v0.0.8`). This is the **area floor** for `cache`
(`roadmaps/agent-workflow.md`, "Feature floors with named areas"): one long staged floor, landing at
checkpoints. One Worker; one Reviewer, recruited at the first checkpoint and kept for the later ones
(it re-checks only fix diffs once every finding is fixed).

**Areas:** `cache` (owner), `convert` for stage 0 and `convert`'s raw rows, `app` for the store-v3 dialog
and Settings › Cache rows; `io` (`folder_cache.py`) only from step 5, after I/O Fixes has landed.

## Read first

`AGENTS.md` (the disk cache rules, all of them: helpers only, save guards, `_migrate`, nothing removed
without asking and the housekeeping list, `cache_dir()`, byte units); `.ai/architecture/cache-store.md`,
`data-roots.md`, `converter.md`, `io-and-browsing.md`, `testing.md`; the plan `roadmaps/caching-v2.md`;
the design `.ai/sessions/2026-10-29-claude-caching-audit/store-v4-design.md` (§7 tests and build order);
the readiness review `.ai/sessions/2026-10-29-claude-caching-v2-readiness/readiness.md` (D1–D13, the 11
gaps, §4 data risks, stop conditions); `.ai/DECISIONS_TODO.md` blocks 19, 22, 27, 28 and Recently
decided; `.ai/memory/results/caching-v2.md`; the area review's `cache.md` and `convert.md` (convert-3)
(`git show 573361f:.ai/sessions/2026-10-31-claude-area-review/<area>.md`).

## Base and branch

Base `0571ff2` (`dev/v0.0.8`). Branch `agent/caching-v2`. Running beside you: I/O Fixes (`io`: owns
`folder_cache.py`, `io_service.py`, `io_ops/` except `convert.py`, `helab_txy.py`, `stores.py`,
`admin.py`) and Plot Identity (`plots`). Merge `dev/v0.0.8` when CoCo says (at least once I/O Fixes
lands, before step 5).

## Objective (in this order; commit each separately; stop and report to CoCo at each ◆)

1. **Stage 0 and the small cache fixes (store-v3):**
   - A19.2: `clear_converted` takes a fence a running conversion checks before each write (or, if a
     fence can't be made safe, show why and propose the doc wording instead).
   - cache-5: a save whose guard names a re-keyed folder is rejected cleanly (`SaveRejected`), retiring
     its file at once.
   - cache-4: tests close their `sqlite3` connections (`contextlib.closing`); correct the known-issues
     entry as a proposal.
   - cache-6: the `admin.py` comment; the doc wording as a proposal. ◆ **checkpoint: land stage 0.**
2. **Stage 1's design addendum** (`.ai/sessions/2026-10-31-claude-caching-v2/design-stage1.md`), before
   any store-v4 code: how you build each of readiness gaps 1–8 (take its proposed default unless you show
   a better one), the switch (Q28.3: a settings row, off; how tests turn it on), Make room's order (D8)
   with "Clear old stores…" for every older version found (Q28.5), Q28.6's warning, the codec (zstd 9 +
   byte shuffle, Q22.7) and its encode cost on a slow CPU, the format-version rule (an additive change
   keeps the version; an older HeLab never rewrites or sets aside a newer file: convert-3 shows what goes
   wrong when it does), cache-2 (per-kind folder epochs) in store-v4's schema (cache-3 and the other several-instances
   cases are moot under Q39.1, one HeLab per computer, built as A39.3 on Quick Fixes 8; say what drops), and Q28.4's `makers` table (what a session row holds, where the
   machine id lives, which rows and `.hlb` headers carry the maker id). ◆ **Send it to CoCo before you write code**: CoCo
   reads it and takes any design question to Tony.
3. **The `.hlb` container and the raw layer codec** (Qt-free, listed in `PURE`): encoder and decoder, the
   layer-equals-file tests on `tests/data/convert/` cases and a fuzz set, `--via-layer` in the sample
   checker **in memory only**.
4. **store-v4's core, behind the switch:** the carried-over tables, layout 4, `meta` (`store_id`,
   `legacy_v3`, `legacy_bytes`, `format`), the `makers` table and this session's row, v4's `_migrate`, the read-only `LegacyStore` for store-v3 with
   a test that fails on any other open of v3, the one-time import of the user's state (Q22.4), Keep's
   read-through of records and results, `cache_move` verifying both stores. With the switch off, nothing
   changes: store-v3 stays the live store and no `store-v4` folder is created (a test). ◆ **checkpoint:
   land steps 2–4 (inert).**
5. **After I/O Fixes lands** (merge `dev/v0.0.8` first): `raw_layers`, save units and guards, `raw_fill`
   (helper op, events in `events.py`, `FolderCache` scheduling on the background lane, pausable, refused
   offline, for Don't cache and without a data root), raw rows from `convert`, Make room's order and
   "Clear old stores…", the admin Clear for raw, Q28.6's warning; and **cache-1** (folder flags and
   `write_beside` dropped on a data root's change of identity, store-v3 and v4).
6. **The store-v3 question and Settings › Cache rows** (Keep / Ignore / Clear… per old store, raw pulses
   with size and Clear), `removed` kinds `raw` and `legacy`; every control named with an ID.
7. **Integration check, switch on, in temp stores:** load → `raw_fill` → layer equals file → Clear → Make
   room's order → v3's files unchanged (hash before and after; only SQLite's `-wal`/`-shm` allowed) → a
   cache move with both stores. ◆ **checkpoint: land stage 1 (switch still off).**
8. **Docs proposals** in the handoff (AGENTS.md wording "for Tony to confirm": store-v4 helper-only, the
   switch; `cache-store.md`, `data-roots.md`, `converter.md`, the plan, known-issues), provisional
   `Q~`/`A~`/`M~`.

## Data safety (readiness §4; stop and ask CoCo if any is at risk)

- Never run HeLab or `helab convert` without the floor's `floor-env.sh` sourced; before any real-app run,
  show `HELAB_DIR_CACHES_OVERRIDE` is set. Never open Tony's real cache folder.
- store-v3 is opened only by `LegacyStore`; never `CacheStore(...)` on its path.
- `--via-layer` encodes and decodes in memory: nothing is written to `~/HeLab-samples` (read-only).
- Build and test `clear_legacy`, Make room and cache moves in temp stores only.
- **No new automatic removal or housekeeping line.** The switch never defaults on. No change to the 8 GB
  budget, byte units, versions, branches from `main`, PRs.

**Stop conditions** (stop that piece and ask CoCo): a design question the addendum, the design note and
D3–D10's defaults don't cover; an on-disk format change beyond them; any write to a store-v3 outside a
temp store; a failing test after one cause hunt; a RERUN without a cause; a Windows test group over ~25 of
its 30 minutes; an AGENTS.md rule change beyond wording.

## Rules

Owned paths: `helab/utils/cache_store.py`, `cache_paths.py`, `cache_move.py`, `cache_setting.py`,
`data_roots.py`, new store-v4 and `.hlb` modules (say where in the addendum), `helab/io_ops/stores.py`,
`admin.py`, `helab_txy.py` (`clear_converted`), `convert.py` (the fence, raw rows), `events.py` (new
kinds), `helab/views/CacheTab.py`, `CacheDialogs.py`, `helab/utils/settings_defaults.py` (new rows),
`tests/test_headless_imports.py` (`PURE`), their tests; `helab/utils/folder_cache.py` and `io_ops/` raw
fill only from step 5. Ask CoCo before any other file. Strict typing (incl. `--platform win32`, `pyright
--pythonplatform Windows`); tests never touch real data; the full suite (`-n` with `--reruns 5
--reruns-delay 1`) at each checkpoint, every RERUN reported with its reason. Docs only in
`.ai/sessions/2026-10-31-claude-caching-v2/`. Push at checkpoints only; before reporting a CI run, read
every Tests and Converter backends job's log for RERUN (`.ai/memory/feedback_ci_reruns_in_logs.md`).
Each landing needs the Reviewer with no open findings and CI green on 3 OSes by run ID. No version bump,
release, tag or PR.

At each ◆: `maestri ask "CoCo" "Caching v2: <checkpoint> at <hash>, suite <N> passed, RERUNs <…>, CI <run>"`.
