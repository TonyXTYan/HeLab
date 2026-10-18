---
date: 2026-10-18
status: settled
name: data-roots
description: "Data roots: disk caching only below a hidden .helab-root marker (root://uuid/relative keys, nearest wins, RAM only otherwise); Tony's wording and icon: Place .helab-root here…, RAM only in Folder details, ANCHOR badge, Settings → Data roots; Same folder / It's a copy… window once per location per session, Later vs Remind me next session"
metadata:
  node_type: memory
  type: result
---
Decided with Tony in Maestri chat (2026-10-16 and 2026-10-18). Code:
`helab/utils/data_roots.py`, `helab/io_helper.py` (`_discover_root`,
`create_root`, `reassign_root`, `verify_volumes`, `verify_known_roots`),
`helab/utils/folder_cache.py`, `helab/views/DataRootDialogs.py`,
`DataRootsTab.py` and `RootDuplicatesWindow.py`. Plan and stages:
`roadmaps/data-roots.md`, `.ai/sessions/2026-10-16-claude-data-roots/plan.md`.

## Identity

- No root, no disk cache: without a `.helab-root` at or above it, a folder
  uses RAM only, with no fallback to path, share or volume keys.
- Markers everywhere, local and USB disks included: a local disk may be
  shared over the network, where its OS volume ID is invisible but its marker
  is not. OS volume IDs only identify *locations* (`vol://<id>/…`), so two
  same-named USB disks never share one; data rows are keyed by the UUID.
- Marker name `.helab-root`; write-once JSON; the store was cleared once more
  (`store-v3`, no re-keying of `smb://` rows).
- Equivalent locations are remembered per PC; each new one asks.

## Wording and icon (Tony, 2026-10-18)

- Right-click action: **Place .helab-root here…**. Tooltip: no .helab-root
  found above this folder; place it as high up as possible (the top folder of
  the drive or share), unless the folder is also shared on its own, so other
  computers see it as a top folder.
- Sanity checks before writing: not the top of its drive or share ("Place at
  <top>" offered first; Cancel is the default with warnings, per review),
  already inside another root, a home folder (`C:\Users`, `/Users`, `/home`,
  `~`), the startup disk's top (`/`, `/System/Volumes/Data`: read-only on
  macOS, never offered as "Place at") or `/Volumes` itself.
- Placement rule (Tony, 2026-10-18): a marker identifies a drive or share
  across machines, so it goes as high as every machine can see (the shortest
  path), never above the top of a share some machine uses. Windows `C:\` is a
  drive top like any other (a lab PC shares its whole `C:`; the Mac mounts
  `//<pc>/C`): offered as "Place at C:\", no warning, only a note that it may
  need admin rights (the manual dialog follows a refusal).
- RAM only is shown in the **Folder details** panel ("RAM only · no
  .helab-root above this folder", how to enable it in the tooltip), for the
  selected folder or the tab's folder when none is selected; the tooltip and
  Folder details name the .helab-root in use ("⚓ <label> · <path>").
- **ANCHOR** (Tabler) badge beside the status icon on folders holding a
  .helab-root.
- No write permission: a dialog with the file name, folder and exact JSON,
  Copy and Save as… (saved as `helab-root.txt`, then renamed by the user).
- A separate **Settings → Data roots** page lists the known locations;
  "Forget location (found again if its .helab-root is still there)".
- Row menu (Tony, 2026-10-18): **Show in Finder** / Show in File Explorer /
  Show in File Manager (tooltip: the file is hidden; Cmd+Shift+. in Finder,
  View › Show › Hidden items in Explorer), **Copy path**, Forget location…,
  **Delete .helab-root…** (also a footer button). Show and Delete are greyed
  for Not mounted rows ("Not mounted on this computer now").
- Delete confirmation, Cancel default: "Deletes <marker>. This folder and its
  subfolders use RAM only on every computer until a .helab-root is placed
  again. Their cached data stays on this computer under this root's ID; a new
  marker gets a new ID and starts fresh. Other computers that use this drive
  lose their disk cache for it too." Only the marker still holding the row's
  UUID is deleted (never an invalid or replaced one: "changed since… Refresh
  the list"); without permission: "HeLab can't delete <file> (<reason>).
  Delete it by hand (Show in Finder finds it), then Refresh this list."
- **Clear cached data…** (Tony, 2026-10-18; button and row-menu item, for any
  row, mounted or not): everything this computer cached below that root's
  UUID. Confirmation, Cancel default: "Clears N cached folders (X) for data
  root “label” on this computer. The .helab-root and folder flags stay." (or
  "Clears the cached data…" when the inventory has no size). The list shows
  each root's cached size (Cached column).

## Same folder or a copy? (D4, Tony, 2026-10-18)

- Window wording as drafted ("Same folder or a copy?", hints: same/different
  server, marker size and modified time, file ID).
- It opens once per location per session; **Later** asks again the next time
  that location is found this session; **Remind me next session** keeps it
  quiet until then (Tony asked for this button). The status bar shows
  "⚓ N to confirm". Until answered the location is RAM only.
- It's a copy…: the location keeping the original UUID keeps the cached data;
  the other gets a new .helab-root and starts empty.
