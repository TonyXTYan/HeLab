# Handoff: TXY converter stage 4, Live auto-convert (`agent/txy-live`)

Worker: Lantern (Claude Code, Opus 5.5), 2026-10-29. Base `01776d6`; brief in [brief.md](brief.md).

## Summary

Live converts new raw shots when the user turns **Auto-convert** on (a button at the end of the
Live line, shown once Live is on, Q6.8). Each Live check then also asks for the helper's `convert`
operation (through `FolderCache.convert`), one per folder, at least a check interval apart, sending
the last summary's lists back as `seen`/`done`/`kept`/`skip` (helab-core's A~5). The Live line and
Folder details say what it does (converting N, converted K with the last shot, files waiting or
unconvertible with the reason in the tooltip). A converted shot below `convert_low_hits` (default
100) raises one system notification through `events.notify`. Folders can be set to start Live and
auto-convert when HeLab launches (`live_launch_folders`, Q9.6). Writing beside the raw files
(Q9.7, helab-core's flag) is offered in the same menu, asked first.

**Not here, by CoCo's split:** converted shots reach the dataset and plots only once Live's checks
read HeLab's TXY (the UI floor's Q6.6, in `io_ops/live.py` and `io_ops/loading.py`). After each
`shot_converted` this floor asks for Live's next check (at once, or right after the running one),
so the shot is read as soon as those checks can see it. The seam is a strict xfail,
`tests/test_live_convert.py::test_a_converted_shot_reaches_the_live_data`: it fails (XPASS) once
both floors are in, and then its mark goes.

