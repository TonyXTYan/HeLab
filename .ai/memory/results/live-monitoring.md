---
date: 2026-10-19
status: settled
name: live-monitoring
description: "Live L1/L2: wording, one stat per check while unchanged, new shots in RAM saved every 10 and on stop, error keeps Live on with Retry, quit window with Quit now; L3 plots follow Live; L4 (2026-10-29): auto-convert toggle once Live is on, one launch folder, Live on collapses the left panel, low-count alerts"
metadata:
  node_type: memory
  type: result
---
Live L1 and L2 (2026-10-19, `.ai/sessions/2026-10-19-claude-live-l1/`). Architecture is in `.ai/architecture/live.md`.

## Tony's decisions (2026-10-19)

- Polling, 3 s after the previous check finished (Settings → General, "Live: check again after").
- Live greys out the tab's folder explorer, so the GUI focuses on plots and parameters. Since
  2026-10-29 (Q18.3) turning Live on collapses the whole left panel instead (tabs, summary, Live
  line, Folder details; Q23.2 to confirm), and Live off brings it back.
- A tab switch turns Live off (and saves); a restart never restores Live.
- Save to the disk cache every 10 new shots (Settings → Cache, "Live: save to the disk cache every N new shots"), and when Live stops or HeLab quits.
- Files: read only after two checks show the same size and mtime (plus settle age and a whole last row). Partly written files: document the remaining limit. HeLab's own conversions now write to a temporary name and rename (Q18.6); MATLAB's converter isn't changed (Q9.8).

## Wording

- Line 3: `Live · checked … · N new shots · N still being written · next check in N s · N not cached yet`.
- Errors: `Live stopped: <why>` in amber with Retry; the data stays and Live stays on.
- Status bar `Live <folder> · N new shots`; plot hint `Live: watching <folder> · N new shots`.
- Quit window: "Saving N folders to the disk cache before HeLab quits:" with Quit now.

## Why

- Live checks pause background work only while reading a file: holding it like a load paused a background load 15 % of the time (-19 % files/s).
- Errors keep Live on so the plots stay the focus and Retry is one click (open question whether to turn it off instead).

## L3: plots following Live (2026-10-19)

- Source line: `rev N · following Live · K new shots waiting`, `updating to rev N`, `pinned (Follow Live off) · K newer shots`; amber `⚠ rev N failed: <error> · showing rev M`; `waiting for the first shot`; empty states "No shots yet", "None of the N shots is chosen (Shots settings)", "No events in the chosen shots".
- Live group labels: Follow Live, Rerun every N new shots, Wait after a run (scatter 5 s).
- Tony: Live off catches held plots up; the scatter keeps its camera; "Highlight the newest shot" (red), its histogram counts on a right axis in its colour; Live may watch any folder (never its subfolders) from no data.

## L4: the converter in Live (Tony, 2026-10-28/29)

Built `6454b4a`, follow-ups `c718c71`; the converter's decisions are in `txy-converter.md`.

- Auto-convert: "show auto convert toggle after live is toggled" (Q6.8); it resets each session
  (Q9.6).
- One launch folder (Q9.6, Q18.3): Live runs in one folder only; an instance set to launch Live and
  auto-convert opens no other folder tabs (the `live_launch_folder` setting; the older list's first
  entry becomes it).
- Low-count alerts through system notifications only (Q9.4): `convert_low_hits`, default 100 hits,
  once per shot; a rate or per-folder thresholds later (Q15.3). Shots converted with no hits are
  named in amber (A17.1; Q23.5 to confirm).
