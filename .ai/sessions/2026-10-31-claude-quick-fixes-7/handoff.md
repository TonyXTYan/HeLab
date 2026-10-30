# Quick Fixes 7: handoff (Rivet → CoCo)

Codex's review 5714055695 of PR #10: three findings fixed on Ground, `dev/v0.0.7`, from `2960680`, one
commit each. Detail (cause, evidence, what the user sees) in `notes.md`.

| Finding | Commit | Files |
|---|---|---|
| P1 4424923871, `txy._rename_new` replaced a file written meanwhile | `c194f37` | `helab/convert/txy.py`, `tests/test_convert_helab.py` |
| P2 4424923880, `save_held` KeyError for a held HeLab shot whose TXY went | `4222b3f` | `helab/io_ops/save_held.py`, `tests/test_txy_sources.py` |
| P2 4424923889, `save_held` didn't pass its signature to `_write_dataset` | `a7dac90` | `helab/io_ops/save_held.py`, `tests/test_txy_sources.py` |

## What changed

1. **No-replace rename.** After a failed `os.link`: Windows `os.rename` (refuses an existing name);
   macOS `renamex_np(RENAME_EXCL)`, Linux `renameat2(AT_FDCWD, …, RENAME_NOREPLACE)` via ctypes
   (`txy._exclusive_rename(platform)`, cached; `txy.PLATFORM` the seam). EEXIST → `FileExistsError` (as
   before, `shot_kept`). No call in the C library, or EINVAL/ENOSYS/ENOTSUP/EOPNOTSUPP → **refused**:
   `OSError(ENOTSUP, "Not written: this folder's file system can't add a file without risking replacing
   one already there (no hard links, and <reason>)")`, nothing left behind. Other errnos raised as they
   are. Byte output unchanged.
   *What the user sees on refusal:* the conversion run fails with that message (it isn't
   FileExistsError or a path too long, so `convert_folder` raises): auto-convert stops with the amber
   line and Retry, Live goes on; `helab convert` prints it; nothing is written to the source folder.
   *Lost beside conversion where it worked before?* Not on macOS FAT: on a scratch FAT32 image here
   `os.link` is ENOTSUP and `renamex_np(RENAME_EXCL)` refuses an existing name and renames onto a new one.
   Not on Linux's local file systems (ext4, btrfs, xfs, tmpfs, vfat support NOREPLACE; glibc 2.28+).
   **Unknown for the lab's SMB share** (M~1).
2. **Held HeLab shot with no TXY now.** It keeps the name its TXY would have beside the raw file
   (`provenance.txy_name(profile_tag, shot)`); the save goes on and the shot counts as unsettled (as the
   `helab_off` comment intended), so the next quick check is a full one.
3. **Signature.** `_write_dataset(..., signature=signature)`, as `loading.py` does.

## Tests (each fails on `2960680`, passes now)

- `test_convert_helab.py`: `test_without_links_a_file_written_meanwhile_is_never_replaced` (old code: `DID NOT RAISE
  FileExistsError`, the other writer's file replaced); `test_the_refusing_rename_is_the_oss_own` (real call;
  skipped on Windows); `test_without_links_or_a_refusing_rename_nothing_is_written` (×5: no call, EINVAL,
  ENOSYS, ENOTSUP, EOPNOTSUPP); `test_the_refusing_renames_other_answers` (EEXIST, EACCES);
  `test_on_windows_without_links_its_rename_refuses`; `test_a_beside_conversion_that_cant_add_a_file_safely_fails_with_why`.
  The seam tests fail on the old code with AttributeError (no `PLATFORM` / `_exclusive_rename`); the race
  test is the behavioural one.
- `test_txy_sources.py`: `test_a_live_save_whose_held_helab_txy_went_saves_the_rest` (old: `KeyError: 3`);
  `test_a_live_saves_dataset_has_the_signature_it_sent` (old: stored `89490808…` ≠ sent `7ea4d6ce…`).

## Checks (on the tree at `a7dac90`)

- `pytest -n 12 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-qf7`: **8503 passed, 672 skipped,
  2 warnings in 79.84s; no RERUN.** (Warnings: pyqtgraph's NumPy 2.5 `arr.shape` DeprecationWarning in
  `test_t_spectrum.py`, unrelated.) Log: `.ai/temp/qf7-suite.log`.
- `mypy helab/ --strict`: no issues in 195 files; `mypy tests --strict`: no issues in 175;
  `mypy helab/ --strict --platform win32`: no issues in 195; `pyright helab tests` and
  `pyright --pythonplatform Windows helab tests`: 0 errors, 0 warnings.

## Pushed

`dev/v0.0.7` pushed with the fixes (`c194f37`..`a7dac90`) and this session's commit on top (its hash and
the CI run ID are in the report to CoCo: this file is committed before the push, so they can't be in it).

## Doc proposals (for CoCo)

