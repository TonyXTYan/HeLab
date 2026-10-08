---
date: 2026-10-09
status: settled
name: subfolder-derived-status
description: "A folder's status from its subfolders: 'something' if any listed subfolder has data, 'nothing' only when all were checked and empty, else its own; saved (folder-subtree-v1) so it survives restarts, tooltip says saved vs derived just now; never recursive"
metadata:
  node_type: memory
  type: result
---
Rules Tony chose (2026-10-08/09) for showing a folder's status from its
subfolders in the active browser. Code: `SnapshotFileSystemModel._derive`,
`FolderCache.save_subtree`, `io_helper._subtree_info` / `save_subtrees`.
Tests: end of `tests/test_two_step_browse.py`.

- A folder's own result (`report`) is unchanged: own TXY data always wins, and
  a derived status never makes a folder loadable.
- Derived from the subfolders listed in the tab, each counted with what it
  shows (its own status, or its own derived/saved one):
  - any subfolder with data → `something`;
  - listing complete and every subfolder checked and `nothing`/`missing` →
    `nothing`;
  - some subfolders unchecked → the folder's own status (`unknown`).
- Only when no listed subfolder was checked (or the folder is not listed)
  does the **saved** result show. A recheck follows the subfolders' current
  status, e.g. B emptied → A `nothing`.
- **Never recursive**: deriving reads only direct subfolders' in-memory
  statuses; listings attach each subfolder's saved result from the local
  cache, nothing deeper. Why: walking saved descendants could be a very long
  recursion.
- **Saved so it survives restarts** (Tony: more useful than session-only):
  `("folder-subtree-v1", path)` in `data_ram_cache` with status, `derived_at`,
  folder identity, `older`, and data/checked/total subfolder counts. Saved only
  after a complete listing and only when status or outdated hint differs from
  the saved one; an empty folder listing removes it. Written by a batched
  `subtree_save` helper (500 ms debounce, one at a time, up to 256 records) in
  the **local lane**: it touches only the local cache, so it never waits for
  source I/O. Other tabs see it at once through `FolderCache.subtrees`.
- **Tooltip**: `Subfolders: 3 · TXY data in 1` when derived now, with
  `· saved <date> (<age>)` when the saved result shows; see
  [[folder-row-tooltip]].
- **Outdated hint (clock icon)**: derived now → `something` when every data
  subfolder (or the folder) may be outdated, `nothing` when any may be; saved →
  its `older` flag or the folder modified after `derived_at`. A folder's mtime
  changes only with its direct entries, so changes deeper down show on the
  subfolder, not the parent. No timer expires a derived status.
- **Expandability is cached too** (Tony, 2026-10-09): an unlisted folder
  whose saved summary says it has no subfolders (`has_dirs`) shows no expand
  arrow, instead of an arrow that vanishes when clicked. Unknown stays
  expandable. Selecting the row lists it (or, cache first, the load's listing
  reports `has_dirs`), and the arrow returns if subfolders appeared. The tree
  updates the arrow through the row's `dataChanged`; no layout reset needed.
