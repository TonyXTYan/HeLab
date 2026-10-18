# Data roots: smaller follow-ups

Open items found while reviewing D1–D4 and the fixes that followed (2026-10-18).
Tony chose to do the placement rule, Show/Delete in Settings › Data roots,
clearing one root's cached data, and a warning for unresolved duplicates now
(`dev/root-placement`). These are left for later, most useful first.

- **Remove .helab-root… in the tree's right-click menu** on a root folder,
  where Place is greyed now. It would reuse `root_remove` from Settings ›
  Data roots.
- **The duplicates window shows only the first known location** when a root
  is known in several places (D4 limit). A list of every confirmed location,
  with its hints, would help choose.
- **NFS and AFP mounts could use the disk cache.** They are refused because
  their mount sources once lacked a stable identity. The marker now gives the
  identity; only a location key such as `nfs://server/export/…` is missing.
  The lab doesn't use them; WebDAV stays unsupported.
- **A label can't be changed.** The marker is write-once by design. A
  per-PC display name in the roots table could cover typos.
- **A USB disk swapped between verifications** is caught only by
  `shots_missing` when its cached shots aren't there. Verification runs at
  startup and after a mount change.
- **`roots_verify` can wait a long time** behind steady background work,
  since it goes after anything queued later. Nothing waits for it, so stale
  markers only show later.
- **Folders without a root keep scan-failure history for the session only**,
  so a failing folder may be retried in each session (automatic scans are off
  by default).
