# F0b notes: design and choices

Branch `agent/dld-f0b` from `e7d0aba` (agent/dld-f0a). Items marked **proposed** are
choices made while Tony was away, for him to confirm.

## Layers and where they live

| Layer | Set in | Stored | In memory (what runs read) |
|---|---|---|---|
| Default | `physics.CONSTANTS` | code | `physics.DEFAULTS` |
| Lab | Settings → Lab parameters | QSettings `lab_constants/<key>` (only values set) | `FolderCache.lab_constants` (`set_lab_constants`, from the main window at startup and after Settings) |
| Folder | Right-click › Folder constants… | store table `folder_constants` (helpers only) | `FolderCache.folder_constant_records`; `effective_folder_constants(path)` |
| Plot | the plot's Constants group | the plot's parameters | its parameter tree |

- The lab tab lists the rows with `level == "lab"`; the folder dialog the rows with
  `level == "folder"` (fall distance, fall time, trap radial, trap axial). `resolve`
  still accepts any key at any layer, so a plot can override any constant.
- **Release time is not built** (no table row yet): it has no default (it comes from
  the data, D8). Proposed: D8 adds a `release_time` row then, with its own
  "from the data" origin; `ResolvedConstants` would need a non-finite-safe record.

## Store change (additive)

`CREATE TABLE IF NOT EXISTS folder_constants (path TEXT PRIMARY KEY, record TEXT NOT NULL,
set_at REAL NOT NULL)`; record = `{key: number}` JSON. Nothing else in the schema
changed (the `datasets` table is untouched, so agent/dld-d7's `raw_times` column merges:
a trial merge of agent/dld-d7 went through without conflicts).

- `CacheStore.read_constants(paths, keyed_only=False)`, `set_constants(path, values,
  set_at)`. The newest `set_at` wins, as for the folder flags; restoring every value
  keeps the row, so an older choice arriving late can't bring values back.
- **Cleared:** never by Clear all, purges, making room or a data root's Clear cached
  data (`clear_root`), and not by the Cache tab's "Forget folder choices" (flags only):
  like the flags, they are the user's choices. Only the dialog's Restore removes a
  value. **Proposed**: a Cache-tab row to forget every folder's constants, later, if
  wanted.
- A nested root's re-key (`rekey_subtree`) moves them, newer wins.
- Written only by `io_helper.cache_admin("constants")` on the local lane; a folder the
  helper can't key (no data root, unsupported mount) is answered `session_only`.

## Coming with listings

- Each listing entry carries `constants` (the subfolder's own record) beside `prefs`.
- `_send_saved` (listings and scans) also sends one `folder_constants` event with the
  listed folder's own record and those of every folder above it that has a key in the
  store (one read; up to 64 levels): a tab's top folder and the folders above it are
  never rows, but their values are inherited.
- A read error leaves a folder out (unknown, never "none set") and sends a `cache_warning`.

## Inheritance (proposed)

A folder's values apply to it and to its subfolders that don't set their own, per
value, from the nearest folder at or above, **up to and including its data root**
(inner roots stop inheritance from outer ones: they are separate data). A folder
without a known root inherits up to the top of its drive (session values only).

One exception keeps `resolve`'s pairing rule: a fall time set in a folder above the
folder that sets the fall distance isn't used with that distance; the run derives it,
√(2h/g) (`constant_layers.folder_layer`). The dialog says "A folder's values apply to
it and to its subfolders that don't set their own, up to its data root."

## RAM-only folders

`FolderCache.constants_session_only(path)` gives why (disk cache off, no
`.helab-root`, a pending duplicate root, or the helper's `session_only` answer). Such
values are kept in memory only (never sent to a helper), the dialog shows an amber
"RAM only · kept for this session only: …", and the context-menu tooltip says so.

## Plot overrides and resolution (compatible with agent/dld-d1)

- `AnalysisContext.constants` has **D1's name and shape**: `{"lab": {…}, "folder": {…}}`
  (the layers). `AnalysisInstance._submit` fills it for every plot from memory
  (`constant_layers(path)`), so D1's `plot_constants(values, context.constants)` gets
  real values after the merge with no change.
- `AnalysisContext.resolved_constants` (new): for an analysis that declares constants
  (`DatasetAnalysis.constant_keys`, default: the keys of its `constants_specs` group),
  the runner resolves them at submit with `DatasetAnalysis.run_constants(action,
  values, layers)` (default: `resolve_for_run` over the Constants group's choices).
- `AnalysisResult.constant_layers` and `.resolved_constants`; `constants_record`
  (`{"layers": …, **as_record()}`) goes into `reuse_key()["constants"]`, and
  `describe()` adds a "Constants: …" line with every value and origin.
- `constants_specs(keys)`: per key a choice `const.<key>.from` ("lab/folder" or "this
  plot") titled with the constant's name, and `const.<key>` (the plot's value, SI
  prefixes for m/s/Hz, shown only when set here). After each run (and on a change) the
  choice's title shows the value and source: "Fall distance h: 0.848 m (folder)".
- The source line's second line gets "constants: …" for values not from the table
  defaults (e.g. `g 9.8 m/s² (lab) · h 0.9 m (folder) · t_f 0.4286 s (derived)`) and the
  fall-time note; the Constants group is left out of the parameter text
  (`without_constants`, also in `describe_run`'s default).
- A released plot's reload runs with the layers it was drawn with.

## Open decision 5 (proposed, as suggested)

When a lab value or a folder's values change (`FolderCache.constantsChanged`, "" for
the lab, else the folder; plots of that folder or below listen), each plot that uses
constants resolves again with the parameters it was drawn with and, if any of its keys
differ, shows the amber line "⚠ constants changed (<titles>): Rerun to use them". It
keeps its plot. Rerun and the next Live update resolve anew; the note goes when the
drawn result matches again (also when the value is changed back).

## Other choices

- The folder dialog is window-modal (`open()`), saved on Save; a failed save puts the
  stored values back and the tab shows "HeLab couldn't save the constants for X: … Try
  again." (as for flags).
- Lab tab statuses: "default", "set here", "shown only", amber "unconfirmed" while an
  unconfirmed row is at its default; CODATA rows show "CODATA, read-only".
- Settings tab order: General, Lab parameters, Scripts, Cache, Data roots.
- Local-lane keying of a folder on a volume not yet verified this session may answer
  `session_only` ("no .helab-root") where it would be saved after verification; rare
  (the folder was just listed), noted for later.
