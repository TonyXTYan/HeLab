# Caching v2 / store-v4: readiness for an unattended supervised run

2026-10-29, Side's subagent (claude), read-only on `dev/v0.0.7` at `311a356` with Ground's
uncommitted docs (and an uncommitted `helab/utils/settings_defaults.py`, Q27.1). No code run, no
tests run, no repo file changed except this one. Citations are `file:line` on that tree; "design"
is [`store-v4-design.md`](../2026-10-29-claude-caching-audit/store-v4-design.md), "plan" is
[`roadmaps/caching-v2.md`](../../../roadmaps/caching-v2.md).

## Verdict

**Not ready today; ready for stage 0 + stage 1 after 8 fixes (below), with stage 2 kept for a
second run after Tony has seen stage 1.** The approved non-cache floors (Q26.2's index, A26.1's
units) could run unattended now, once Tony starts a mandate.

The 8 fixes:

1. Tony's go, naming the stages (D1).
2. The branch decision (D2).
3. Store-v4 behind a switch that is off by default (D3).
4. Q27.2's provenance fields in the schema (D4).
5. Make room's order and the case of a full store-v3 (D8, D9).
6. The design note amended: the zstd 9 codec, and gaps 2–5 and 7 in §3.
7. Q26.2 and A26.1 landed first.
8. Ground committed and clean.

Why not today:

- There's no go yet. The plan says "planning only: no cache code until Tony's explicit go" and
  "each [stage] needs Tony's go" (plan:3-4, 134; DECISIONS_TODO:259-260; roadmap
  `_readme.md:50-52`). A mandate can't give that go. Tony has to name the stages himself.
- The branch isn't settled (§2). The plan assumes v0.0.7 is released first, and `dev/v0.0.7`
  is the branch Tony and the lab's source checkouts run.
- The design has a build-order hole. Store-v4 drops `datasets` (design:56), but `txy_layers`
  only arrive in stage 2 (design:417-419). If stage 1 lands as the live store, dataset caching
  stops working until stage 2 lands.
- Q27.2's versioning is a direction with nothing designed yet (DECISIONS_TODO:326-329). Once
  store-v4 rows exist on a user's disk they are hard to change, so the provenance fields have
  to be in the stage 1 schema.
- Ground isn't clean. Eight docs are modified and `settings_defaults.py` has Q27.1 work in it.
  The landing conditions need `git status --short` to print nothing (maestri-setup.md, §6).

## 1. Blocking decisions

