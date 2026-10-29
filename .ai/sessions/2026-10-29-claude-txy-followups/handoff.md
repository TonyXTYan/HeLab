# Handoff: converter follow-ups (`agent/txy-followups`)

Worker: Quill (Claude Code, Opus 5.5), 2026-10-29. Base `6fcf012`; brief in [brief.md](brief.md).
`dev/v0.0.7` (TXY ship, `99d3ba5`) merged in at `0ebf89b`, no conflicts (`io_ops/convert.py` keeps
the tagged names and the ship floor's numba block; `native/check_build.py` keeps the tagged glob).

## Summary

| Item | Commit | What |
|---|---|---|
| Brief | `eef9041` | |
| Q18.4, Q18.6 | `26a2ade` | HeLab's TXY are `d_txy_helab_<tag>_<N>.txt` (records `d_txy_helab_<tag>_<N>.json`); tags on the built-ins (pinned), `u` + 8 hex of the hash otherwise; beside TXY current while newer than their raw file; `.partial` patterns follow the new names |
| Q18.2 | `dda90fd` | Four sources (helab-priority the default, matlab-priority, helab-only, matlab-only); a `txy_source` setting for tabs and Live; the profile chosen by tag; identities and caches keep MATLAB-only data valid and never mix choices |
| Q18.3 | `dbf80e4` | One launch folder (the old list migrates to its first); opened alone; Live on collapses the left (File Explorer) panel, Live off restores it |
| Q18.5 | `2102f28` | Raw files failing the format checks once unmodified for 20 s are damaged: no TXY, skipped from then on, "N damaged" on the Live line and in Folder details, one notification per file |
| A17.1 | `62d156e` | Shots converted with no hits named in amber on the Live line and in Folder details' Auto-convert row (also for a folder loaded later, from its empty HeLab shots) |

**Checks** (at `62d156e`): `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`:
**8497 passed, 353 skipped, no RERUN**; once more with the default basetemp (outside the checkout):
8497 passed, 353 skipped, no RERUN. `mypy helab/ tests --strict` (darwin and `--platform win32`),
`pyright helab tests` (and `--pythonplatform Windows`): clean. Earlier runs during the work: one
failure in Q18.3's full run, `tests/test_settings_defaults.py::test_a_real_window_and_settings_read_only_listed_keys_with_their_defaults`
(5 reruns of the same assertion: `live_launch_folder` read by no window at start under pytest),
fixed in the same commit by listing the key as launch-only; Q18.2's first full run failed
`test_typing` on one annotation of mine (fixed). Neither is flaky, so nothing goes to known-issues.
GUI: not launched by hand; the Qt parts are covered offscreen by the tests (M~1, M~2).

## Review round (Avocet: no blocker; small round)

Commit after `ec1338a` (see the log). Full suite `-n 4 --reruns 5 --reruns-delay 1
--basetemp=.ai/temp/pytest`: **8499 passed, 353 skipped, no RERUN**; mypy --strict (darwin, win32),
pyright (also Windows) clean.

1. **Damaged needs both clocks**: each `waiting` entry now carries a sixth field, when this computer
   first saw the file with that (size, mtime) (this clock; carried while unchanged, sent back in
   `seen`). Damaged needs 20 s by the mtime **and** 20 s since first seen, so a share whose clock is
   behind ours can't make a file paused mid-write look old (`test_a_source_clock_behind_ours_never_makes_a_paused_file_damaged`).
   `helab convert --once` (one look, no history) goes by the mtime alone, as its 60 s settle rule
   does (Q~7). Entries without the field (older app state) count as first seen now.
2. **Tabs after a Settings change**: chosen "**applies when a folder loads again**" (Settings → TXY
   converter says so: "Tabs and Live read (when a folder loads again)", and its tooltip). No re-keying
   any more: a dataset is the tab's because the tab loaded it (`tab` in its `txy` record, set from the
   request by `FolderCache._with_choice`; `with_txy` marks a load asking for no choice as the tab's),
   whatever the setting says now, so `current_dataset`/`latest_dataset`/`_base` keep finding the data
   a tab shows, and a plot "As the folder's tab" reruns on it. A plot's own choice (even the tab's) is
   its own dataset and job (`load:<choice>`). A tab load asking for another choice than the tab's
   running load or Live check doesn't join it: it is queued and runs as its own job once that one
   ends (`test_a_tab_load_of_a_new_choice_waits_for_the_running_one`). Live, while on, keeps each held
   shot's kind of TXY while it exists (the existing held-kind rule); new shots follow the new choice;
   every shot's origin stays exact.
3. `txy_sources` docstring: `DatasetView.txy_choice`.
4. (Docs, below.)
5. `convert_line` computes the no-hit shots once per render; its third value is now "amber" (stopped
   or no-hit shots), which `live_line` uses.

