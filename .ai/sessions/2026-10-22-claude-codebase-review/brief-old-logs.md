# Follow-up brief: old log files (R-11 follow-up)

Tony's decision (2026-10-22, via Quill), replacing the open item "Old log files pile up" in
`roadmaps/known-issues.md`. Mend builds, Lens reviews. Branch `agent/codebase-review`, base
`ae72673` (dev/v0.0.6's head; the floor was fast-forwarded to it). Land as a follow-up merge.

## What to build

1. **Rotation within a session, fixed in code** (`helab/utils/app_log.py`): `LOG_BYTES` = 1 MB
   (easier on a log viewer), `LOG_BACKUPS` = 10.
2. **Settings → General → "Log files to keep"**: a user setting, default 300. It counts every
   `helab-*.log*` file across all sessions, rotated copies included. At startup HeLab deletes the
   oldest files (by mtime) beyond that number, never a running HeLab's files (live instance locks
   in `<app folder>/instances/`, `helab/utils/cache_locks.py`: `other_instances`, and this
   process's own pid). The setting counts as the user asking. Add it to
   `helab/utils/settings_defaults.py` and read it through `read_setting` (untyped number).
3. **At startup, past 50 MB**: if the remaining logs total more than 50 MB, ask once per session
   "Log files use X MB. Delete old ones?" Delete removes the oldest (by mtime, not a running
   HeLab's) until the total is under 20 MB. Keep is the default button and lasts the session.
4. **Help › Show log folder**: a detached reveal, like Help › Show I/O trace folder.
5. Deletion and the folder scan run **off the GUI thread** (the log folder is local, in the app
   folder, but keep it out of rendering and startup's GUI path). Process IDs come round again, so
   go by each file's mtime, never its name. A file that can't be deleted (Windows: open by another
   process) is skipped and logged, not an error.

## Tests and docs

- Tests: rotation constants; the count rule (oldest first by mtime, rotated copies counted,
  running instances' and this process's files kept); the 50 MB question's Delete (down to under
  20 MB) and Keep (once per session); the setting's default and its row in the defaults table;
  the menu action; nothing deleted on the GUI thread. Use temp app folders
  (`HELAB_APP_DIR_OVERRIDE`); never touch the real log folder.
- Docs: AGENTS.md's Running paragraph (replace "Nothing deletes old sessions' files" and the
  2 MB / 4 files figures); `roadmaps/known-issues.md` (move the open item to Fixed with the
  commits); a findings/handoff note. Wording is Tony's above; propose anything new in your
  handoff rather than inventing it.
- Before handing off: full suite with `-n 12 --reruns 5 --reruns-delay 1 -rR` (report any RERUN
  with its reason), strict mypy on `helab/` and `tests`, pyright `helab tests`. Commit on the
  branch; push once when Lens accepts.
