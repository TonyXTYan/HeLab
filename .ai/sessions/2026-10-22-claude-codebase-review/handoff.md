# Codebase review: handoff

Floor "Codebase Review", branch `agent/codebase-review` from `fc0f50d` (`dev/v0.0.6`), with
dev/v0.0.6 merged in at `4ca1f9f` (CI Robustness, `51c0ee2`). Reviewer Lens (Claude Fable 5.1):
[findings.md](findings.md). Worker Mend (Claude Opus 5.5): [notes.md](notes.md), which has each
finding's detail. Brief: [brief.md](brief.md).

## Summary

The review covered all five areas of the brief and found 22 issues: no blocker or high, 2 medium,
14 low and 6 quality (as each finding's heading in `findings.md` grades it; R-22 came with R-1's
review). 20 are fixed in full and R-10 in part (two long functions declined, reasons in the
notes); R-22 needs Tony. The five items first held for Tony (R-1, R-11, R-13, R-16, R-19) were
done after his yes on 2026-10-22, and R-13 and R-15's last part after CoCo landed the CI floor.
Every correctness fix has a test that fails without it and passes with it, except two: a log-only
guard (R-11's Live warning) and the comma fix (R-21), whose list value doesn't change. Lens reviewed
and accepted every commit.

Final checks at `6fac7df` (floor root, `floor-env.sh`): `pytest -n 4 --reruns 5 --reruns-delay 1
-rR --basetemp=.ai/temp/pytest`: 2450 passed, 2 skipped, 2 xfailed, **no RERUN**; `mypy helab/
--strict` (151 files), `mypy tests --strict` (111 files), `pyright helab tests`: clean. Baseline at
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
| R-11 no excepthook; unguarded source timestamps | low | Fixed: guards, then excepthook and log file (Tony's yes) | `e4d3f2d`, `1efcb87` |
| R-12 window icon looked up from the launch folder | low | Fixed | `fbb072f` |
| R-13 Settings placeholders, WARNING on close, unused imports | low | Fixed: placeholders removed (Tony's yes) | `aad0ad4`, `c7eb0a3` |
| R-14 `StatusReport` legacy fields, import-time default | quality | Fixed | `305f19a` |
| R-15 unused/star imports, commented-out code, long functions | quality | Fixed, long functions declined | `f410ccb`, `0406507` |
| R-16 manual marker saved on the GUI thread | low | Fixed: through a helper (Tony's yes) | `c4cf63c` |
| R-17 a script hook that raises when its plot opens ends HeLab | low | Fixed | `c530e7f` |
| R-18 Scripts panel leftover state, stale docstrings | quality | Fixed | `324ae2a` |
| R-19 DLD Transfer fractions duplicates the shared order helpers | quality | Fixed, with the Reference spacing (Tony's yes) | `f7d06e6`, `e4b1712`, `6fac7df` |
| R-20 private joblib import never used | low | Fixed | `a1b75b2` |
| R-21 dead code, two unused modules, probe log lines, a missing comma | quality | Fixed, except `synchronised_dict.py`: restored (Tony kept it on 2026-10-21) | `60a8a99`, `a1b75b2`, `89531cc`, restore: `b68f6b1` |
| R-22 a server clock ahead holds new shots as still being written | low | **Needs Tony** (Lens, with R-1's review) | — |

Also: the dev/v0.0.6 merge `4ca1f9f`; `22ee3fb` (a test-order fix in the CI floor's
`tests/test_settings_defaults.py`, which failed 3 tests when run in one process after
test_settingsDialog.py, from before this branch). Notes and findings commits: `2180d56`, `e266925`,
`db2cc14`, `bcf7afd`, `66d33d9`, `f4d3772`, `4019e17` and this handoff's.

## Questions for Tony

1. **R-22** (low). `_settled` counts a file with an mtime in the future (by this PC's clock) as
   still being written, so a server clock more than 5 s (`SETTLE_SECONDS`) ahead holds every new
   shot back for the whole skew, in loads, scans, Live and saves; a folder whose shots are all that
   young fails with "TXY files are still being written — Retry". Possible rules: a file more than
   `SETTLE_SECONDS` ahead of our clock counts as settled (the change-while-read and Live's `seen`
   checks still guard it), or ages measured against the folder's own mtime (the server's clock).
   Change the rule?
2. **Wording and UI added here, for a look** (all approved in substance; say if any should read
   differently):
   - R-11: the status bar's "Unexpected error, logged: <type>: <message>"; the log file
     `<app folder>/logs/helab.log` (macOS `~/Library/Caches/HeLab/logs/`, Windows
     `%LOCALAPPDATA%\HeLab\logs\`), INFO and up, 2 MB × 5 files.
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
  console and the log file, and the status bar says so.
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
- R-11: two HeLabs share `helab.log`. Past 2 MB on Windows, the instance that loses the rollover
  drops its records and prints a traceback to stderr for each; on macOS/Linux the other keeps
  writing into `helab.log.1`. A per-instance name (`helab-<pid>.log`) avoids both; the file's name
  and place are Tony's call.
- R-16 (nit): the dialog's owner key `marker-save:<id(self)>` could be reused by a later dialog
  while an old save still runs; a counter wouldn't. Negligible.
- R-2: every Live autosave (each 10 shots) and Live off still writes the whole held dataset to the
  temp folder and the helper reads it back (by design); it no longer times out, but its cost grows
  with the dataset.
- R-3: the reader change runs only in the frozen build (its test fakes the process); not yet seen
  in a packaged app.
- R-6: the behaviour change hasn't been tried on a real duplicate root.
- R-12: `HeLab.spec`'s `datas` doesn't bundle `ai-icon.icns`, so the packaged app still logs "Icon
  file not found" (the bundle has its own icon). Add it to `datas`, or skip the check when frozen.
- R-20: joblib now has no importer in `helab/` (`requirements*` were off-limits here).
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
- Running or Architecture: "HeLab logs to `<app folder>/logs/helab.log` (INFO up, rotated at 2 MB,
  4 older files) and logs an unhandled exception with its traceback and carries on, with a
  status-bar note (`helab/utils/app_log.py`, started first in `main()`); tests never write the app
  folder."
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
- Open: R-22 (a server clock ahead holds new shots as still being written), until Tony decides.
- Open: two HeLabs sharing `helab.log` (R-11), until Tony decides on the name.
- Open: R-1's residual (clock off > 2 s plus a change in the same mtime step after a listing).
- Open: the packaged app lacks `ai-icon.icns` (R-12, `HeLab.spec` datas).
- Open: joblib is in `requirements.txt` with no importer left (R-20).
- Fixed (this branch): R-1, R-2, R-3, R-4, R-5, R-6, R-7, R-8, R-11, R-12, R-16, R-17, with their
  commits; and the settings-defaults test-order failure (`22ee3fb`).

**.ai/memory/results/folder-io-queue.md**
- The quick check's rule (exact folder mtime, the 2 s margin, a listing after each Live save).
- The R-7 behaviour, if the memory describes a status check cancelling a running load.

**Other**
- `HeLab.spec`: add `ai-icon.icns` to `datas` (R-12).
- `requirements.txt` / `requirements.lock`: drop joblib if nothing else needs it (R-20).

## Lens's sign-off

Lens reviewed every fix commit by diff and accepted them with no changes asked: area 1
(`265f35e..f684720`), areas 2–3 (`c530e7f..f410ccb`), areas 4–5 (`f7d06e6`, `e4b1712`, `60a8a99`,
`a1b75b2`, `89531cc`), the restore `b68f6b1`, and the held items: R-1 `4468eaf`, R-11 `1efcb87`,
R-16 `c4cf63c`, R-13 `c7eb0a3`, R-15 `0406507` with `22ee3fb`, and R-19 `6fac7df` (records in
`findings.md`; Lens checked several fail-before claims in a scratch worktree). Lens reruns the full
suite with `-rR`, strict mypy and pyright on the final head for the sign-off.
