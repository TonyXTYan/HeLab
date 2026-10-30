# Brief: Quick Fixes 7, Codex's review of PR #10 (on Ground)

Coordinator: CoCo, 2026-10-31. Tony (Chat): "launch a quick fixer terminal on the ground floor to fix
then reply to codex for further review". Codex's automatic review of
[PR #10](https://github.com/TonyXTYan/HeLab/pull/10) (HeLab 0.0.7a1, head `release/v0.0.7a1` = `dev/v0.0.7`
`2960680` + the bump `a31edff`), review 5714055695, found three bugs in v0.0.7's new code. CoCo read each
against the code and all three look real. Fix them before the merge.

## Where you work: Ground, by Tony's explicit go

You run on **Ground** (`~/GitHub-Local/HeLab`, branch `dev/v0.0.7`), not a floor. Your role prompt says to stop
on Ground: Tony's go above overrides that for this brief only. Because Ground is shared:

- **Side (the Assistant) also works on Ground.** Before every commit, run `git status` and stage only the files
  you changed (`git add <path>`, never `-A` or `.`). Never stash, reset, check out over or discard anything you
  didn't change; if a file you need has someone else's uncommitted change, stop and ask CoCo.
- You may commit on `dev/v0.0.7` (Tony's go for these fixes): one commit per finding, plus this folder's notes and
  handoff. Push `dev/v0.0.7` once, at the end, after the full suite and type checks pass.
- No GUI launch is needed. `HELAB_*` overrides as `tests/conftest.py` sets them; tests never touch real data.

## Read first

`AGENTS.md` (I/O rules: "HeLab writes nothing into source folders except …", "Never modify raw `d*.txt` or an
existing TXY"; the converter rules; tests and typing); `.ai/architecture/converter.md` (write_atomic, beside
writes), `.ai/architecture/io-and-browsing.md` and `.ai/architecture/live.md` (Live saves, held shots,
signatures), `.ai/architecture/testing.md`.

## The three findings (Codex's text is on the PR; IDs are its comment IDs)

1. **P1, `helab/convert/txy.py` `_rename_new` (comment 4424923871).** `replace=False` (the beside writes) must
   never replace an existing TXY. Where `os.link` fails with an OSError other than FileExistsError (filesystems
   without hard links: FAT, and often macOS SMB mounts, i.e. the lab share), it checks `os.path.lexists` and then
   `os.rename`s: on macOS and Linux that rename silently overwrites a file another writer created in between
   (Windows' `os.rename` refuses an existing target, so it is safe there). Fix: an atomic no-replace rename where
   the OS has one (macOS `renamex_np(old, new, RENAME_EXCL)`; Linux `renameat2(AT_FDCWD, old, AT_FDCWD, new,
   RENAME_NOREPLACE)`, via `ctypes`, standard library only, `helab/convert/` stays Qt-free), and where neither works
   (unsupported by the filesystem or the libc) **refuse** rather than overwrite: say what the user sees then (the
   shot's conversion fails with a clear reason?) and whether that loses beside conversion on a filesystem HeLab
   wrote to before; propose it in the handoff if it's Tony's choice (`Q~1`). Windows keeps `os.rename`. Tests:
   the race (a file appearing between the check and the rename) is never overwritten, with `os.link` patched to
   fail as on such a filesystem; each fallback path; Windows behaviour by patching `convert.PLATFORM` or the
   module's own seam. Byte-for-byte output is unchanged.
2. **P2, `helab/io_ops/save_held.py` (comment 4424923880).** A held shot read from HeLab's TXY whose TXY has since
   gone (cleared, converted again) with no MATLAB TXY to fall back on is in `fingerprint` but not in `chosen`, so
   it has no `file_names` entry; line ~192 `names = [file_names[shot] for shot, _, _ in fingerprint]` raises
   KeyError and the whole Live save fails, including the save at quit. Fix: keep a name for such held shots (the
   one it was read from, from the held record) or handle its absence, so the save goes on and the shot counts as
   unsettled as the comment above `helab_off` intends. Test: a Live save whose held HeLab shot's TXY was removed
   saves the others and doesn't raise (fails on today's code).
3. **P2, `helab/io_ops/save_held.py` (comment 4424923889).** `_write_dataset(...)` isn't passed the `signature`
   computed just above it (`matlab_print`, which includes a shadowed MATLAB TXY), so `_write_dataset` recomputes
   it with `helab_txy.matlab_signature` and the saved cache's signature differs from the `loaded` event's: the tab
   can't match `cache_saved` and restored data looks out of date. Fix: pass `signature=signature`, as
   `loading.py`'s ordinary load does. Test: a held HeLab shot with a settled MATLAB TXY: the `loaded` event's
   signature equals the saved dataset's (fails on today's code).

Each test must fail on today's code (say so in the handoff). Smallest change; no refactors.

## Done means

- The touched tests pass; then the full suite (`pytest -n 12 --reruns 5 --reruns-delay 1
  --basetemp=.ai/temp/pytest-qf7`) and the five type checks (`mypy helab/ --strict`, `mypy tests --strict`,
  `mypy helab/ --strict --platform win32`, `pyright helab tests`, `pyright --pythonplatform Windows helab tests`),
  output kept whole; every RERUN reported with its reason.
- Commits on `dev/v0.0.7` (one per finding; the message says what, why, how checked, and the Codex comment ID),
  then `git push origin dev/v0.0.7`.
- `handoff.md` in this folder: what changed per finding, the tests and that they failed before, the checks, the
  pushed hash and its CI run ID, doc proposals (`converter.md`'s write_atomic paragraph; `live.md` if the held-shot
  rule changes) and provisional `Q~`/`A~`/`M~`. Don't edit `AGENTS.md`, `.ai/architecture/`, `roadmaps/` or the
  `.ai/*_TODO.md` lists; CoCo applies your proposals.
- Report back: `maestri ask "CoCo" "QF7 pushed at <hash>, CI <run id>; handoff in .ai/sessions/2026-10-31-claude-quick-fixes-7/handoff.md"`.
  CoCo then merges `dev/v0.0.7` into `release/v0.0.7a1`, replies to Codex on the PR and asks it to review again.
  You don't touch the PR or `release/v0.0.7a1`.

No version bump, release, tag or PR. Ask CoCo (`maestri ask "CoCo" "…"`) before any file outside
`helab/convert/txy.py`, `helab/io_ops/save_held.py`, their tests and this folder.

## Round 2: Codex's re-review (review 5714477187, on `e56d3d2`)

Codex accepted round 1 and found two more (both checked by CoCo against the code; both session-only: a
restart clears them). Same rules as above; also allowed: `helab/io_ops/convert.py`, `helab/utils/folder_cache.py`
and their tests (still ask before any other file).

4. **P2, `helab/io_ops/convert.py` ~line 568 (comment 4425255644).** For cache/temp output `there` is always true,
   so a shot in the folder's remembered `done`/`kept` lists (from `FolderCache.convert`'s `convert_lists`) is
   reported current without checking its TXY still exists. After Settings › Cache clears HeLab's converted TXY
   (or the destination setting changes), those shots aren't converted again for the rest of the session, even after
   Live off/on. Fix (your call, smallest that's right): validate that the TXY is still there for cache/temp too (the
   index/listing the run already reads), or drop `convert_lists` when HeLab's converted TXY are cleared or the
   output destination changes. Test: clear (or remove) the converted TXY, convert again: the shots convert.
