# Brief: one index for HeLab's converted TXY (`agent/txy-index`)

Coordinator: CoCo, 2026-10-29. Tony's decision **Q26.2** (go, "26.2 ok"; `.ai/DECISIONS_TODO.md`, with
Q19.8: "an index to store the hash table from temp dir to real dir is fine"): replace `converted-txy/<hash>/folder.json` and the per-shot `d_txy_helab_<tag>_<N>.json`
provenance records with **one SQLite file per base, `converted-txy/index.sqlite`**, before v0.0.7 is
released (so no per-shot JSON ever reaches users: no migration). One Worker, then a Reviewer. A small
floor, on v0.0.7's release path: keep the scope tight. The design is in `.ai/architecture/converter.md`
"Where files go" and "Provenance" (both sections change with this floor).

**Maybe added (Tony to answer; CoCo will tell you):** Q27.4 (build Q19.5: a Don't-cache folder converts
to temp, not the cache folder; `_places` in `io_ops/convert.py`) and Q27.5 (A19.1: Settings › Cache lists
and clears the temp folder's converted TXY too). Design so both fit (the index is per base); don't build
them until told.

**Not caching v2.** Don't touch the store (`CacheStore`, `store-v3`, `cache_store.py`), `FolderCache`'s
store paths or the store-v4 design; caching v2 later moves this provenance into the store's
`txy_layers`. Cache code waits for Tony's go.

## Read first

`AGENTS.md` (the source-folder write rule, the housekeeping list, I/O rules, settings); `.ai/DECISIONS_TODO.md`
Q26.2, Q19.8, Q19.5, Q27.4, Q27.5, Q12.3, Q12.7/Q18.6, Q18.4; `.ai/architecture/{converter,io-and-browsing,cache-store}.md`;
the follow-ups floor's handoff (`.ai/sessions/2026-10-29-claude-txy-followups/handoff.md`).

## Base and branch

Base `1d3bbb9` (`dev/v0.0.7`; with Q27.1, saved-result reuse off by default: tests that need it use the
`reuse_on` fixture). Branch `agent/txy-index`.

## Today (where to look)

- `helab/convert/provenance.py`: `Provenance` (raw fingerprint, profile hash, TXY name, size, SHA-256),
  `provenance_name`, `stale`, `beside_stale`, JSON (de)serialising. Qt-free and in `PURE`.
- `helab/io_ops/convert.py`: `FOLDER_RECORD = "folder.json"` (which source folder a `<hash>/` folder
  stands for; rewritten when it moved), the per-shot record read in the staleness check, written
  before the TXY in HeLab's folder (and for a beside conversion, only the record is there), removed
  on a failed write (by its SHA-256), and `own_partial()` (the record's and `folder.json`'s leftover
  temporaries).
- `helab/io_ops/helab_txy.py`: `_OWN_FILE`, `converted_usage`, `clear_converted` (Settings › Cache's
  Clear, Q12.3: keeps a beside TXY's record; a folder left with `folder.json` alone goes).
- `helab/views/CacheTab.py`: the "HeLab's converted TXY" row and its tooltip; `helab/convert_cli.py`.

## Objective

1. **`converted-txy/index.sqlite`** in each base (the cache folder's and the temp folder's
   `converted-txy/`): a `folders` table (hash → location key, source path, bytes, last used) and a
   `shots` table (the provenance rows: folder hash, tag, shot, raw size/mtime fingerprint, profile hash,
   TXY name, size, SHA-256, beside or not, written at). A schema version (`PRAGMA user_version`);
   say the journal mode you chose and why (the cache folder is local, but say what happens if it is
   not). Short transactions; a busy timeout; the helper and `helab convert` side by side stay safe
   (a test with two writers).
2. **The rules keep their meaning**: a shot is current exactly when it was before (the provenance
   row instead of the JSON); the row is written before the TXY's rename, and removed on a failed
   write only if it is still ours; a beside conversion's row stays when its TXY isn't in HeLab's
   folder; the folder's source path is updated when it moved.
3. **A missing, unreadable or damaged index only means shots convert again** (they are rebuildable):
   never an error the user must fix, never a crash. Say what HeLab does with a damaged file (proposed:
   set it aside under an exact name and start a new one; never delete it silently: it is HeLab's own
   file, so propose the housekeeping line and its exact pattern in your handoff if you remove it).
4. **No per-shot JSON or `folder.json` is written again.** Ones from tonight's builds: say how
   they're treated (proposed: ignored, still measured and cleared by Settings › Cache like the
   untagged files before Q18.4; never deleted otherwise).
5. **Settings › Cache** measures and clears through the index (`folders`: count, bytes, last used),
   still through a helper (the GUI never opens it), the Clear still asked first (Q12.3). The tooltip
   says what's there.
6. **Housekeeping** (`own_partial()` and AGENTS.md's list): the exact patterns change; SQLite's own
   `-wal`/`-shm`/`-journal` files are SQLite's, not housekeeping's. Propose AGENTS.md's wording.
7. The cache-folder move (`cache_move.py`): check that `converted-txy/` (and so the index) moves
   with it or say why it needn't; tests if it does.

## Rules

Owned paths: `helab/convert/provenance.py`, `helab/io_ops/convert.py`, `helab/io_ops/helab_txy.py`,
`helab/convert_cli.py`, the converted-TXY row in `helab/views/CacheTab.py`, their tests. Not the store,
`FolderCache`'s store code, or the converter's backends. A new module goes into `PURE` if Qt-free.
Keep your CacheTab change to the converted row (a byte-units floor, A26.1, may later edit its
`byte_size` calls), and ask CoCo before touching a file outside these paths.
Tests never touch real data (synthetic raw files; the private cache from conftest). Strict typing
(incl. `--platform win32`, `pyright --pythonplatform Windows`); the full suite inside and once outside
the checkout basetemp, every RERUN reported. Docs only in `.ai/sessions/2026-10-29-claude-txy-index/`
(proposals for converter.md, cache-store.md, io-and-browsing.md, AGENTS.md's housekeeping list and
code map; provisional `Q~`/`A~`/`M~`). Push when done; the landing needs a Reviewer with no open
findings and CI green on 3 OSes by run ID. No version bump, release, tag or PR.