| # | Item (doc line) | Blocks | Proposed default the Assistant could take "for Tony to confirm" |
|---|---|---|---|
| D1 | **Go, and for which stages.** plan:3-4, 134 ("each needs Tony's go"); A19.1 and A19.2 are on hold for the same go (AI_TODO A19.1/A19.2; plan:136-137) | everything | **Must wait for Tony.** Proposed: stage 0 (A19.1 and A19.2 folded into the Q26.2 floor) and stage 1 only |
| D2 | **Branch** (§2). AGENTS.md:225; app-versioning.md:180-199 (squash, abandon the dev branch, next branch from `main`) | everything | **Must wait for Tony** (creating a branch line and a version bump are his) |
| D3 | **Store-v4 inert until stage 2.** Not in the plan or design. Needed because of the `datasets` gap above, and because Tony's Mac and the lab PCs run source checkouts | stage 1 | Build store-v4 behind a switch that is off by default (e.g. `HELAB_STORE_V4=1` or a hidden settings row). Store-v3 stays the live store until stage 2 lands and Tony turns it on. Reversible |
| D4 | **Q27.2, the minimum for the schema.** plan:120-122 lists "version, commit and modified flag, the machine, and the environment". Undecided: what "machine" is (hostname, or a random id in the app folder), where the fields live (columns or a JSON `made_by`), and the format-version field of every file (plan:126-130) | stage 1 schema | One additive `made_by TEXT NOT NULL DEFAULT '{}'` on `raw_layers`, `txy_layers`, `results`, and the same object in every `.hlb` header: `{helab_version, commit, modified, frozen, machine_id (random UUID in the app folder), hostname, python, numpy, scipy, blosc, backend}`. A `format` integer in `.hlb` and in v4 `meta`. Recorded only, never a key in stage 1 |
| D5 | **Dev builds say `.devN`** (plan:117-119). This contradicts AGENTS.md:225 ("the version bump goes on the PR branch") and is a version bump | release flow | **Must wait for Tony** (the mandate forbids version bumps, maestri-setup.md:712). Not needed for stage 1 |
| D6 | **Result reuse by release or clean commit; a modified checkout neither reuses nor saves "(or keeps its results apart)"** (plan:123-125). Two options are left open. Q27.1 (DECISIONS_TODO:317-325) is still "Proposed" and is being built uncommitted on Ground | results; not stage 1 | Leave it out of the run. Record `made_by` only (D4) |
| D7 | **Q19.3 vs the "raw" policy.** Q19.3 says every TXY source a plot uses is cached as its own layer (DECISIONS_TODO:175-176; plan:61). Design §6 says `raw` writes no HeLab layer (design:368), and plan:69-70 calls raw + tag "the default once the converter is robust". So what is today's default? | stage 2 | Default policy: raw + every layer a plot uses (Q19.3). "Raw only" is an explicit non-default choice. Stage 2 decides this, so it doesn't block stage 1 |
| D8 | **Make room's first group calls every TXY layer "rebuildable from the raw layer locally"** (design:343; plan:72-73, 108-109). The `matlab` layer and `txy`-policy layers can't be rebuilt from raw (design:194-196) | stage 1 (Make room order is in stage 1, design:415-416) | Order: HeLab layers (rebuildable locally) → `matlab`/`txy` layers whose source file the last listing saw → raw layers seen → only-copy layers of any kind last, named in the dialog |
| D9 | **Keep with a full store-v3.** Keep is the default before the user chooses (Q22.3), and v3's bytes count in v4's budget (design:310-313). A user with ~6 GB in v3 then hits the 80 % pause at once, and Make room can't remove v3 rows (v3 is read-only) | stage 1 | Make room's dialog offers "Clear store-v3…" (asked, with its size) as a row when v3 is counted. The 80 % pause message names store-v3 |
| D10 | **Q22.5's "big warning"** for an overwritten raw file (DECISIONS_TODO:164-166). Its form isn't defined, and stage 1's `raw_fill` already meets changed fingerprints | stage 1 (raw_fill) | A system notification (`events.notify`), once per shot per session, plus an amber Folder details line and a log line. Live goes on |
| D11 | **Q12.3, the separate converted-TXY budget:** its default size and what happens when it's full (DECISIONS_TODO:229-233). Q19.2's "Proposed: yes, counted" (DECISIONS_TODO:272-274) is stale against it | stage 3/4 | Not needed for stages 0–2. Fix the stale line |
| D12 | **Q19.1, to confirm** (DECISIONS_TODO:262-269; plan:153-154) | stage 3 | Not needed for stages 0–2 |
| D13 | **The v0.0.7 release:** smoke pass M1.1–M1.10, Q23.1 tags frozen (DECISIONS_TODO:364-365), the bump, the PR (`_readme.md:46-49`) | D2 option (a) | **Tony's** |

Settled, but the design note still says otherwise (a builder would follow the wrong text):

- **Raw codec:** Q22.7 decided zstd 9 + byte shuffle (DECISIONS_TODO:169-170, 296-305). The
  design still says zstd 5 (design:19-20, 145-147) and that zstd 9 costs "16× the encode time"
  (~27 MB/s of raw text). Fix the note, and have stage 1 measure the encode cost on the Sandy
  Bridge lab PC's class of CPU (`raw_fill` and Live autosave pay it).
- **Units:** Q26.1 (OS-aware) replaces AGENTS.md:189 ("every byte size shown is SI"), but only
  when A26.1 lands. Store-v4's new size labels should go through A26.1's helper, so A26.1 lands
  first.
- The design's Q~1–Q~10 (design:427-452) are now Q22.1–Q22.10. Line 3/8 still says the Q18.2/Q18.4
  code is unlanded (it landed in `c718c71`). `helab_txy.py` changed 164 lines since `aa84e77`, so
  re-check its line references.

## 2. Sequencing

- **What the docs say:** caching v2 comes after v0.0.7. The plan's horizon is "after v0.0.7's
  converter" (plan:3). The roadmap says "v0.0.7 covers its planning only" (`_readme.md:50-52`).
  Q26.2's index goes in "before v0.0.7's release ... caching v2 later moves the provenance into
  the store's `txy_layers`" (DECISIONS_TODO:340-343). The release flow squash-merges a dev branch
  into `main`, abandons it, and starts the next one from `main` (app-versioning.md:180-199).
  `origin/main` (`9c477c2`) is an ancestor of `dev/v0.0.7`, so this is the flow in use.