**Found by a real-app run (helab-core's, fixed by Keel):** IOService gives every helper its private
folder as `payload["output"]`, which overwrote `ConvertRequest.output` (cache/temp), so every
conversion the app asked for failed ("Unknown converter output '/var/folders/…/helab_io_…'").
helab-core's tests call the helper directly, not through IOService. CoCo's call: Keel renames the
request field to `destination` (ConvertRequest, `convert_folder`, CLI, tests) with an end-to-end
test; `FolderCache.convert` already sends `destination`. Until that is merged, Live's conversions
in the app still fail (auto-convert stops with that message), and
`test_a_conversion_the_app_asks_for_runs_in_a_helper_process` (a real IOService helper process) is
a strict xfail that flips when it arrives (A~1).

**Checks:** see "Checks" at the end.

## What was built

| Path | What |
|---|---|
| `helab/views/explorer_live.py` | `AutoConvert` (per Live session: request, counts, last shot, plan, waiting/unconvertible/kept with reasons, error); `LiveController.set_auto_convert`, `auto_converting`, `_convert_tick` (in `_live_tick`), `_convert_event`, `_converted` (next check, low-count notification), `convert_line` (Live line part and tooltip lines), `fill_convert_menu` (Auto-convert, Write beside…, Start at launch, Notify below N hits…); `resume_live` also clears a conversion error; `LiveSession.check_soon`; `low_hits_threshold()`. |
| `helab/views/live_launch.py` (new) | The launch list (`launch_folders`, `starts_at_launch`, `set_starts_at_launch`), `start(window)` and `LaunchFolder` (as `PresetFolder`: loads deliberately once data is known, Live once shown or no shots yet; a folder that can't be listed notifies once, no retry). Never under pytest unless `in_tests=True`; offline it starts nothing and says so. |
| `helab/views/FolderExplorer.py` | The Live line is a row with the Auto-convert button (`auto_convert_button`, checkable, menu arrow; `_update_auto_convert_button`); Retry shows for a conversion error too. |
| `helab/views/FolderDetailsPanel.py` | Row "Auto-convert" (same text, tooltip with the details). |
| `helab/utils/folder_cache.py` | `auto_convert` (folders converting this session), `convert_lists` (last summary per folder, bounded), `convert_profile` (None: the default built-in; for the profile manager), `convert(owner, path)` (builds the payload: profile, temps, cache, output setting, beside flag, the lists), `_remember_convert` (from `convert_summary`). |
| `helab/utils/settings_defaults.py` | Rows `live_launch_folders` (JSON list, "") and `convert_low_hits` (int, 100). |
| `helab/views/HelabMainWindow.py` | Two lines (CoCo's approval): the import and `QTimer.singleShot(40, lambda: live_launch.start(self))`. |
| `tests/test_live_convert.py` (new) | 15 tests, 2 of them strict xfails (below). `tests/test_settings_defaults.py`: the two rows listed as read outside a bare window. |

## How it behaves

- **The toggle.** Shown only while Live watches the selected folder. Turning it on asks the store
  for the folder's `write_beside` flag (if not known) and starts the first conversion at the next
  tick; that first one only records (`seen` = `[]`), so a file converts at the earliest a check
  interval later. On is remembered for the session per folder (`FolderCache.auto_convert`): Live
  off and on again there converts again. Off cancels a running conversion (each TXY is written
  whole, so nothing half-written stays) and stops new ones. Never saved across sessions except
  through the launch list (Q9.6).
- **Cadence.** A conversion is asked for in Live's tick (before its check), only when none is
  running for the folder and at least `live_interval` after the last ended, so two conversions are
  a check interval apart (the settle rule's two checks). It runs in the background lane (pausable,
  paused while a Live check reads a file), as helab-core left it. A converted shot sets
  `check_soon` when a check is running (the next starts at once) or starts one now.
- **Errors.** A conversion that fails (or is refused offline) stops auto-convert, not Live: the
  line goes amber, "auto-convert stopped: <why>", and Retry converts again. A conversion cancelled
  by someone else (a cache move's hold) is simply asked for again at the next tick.
- **Status.** Line: `auto-convert converting 2, 12 converted (last: shot 341), 1 waiting, 1
  unconvertible` (or `auto-convert on`). "Waiting" counts only files waiting for more than being
  written (no final newline, off the trigger channel, dated ahead, unreadable now: Q12.5 keeps
  them waiting, re-checked when they change); files being written are counted in the tooltip.
  Tooltip: since when, where the TXY go (and why not where asked), profile and backend, converted
  count and the last shot's hits and time, the low-count threshold, each waiting/unconvertible/kept
  file with its reason (first 8).
- **Low counts.** `hits` from `shot_converted` below `convert_low_hits` (0: never) →
  `events.notify(events.LOW_COUNTS, "Shot N of <folder>: H hits (fewer than T), converted by HeLab",
  title="HeLab: low counts", key=("convert_low_hits", path, shot, raw_sha256), desktop=True,
  source="convert", …)`: once per shot and raw file (a re-conversion of the same raw doesn't
  notify again). Edited from the Auto-convert menu (an input dialog).
- **Start at launch.** The menu's "Start Live and auto-convert here when HeLab launches" adds the
  folder to `live_launch_folders`. At launch each listed folder opens in a tab; Live and
  auto-convert start in the first one listed (opened last, so current), the others' tab tooltips
  say Live follows the current tab. All listed folders are set to auto-convert this session, so
  turning Live on in another of those tabs converts too. A folder whose listing fails (missing,
  unmounted) or where Live can't start: one desktop notification, then nothing more.

## Decisions made here (technical; say if one is Tony's)

- The convert payload is built in `FolderCache.convert` (output from the setting at each call,
  read with `read_convert_output(app_settings())`; `temps` = `constants.DIR_TEMPS`; the profile
  `FolderCache.convert_profile` or `builtin_profile()`), so any later caller (the UI floor's
  manual conversion, say) gets the same lists loop.
- The output setting goes as `destination` (above).
- `LaunchFolder` is done before it starts Live: starting Live on a folder with no shots yet shows
  its empty data before the session exists, and that signal re-entered the watcher, which started
  Live twice (seen in the real-app log). `PresetFolder` (`helab/views/plots/presets.py`) has the
  same shape; not checked or changed here (A~4).
- The folder's `write_beside` flag is asked for once a conversion's plan names a data root (asking
  when auto-convert turned on warned "no data root" for folders without one).
- `done`/`kept` are sent back only for the same profile dict; `seen`/`skip` always (they are about
  the raw files).
- The Live check's owner (`<tab>:live`) also owns its conversions (`operation == "convert"`
  tells them apart), so `FolderExplorer._io_event` needed no new route.
- Background lane kept: making `convert` foreground would hold the selected load and Live's own
  checks while it lists (one listing at a time in the foreground).

## Proposed doc changes (for the Coordinator)

### `.ai/architecture/live.md`

Append: "**Auto-convert** (TXY converter stage 4, Q6.8; `AutoConvert` in `explorer_live.py`): the
Live line's Auto-convert button (shown while Live watches the selected folder; its menu: Write TXY
beside the raw files…, Start Live and auto-convert here when HeLab launches, Notify below N hits…)
makes each Live tick also ask for `FolderCache.convert` (owner `<tab>:live`, operation `convert`,
background lane): one per folder, at least `live_interval` after the last ended, each sending the
last `convert_summary`'s lists back (`seen`/`done`/`kept`/`skip`; `done`/`kept` only for the same
profile). On is kept for the session per folder (`FolderCache.auto_convert`, Q9.6). A converted
shot asks for Live's next check (now, or right after the running one: `LiveSession.check_soon`);
one with fewer hits than `convert_low_hits` (100; 0 never) notifies once per shot and raw file
(`events.LOW_COUNTS`, `source="convert"`). A conversion's error (or Work Offline's refusal) stops
auto-convert, not Live: amber line, Retry. The Live line and Folder details' Auto-convert row say
converting N, converted K (last shot), waiting (no final newline, off trigger, future, unreadable)
and unconvertible, reasons in the tooltip. **At launch** (`helab/views/live_launch.py`, from the
main window 40 ms in): the folders in `live_launch_folders` open in a tab each, all set to
auto-convert, and Live starts in the first (current) once its data shows or it has no shots yet
(`LaunchFolder`, as `PresetFolder`); a folder that can't be listed or started notifies once, no
retry; working offline nothing starts and a notification says so; never under pytest unless a test
asks."

