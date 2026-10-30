# Quick Fixes 7: notes (Rivet, Claude Code, on Ground by Tony's go)

Brief: `brief.md` (CoCo). Codex's review 5714055695 of PR #10. Base `dev/v0.0.7` `2960680`.

## 1. P1 `txy._rename_new` replaced a file written meanwhile (comment 4424923871)

**Cause.** `write_atomic(replace=False)` (beside writes) used `os.link` to add the TXY without replacing.
Where links fail with an OSError other than EEXIST (FAT, many SMB mounts), it checked `os.path.lexists`
and then called `os.rename`, which on macOS and Linux replaces an existing target. A file another writer
made between the check and the rename was silently overwritten.

**Evidence.** The new test `test_without_links_a_file_written_meanwhile_is_never_replaced` (link refused,
the other writer's file made at that moment, and a check that misses it) fails on `2960680`'s `txy.py`
with `DID NOT RAISE FileExistsError`: the other file was replaced. On a scratch FAT32 disk image on this
Mac (hdiutil, msdos/fskit; no real data), `os.link` gives `[Errno 45] Operation not supported`;
`renamex_np(old, new, RENAME_EXCL)` returns -1/EEXIST over an existing file (left unchanged) and 0 onto a
new name.

The probe (run with a scratch folder as its argument; it writes `a`, `b`, `c` there):

```python
import ctypes, errno, os, sys
d = sys.argv[1]
a, b, c = (os.path.join(d, n) for n in ("a", "b", "c"))
for p in (a, b): open(p, "wb").write(p[-1].encode())
try:
    os.link(a, c); print("link ok"); os.unlink(c)
except OSError as e: print("link:", e)
libc = ctypes.CDLL(None, use_errno=True)
f = libc.renamex_np; f.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
r = f(a.encode(), b.encode(), 4); print("excl over existing:", r, errno.errorcode.get(ctypes.get_errno()), open(b,'rb').read())
r = f(a.encode(), c.encode(), 4); print("excl to new:", r, errno.errorcode.get(ctypes.get_errno()), os.path.exists(c), os.path.exists(a))
```

On FAT32 here: `link: [Errno 45] Operation not supported`, `excl over existing: -1 EEXIST b'b'`,
`excl to new: 0 … True False` (a successful call leaves errno as it was).

**Fix.** Where the link fails: Windows keeps `os.rename` (MoveFileEx without replace refuses an existing
name; the redundant check is gone); macOS and Linux call the OS's atomic no-replace rename through ctypes
(`renamex_np(RENAME_EXCL)`, `renameat2(AT_FDCWD, …, RENAME_NOREPLACE)`; `_exclusive_rename(platform)`,
cached). EEXIST → `FileExistsError` (as before: `io_ops.convert` sends `shot_kept`). Where the C library
has neither call, or it answers EINVAL/ENOSYS/ENOTSUP/EOPNOTSUPP (the file system or kernel can't), the
write is **refused**: `OSError(ENOTSUP, "Not written: this folder's file system can't add a file without
risking replacing one already there (no hard links, and <reason>)", target)`, temporary removed. Other
errors are raised as they are. `txy.PLATFORM` (read at call time) is the test seam. Byte output unchanged
(only the rename changed). `helab/convert/` stays standard library + NumPy, Qt-free.

**What the user sees on refusal.** The OSError leaves `convert_folder` (it isn't FileExistsError or a
path too long), so the conversion fails with that message: for Live's auto-convert the amber line with
Retry and auto-convert stops (live.md: "A conversion's error … stops auto-convert, not Live"); `helab
convert` prints it. Nothing is written to the source folder. It is tried again at the next run, failing
the same way. See Q~1.

**Does it lose beside conversion where HeLab wrote before?** Not on macOS FAT (checked above), nor on
Linux local file systems (renameat2 NOREPLACE: ext4, btrfs, xfs, tmpfs, vfat… since 3.15–4.9; glibc
2.28+). Unknown for the lab's SMB share from macOS (smbfs) and Linux (cifs): M~1.

**Tests** (`tests/test_convert_helab.py`): the race; the real OS call refuses an existing name and
renames to a new one (skipped on Windows); no call / EINVAL / ENOSYS / ENOTSUP / EOPNOTSUPP → refused,
nothing written, `os.rename` never called; EEXIST → FileExistsError, EACCES → PermissionError; Windows
(`PLATFORM = "win32"`, a Windows-like `os.rename`) uses `os.rename` and refuses an existing file; a beside
conversion that can't add a file safely fails with the reason and leaves the source folder unchanged.

**Proposed known-issues line:** none (fixed). If Q~1 keeps the refusal: "Beside conversion fails on a
file system with neither hard links nor a no-replace rename (Q~1; M~1 for the lab share)".

## 2. P2 `save_held` KeyError for a held HeLab shot whose TXY went (comment 4424923880)

**Cause.** A held shot read from HeLab's TXY whose TXY has since gone (cleared, converted again) with no
MATLAB TXY is in `fingerprint` (and `helab_off`) but not in `chosen`, so not in `file_names`;
`names = [file_names[shot] …]` raised KeyError and the whole save failed, the save at quit too.

**Fix.** Such a shot keeps the name its TXY would have beside the raw file
(`provenance.txy_name(<record's or request's profile_tag>, shot)`). The quick check's sample finds that
name gone or changed, and `unsettled` already makes the next check a full one, as the comment above
`helab_off` intends.

**Test** (`tests/test_txy_sources.py::test_a_live_save_whose_held_helab_txy_went_saves_the_rest`): fails
on `2960680` with `KeyError: 3`; passes now. Shots 1–4 saved, unsettled 2, names for every shot (the
store's `names` too).

## 3. P2 `save_held`'s saved signature differs from its `loaded` event's (comment 4424923889)

**Cause.** `_write_dataset` wasn't passed the `signature` computed from `helab_txy.folder_print` (which
counts a settled MATLAB TXY shadowed by a held HeLab shot), so it recomputed `matlab_signature` without
it; the tab couldn't match `cache_saved`, and the restored data looked out of date.

**Fix.** `signature=signature`, as `loading.py`'s load passes its summary's.

**Test** (`test_a_live_saves_dataset_has_the_signature_it_sent`): a settled MATLAB TXY of held HeLab
shot 3; the stored signature equals `loaded`'s. Fails on `2960680` (`89490808… != 7ea4d6ce…`); passes now.