- **Never land caching v2 into `dev/v0.0.7`.** It would hold the release back behind a store
  rewrite, put a half-built store-v4 into Tony's source checkout and the lab PCs' checkouts
  (memory: lab PCs run uv source venvs), and make the v0.0.7 PR huge.
- **Safest (a):** Tony releases v0.0.7 (D13), then `dev/v0.0.8` is branched from `main` after
  the squash, with its first commit setting the version (Tony's; `0.0.8.dev0` if D5 says so).
  Caching floors land there.
- **If Tony wants it before the release (b):** an integration branch, e.g. `dev/caching-v2`, cut
  from `dev/v0.0.7` once Q26.2 and A26.1 have landed. Floors branch from it and land into it.
  After v0.0.7's squash it moves with `git rebase --onto origin/main dev/v0.0.7 dev/caching-v2`
  (clean, since the squash has the same tree). The mandate has to restate the landing
  conditions for that branch: maestri-setup.md:644 and AGENTS.md:41 name `dev/v0.0.7`. Creating
  the branch is Tony's call.
- Either way, the floors before caching v2 need to land first: **Q26.2** (approved,
  DECISIONS_TODO:182-183) rewrites `io_ops/convert.py` and `helab_txy.py`, which stage 1 also
  edits (raw rows from `convert`, design:226). **A26.1** (approved, DECISIONS_TODO:184-189)
  touches ~67 size calls, including `CacheTab`/`CacheDialogs`, which stage 1's store-v3 dialog
  and Settings rows also edit.

## 3. Design gaps (not specific enough to build without questions)

1. **Build order vs `datasets`** (design:56, 412-419). Without D3, stage 1 alone loses dataset
   caching. With D3, say whether v3 or v4 is live per switch state, and that the switch flips
   only after stage 2.
2. **`pending_saves` keeps `UNIQUE (path)`** (design:54). `raw_fill`, a load's save and Live's
   `save_held` can each leave a pending unit for one folder, and a second one would replace the
   first. Proposed: unique on (path, unit kind), or merge the parts.
3. **`raw_fill` granularity.** "One save unit per job ... one transaction with one budget check"
   (design:251-252). For a 1,000-shot folder that means holding everything to the end, losing it
   all on a kill, and a pending unit listing 1,000 files. It also doesn't say how pause and resume
   or `job_seq` work across batches. Proposed: commit every N shots or M bytes, each batch its
   own unit, resuming from the rows already saved. Lane: it shares the one background slot
   (io-and-browsing.md:16) with scans and saves, so give it a yield rule.
4. **The `.hlb` container** (design:123-129) doesn't define: byte order (explicit `<i8`), header
   size limit, the format-version field vs the magic `HLB1`, a per-chunk checksum (Blosc 1 has
   none), how deltas cross a 64 MB chunk boundary, per-array typesize for shuffle, or the atomic
   write (temporary name, fsync, rename). Needs D4's `made_by` in `meta`.
5. **Reading store-v3 without adding files.** The design uses `mode=ro` (design:286-290) and
   tests that "no file is added" to v3 (design:399-400). `cache_move.py:120-122` notes that a
   read-only open of a WAL database fails without its `-shm` file, which is why it uses
   `query_only` there. SQLite may also create `-wal`/`-shm` beside v3. Proposed: the test hashes
   `records.sqlite` and the data files and allows only SQLite's `-wal`/`-shm`. Opening with
   `immutable=1` is unsafe while an older HeLab writes v3.
6. **Cache move with two stores.** `cache_move.verify` and `store_id_at` know only v3's tables and
   `LAYOUT_VERSION` (`cache_move.py:131-145, 162-163`), so they need v4's (`raw_layers`,
   `txy_segments`, results) and v3 kept as an unverified passenger. The design only says the whole
   folder moves (design:283-285).
7. **Clear and inventory for raw from day one.** Raw rows fill the budget from stage 1
   (design:415-416), but Clear by kind "Raw pulses" and the Settings rows are listed under stage 4
   (design:264-268, 424-425). Stage 1 needs at least the admin Clear plus a Settings › Cache row,
   or the user's only way back to space is Make room.
