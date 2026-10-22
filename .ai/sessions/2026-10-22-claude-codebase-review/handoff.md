# Codebase review: handoff

Floor "Codebase Review", branch `agent/codebase-review` from `fc0f50d` (`dev/v0.0.6`), with
dev/v0.0.6 merged in at `4ca1f9f` (CI Robustness, `51c0ee2`) and `17ad7e1` (its CI fix, `23e922f`). Reviewer Lens (Claude Fable 5.1):
[findings.md](findings.md). Worker Mend (Claude Opus 5.5): [notes.md](notes.md), which has each
finding's detail. Brief: [brief.md](brief.md).

## Summary

The review covered all five areas of the brief and found 22 issues: no blocker or high, 2 medium,
14 low and 6 quality (as each finding's heading in `findings.md` grades it; R-22 came with R-1's
review). 21 are fixed in full and R-10 in part (two long functions declined, reasons in the
notes). The five items first held for Tony (R-1, R-11, R-13, R-16, R-19) were done after his yes
on 2026-10-22, R-13 and R-15's last part after CoCo landed the CI floor, and then Tony's two later
decisions: R-22 (keep the settle rule; warn that the clocks are out of sync, and stop Live) and
per-instance log files for R-11; and, at CoCo's word, R-12's `HeLab.spec` entry and R-20's
requirements change, which were proposals before.
Every correctness fix has a test that fails without it and passes with it, except two: a log-only
guard (R-11's Live warning) and the comma fix (R-21), whose list value doesn't change. Lens reviewed
and accepted every commit.

Final checks at `ccce741` (floor root, `floor-env.sh`, the default basetemp as CI uses, joblib
uninstalled): `pytest -n 4 --reruns 5 --reruns-delay 1 -rR`: 2462 passed, 2 skipped, 2 xfailed,
**no RERUN**; `mypy helab/ --strict` (152 files), `mypy tests --strict` (113 files), `pyright helab
tests`: clean.
CI on `17ad7e1` (run 39718624587): green on macOS, Ubuntu and Windows, no RERUN; the run before it
(39716589995, `44ad4eb`) failed one CI-floor test that dev/v0.0.6 had too, fixed by `23e922f`. Baseline at
`fc0f50d`: 2378 passed, no RERUN. Full runs that had a RERUN, each a real failure fixed before its
commit: the first run of areas 4–5 (`test_typing` after R-19's first commit, fixed in `e4b1712`),
and two runs before R-16's commit (`test_typing` on a test's `markers.os` patch, and
`test_helper_dispatch`'s routing table lacking `marker_save`).

## Outcomes

| ID | Sev. | Outcome | Commits |
|---|---|---|---|
| R-1 quick check compares the share's clock with this PC's | medium | Fixed (Tony's yes) | `4468eaf` |
| R-2 a Live save's data dump runs under the no-progress timer | medium | Fixed | `265f35e` |
| R-3 frozen reader can miss a helper's last lines | low | Fixed | `6299fdd` |
| R-4 roots-table reads raise raw sqlite errors and fail a listing | low | Fixed | `af632a3` |
| R-5 store-open failures reported as "Mount information is unavailable" | low | Fixed | `2447a66` |
| R-6 a pending root stays pending after its duplicate is gone | low | Fixed | `d586f9d` |
| R-7 a scan's new signature cancels the folder's running jobs | low | Fixed (confirmed by test first) | `2559c77` |
| R-8 a crashing helper leaves no cause in the log | low | Fixed | `34bcb78` |
| R-9 details scan stats each subfolder a second time | low | Fixed | `6ddec21` |
| R-10 `_on_event` and `_load` too long | quality | Part (three handlers lifted; rest declined, reasons in notes) | `f684720` |
| R-11 no excepthook; unguarded source timestamps | low | Fixed: guards, then excepthook and log file, one file per HeLab (Tony's yes) | `e4d3f2d`, `1efcb87`, `752c638` |
| R-12 window icon looked up from the launch folder | low | Fixed, and bundled by `HeLab.spec` and in wheels | `fbb072f`, `4c9f2a8`, and the wheel commit after `1ff3c72` |
| R-13 Settings placeholders, WARNING on close, unused imports | low | Fixed: placeholders removed (Tony's yes) | `aad0ad4`, `c7eb0a3` |
| R-14 `StatusReport` legacy fields, import-time default | quality | Fixed | `305f19a` |
| R-15 unused/star imports, commented-out code, long functions | quality | Fixed, long functions declined | `f410ccb`, `0406507` |
| R-16 manual marker saved on the GUI thread | low | Fixed: through a helper (Tony's yes) | `c4cf63c` |
| R-17 a script hook that raises when its plot opens ends HeLab | low | Fixed | `c530e7f` |
| R-18 Scripts panel leftover state, stale docstrings | quality | Fixed | `324ae2a` |
| R-19 DLD Transfer fractions duplicates the shared order helpers | quality | Fixed, with the Reference spacing (Tony's yes) | `f7d06e6`, `e4b1712`, `6fac7df` |
| R-20 private joblib import never used | low | Fixed; joblib dropped from the requirements | `a1b75b2`, `ccce741` |
| R-21 dead code, two unused modules, probe log lines, a missing comma | quality | Fixed, except `synchronised_dict.py`: restored (Tony kept it on 2026-10-21) | `60a8a99`, `a1b75b2`, `89531cc`, restore: `b68f6b1` |
| R-22 a server clock ahead holds new shots as still being written | low | Rule kept (Tony); clocks-out-of-sync warning and Live stop added | `cdc255f`, `bf05b59` |

Also: the dev/v0.0.6 merges `4ca1f9f` and `17ad7e1`; `22ee3fb` (a test-order fix in the CI floor's
`tests/test_settings_defaults.py`, which failed 3 tests when run in one process after
test_settingsDialog.py, from before this branch). Notes and findings commits: `2180d56`, `e266925`,
`db2cc14`, `bcf7afd`, `66d33d9`, `f4d3772`, `4019e17`, `44ad4eb`, `6d1f327` and this handoff's.

## Questions for Tony

1. **Old log files** (R-11). Each HeLab now writes `<app folder>/logs/helab-<pid>.log` (rotated at
   2 MB, 4 older files), so every session leaves its own files and nothing removes them: HeLab has
   no rule that deletes anything without the user asking, and none was built. Proposed, in the
   manner of Help › Record I/O trace's "Delete old traces" question: Help › Show log folder; and at
   startup, when earlier sessions' logs (pids with no live instance lock in `instances/`) pass,
   say, 50 MB or 30 days, ask once "Delete old log files?" (Delete / Keep, Keep the default; Keep
   lasts the session). Lens: process IDs come round again, so a later HeLab with an old one appends
   to that `helab-<pid>.log`; a rule by age should go by each file's mtime, not its name. Approve, or
   another rule?
2. **R-20's lock refresh.** `requirements.lock` was refreshed with the README's command without
   `--upgrade` (`uv pip compile requirements.txt --universal --python-version 3.13 -o
   requirements.lock`, over the existing lock), so it drops only joblib and cloudpickle. With
   `--upgrade` it would also move `python-dateutil` 2.9.0.post0 → 3.0.0, `pyinstaller-hooks-contrib`,
   `setuptools`, `zipp` and `tzdata`'s markers: a separate dependency update, if wanted.
3. **Wording and UI added here, for a look** (all approved in substance; say if any should read
   differently):
   - R-11: the status bar's "Unexpected error, logged: <type>: <message>"; the log files
     `<app folder>/logs/helab-<pid>.log` (macOS `~/Library/Caches/HeLab/logs/`, Windows
     `%LOCALAPPDATA%\HeLab\logs\`), INFO and up, 2 MB × 5 files per HeLab.
   - R-22: the warning window "Computer clocks out of sync" (macOS shows no title): "Files in
     <folder> are dated <skew> ahead of this computer's clock: this computer's clock and the clock of
     the computer or server holding the folder are out of sync.", with "HeLab treats files dated in
     the future as still being written, so it doesn't read them until this computer's clock catches
     up, and Live stops on them. Set both computers to set their time automatically, then Retry.";
     the skew as "4 s", "2 min 5 s", "1 h 3 min", "2 d 5 h"; and Live's amber line "Live stopped:
     the folder's new files are dated <skew> ahead of this computer's clock: the computers' clocks
     are out of sync".
   - R-16: "Couldn't save <file>: HeLab is quitting." (save refused while quitting) and "stopped"
     as the reason for a cancelled save; the activity labels "Save .helab-root to folder",
     ".helab-root save", "Saving .helab-root".
   - R-13: the General tab's 10 px gap above "When selecting another folder:" went with the
     placeholders.
   - R-19, in the DLD port's Transfer fractions: the new setting Orders › Reference spacing (15 ms)
     and its tooltip (Basic plots v1's), the Orders tooltip ("the clear side peaks near multiples of
     the reference spacing"), the settings line "auto orders ±2 ~15 ms" and the no-side-peak note
     ("… within 30 % of k × the reference spacing (15 ms): spacing as set").

## Behaviour changes to know about

- R-1: the quick check of cached (or RAM-held) data now skips the listing only while the folder's
  mtime is exactly the one its last listing saw, so a share whose clock is behind no longer hides
  new shots, and one ahead no longer forces a listing every time. A folder modified within 2 s of
  its listing is listed again at its next check; so is a folder after each Live save (Live saves
  don't stat the folder). Caches saved by an older HeLab keep the old rule until their next full
  listing.
- R-11: an unhandled exception no longer ends HeLab: it is logged, with its traceback, to the
  console and the session's own log file, and the status bar says so.
- R-22: when a load, scan, Live check or Live save finds a folder's files dated more than 2 s ahead
  of this computer's clock, a warning names the folder and the skew, once per share or volume per
  session; such files still aren't read (the rule is unchanged), and Live stops on them as on an
  error (data kept, Retry).
- R-16: Save to folder… is off the GUI thread; the button is disabled until the save ends, and
  Replace is asked after the helper finds the file there.
- R-13: a saved `example_checkbox` / `example_text` is removed the next time settings are saved.
- R-19: the DLD port's auto orders take ±k only near k reference spacings, like Basic plots v1; its
  version is 3, so earlier results aren't reused.
- R-6: a pending root location whose other locations have all been forgotten is now confirmed by its
  next listing (no question asked) and uses the UUID's cached data.
- R-7: when a status check or details scan finds a folder changed, the folder's datasets are dropped,
  but running loads, Live checks and cached reads go on (before: "Cancelled — Retry", Live halted). A
  `loaded` event from before the change is still discarded by its signature check.
- R-5: a store that can't be opened now says "Disk cache could not be opened: …" once, not wrapped
  in "Mount information is unavailable".
- R-17: a plot whose script fails while it opens shows "<name> failed: …" in its dock or the status
  bar instead of ending HeLab.
- R-21: the log no longer starts with six probe lines (an ERROR and a CRITICAL among them).

## Open risks

- R-1 residual (agreed with Lens): with a server clock more than 2 s off ours, a change in the same
  mtime step right after a listing (FAT and some shares keep 2 s) isn't seen until the folder's
  next change (the next shot) or a Retry / Refresh.
- R-11: old sessions' log files accumulate until a removal rule is decided (question 1).
- R-22: only TXY files' mtimes are compared (a load's, scan's, Live check's or save's); raw
  `d<N>.txt` files and the folder's own mtime aren't, as they come from the same server clock. A
  skew of 2–5 s gives the warning while files still settle after 5 s more of our clock.
- R-16 (nit): the dialog's owner key `marker-save:<id(self)>` could be reused by a later dialog
  while an old save still runs; a counter wouldn't. Negligible.
- R-2: every Live autosave (each 10 shots) and Live off still writes the whole held dataset to the
  temp folder and the helper reads it back (by design); it no longer times out, but its cost grows
  with the dataset.
- R-3: the reader change runs only in the frozen build (its test fakes the process); not yet seen
  in a packaged app.
- R-6: the behaviour change hasn't been tried on a real duplicate root.
- R-12: the packaged app bundles `ai-icon.icns` (seen in a local macOS build; CI builds all three
  OSes), and so does a wheel (`setup.py` `package_data`, by name: the unused `Beatunes.icns` stays out).
- The DEBUG level of `coloredlogs.install` (`main.py`) is unchanged.

## Proposed doc changes (for the Coordinator)

**AGENTS.md**
- Responsive filesystem I/O, cache-first rule: replace "When the cache has no unsettled files and
  the folder is not modified since the cache's file list (`snapshot_at`)" with "When the cache has no
  unsettled files and the folder's mtime is exactly the one stat'ed just before the cache's listing
  (`info["folder_mtime_ns"]`; None when within `RACY_SECONDS` = 2 s of the listing, and after a Live
  save; caches without it compare `snapshot_at`)", and add that `memory_check` carries the same
  value (`fingerprints._mtime_unchanged`).
- Responsive filesystem I/O, after "Daemon reader threads deliver results…": "A helper's stderr goes
  to `stderr.txt` in its private folder; when it exits without `done` or `error`, the last 2 KB are
  logged with the operation and path. Writing a Live save's held arrays to that folder counts as
  progress for the no-progress timer."
- Running or Architecture: "Each HeLab logs to `<app folder>/logs/helab-<pid>.log` (INFO up, rotated
  at 2 MB, 4 older files; nothing deletes old sessions' files yet) and logs an unhandled exception with its traceback and carries on, with a
  status-bar note (`helab/utils/app_log.py`, started first in `main()`); tests never write the app
  folder."
- Responsive filesystem I/O, "Files still being written": "A file dated more than
  `fingerprints.FUTURE_SECONDS` (2 s) ahead of this computer's clock is still being written, and the
  helper sends `clock_skew` (folder, seconds, its share or volume); `FolderCache.clockSkew` passes it
  on once per location per session to `ClockSkewWarning` (and `helab.utils.events`, `CLOCK_SKEW`). A
  Live check whose new files are ahead fails, so Live stops as on an error (R-22, Tony 2026-10-22)."
- Data roots › Placing one: "`ManualMarkerDialog`'s Save to folder… writes through the `marker_save`
  helper (foreground, like `root_create`)."
- Data roots › Duplicates, after "…a forgotten or removed location (`root_changed` with its location)
  settle it.": "A pending location whose other locations have all been forgotten is confirmed by its
  next listing."
- Caching or the I/O queue rules (where `FolderCache` signatures are described): "A status check or
  details scan that finds a folder's signature changed drops its datasets (`_folder_changed`) but
  leaves its running load, Live check and cached read; only a clear (`_invalidate_data`) cancels them."
- Browsing (`details` step): "Subfolder dates come from the listing's entries (`_entry_stat(...,
  follow_symlinks=False)`: no call per subfolder on Windows)."
- Script system: "A script hook that raises while its plot opens (`live_policy`, `constant_keys`,
  `parameters`, `backends`, `minimum_size`) is logged and shown as '<name> failed: …' (status bar or
  dock); HeLab goes on."
- Script system, Transfer fractions: "(in Basic plots v1, order ±k is the most prominent clear peak
  …)" becomes "(in both groups, order ±k is the most prominent clear peak …)", and "the DLD port's in
  ms with a Mask and the same highlight" gains "and the same detection (`orders.detect`, Reference
  spacing in ms)".

**roadmaps/known-issues.md**
- Open: old sessions' log files accumulate (R-11), until a removal rule is decided.
- Open: R-1's residual (clock off > 2 s plus a change in the same mtime step after a listing).
- Fixed (this branch), with their commits: R-1, R-2, R-3, R-4, R-5, R-6, R-7, R-8, R-11 (excepthook,
  log file per HeLab), R-12 (icon looked up beside the package and bundled by `HeLab.spec`), R-16,
  R-17, R-20 (joblib gone from the code, requirements and lock), R-22 (the clocks-out-of-sync warning
  and Live stop; the settle rule kept); and the settings-defaults test-order failure (`22ee3fb`).

**.ai/memory/results/folder-io-queue.md**
- The quick check's rule (exact folder mtime, the 2 s margin, a listing after each Live save).
- The R-7 behaviour, if the memory describes a status check cancelling a running load.


## Lens's sign-off

Lens reviewed every fix commit by diff and accepted them with no changes asked: area 1
(`265f35e..f684720`), areas 2–3 (`c530e7f..f410ccb`), areas 4–5 (`f7d06e6`, `e4b1712`, `60a8a99`,
`a1b75b2`, `89531cc`), the restore `b68f6b1`, the held items (R-1 `4468eaf`, R-11 `1efcb87`, R-16
`c4cf63c`, R-13 `c7eb0a3`, R-15 `0406507` with `22ee3fb`, R-19 `6fac7df`), the merges `4ca1f9f` and
`17ad7e1`, and Tony's later items: R-22 `cdc255f` with its test nits `bf05b59`, R-11's log names
`752c638`, R-12 `4c9f2a8` and R-20 `ccce741` (records in `findings.md`; Lens checked several
fail-before claims in a scratch worktree). Lens reruns the full suite with `-rR`, strict mypy and
pyright on the final head before the push.

## Tony's answers (2026-10-22, after his check of the app)

Both floors landed (Lens's last findings note: merge `c13b225`). Question 3's wording is approved
as is. Question 1 wasn't answered: the old-log rule stays an open item in
[known issues](../../../roadmaps/known-issues.md), not built. Question 2 (the `--upgrade` lock
refresh) is undecided.

## Follow-up: old log files (2026-10-22, brief `brief-old-logs.md`)

Built in `fed0fae` on `agent/codebase-review` from `ae72673`, by Tony's rule (question 1 above, now
answered):

- Rotation within a session: 1 MB per file, 10 older files (`app_log.LOG_BYTES`, `LOG_BACKUPS`).
- **Settings → General → Log files to keep** (`log_files_keep`, default 300, 1 to 100,000; a row in
  `settings_defaults.py`, read untyped by `constants.read_log_keep`). It counts every session's
  `helab-<pid>.log` files, rotated copies included. At startup HeLab deletes the oldest by mtime
  beyond it (`app_log.tidy_logs`).
- If the logs left pass 50 MB, HeLab asks once per session "Log files use X MB. Delete old ones?"
  (Delete / Keep; Keep is the default and Escape button and lasts the session). Delete removes the
  oldest until the total is under 20 MB (`app_log.trim_logs`).
- **Help › Show log folder**: a detached reveal of `<app folder>/logs`.
- Never deleted: a running HeLab's files (live instance lock: `cache_locks.other_instances`; this
  process's pid). Files go oldest first by mtime, never by name. A file that can't be deleted is
  skipped and logged at INFO.
- The scan and the deletes run on a daemon thread of their own (`helab/views/OldLogs.py`), started by
  `main` once the window is shown and this instance holds its lock. Results come back through queued
  signals.

**One addition beyond the brief, for Lens to judge:** a file modified within the last 60 s is never
deleted either (`app_log.STARTING_SECONDS`). A HeLab starting up writes its log (`main`, first line)
before it takes its instance lock in `_start_cache`, so for that moment its files look ended. That
moment can be long if it is waiting out another HeLab's cache move and logging nothing; the guard
covers only the usual case.

**New wording, for Tony's read:**
- The question's window title is "HeLab" (macOS doesn't show it); the buttons are "Delete" and
  "Keep". X is whole binary MB (MiB, like the 1 MB rotation).
- Setting label: "Log files to keep:". Tooltip: "Each HeLab writes its own log file, renamed and
  started again every 1 MB. At startup HeLab deletes the oldest log files beyond this number, every
  session's counted, never a running HeLab's. Help › Show log folder shows them."
- After Delete nothing is shown; one INFO line logs "Deleted N old log file(s), X MB". A status-bar
  note could follow if wanted.

**Checks:** `pytest -n 12 --reruns 5 --reruns-delay 1 -rR`: 2474 passed, 2 skipped, 2 xfailed, **no
RERUN**. `mypy helab/ --strict` (154 files), `mypy tests --strict` and `pyright helab tests` are
clean. The new tests fail before `fed0fae`: `OldLogs` and the setting don't exist, and the rotation
constants differ.

**Proposed doc changes (for the Coordinator).** My role doesn't edit these; text ready to apply:

- `AGENTS.md`, Running paragraph: replace "(INFO and up, rotated at 2 MB, 4 older files; macOS
  `~/Library/Caches/HeLab/logs/`, Windows `%LOCALAPPDATA%\HeLab\logs\`)" with "(INFO and up, rotated
  at 1 MB, 10 older files; macOS `~/Library/Caches/HeLab/logs/`, Windows `%LOCALAPPDATA%\HeLab\logs\`;
  Help › Show log folder)". Replace "Nothing deletes old sessions' files." with: "At startup, off the
  GUI thread (`helab/views/OldLogs.py`), HeLab deletes the oldest log files by mtime beyond Settings
  → General → Log files to keep (default 300, every session's files and rotated copies counted);
  past 50 MB left it asks once per session "Log files use X MB. Delete old ones?" (Keep the default,
  for the session; Delete goes under 20 MB). Never a running HeLab's files (live instance locks, this
  pid) or one modified in the last minute; one that can't be deleted is skipped and logged
  (`app_log.tidy_logs`, `trim_logs`)."
- `AGENTS.md`, Architecture › Threading: after "the single analysis worker thread (`AnalysisRunner`)…",
  add "and the short-lived startup thread that tidies old log files (`OldLogs`)".
- `roadmaps/known-issues.md`: move "Old log files pile up" to Fixed: "Old log files pile up
  (2026-10-22, R-11): fixed in `fed0fae`: 1 MB × 10 rotation, Settings → General → Log files to keep
  (300) at startup, the 50 MB question down to under 20 MB, Help › Show log folder."