## What changed, by item

### Q18.4 / Q18.6 tagged names

- `helab/convert/profile.py`: `DetectorProfile.tag` (descriptive, out of the hash, neutral ""), set
  on the built-ins and their packaged JSON: `matlab-2019` **m19v1**, `matlab-2023-lab-edit` **m23v1**,
  `plates-2017` **p17v1**, `plates-2022` **p22v1**, `plates-2025` **p25t1** (Q~1).
  `file_tag(profile)`: a built-in's tag only while the profile is that built-in (name, tag and hash),
  else `u` + `USER_TAG_DIGITS` = 8 hex digits of the content hash. A tag is a lowercase letter plus
  1-15 lowercase letters or digits; `u` is reserved for hash tags. `tests/test_convert_profile.py::test_a_builtins_tag_never_changes`
  pins them.
- **Why 8 hex digits:** 32 bits keeps names short (`d_txy_helab_u1a2b3c4d_17.txt`); among a lab's few
  dozen user profiles the chance two share a tag is about 1 in 10 million (k²/2³³: 100 profiles ≈ 1e-6).
  **On a collision**: in HeLab's own folders each record holds the full hash, so the other profile's
  TXY is found stale and converted again (overwriting there, as before); beside the raw files (no
  record) a reader would take the other profile's TXY as current. Built-ins can't collide (fixed tags).
- User profiles carry no tag: `ProfileLibrary.save` and `duplicate` drop one; the editor shows the
  derived tag read-only; the details line names the files.
- `provenance`: tagged names, `parse_txy_name`, `BARE_NAME` (no groups, for joined patterns),
  `beside_stale` ("TXY newer than raw"); records are **version 2** with `profile_tag` (a version-1
  record belongs to an untagged name and is refused).
- `file_kinds.HELAB_TXY`: tagged `.txt` names only (the tag a non-capturing group).
- `io_ops/convert.py`: tagged names; beside, only TXY of this profile's tag count, current while newer
  than the raw file (an older one is kept, never replaced); the provenance record still goes to
  HeLab's folder. `partial()`/`own_partial()` are exactly `write_atomic`'s names for the new TXY and
  records (Q18.6: temporary name and rename kept).
- `io_ops/helab_txy.py`: loads, Live checks and saves keep the listing's beside TXY of the wanted
  tag only (`beside_wanted`) and judge them by date (no record needed: another computer's count);
  HeLab's folders by their tagged records. `converted_usage`/`clear_converted` (Settings → Cache)
  also cover the untagged files of before.
- `FolderCache.with_txy` sends `profile_tag` and the profile's name/version/calibrated; quick checks
  compare the tag as well as the hash (matlab-2019 and the plates share a hash but not a tag).
- **Untagged `d_txy_helab_<N>.txy` from earlier builds**: ignored (not matched, never loaded), never
  removed; a folder converted before is converted again under the new names. Their leftover
  `.partial` files are no longer matched either, so they stay (never removed). In HeLab's own
  `converted-txy/`, Settings → Cache's Clear (asked first) removes them with the rest.
- `native/check_build.py`: its glob for HeLab's TXY uses the tagged name (one line, agreed).

### Q18.2 four sources

- `helab/utils/txy_sources.py`: `HELAB_PRIORITY` (`DEFAULT_SOURCE`), `MATLAB_PRIORITY`, `HELAB_ONLY`,
  `MATLAB_ONLY`; `MATLAB`/`HELAB` stay as the two *kinds* `choose` returns. Old names
  (`matlab`, `helab`) read as the priority modes everywhere (`normal_source`, `requested_source`).
  A dataset's **choice** = source + profile tag (`choice_text`, e.g. `helab-only@p22v1`; MATLAB-only
  has no tag), from its `txy` record (`metadata_choice`, `tag_of`).
- Setting **`txy_source`** (default `helab-priority`; `constants.read_txy_source`), in Settings → TXY
  converter: "Tabs and Live read". `FolderCache.tab_source()`/`set_tab_source()`.
- **Identity**: `identity_source` is "" for both priority modes (the result key has no
  `txy_source`), the mode's name for the `-only` ones. The two priority modes differ only on shots both
  kinds have, and there their `Coverage.origins` differ, so their saved results never mix; data of
  MATLAB's TXY alone keeps the identity and saved results it had, under either default.