### `.ai/architecture/converter.md` ("In HeLab (stage 4)")

In "The operation", replace "(through `FolderCache`; Live auto-convert is the first caller)" with
"(through `FolderCache.convert(owner, path)`, which builds the payload and sends the folder's last
summary's lists back; Live auto-convert is the first caller, `live.md`)".

### `.ai/architecture/settings.md` (or wherever rows are listed)

The two rows: `live_launch_folders`, `convert_low_hits`.

### `AGENTS.md`

Code map: add `helab/views/live_launch.py` (start Live and auto-convert at launch) to the
`helab/views/` row's list, e.g. "…, Folder details, Settings tabs, dialogs, `live_launch.py`".

### `roadmaps/txy-converter.md`, `roadmaps/live-monitoring.md`

Stage 4 / L4: Live's auto-convert toggle, start at launch and low-count alerts done
(`agent/txy-live`); converted shots reaching plots with the UI floor's Q6.6.

## Provisional items

- **Q~1** (CoCo approved as a Q~; Tony to confirm): the start-at-launch list is a **settings row**
  (`live_launch_folders`, a JSON list), not a store table like the folder flags: it must be known
  before any folder is listed, and it works for folders without a `.helab-root`. Reset all
  settings clears it. Alternative: a `convert_prefs` column (needs a data root and a store query
  at launch).
- **Q~2** (CoCo approved as a Q~; Tony to confirm): **several launch folders**: Live follows the
  current tab (switching tabs turns it off), so each opens in a tab but Live and auto-convert run
  only in the first one listed; the others' tab tooltips say so, and they are set to auto-convert
  if Live is turned on there. Alternative: allow one launch folder only.