- `converter.md`, "In HeLab (stage 4)" sentence "`txy.write_atomic(replace=False)` never replaces an
  existing file (HeLab's writes beside raw files)" → append: "a hard link, else the OS's no-replace rename
  (macOS `renamex_np(RENAME_EXCL)`, Linux `renameat2(RENAME_NOREPLACE)`, through ctypes; Windows' `os.rename`
  refuses an existing name itself), never a check then a rename; where neither works (no such call, or
  EINVAL/ENOSYS/ENOTSUP/EOPNOTSUPP) the write is refused (`OSError` ENOTSUP, 'Not written: this folder's
  file system can't add a file without risking replacing one already there …') and the conversion fails
  with that reason (`txy.PLATFORM` is the seam; Codex on PR #10)."
- `live.md`: no rule change; optionally, after "a background save writes the folder from RAM (…)": "a held
  HeLab shot whose TXY has gone is saved as held and counts as unsettled (named as its beside TXY would
  be); the saved dataset carries the signature `loaded` sent (`folder_print`'s)."
- `known-issues.md`: nothing new unless Q~1 keeps the refusal, then: "Beside conversion fails on a file
  system with neither hard links nor a no-replace rename (Q~1; M~1 for the lab share)".

## Provisional items

- **Q~1** (Tony): beside conversion where the file system can't add a file without risking a
  replacement. (a) **Proposed:** keep the refusal as built: the run fails with the reason, auto-convert
  stops (amber, Retry). (b) Make it per shot: `shot_unconvertible` with the reason, not tried again while
  the raw file is unchanged, as for a path too long (needs `io_ops/convert.py`). (c) Fall back to HeLab's
  cache/temp folder for that run, saying so in the plan (as `convert_plan`'s `fallback` does when the
  folder's flag is off). (b) or (c) only if M~1 shows the lab share needs it.
- **M~1** (Tony, on the Mac with the lab share mounted): in a scratch folder on the share (not a data
  folder), run the probe in `notes.md` §1 (`python3 -I probe.py <scratch folder>`): it reports whether
  `os.link` works and whether `renamex_np(RENAME_EXCL)` refuses an existing name and renames onto a new
  one, then leaves files `a`, `b`, `c` to delete. If neither works there, beside conversion on the share
  from macOS now fails with the reason (Q~1). Windows PCs are unaffected (`os.rename` refuses itself).
- **A~1** (optional): Codex's three findings had no test because `save_held`'s HeLab-TXY paths had none for
  "TXY gone" and "shadowed MATLAB TXY settled"; a short audit of `live.py`'s matching paths (same
  `file_names`/signature shapes) could look for the same two gaps.

# Round 2 (Codex's re-review 5714477187 on `e56d3d2`)

Detail in `notes.md` (Round 2). Round 1's CI run **41078799066 passed on every job** (macOS, Windows,
Ubuntu: Tests 1/2 and 2/2, Build, Converter backends).

| Finding | Commit | Files |
|---|---|---|
| P2 4425255644, done/kept shots current without their TXY (cache/temp) | `b069c1f` | `helab/io_ops/convert.py`, `tests/test_convert_helab.py` |
| P2 4425255663, `skip` sent whatever the profile | `d5da485` | `helab/utils/folder_cache.py`, `tests/test_live_convert.py` |

4. When done or kept shots are sent back and the output is the cache or temp folder, one local listing of
   HeLab's folder for the output (`_txy_shots`) says which have this tag's TXY; one without goes through the
   ordinary check and converts again. That covers TXY cleared from Settings › Cache, deleted by hand, and a
   change of destination. Beside is unchanged.
5. `skip` only with the same profile, as `done`/`kept`. No unconvertible reason is profile-independent
   except an empty raw file (cheap to read again), so nothing is kept apart. User-visible: under a new
   profile the file waits one tick, then is read; still damaged, it is listed as damaged again on the Live
   line and in Folder details, with **no second notification** (keyed by path, name, size, mtime).

**Tests (fail on `51cd8c4`, pass now):** `test_done_shots_whose_txy_went_convert_again` (`[] == [1, 2]`);
`test_a_file_unconvertible_under_one_profile_is_tried_under_another` (`[] == [4]`);
`test_the_lists_of_the_last_conversion_are_sent_back` updated (it asserted `skip` under another profile).

**Checks:** full suite -n 12: 8505 passed, 672 skipped, no RERUN; five type checks clean.

**Pushed:** `dev/v0.0.7` with `b069c1f`, `d5da485` and this session commit on top (hash and CI run in the
report to CoCo).

**Doc proposals:**
- `converter.md` table row `done`, `kept`, `skip` → "the previous summary's `current`, `kept`,
  `unconvertible`, sent back (`FolderCache.convert`, all three only for the same profile): not checked again
  while unchanged; a done or kept shot only while its TXY is there (beside: the source listing; cache or
  temp: one listing of HeLab's folder for the output)".
- `live.md` Auto-convert: "(`seen`/`done`/`kept`/`skip`; `done`/`kept` only for the same profile)" →
  "(`seen`/`done`/`kept`/`skip`; `done`/`kept`/`skip` only for the same profile: a file unconvertible under
  one is read again under another, its damaged notification not repeated)".

No new Q~/M~/A~ items.
