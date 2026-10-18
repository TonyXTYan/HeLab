# Data roots and folder identity

Horizon: now, next after the SMB cache-key change. Added: 2026-10-16.
Direction from Tony (2026-10-16); decisions confirmed 2026-10-18 (marked below).
Priority and completion: [overview](_readme.md). Implementation plan:
[session plan](../.ai/sessions/2026-10-16-claude-data-roots/plan.md).

## Purpose

Give every cached folder an identity that survives remounts, `/Volumes`
suffix swaps, drive letters, server spellings (IP vs host name), SMB accounts
and same-named USB disks, and that later serves as the cross-machine
**logical root ID** in the [network plan](network-runners-and-web.md#machine-data-root-and-path-identity).
The same mechanism maps equivalent folders on one machine: for example a
folder reached as `/Volumes/<server>/C/.../dld_output` and as the separately
exported `dld_output` share.

## Identity model

A folder's cache key is its nearest **data root** at or above it, plus the
relative path below that root: `root://<uuid>/run_042`.

- **Root:** a folder containing a `.helab-root` file. Nested markers
  are allowed: the nearest wins. `C/.helab-root` and
  `C/.../dld_output/.helab-root` hold different UUIDs, so folders elsewhere on
  C use C's root and folders inside `dld_output` use its own, whichever mount
  path reached them.
- **Markers everywhere** (Tony, 2026-10-18): local disks and USB volumes use
  markers too, not OS volume IDs. A local disk may also be shared over the
  network, where its OS volume ID is invisible but its marker is not, so one
  mechanism gives the same identity locally and remotely.
- **No root, no disk cache** (Tony, 2026-10-16): without a marker, the folder
  uses session RAM only. No saved statuses, scan-failure history, folder flags,
  datasets or pending saves are read or written for it. There is no fallback
  to path, share or volume keys.

The current `smb://server/share/relative` key (`helab/utils/cache_paths.py`)
becomes a **location** key: it records *where* a marker was seen, so remounts
and suffix swaps don't matter, but data rows are keyed by root.

## The marker file

Name `.helab-root` (Tony, 2026-10-18). Small JSON, written once:

```json
{"helab": "root", "version": 1, "uuid": "…", "label": "dld_output",
 "created_at": "2026-10-16T12:00:00Z"}
```

- Readers ignore unknown fields and reject other versions or malformed files
  (no root, with a warning), so later metadata can be added.
- Keep it write-once identity. Mutable metadata would need write access that
  many users lack and would race between PCs; put that elsewhere if needed.
- Hidden: the dot prefix on macOS/Linux, plus the Windows hidden attribute
  (check that a marker written from macOS over SMB is hidden on Windows).
- Created only when the user asks: right-click **Place .helab-root here…** on
  a mount root (`/Volumes/<name>`, `N:\`) or any folder. Written with exclusive
  create, then read back; if one already exists, HeLab adopts it.
- Without write permission, HeLab shows the exact file name and contents with
  Copy and Save as… (to a writable folder) for the user to move into place.
  The next listing of that folder finds it.
- Creating it changes the folder's modification time: one amber clock and one
  full check for that folder.
- Check that the TDC converter and lab MATLAB scripts ignore the file.

## Where markers can't be written

Markers are universal, but some roots are read-only:

- **macOS startup disk:** `/` is the sealed, read-only system volume. Mark a
  folder instead (e.g. `~/data`); `/Users/...` is writable through firmlinks.
- **Windows `C:\`:** the root needs admin rights. Mark a data folder instead.
- **Read-only shares, write-protected USB disks:** the manual flow above, or
  RAM only.

OS volume IDs were considered (APFS volume group ID, Windows volume serial,
Linux `/dev/disk/by-uuid`) and set aside on 2026-10-18: they are invisible over
network shares and differ between macOS and Windows for the same disk. They
could later help detect cloned disks.

## Finding roots without scanning

No recursive scan, ever. HeLab remembers where it last found each root:

1. **Listings discover markers.** A names-only listing already returns
   `.helab-root` when present; the helper then reads that small file (new
   marker, changed location, or Refresh).
2. **A local `roots` table** in the store maps location key → UUID, with
   first/last seen, last verified and the user's duplicate decisions. Shares
   use `smb://server/share/...` locations; local volumes use their OS volume ID
   (`vol://<id>/...`, read locally) so two same-named USB disks at
   `/Volumes/USB` never share a location. This is only where a marker was
   seen; data stays keyed by the marker's UUID.
3. **Every key lookup is a longest-prefix match** in that table, without
   source I/O. Local-lane work (cached reads, subtree saves) uses only the
   table, keeping the rule that the local lane never touches source folders.
4. **Late discovery re-keys.** If a deeper marker is found after records were
   saved under an outer root, one local-lane transaction moves that subtree's
   rows to the new root (newer record wins; replaced dataset files are
   retired, not deleted).
5. **Stale entries are corrected by the next listing** of that folder. Once per
   session and mount change, a background request re-reads the known markers
   on mounted volumes (a few small reads).

## Duplicates and copies (Tony, 2026-10-16)

The same UUID seen at a new location is either the same folder reached another
way (another share, mapped drive, server spelling) or a copy. HeLab alerts the
user every time it finds an equivalent location this PC hasn't confirmed yet
(Tony, 2026-10-18), in a non-modal window like the mismatched-folders window.
Answers are remembered per PC, so a confirmed location doesn't ask again:

- **Same folder:** record the location as an alias of that root.
- **Copy:** the user chooses which location gets a new UUID. HeLab rewrites
  that marker (or shows the manual steps). Cached data stays with the location
  keeping the original UUID; the re-assigned one starts fresh.
- Until answered, the new location uses RAM only.
- Hints for the user: same or different server, and the marker files' size,
  modification time and file ID. These are hints; the user decides.
- A cloned USB disk carries its marker, so it is found the same way.

## Relation to other plans

- [Network runners](network-runners-and-web.md#machine-data-root-and-path-identity):
  the root UUID is the logical root ID. Other machines exchange
  `(uuid, relative path)` plus input fingerprints; location keys and server
  addresses stay local.
- [Cache-only browsing](cache-only-browsing.md): offline roots are rows of the
  `roots` table; saved listings are keyed by root.
- [Cache storage](cache-storage-and-settings.md): store tables gain the `roots`
  table and root-keyed paths; Settings → Cache shows roots and their locations.

## Acceptance

- Remounting shares in any order, changing drive letters, IP vs host name, and
  two same-named USB disks each keep their own cache records.
- One folder reached through two mounts uses one set of records after the user
  confirms they are the same folder.
- A copied root is detected when it appears at a new location and never shares
  records with the original once the user chooses.
- Folders without a root use RAM only and say why in one line, with the action
  to enable disk caching.
- No source I/O on the local lane or during rendering; no recursive scans.
- A read-only share can be enabled through the manual marker flow.

## Decisions (Tony, 2026-10-18)

- Marker file name: `.helab-root`.
- When this lands, the existing cache is cleared once more (no re-keying of
  `smb://` rows).
- Markers on every root, local and USB included; no OS volume IDs.
- Equivalent locations are remembered per PC; each newly found one alerts.

## Wording and icon (Tony, 2026-10-18)

- Right-click **Place .helab-root here…**, with checks before writing (not
  the top of its drive or share, inside another root, a system or home
  folder). The **ANCHOR** badge marks root folders beside their status icon.
- RAM only and the .helab-root in use are shown in the Folder details panel
  and the row tooltip; Settings → Data roots lists the known locations.
- "Same folder or a copy?" opens once per location per session; Later asks
  again at the next sighting, Remind me next session not until then.
- Details and the reasons: `.ai/memory/results/data-roots.md`.

## Status

Stages D1–D4 implemented on `dev/data-roots` (2026-10-18), each reviewed;
native checks are in `.ai/MANUAL_TODO.md` (Data roots).