5. **P2, `helab/utils/folder_cache.py` `convert()` ~line 1241 (comment 4425255663).** `skip` (the unconvertible
   list) is sent whatever the profile, while `done`/`kept` are only for the same profile. A raw file unconvertible
   under one profile (e.g. damaged because its trigger channel differs from that profile's) is never retried after
   the user picks a corrected profile. Fix: reuse unconvertible entries only for the same profile (or keep
   profile-independent failures, if any, apart: say which in the handoff); mind the "damaged: said once" rule (a
   retry under a new profile may notify again: say what the user sees). Test: unconvertible under profile A, then
   profile B: retried.

Commit each on `dev/v0.0.7` (message names the Codex comment ID), full suite + five type checks, push once, add a
"Round 2" section to `handoff.md` (and any doc proposals), then report back:
`maestri ask "CoCo" "QF7 round 2 pushed at <hash>, CI <run id>"`.

## Round 3: Codex's third review (review 5714741098, on `c7859b8`)

Codex accepted round 2 and found one more (CoCo checked it against the code). Same rules; also allowed:
`helab/io_ops/live.py`, `helab/io_ops/helab_txy.py` (only if needed) and their tests.

6. **P2, `helab/io_ops/live.py` ~line 186 and `helab/io_ops/save_held.py`'s same call (comment 4425456506).**
   `held_origins` holds only HeLab-origin shots, so `helab_txy.compose(..., held_origins)` gives `choose()` no
   sign that a shot is held **from MATLAB**. Under `helab-priority` (the default), a shot Live holds from MATLAB's
   TXY switches to a HeLab TXY converted later (auto-convert, cache or beside); the check then compares that file
   with the held MATLAB fingerprint and sends `shots_missing(reason="changed")`, stopping Live when the shot isn't
   in the recent-reread set, though the MATLAB file is unchanged. Fix as Codex suggests if it holds: pass an origin
   for every held shot (`""` for MATLAB) so `choose()`'s held-kind rule keeps it, in both calls; check that
   nothing else reads `held_origins` as "HeLab shots only" (`held_helab`, `trusted`, `kept_origins`,
   `could_take`) and keep those as they are. Tests: one held MATLAB shot, then a current HeLab TXY of it appears:
   Live's check and a Live save keep the MATLAB one, no mismatch (fails on today's code). Say in the handoff when
   the held shot does move to HeLab's TXY (e.g. a load, Live off and on), so a user still gets HeLab's in the end.