8. **Budget under Keep** (design:310-313): `legacy_bytes` is measured "at inventory". When is it
   re-measured, given an older HeLab may still be writing v3? Proposed: at each startup inventory
   and after any v3 change by `writes`. Also: does a decoded raw layer count in the RAM budget
   while it converts (`ram_buffers`)? Unspecified.
9. **Who opens the store.** AGENTS.md:165-166 names `store-v3`/`CacheStore` and AGENTS.md:172
   names `store-v3` for `_migrate`. `LegacyStore` must also be helper-only. The housekeeping line
   AGENTS.md:176 changes wording (design:356-359). The Coordinator applies these at landing, as
   wording "for Tony to confirm". **No new removal rule**, and that is a stop condition (§4).
10. **Stage 2 ambiguities**, not stage 1: the `txy`-policy layer keyed by TXY file fingerprint
    with `by_txy` "in `info`" (design:370). Is that per layer or per shot, given one
    `(path, layer)` row? And is the per-folder "source priority" (Q22.11) the existing Q18.2
    source mode or a new `cache_policy.tag` (design:95-98)? These look like two settings for one
    choice.
11. **Distributed identity** (Q27.2): a raw fingerprint is (size, mtime_ns), and mtime resolution
    differs between SMB clients on macOS and Windows. Results "made elsewhere" may then never match.
    The design already stores `sha256` (design:66). Say whether cross-machine matching uses it.
    Not stage 1.

## 4. Risk to user data (stages 0–2)

- **Source folders:** `raw_fill` and `convert` only read raw files, and the write rule is
  unchanged (AGENTS.md write rule; Q12.4). Tests stay under `HELAB_TEST_SOURCE_GUARD`
  (testing.md:11). **Trap:** the `--via-layer` sample check (design:388) must run encode and decode
  in memory. Writing layers through the store would need a `.helab-root` in `~/HeLab-samples`,
  which is writing to the samples and is forbidden.
