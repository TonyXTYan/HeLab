---
date: 2026-10-19
status: settled
name: live-monitoring
description: "Live L1/L2: wording, one stat per check while unchanged, new shots in RAM saved every 10 and on stop, error keeps Live on with Retry, quit window with Quit now"
metadata:
  node_type: memory
  type: result
---
Live L1 and L2 (2026-10-19, `.ai/sessions/2026-10-19-claude-live-l1/`). Architecture is in AGENTS.md › Live.

## Tony's decisions (2026-10-19)

- Polling, 3 s after the previous check finished (Settings → General, "Live: check again after").
- Live greys out the tab's folder explorer, so the GUI focuses on plots and parameters.
- A tab switch turns Live off (and saves); a restart never restores Live.
- Save to the disk cache every 10 new shots (Settings → Cache, "Live: save to the disk cache every N new shots"), and when Live stops or HeLab quits.
- Files: read only after two checks show the same size and mtime (plus settle age and a whole last row). Partly written files: document the remaining limit, and plan the converter's temp-name rename.

## Wording

- Line 3: `Live · checked … · N new shots · N still being written · next check in N s · N not cached yet`.
- Errors: `Live stopped: <why>` in amber with Retry; the data stays and Live stays on.
- Status bar `Live <folder> · N new shots`; plot hint `Live: watching <folder> · N new shots`.
- Quit window: "Saving N folders to the disk cache before HeLab quits:" with Quit now.

## Why

- Live checks pause background work only while reading a file: holding it like a load paused a background load 15 % of the time (-19 % files/s).
- Errors keep Live on so the plots stay the focus and Retry is one click (open question whether to turn it off instead).