- **Q~3** (Tony): the **low-count threshold**: `convert_low_hits`, default **100 hits**, 0 = off,
  notified once per shot. Why not Shot trends' Notify during Live: its rule needs a plot and the
  shot's TXY loaded (counts in the View range). Why not MATLAB's rule (`tdc_auto_convert`:
  hits/max T < `min_counts_hz` = 700 Hz): `shot_converted` carries hits but not the shot's
  duration (max T); adding `t_max` to the event would allow it (helab-core's event, not changed
  here). 100 catches empty and near-empty shots (no atoms, MCP off) without firing on low-density
  runs (the test samples have 800–1,400 hits over ~4 s, which MATLAB's 700 Hz rule would flag).
  Options: (a) 100 hits (built); (b) a rate like MATLAB's (needs `t_max` in `shot_converted`);
  (c) per-folder thresholds.
- **Q~4** (Tony): the Live line says "waiting for the first shot" next to "auto-convert 3
  converted" until Live's checks read HeLab's TXY (the UI floor). Nothing to do if Q6.6 lands
  with this; otherwise the line could count converted shots as the folder's.
- **A~1** (Coordinator, after merging): two strict xfails flip (XPASS fails strict) and their marks
  go: `test_a_conversion_the_app_asks_for_runs_in_a_helper_process` once Keel's `destination`
  rename is merged; `test_a_converted_shot_reaches_the_live_data` once the UI floor's Q6.6 loading
  is merged (it drives four ticks after a raw file arrives and expects shot 1 in the tab's data).
  Then a real-app run as below (start at launch, raw files copied in) should show the shots
  converting and joining the data.
- **A~2** (UI floor or later): `FolderCache.convert_profile` is the profile Live converts with
  (None: `matlab-2019`); the profile manager sets it. A profile change makes `done`/`kept` stale
  for the next conversion (checked again; the provenance decides).
- **A~3**: each conversion lists the folder and stats its raw files (a helper process every
  `live_interval` while auto-convert is on). Fine locally; on a share with thousands of raw files
  it may be worth pacing conversions to the Live check's own listing (only after a listing found
  new names), if M~1 shows it costs.
- **A~4**: check whether `PresetFolder.check` (arrangement presets with Live) starts Live twice on
  a folder with no shots yet, as `LaunchFolder` did (its `start_live` shows the empty data, which
  signals the watcher before Live is on); same fix if so.
- **M~1** (Tony, lab): on the acquisition PC, Live + Auto-convert on a copy of a run folder while
  raw files arrive (or are copied in one by one): each shot converts once written, the Live line
  counts them, a deliberately truncated file waits with its reason, and a near-empty shot notifies
  once. Also start-at-launch with the run folder listed, and with it unplugged (one notification).
- **M~2** (Tony, screen): the Auto-convert button on the Live line on Windows and macOS (its menu
  arrow, the checked look) and the menu's texts.

## Tests (`tests/test_live_convert.py`)

A raw file arriving during Live converts once written, not before (the first pass records; a file
seen once waits; a half-written one waits for its final newline with the reason on the line and in
Folder details; when its writer finishes it waits one more check as changed, then converts); the
lists go back (`seen`, `done` for the next pass); a converted shot asks for Live's next check at
once; off cancels the running conversion and none start; on again; auto-convert kept for the
session and the button shown only while Live is on; the lists sent back, and `done`/`kept` not for
another profile; Work Offline refuses (`offline`, then `cancelled`, no helper); refused offline
inside Live: amber line, Retry converts again; an error stops auto-convert, not Live, until Retry;
a low-count shot notifies once, not again for the same shot, never at 0; the launch list setting
(order, duplicates, unreadable); launch folders open and the first starts Live with auto-convert
(a real window, `in_tests=True`; plain `start` does nothing under pytest); a missing launch folder
notifies once and isn't retried; offline nothing starts and it says so; Live starts once at launch
(the log); the two strict-xfail seams (a conversion through a real IOService helper; a converted
shot reaching the Live data).

## Real-app check (floor settings, synthetic folder under `.ai/temp/live-gui`)

`live_launch_folders` set to an empty folder, HeLab launched with `floor-env.sh`: the folder opened
in a tab and Live started with auto-convert ("Live at launch", "Live on" in the log; twice before
the re-entrancy fix). Raw files copied in (500 hits, 30 hits, one without its final newline); the
first conversion failed on the `output` collision above, and auto-convert stopped with the message
on the Live line, as designed. The Live line and the Auto-convert button were also checked on a
grab of the summary (`.ai/temp/visual/`): its label, checked look and menu arrow.

## Checks

At `937c2bd` (base `01776d6`, dev/v0.0.7 not merged yet): `pytest -n 4 --reruns 5 --reruns-delay 1
--basetemp=.ai/temp/pytest`: 8049 passed, 669 skipped (unbuilt backends, by design), 2 xfailed (the
two strict seams), **no RERUN**. An earlier run (at `ae44c57`) had 1 failure, my arrival test, in all
5 reruns: its tick helper waited for a conversion while a check that a converted shot had asked for
was unanswered (a race in the test, fixed in `46ff46e`; not an app bug). Types: `mypy helab/
--strict`, `mypy tests --strict`, `pyright helab tests` clean on macOS and with `--platform linux` /
`--pythonplatform Linux`; with `--platform win32` / `--pythonplatform Windows` only helab-core's
known errors (`helab/io_ops/convert.py:344–346`, Keel's fix). Branch CI: pushed for a run on all
three OSes (result to CoCo).
