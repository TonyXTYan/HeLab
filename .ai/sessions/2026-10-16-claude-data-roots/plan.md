# Data roots: single-machine plan

Session: Terminal #4 (Claude), 2026-10-16. Roadmap: [data roots](../../../roadmaps/data-roots.md).
Status: decisions confirmed 2026-10-18; S0 committed, ready to start D1.

Builds on the SMB cache-key change ("S0", [notes](../2026-10-15-codex-status-remount/notes.md)):
its mount-table capture, `CachePaths.key`/`source` hook in `CacheStore`, and the
unresolved-path → no-disk-cache handling are reused. Its `smb://` keys become
location keys only.

## Tony's direction (2026-10-16)

- Disk caching requires a root identity; without one, RAM only. No fallback.
- Network drives get a hidden JSON marker file, created on request
  (right-click a mount root or drive letter). Without write permission, show
  the UUID/contents to place manually, or Save as… elsewhere.
- (Superseded 2026-10-18) Local and USB volumes use the OS identifier.
- Two locations with the same UUID: alert; the user says whether it is the same
  folder or a copy, and for a copy picks which location gets a new UUID.
- Nested markers: `C/` and `C/.../dld_output` have different UUIDs; the nearest
  marker wins, so `dld_output` reached through C or through its own share
  shares one cache. No full tree scan: remember the last root found near a path.

## Decisions (Tony, 2026-10-18)

1. Marker file name: `.helab-root`.
2. Clear the existing cache once more when D1 lands; no re-keying of `smb://` rows.
3. Markers on every root, local and USB included (a local disk may be shared
   over the network, where only the marker is visible). No OS volume IDs as
   data identity.
4. Equivalent locations are remembered per PC; each newly found one alerts.

One detail kept from the OS-ID idea: the `roots` table's **location** key for a
local volume includes its OS volume ID (`vol://<id>/relative`), read locally in
the helper. Otherwise two same-named USB disks share the location
`/Volumes/USB`, and a cached read before the next listing would use the other
disk's root. Network locations keep the `smb://server/share` key.

## Stages

Each stage lands separately with tests; nothing reaches lab PCs until D4.

### D1 Root resolver and store (no GUI change beyond RAM-only)

- `helab/utils/data_roots.py` (or extend `cache_paths.py`):
  - parse and validate markers (`version`, `uuid`; unknown fields ignored);
  - location keys: `smb://server/share/rel` (S0) for shares; `vol://<id>/rel`
    for local volumes, from macOS `getattrlist` (`ATTR_VOL_UUID`; the APFS volume
    group ID for the startup disk, since `/` is the sealed snapshot and
    `/Users` is firmlinked to the Data volume), Windows `GetVolumeInformationW`
    serial, Linux `/dev/disk/by-uuid`. All injectable for tests;
  - data key = `root://<uuid>/rel` from the nearest known marker; no root →
    `UnresolvedRemotePath` (renamed, e.g. `NoDataRoot`), so the existing skip
    path makes it RAM-only.
- Store: `roots` table (location key, uuid, kind, label, first/last seen,
  verified_at, decision). Store version bump (clean slate per decision 2).
- `CacheStore` uses the root resolver for `path_key`/`source_path`; source
  mapping returns the location currently mounted for that root.
- Tests: fake mounts and roots; nested markers; startup-disk firmlink case;
  remount/suffix swap; Windows letters; same-name USB disks at one path;
  no root → nothing
  read or written. Existing tests keep identity keys (default `CacheStore`).

### D2 Discovery and re-keying

- `list` notices `.helab-root` among names; the helper reads it (timeout,
  heartbeat), updates `roots`, sends `root_found` / `root_changed`.
- Local lane uses only the `roots` table (no source I/O).
- Re-key op (local lane, one transaction): move a subtree's rows from outer to
  inner root; newer wins; retire replaced dataset files; send `removed`/`rekeyed`
  so `FolderCache` resets those paths' flags.
- Background verification of known markers once per session/mount change.
- Tests: late nested discovery re-keys rows; stale entry corrected by listing;
  deleted marker → RAM-only; local lane never touches source.

### D3 GUI: enable and status

- Tab line when RAM-only: "Disk cache off: no data root · Enable…" (single line;
  detail in tooltip). Also replaces S0's silent `cache_skipped`.
- Right-click **Enable disk cache here…**: confirm, exclusive-create the marker
  with hidden attribute, read back; adopt an existing one.
- No write permission: dialog with file name, JSON, Copy, Save as…; Refresh
  finds the placed file.
- Root badge and tooltip for root folders; Settings → Cache lists roots and
  their known locations.
- Folder flags and other disk-cache menu items disabled with the reason when
  RAM-only.

### D4 Duplicates and docs

- `root_duplicate` event → non-modal window (pattern of `MissingShotsWindow`):
  Same folder / Copy (choose which location gets a new UUID) / Later. New
  location RAM-only until answered. Decisions stored in `roots`.
- Copy: rewrite the chosen marker (or manual flow); cache stays with the
  original location.
- Docs: AGENTS.md cache-key paragraph, memory result, MANUAL_TODO native
  checks: SMB marker from macOS and Windows (hidden attribute), read-only share
  manual flow, two mounts of one folder, copied USB/folder, firmlinked startup
  disk paths, TDC converter/MATLAB ignore the file.

## Risks and checks

- Marker read cost: one small read per discovered marker; never per folder.
- Writing to a share changes its root folder's mtime (one full check).
- Two PCs enabling the same folder at once: exclusive create; the loser adopts.
- Copies made while HeLab is closed are only detected when both locations are
  seen; until then each location's cache is valid for what it lists, and TXY
  fingerprints still protect datasets.
- Without a root, scan-failure history is session-only, so failing folders may
  be retried each session (auto scan is off by default).

## Later (network plan)

The root UUID is the logical root ID: machines exchange `(uuid, relative path)`
with input fingerprints; location keys stay local
([network plan](../../../roadmaps/network-runners-and-web.md#machine-data-root-and-path-identity)).