- **The real cache folder** (`~/Library/Caches/HeLab`, the lab PCs' caches) is the main risk.
  Floors are isolated by `floor-env.sh` (`HELAB_DIR_CACHES_OVERRIDE`, app folder and settings
  file; maestri-setup.md:402-450), and tests use `private_store`. But any `helab` started without
  that env, or from Ground after a landing, creates store-v4 in the real cache, imports user
  state and shows the v3 question. D3's switch plus a "never run HeLab from Ground during the
  run" rule covers this. Before any real-app run, a worker shows that `HELAB_DIR_CACHES_OVERRIDE`
  is set.
- **store-v3** must only ever be opened by `LegacyStore`. Any `CacheStore(...)` on v3's path in
  the new code would `makedirs` it and run `_migrate` (design:286-288). Needs a test that fails on
  any v3 open except `LegacyStore`, using the I/O trace or a patched `CacheStore`.
- **Keep out of the unattended run:** running `clear_legacy` or Make room against any real cache
  (building and testing them in temp stores is fine); a cache move of a real cache; any new
  automatic removal or housekeeping line (design:361-362 rules it out); any change to the 8 GB
  budget or its units outside A26.1; turning the store-v4 switch on by default; version bumps,
  branch creation from `main`, PRs; Q27.1's `result_reuse` change (being done on Ground);
  AGENTS.md rule changes beyond D9's wording (as "to confirm").
- **Settings:** a new global-policy row goes in `settings_defaults.py` through `read_setting`
  (AGENTS.md settings rule). Tests use their own ini.

## 5. Proposed floors for an unattended run

The previous run's lessons, built in: land only on green CI on all three OSes, checked by run ID
(mandate:278, Q24.4); keep the suite's output whole (mandate:277); Claude Reviewers only
(mandate:96-100, Q24.1); write the seams between floors into the briefs up front, with an
integration check at the end (mandate:275, 287); **at most 3 floors running at once**, since load
28–30 failed tests (mandate:291); a heartbeat that nudges when nothing has landed for an hour
(mandate:288); watch Windows CI time (mandate:303).

**Phase A (approved, not cache code; can run before Tony's caching go), on `dev/v0.0.7`, in parallel:**

- **F1 `agent/txy-index`** (Q26.2): `converted-txy/index.sqlite`. Plus A19.1 and A19.2 if D1
  includes stage 0, since they rewrite the same `converted_usage`/`clear_converted`. Small to
  medium.
- **F2 `agent/byte-units`** (A26.1): `byte_size(n, kind)`, budgets and minimums. Small to medium,
  but wide (15 modules).

**Phase B (stage 1), on the branch D2 picks, behind D3's switch:**

1. **F3 `agent/v4-hlb-raw`** (Qt-free, PURE list): the `.hlb` container and the raw encoder and
   decoder (`i8-i64d-1`, `f64-1`, facts, zstd 9), the layer-equals-file tests and the fuzz set
   (design:381-388), and `--via-layer` in memory. Medium. Can start with F4.
2. **F4 `agent/v4-store-core`**: store-v4 with the carried-over tables, layout 4, `meta`
   (`store_id`, `legacy_v3`, `legacy_bytes`, `format`, D4's `made_by`), v4's `_migrate`, the
   `LegacyStore` read-only reader and its guard test, the one-time import of user state (Q22.4),
   Keep-before-choice reads of records and results, and `cache_move` verify for both stores.
   Large; the critical path.
3. After F3 + F4, in parallel:
   - **F5 `agent/v4-raw-layer`**: the `raw_layers` table, save units (gaps 2–3), guards and
     `job_seq`, Make room's order (D8, D9), the sweep and `_known_files` for `raw/`, the
     `raw_fill` helper op, events and `FolderCache` scheduling (background lane, pausable,
     refused offline and for Don't cache or no data root), raw rows from `convert`, the admin
     Clear for raw, and D10's warning. Large.
   - **F6 `agent/v4-legacy-ui`**: the store-v3 question (CacheDialogs), the Settings › Cache rows
     for store-v3 (Keep / Ignore / Clear…) and raw pulses (size, Clear), `clear_legacy` with the
     instance-lock check, and `removed` kinds `raw` and `legacy`. Medium. F6 owns `helab/views`;
     F5 owns `cache_store`/`io_ops`/`folder_cache`.
4. **Integration check** (Coordinator or a small floor), switch on, in temp stores: load → raw_fill
   → layer equals file → Clear → Make room order → v3 files unchanged (gap 5), and a cache move
   with both stores.

Rough size: stage 1 is 4 floors and about the scale of the converter's stage 4 (4 floors, ~6 h
overnight). `cache_store.py` (2,673 lines) and `folder_cache.py` (4,198) are the hotspots, and 16
test files call `start_dataset_job`/`save_dataset`.

**Stage 2 (F7 `txy_layers` + segments + loading order + identity + v3 `matlab` seed; F8 Live
segments + compaction) waits for a second run**, after Tony has used stage 1 with the switch on
and answered D7 and gap 10.

**Stop conditions** (stop that piece and wait for Tony):

- any design question not covered by D3–D10's defaults, or one that changes an on-disk format
  beyond the design plus D4;
- any write, `-wal` aside, to a store-v3 folder outside a temp store, or any HeLab run without
  the floor's cache override;
- a failing test after one cause hunt; any RERUN without a cause;
- a Windows test group over ~25 of its 30 minutes (raise it, don't change limits);
- a floor needing AGENTS.md rule changes beyond wording;
- the switch needing to default on;
- account or rate limits stalling agents (report and pause).

## 6. What Tony must answer before starting

1. **D1:** the go, and for which stages. Proposed: stage 0 (A19.1/A19.2 inside Q26.2's floor) and
   stage 1; stage 2 in a later run.
2. **D2:** release v0.0.7 first and build on `dev/v0.0.8` from `main` (safest), or now on an
   integration branch (`dev/caching-v2` from `dev/v0.0.7`, rebased after the squash). Never into
   `dev/v0.0.7`.
3. **D3:** store-v4 behind a switch that stays off until stage 2 and his go.
4. **D4:** the provenance fields in the stage 1 schema, and machine identity: a random id in the
   app folder plus hostname, or something else.
5. **D8 / D9:** Make room's order with `matlab` layers not rebuildable from raw, and offering
   "Clear store-v3…" in Make room under Keep.
6. **D10:** the form of Q22.5's "big warning".
7. **Start the mandate** (only Tony can, maestri-setup.md:707) with Ground committed first.

D5–D7 and D11–D13 can wait: D7 until stage 2, D11–D12 until stage 3, D5–D6 and D13 until release
work. The doc fixes (codec, stale IDs and branch note, Q19.2's stale line) the Assistant can make
on Ground with Tony's OK to commit.
