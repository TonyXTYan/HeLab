# Codebase review: handoff

Floor "Codebase Review", branch `agent/codebase-review` from `fc0f50d` (`dev/v0.0.6`). Reviewer Lens
(Claude Fable 5.1): [findings.md](findings.md). Worker Mend (Claude Opus 5.5): [notes.md](notes.md),
which has each finding's detail. Brief: [brief.md](brief.md).

## Summary

The review covered all five areas of the brief and found 21 issues: no blocker or high, 2 medium,
13 low and 6 quality (as each finding's heading in `findings.md` grades it). Fixed: 17 in full, 3 in part (the rest waits for Tony or for the CI floor to
land). R-1 (medium) is held for Tony, unchanged. Every correctness fix has a test that fails without
it and passes with it, except two: a log-only guard (R-11's Live warning) and the comma fix
(R-21), whose list value doesn't change. Lens reviewed every fix commit (areas 1–3 accepted; areas
4–5: see the end).

Final checks at the last code commit (`e4b1712`), floor root with `floor-env.sh`:
`pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: 2408 passed, 2 skipped,
2 xfailed, **no RERUN**; `mypy helab/ --strict` (148 files), `mypy tests --strict` (106 files) and
`pyright helab tests`: clean. Baseline at `fc0f50d`: 2378 passed, no RERUN. Every full run in
between had no RERUN, except the first run of areas 4–5. There `tests/test_typing.py::test_mypy_helab_tests_strict`
was rerun 5 times and failed: a real failure from R-19 (tests reached names the DLD module had
started importing), fixed in `e4b1712`.

## Outcomes

| ID | Sev. | Outcome | Commits |
|---|---|---|---|
| R-1 quick check compares the share's clock with this PC's | medium | **Needs Tony** (held by CoCo) | — |
| R-2 a Live save's data dump runs under the no-progress timer | medium | Fixed | `265f35e` |
| R-3 frozen reader can miss a helper's last lines | low | Fixed | `6299fdd` |
| R-4 roots-table reads raise raw sqlite errors and fail a listing | low | Fixed | `af632a3` |
| R-5 store-open failures reported as "Mount information is unavailable" | low | Fixed | `2447a66` |
| R-6 a pending root stays pending after its duplicate is gone | low | Fixed | `d586f9d` |
| R-7 a scan's new signature cancels the folder's running jobs | low | Fixed (confirmed by test first) | `2559c77` |
| R-8 a crashing helper leaves no cause in the log | low | Fixed | `34bcb78` |
| R-9 details scan stats each subfolder a second time | low | Fixed | `6ddec21` |
| R-10 `_on_event` and `_load` too long | quality | Part (three handlers lifted; rest declined, reasons in notes) | `f684720` |
| R-11 no excepthook; unguarded source timestamps | low | Guards fixed; **excepthook needs Tony** | `e4d3f2d` |
| R-12 window icon looked up from the launch folder | low | Fixed | `fbb072f` |
| R-13 Settings placeholders, WARNING on close, unused imports | low | Part; **placeholder controls need Tony** | `aad0ad4` |
| R-14 `StatusReport` legacy fields, import-time default | quality | Fixed | `305f19a` |
| R-15 unused/star imports, commented-out code, long functions | quality | Part (`FolderTabWidget.py`; the rest after the CI floor lands; long functions declined) | `f410ccb` |
| R-16 manual marker saved on the GUI thread | low | **Needs Tony** (note only) | — |
| R-17 a script hook that raises when its plot opens ends HeLab | low | Fixed | `c530e7f` |
| R-18 Scripts panel leftover state, stale docstrings | quality | Fixed | `324ae2a` |
| R-19 DLD Transfer fractions duplicates the shared order helpers | quality | Fixed; **one question for Tony** | `f7d06e6`, `e4b1712` |
| R-20 private joblib import never used | low | Fixed | `a1b75b2` |
| R-21 dead code, two unused modules, probe log lines, a missing comma | quality | Fixed, except `synchronised_dict.py`: restored (Tony kept it on 2026-10-21, a vendored MIT thread-safe dict) | `60a8a99`, `a1b75b2`, `89531cc`, restore: `b68f6b1` |

Notes commits: `2180d56`, `e266925`, `db2cc14`.

## Questions for Tony

1. **R-1** (medium; held). The cached-data quick check answers `unchanged` when the folder's mtime
   isn't later than `snapshot_at`. The mtime comes from the share's clock and `snapshot_at` from this
   PC's, so a server clock behind ours hides new shots until a Retry / Refresh (Lens confirmed this
   with a probe). Proposed fix: save the folder's pre-listing `st_mtime_ns` as an optional
   `info["folder_mtime_ns"]` in the cached dataset (refreshed by `confirm_dataset`, and carried in
   `memory_check`), and require equality in both quick checks. Caches without the key keep today's
   rule. The store format gains one optional JSON key, compatible both ways, with nothing to
   migrate. Approve?
2. **R-11.** Install a `sys.excepthook`? Without one, PyQt6 aborts on an exception in a slot or
   `data()`. With one, HeLab carries on after it instead. Nothing logs to a file, so in the
   windowed packaged build a crash leaves no trace either way. Choose: keep aborting, or log and go
   on? And should HeLab write a log file in its app folder?
3. **R-13.** Remove "Enable feature X" and "Example Text" from Settings → General, and their
   `example_checkbox` / `example_text` keys?
4. **R-16.** The manual marker's Save to folder… writes `.helab-root` on the GUI thread into whatever
   folder the picker returns, which can be a hung share. Say "a local folder" in the dialog and the
   picker's title, or send the write through a helper?
5. **R-19.** Should the DLD port's Transfer fractions also take the Reference spacing
   (`orders.guided_spacing`, Basic plots v1's "a bump between orders isn't one" fix)? That is a new
   setting and a detection change. Its `detect` is unchanged here.

## Behaviour changes to know about (bug fixes restoring documented behaviour)

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

- R-2: every Live autosave (each 10 shots) and Live off still writes the whole held dataset to the
  temp folder and the helper reads it back (by design); it no longer times out, but its cost grows
  with the dataset.
- R-3: the reader change runs only in the frozen build (its test fakes the process); not yet seen
  in a packaged app.
- R-6: the behaviour change hasn't been tried on a real duplicate root.
- R-12: `HeLab.spec`'s `datas` doesn't bundle `ai-icon.icns`, so the packaged app still logs "Icon
  file not found" (the bundle has its own icon). Add it to `datas`, or skip the check when frozen.
- R-15: the star imports in `HelabMainWindow.py` and `SettingsDialog.py` (and `QDirIterator`, unused,
  on `constants.py`'s QSettings import line) wait for the CI Robustness floor to land, because it is
  changing those lines. CoCo cleared `constants.py`'s other lines for R-20/R-21; the hunks there stay
  away from the QSettings reads and their neighbouring lines.
- R-20: joblib now has no importer in `helab/` (`requirements*` were off-limits here).
- The DEBUG level of `coloredlogs.install` (`main.py`) is unchanged.

## Proposed doc changes (for the Coordinator)

**AGENTS.md**
- Responsive filesystem I/O, after "Daemon reader threads deliver results…": "A helper's stderr goes
  to `stderr.txt` in its private folder; when it exits without `done` or `error`, the last 2 KB are
  logged with the operation and path. Writing a Live save's held arrays to that folder counts as
  progress for the no-progress timer."
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
- DLD analyses, Transfer fractions: "the DLD port's imports the shared order helpers from
  `orders.py`/`peaks.py`; only its `detect` (nearest side peak, no Reference spacing), ms texts and
  Search T helpers are its own."

**roadmaps/known-issues.md**
- Open: R-1 (quick check vs the server's clock), until Tony decides.
- Open: no log file; a crash in the packaged build leaves no trace (R-11's question).
- Open: the packaged app lacks `ai-icon.icns` (R-12, `HeLab.spec` datas).
- Open: joblib is in `requirements.txt` with no importer left (R-20).
- Fixed (this branch): R-2, R-3, R-4, R-5, R-6, R-7, R-8, R-11's timestamp guards, R-12, R-17, with
  their commits.

**.ai/memory/results/folder-io-queue.md**
- The R-7 behaviour, if the memory describes a status check cancelling a running load.

**Other**
- `HeLab.spec`: add `ai-icon.icns` to `datas` (R-12).
- `requirements.txt` / `requirements.lock`: drop joblib if nothing else needs it (R-20).

## Lens's sign-off

Lens reviewed every fix commit by diff and accepted them with no changes asked: area 1
(`265f35e..f684720`), areas 2–3 (`c530e7f..f410ccb`) and areas 4–5 (`f7d06e6`, `e4b1712`,
`60a8a99`, `a1b75b2`, `89531cc`). Lens's own checks at `db2cc14`: strict mypy (helab, tests) and
pyright clean; full suite (`--basetemp=.ai/temp/pytest-review`) 2408 passed, 2 skipped, 2 xfailed,
twice: the first run had 1 RERUN that `-q` didn't name, the second none. Lens confirms to CoCo.

## Before the push

`synchronised_dict.py` restored (`b68f6b1`). Full suite at that commit with `-rR`: 2408 passed,
2 skipped, 2 xfailed, **no RERUN**; strict mypy (helab 149 files, tests 106) and pyright clean.