- **RAM separation**: `DatasetView.txy_choice`; `revise`/`restore` never cross choices (data naming
  none, made before Q6.6, counts as a priority mode's, `same_choice`). FolderCache keys datasets,
  jobs and bases by choice (`dataset_choice`, `tab_choice`, `choice_suffix`; the tab's choice keeps the
  plain signature key and every dataset is keyed again when it changes, `_rekey`); a `loaded`
  record naming no source/tag gets its request's (`_with_choice`); the empty Live dataset names the
  tab's choice.
- Quick checks (`loading._helab_unchanged`): data saved naming no source (MATLAB's alone) stays valid
  for every source but helab-only while no HeLab folder has turned up. Data saved tonight under
  `matlab` (now matlab-priority) is listed once under the new default (shots reused, no TXY reread).
- Plot settings' TXY row (`views/plots/txy_source.py`): "As the folder's tab" or a source, plus a
  profile (built-ins and user profiles by name and tag; "Conversion profile" by default). A plot on
  another choice loads its own RAM-only dataset with that profile's hash, tag and name
  (`AnalysisInstance.txy_choice`, `on_tab_choice`, `set_txy_source(source, profile)`).

### Q18.3 one Live folder, one launch folder

- `views/live_launch.py`: setting **`live_launch_folder`** (a path; Reset all settings clears it).
  `live_launch_folders` (the list) is read once when the new key is unset: its first folder kept,
  the list removed. Setting a folder replaces any other. "Started in <first>'s tab" notes are gone.
- `HelabMainWindow._open_first_tab`: with a launch folder set, its tab is the only one (no usual
  first tab); working offline that tab opens without Live and a notification says so.
- `HelabMainWindow._live_panel`: Live on collapses the left panel (its tabs are the "File Explorer"
  tabs); Live off restores it, as does an error stopping Live's checks (the Retry is on the Live
  line). A panel the user collapsed stays so; one reopened during Live stays open.
- Live already runs in one folder (one tab at a time; a tab switch turns it off): unchanged.

### Q18.5 damaged raw files

- `io_ops/convert.py`: `DAMAGED_SECONDS` = 20; a file failing `raw.not_done` (no final newline, off
  the trigger channel, **no rows**) and unmodified for 20 s → `shot_unconvertible`, reason `damaged`,
  `problem` the check, message `Damaged: …`. A file read unfinished before and unchanged since turns
  damaged without a read. Skipped from then on while unchanged (`skip`), never holding up later shots.
  `--once` (60 s settle) finds such files damaged at once. **No rows now waits until 20 s** like the
  others (it was unconvertible as soon as settled, Q10.2).
- `events.ShotUnconvertibleEvent.problem` (NotRequired); `helab/utils/events.DAMAGED_RAW`.
- Live (`explorer_live.AutoConvert.damaged`): "N damaged" on the Live line and in Folder details'
  Auto-convert row, apart from other unconvertible files, reasons in the tooltip; one system
  notification per file (keyed by name, size and mtime); kept across auto-convert off and on.

### A17.1 no-hit shots

- `AutoConvert.no_hits` (shots converted with 0 hits) plus `txy_sources.empty_helab_shots` (the data's
  empty HeLab shots, from RAM): "N shots with no hits" on the Live line (the line goes amber, Q~5)
  and in Folder details' Auto-convert row (amber), shot numbers in the tooltip; a folder shown later
  (no Live) has the row from its data alone.

## Questions for Tony (provisional)

- **Q~1 Tags for the two built-ins Tony didn't name**: `matlab-2023-lab-edit` → `m23v1`, `plates-2017`
  → `p17v1` (CoCo agreed for now). Frozen once released: confirm before v0.0.7 ships.
- **Q~2 "File explorer panel" = the whole left panel** (tabs, summary, Live line, Folder details),
  collapsed while Live watches. Alternative: collapse only the folder tree inside the tab, keeping the
  Live line and Folder details visible. Proposed: as built, since the toolbar's Live turns it off and
  errors reopen it.
- **Q~3 No rows waits 20 s** before it is damaged (was: unconvertible once settled, Q10.2). Proposed:
  keep (one rule for all three checks).
- **Q~4 A plot's profile choice isn't saved** with presets, arrangements or reopened plots (Q14.2
  still open): a reopened plot starts "As the folder's tab".
- **Q~5 The Live line turns amber for no-hit shots** (the whole line; it can't colour one part),
  which otherwise means "stopped". Alternative: amber only in Folder details. Proposed: as built.
- **Q~7 `helab convert --once` and damaged files**: one look has no "first seen", so `--once` goes by
  the mtime alone (≥ 20 s; its settle rule is 60 s by the mtime alone too). Alternative: `--once`
  never reports damaged (only waiting). Proposed: as built.
- **Q~6 Beside TXY from another computer with a colliding `u` tag** would be taken as current (no
  record there). Proposed: accept (≈1e-6), or later write the hash into the name (longer names).

## Follow-ups (provisional)

- **A~1** Count HeLab's TXY of the tab's tag in folder status (A18.1, waits for Tony).
- **A~2** The Live line could colour its no-hit part if `ElidedLabel` learned rich text.
- **A~3** Remove the `live_launch_folders` row (and its migration) a release or two after v0.0.7.

## Manual checks (provisional)

- **M~1** In the running app (floor-env settings): Settings → TXY converter shows "Tabs and Live
  read"; a plot's TXY row has the source and profile combos; choosing HeLab only + plates-2022 loads
  its own data and the source line says `TXY: HeLab only (p22v1)`.
- **M~2** Set a launch folder, restart: only its tab opens, Live and auto-convert start, the left
  panel collapses; Live off brings it back.
- **M~3** On the acquisition PC: a deliberately truncated raw file is reported damaged after ~20 s
  with one notification; later shots convert.

## Proposed doc changes (for the Coordinator)

**AGENTS.md**, I/O and threads, the write rule (line ~131):

> - HeLab writes nothing into source folders except the user's `.helab-root` markers and, where
>   the user turns it on per folder or asks for it on the command line (Q12.4), converted
>   `d_txy_helab_<tag>_<N>.txt` (`<tag>` the profile's, Q18.4; temporary name, then rename; Q9.7,
>   Q18.6). Never modify raw `d*.txt` or an existing TXY.

and the housekeeping item (line ~171): `(.d_txy_helab_<tag>_<N>.txt.<16 hex>.partial`, …, records'
`.d_txy_helab_<tag>_<N>.json.<16 hex>.partial`, …) (Q12.7, Q18.6)`. Code map: `file_kinds` row
`HELAB_TXY d_txy_helab_<tag>_<N>.txt`; `helab/views/live_launch.py` in the views row ("one launch
folder").

**`.ai/architecture/converter.md`**:
- `profile` row: add "`tag` (built-ins only) and `file_tag`: the tag in HeLab's TXY names".
- `provenance` row: version 2 (`profile_tag`), `beside_stale`, `parse_txy_name`.
- "Writing TXY": HeLab's own output name is `d_txy_helab_<tag>_<N>.txt` (Q18.4).
- A new "Tags (Q18.4)" paragraph: the five built-in tags, frozen; `u` + 8 hex for others, why 8 and
  what a collision does (above); untagged files of before ignored, never removed.
- Settle rules: add the damaged rule (20 s, `DAMAGED_SECONDS`, reason `damaged` + `problem`; no rows
  now waits like the others); events table: `shot_unconvertible` reasons `damaged` (with `problem`) or
  `failed`; `shot_waiting` reasons gain `no_rows`; `convert_plan.profile` gains `tag`.
- "Where files go": every `d_txy_helab_<N>.txy/.json` → `d_txy_helab_<tag>_<N>.txt/.json`; beside:
  current while newer than the raw file; the partial regex now `BARE_NAME`-based
  (`^\.d_txy_helab_[a-z][a-z0-9]{1,15}_(?:0|[1-9][0-9]*)\.txt\.[0-9a-f]{16}\.partial$`).
- "TXY sources": replace the four sources' paragraph with Q18.2's (modes, setting, choice =
  source + tag, identities "" for the priority modes, `DatasetView.txy_choice`, FolderCache keys by
  choice and `_rekey`, the plot row's profile).

**`.ai/architecture/live.md`**, Auto-convert paragraph: the Live line and Folder details also say
"N damaged" (with one notification per file) and "N shots with no hits" (amber; also for a folder
shown later); **At launch**: one folder (`live_launch_folder`; the old list migrated to its first),
opened as the only tab; working offline its tab opens without Live; drop the "other launch folders"
sentence (Q15.2 superseded by Q18.3); Live on collapses the left panel, Live off or an error
restores it.

**`.ai/architecture/settings.md`** (Converter rows line): drop `live_launch_folders` as a list; add
`txy_source` (helab-priority; `read_txy_source`; Settings → TXY converter "Tabs and Live read (when a
folder loads again)") and `live_launch_folder` (one path, `live_launch`); `live_launch_folders` stays
only as the row read once to move an old list over (its first folder), then removed (A~3).

**converter.md, also (Avocet's item 4)**: MATLAB's `tdc_autoconverter` skips HeLab's beside
`d_txy_helab_<tag>_<N>.txt` only through its first-line check (the file isn't a raw `channel,time`
file), not by name; and lab scripts that glob `d*.txt` in a raw folder now also see HeLab's beside
TXY (they match `d*.txt`), so such scripts should match `d<N>.txt` exactly.

**`.ai/DECISIONS_TODO.md`**: Q15.2 superseded by Q18.3 (built); Q14.3 settled by Q18.2 (profile by
tag); Q12.7 confirmed as Q18.6 (the patterns now tagged).