Commit on `dev/v0.0.7` (message names comment 4425456506), full suite + five type checks, push once, a "Round 3"
section in `handoff.md`, then report back: `maestri ask "CoCo" "QF7 round 3 pushed at <hash>, CI <run id>"`.

## Round 4: Codex's fourth review (review 5714936123, on `fb40034`)

Codex accepted round 3 and found one more, next to round 2's item 5. Same rules and files as round 2.

7. **P2, `helab/utils/folder_cache.py` `convert()` (comment 4425610377).** `seen` (the waiting list) is sent
   whatever the profile. A raw file waiting with a profile-dependent reason (e.g. `not_trigger_first`) when the
   user picks a corrected profile keeps that reason: `convert_folder()` rebuilds `unfinished` from `seen` and skips
   `raw.not_done()` for unchanged files, so the shot keeps waiting, becomes damaged under the corrected profile and
   is then skipped. Fix: like item 5, reuse the waiting history only for the same profile (or keep only the
   fingerprint, without profile-dependent reasons); say which in the handoff, and what it does to the
   "taken as finished only after two conversions saw it unchanged" rule on a profile change. Test: a file waiting
   with `not_trigger_first` under profile A, then profile B (the right trigger): it converts (fails on today's
   code). Check the other remembered list fields (anything else profile-dependent?) and say so.

Commit on `dev/v0.0.7` (message names comment 4425610377), full suite + five type checks, push once, a "Round 4"
section in `handoff.md`, then report back: `maestri ask "CoCo" "QF7 round 4 pushed at <hash>, CI <run id>"`.

## Round 5: Codex's fifth review (review 5715183970, on `b836b56`)

Codex accepted round 4 and found two more in `helab/io_ops/loading.py` (CoCo checked the second against the code;
check the first yourself before fixing: if it can't happen, say why in the handoff and in the reply). Also allowed:
`helab/io_ops/loading.py`, `helab/utils/folder_cache.py` and their tests.

8. **P1, `loading.py` cached quick check (comment 4425801677).** Dataset signatures describe only the folder's MATLAB
   TXY, so when **another HeLab instance** converts shots this one holds from MATLAB and saves the dataset with HeLab
   origins, `base_signature` is unchanged; the quick check validates the newer disk row against the files but never
   compares its fingerprints/origins with the RAM base, and `memory_shots` makes `FolderCache` reuse the MATLAB arrays
   while adopting the cached HeLab fingerprints and origins (data labelled HeLab-origin that is MATLAB's; with a
   non-matlab-2019 profile the arrays genuinely differ). Fix: before the shortcut, compare the held fingerprints and
   `memory_origins` with the cached dataset's; on any difference, don't reuse RAM for those shots. Test: two-instance
   scenario simulated (RAM base from MATLAB, disk row updated with HeLab origins): the shots are read, not reused.
9. **P2, `loading.py` `stop_if_missing` (comment 4425801688).** `listed` comes from the source-filtered `chosen`, so
   after Settings › TXY converter › "Tabs and Live read" → HeLab only, cached MATLAB-origin shots without a current
   HeLab TXY count as deleted and the load stops with `shots_missing` (a mismatch hold), though their MATLAB files are
   still there. Fix: check missing shots against the unfiltered listing (MATLAB TXY that exist), so a shot merely left
   out by the source mode isn't "missing"; the load gives the HeLab subset. Say what the user sees then (counts,
   the source line). Test: cached MATLAB shots, switch to helab-only with HeLab TXY for some: loads that subset, no
   `shots_missing` (fails on today's code).

Commit each (messages name the comment IDs), full suite + five type checks, read **every** job log of the CI run you
report (RERUNs with reasons), push once, a "Round 5" section in `handoff.md`, then report back:
`maestri ask "CoCo" "QF7 round 5 pushed at <hash>, CI <run id>"`.
