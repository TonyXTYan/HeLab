# Analysis behaviour discovery

2026-10-14. Working design notes from the Maestri blue thread. These record
Tony's stated behaviour and unresolved questions behind the concise
[analysis workflow](../../../roadmaps/analysis-workflow.md),
[QC/repair](../../../roadmaps/quality-control-and-repair.md),
[presets](../../../roadmaps/presets-and-workspaces.md) and
[Live](../../../roadmaps/live-monitoring.md) plans. Nothing here has been
implemented.

## User-facing behaviour Tony specified

- The chosen analysis scripts stay selected when the selected folder changes.
  Unpinned analysis windows/tabs follow the selected folder and show analysis
  for that folder's data.
- Each script declares in code whether it may run automatically or requires
  the user to start it. Available cached results should display even for a
  script that requires a user-initiated run.
- An outdated cached result can display immediately with an `outdated`
  indicator. If that script may auto-run, a new run starts in the background;
  when it finishes, HeLab indicates that the new result is ready to view.
- Pinning fixes a result panel together with its analysis panel. It stays on
  that result when the folder selection changes. A script supports multiple
  instances, so the same script can also run for the newly selected folder in
  another tab. Multiple instances may support future parameter scans.
- A folder can have different parameters for each analysis script. Persist
  values changed from the script defaults; a new folder or newly used analysis
  starts from the script defaults. Examples include X/Y/Z crop ranges, a
  data-dependent auto-crop range and initial guesses for fitting functions.
- A user-level default controls behaviour, with per-folder/per-script
  overrides. Result caching and saving analysis parameters are separate
  toggles. Every saved result remains bound to the exact parameters and
  analysis version used to produce it.
- Quick analyses, including quick scripts during Live, should run on data
  already in RAM without writing each input snapshot or result to disk.
  Stronger retention or a durable input snapshot is for expensive analyses
  or cases that need it during Live. A run still needs enough lightweight
  identity to label any result that is saved or exported correctly.
- Scripts declare three separate capabilities: ordinary caching of a one-off
  run, Live updates, and Live cache updates that advance a prior cached result
  through the Live protocol. The third requires the first two. A Live-capable
  script without Live-cache support still updates in RAM. Only a script with
  Live-cache support offers **Auto-update cache**; its persistence cadence must
  avoid rewriting huge artifacts for every new shot.
- Shot selection and exclusion are settings of one script on one folder.
- Each folder/script pair can choose whether to retain a history of runs and
  set limits such as maximum history length and size.
- Each Live script reports the TXY shots it has already analysed. HeLab knows
  the shots currently loaded in RAM, compares coverage and sends missing shot
  data by the script's declared update method. The contract must accommodate
  different languages and script styles.
- HeLab needs a catalogue of quality-control scripts. Migrate the status-icon
  backend to a QC backend that can combine multiple QC results into one status
  icon. The first QC entry can reproduce today's quick folder checks of
  `d*.txt` and `d_txy*.txt`, keeping their initial behaviour. Another
  script type is needed for file modifications that repair QC findings. A QC
  script may optionally bind to one of these repair scripts and offer a
  user-initiated **Try auto fix** action for a matching finding.
- The QC status icon may show the number of completed QC checks in a
  top-left overlay, distinct from the bottom-right loading spinner. Its
  tooltip gives the per-check findings.
- For now a repair writes a new derived file such as
  `d_txy*_repaired_QC_1_v1.txt`. It never modifies raw `d*.txt` or
  existing `d_txy*.txt`. Analyses use the repaired variant by default for
  that shot, while the original stays available. After successful repair,
  saved analyses using the original are marked invalidated/outdated. Their
  result payloads stay immutable and viewable until a new run produces a
  result for the repaired input. A future HeLab-managed run of
  the `tdc_autoconverter` submodule may introduce a separate, explicitly
  designed TXY-generation capability.

## Proposed state model for discussion

The following is an interpretation to test, not an approved schema:

| Scope | Candidate state | Why it has this scope |
|---|---|---|
| Analysis workspace | Chosen script IDs and the active folder | Script choice survives folder navigation |
| User defaults | Result-cache, parameter-save and other default behaviour | A new folder/script starts with the user's choices |
| Folder + script | Overrides, shot selection/exclusions, history policy | The same script can be configured differently for each folder |
| One run | Stable input reference, effective parameters, selected shots, script/environment identity, result and outcome | Results stay interpretable after selection or source data changes without always copying inputs |
| One analysis instance/view | Script, own parameter controls, shown run/folder, pinned state and layout | Several instances of one script may coexist |

The folder reference needs more than a path for source identity. A persisted
result's identity also needs the actual included shots and selected file
variants/fingerprints, script version, effective parameters and relevant
runtime identity. Switching a shot from its original to a repaired variant
must not reuse an analysis result made from the original. This does not
require a separate disk copy of the input for every run. A quick script can
hold a read-only view of arrays already in RAM for its duration; Live can
publish a new view as shots arrive without mutating arrays used by an active
run. The lifetime of an ephemeral or pinned RAM result still needs limits.
A parameter override is separate state from a cached result: changing one
should not silently make an older result appear current. An instance's
currently edited parameters can differ from saved folder/script defaults;
the exact save/apply behaviour is still open.

## Analysis execution and storage tiers

This is a design direction, not a fixed cost threshold:

| Use | Input/result handling |
|---|---|
| Quick script on current data | Reuse read-only RAM arrays; keep transient result in RAM; no automatic disk write |
| Quick script during Live | Consume current RAM view or missing-shot updates; keep intermediate results in RAM; Live-cache-capable scripts may advance a saved revision under a bounded write policy; ordinary caching may save a separate final one-off result |
| Expensive/long job | Retain a stable input view for the job; optional durable result according to user/script policy |
| Saved or exported result | Record exact input identity, effective parameters, shot selection and script/environment version |

Automatic disk-result caching should be explicit policy with user defaults and
folder/script overrides, not a side effect of every run. Analysis result
caching remains separate from parameter persistence and from HeLab's TXY
dataset cache. Live's existing plan keeps newly loaded shots in RAM and writes
the dataset cache when monitoring stops or HeLab quits; quick analysis updates
must not add a large disk write for each update. The Auto-update cache control
appears only for scripts declaring Live-cache support; it advances a saved
result through the Live protocol with bounded/coalesced persistence and saves
the latest completed revision at Live stop. This differs from ordinary caching
of a completed one-off run. A Live script without Live-cache support stays in
RAM while updating; if it supports ordinary caching, its final result can be
saved as a one-off run under that separate setting. Which script instances
count as the latest results and the checkpoint cadence remain open.

## Candidate folder-selection flow

1. Selection changes the active folder, while chosen scripts remain selected.
   Pinned views retain their original folder/run.
2. Each unpinned view looks up that folder/script's saved parameter and shot
   choices, then finds available cached results. An outdated result can appear
   at once with an `outdated` indicator and its source/parameters visible.
3. If a matching current result exists, avoid duplicate work. Otherwise,
   auto-run a script that permits it in the background; a manual-only script
   offers Run. Keep the displayed result understandable while a new run works.
4. A new run keeps a stable reference to its input and effective parameters/
   shot selection. A quick run may use read-only arrays already in RAM;
   changing folders while it runs does not redirect its input.
5. On completion, signal that the new result is ready to view. Apply the
   folder/script's result-cache and history policies. Multiple instances let
   a pinned old result coexist with a new folder's run.

This flow must also define no-data, unchecked-cache, missing-shot, disabled
cache, failed-run and source-unavailable states before it becomes an
implementation contract.

## QC design questions

Today's quick status is part of the folder-browser metadata path. The proposed
migration makes it the first QC provider and preserves its current checks and
icon meaning initially, rather than running a duplicate scan. The backend
later accepts multiple QC script types and combines their results into a
folder's status QC icon. The icon may show the count of completed checks at
top left; its tooltip lists each check, outcome and date. The bottom-right
loading spinner keeps its present role. Define whether the count includes
stale, skipped or inapplicable checks. The backend must define which checks
consume file metadata, raw `d*.txt`, loaded TXY arrays or analysis results,
and which process may read each input. Browser model rendering remains
memory-only. Aggregation needs severity, provenance, freshness and conflict
rules before more QC providers are enabled.

File-generating repair scripts are a distinct capability from read-only QC
checks. A QC script may declare an optional compatible repair action so a
finding offers **Try auto fix**; clicking it initiates the repair. For now
repair writes a new file and never edits raw or existing converted TXY files.
Design the output name, collision handling, atomic publication, provenance,
selection among multiple repair versions, cache/result freshness and
re-running affected QC. A successful repair leaves old result payloads
immutable, marks them invalidated/outdated in the result index, and prevents
reuse as current for the repaired shot until an analysis reruns. By default,
analyses use the repaired variant for
that shot while retaining the original. The example
`d_txy*_repaired_QC_1_v1.txt` does **not** match today's loaded-TXY
`d_txy_forc<number>.txt` pattern in `helab/utils/file_kinds.py`, so HeLab will
currently ignore it. Recognition must be designed explicitly to avoid
double-counting the original and repaired shot. A future converter runner
that generates ordinary TXY files is a separate feature. QC findings should
not silently exclude shots from an analysis; exclusion policy belongs to the
relevant folder/script settings unless Tony chooses a shared rule.

## Parameter scans (candidate feature)

Multiple instances of one script allow users to compare runs with different
parameters. A parameter-scan meta-analysis could later generate a series of
child runs from a declared parameter range/grid, retain each child's exact
settings/result, and produce an aggregate plot or table. Decide whether this
is merely a UI convenience or a first-class job type with cancellation,
partial-success and reuse rules before implementing it. The idea is not yet
an agreed feature or scientific definition.

## Live-update capability to design

Capability declarations are separate: `cache_supported` covers ordinary
one-off result persistence; `live_supported` covers processing arriving shots;
`live_cache_supported` covers advancing a saved result via the Live protocol.
The last is valid only when the first two are true. The possible states include
Live support without Live-cache support; such a script keeps incremental
results in RAM. A non-Live script may still support one-off caching. The runner
validates declarations before showing **Auto-update cache**.

HeLab maintains the currently loaded RAM TXY set as stable shot identity plus
file variant/fingerprint. For each script instance, apply its folder-specific
shot selection/exclusions before comparing coverage. Each Live script maintains
and reports the exact analysed set, bound to its effective parameters, script
identity and result revision. The runner compares the eligible loaded set with
that acknowledged coverage and supplies only missing shot arrays for a true
incremental adapter. Acknowledged updates prevent duplicate notifications or
reconnects from double-counting. A full-rerun adapter receives a fresh
read-only view instead. Changed, removed or repaired variants are not merely
missing additions: they require invalidating coverage and a declared
recompute/recovery path. The runner must be able to recover the last
acknowledged coverage from a saved checkpoint, or recompute after restart.

Live-cache-capable scripts can update an existing saved result logically while
keeping prior published revisions immutable. They need a declared cache-update
method or checkpoint format; a full rewrite of a huge result for each shot is
not acceptable. The runner should coalesce many shot updates, cap artifact
size/write rate and flush the latest completed revision on Live stop when
enabled. A script unable to stay within that policy keeps its Live work in RAM
until a permitted checkpoint/final save. Exact cadence and recovery semantics
remain open. A saved revision includes shot coverage, effective parameters and
script version or unmanaged hash. RAM updates should not wait for disk
persistence to make progress.

At minimum, distinguish unsupported, full recomputation on a new snapshot,
and true incremental update. An incremental adapter needs an explicit
new/removed/changed-shot message and a rule for recovering after a missed
event; external runtimes may only support full reruns. Capability declarations
must be checked by the runner, not inferred from a GUI toggle. The UI needs
to show whether a result is fixed to a snapshot or following Live data.

## Open decisions to resolve with Tony

- Which outdated cached result appears when several exist? Does completing
  the new run leave the older one visible until the user selects the ready
  result, or switch automatically?
- Which controls have user defaults and folder/script overrides, and does
  disabling saved parameters also disable persistence of shot exclusions?
- What happens to a pinned result and its analysis controls if the source
  folder is removed or its shots change? Can its parameters still be edited
  to create a new run without unpinning?
- Should unpinned views reuse one tab per script, one tab per folder/script,
  or always create a tab for a new run? How does a user reopen a prior result?
- How are several QC findings combined into one icon and explained in a
  tooltip or detail view? May any QC rule change shot inclusion automatically?
- How are generated repair files named and mapped to shots without loading
  both repaired and original variants? If several repairs exist, which
  successful variant wins by default? How do repairs invalidate cached
  datasets, QC findings and analysis results?
- What does the QC-count overlay include: only current completed checks, or
  also saved/stale findings, skipped checks and inapplicable checks?
- For quick or Live results kept only in RAM, what are the memory and lifetime
  limits, especially for pinned panels and optional history?
- At Live stop, which latest quick results are saved: one per active script,
  one per script instance, or only results visible in panels?
- Does a live-capable script choose its own update method, or can a user opt
  between supported full-rerun and incremental modes? How are partial updates
  validated against the full calculation?
- Where do parameter overrides, caching choices and history policy live
  locally, and how do they survive cache clearing and folder moves?
- Defaults and eviction rules for per-folder/script history; whether pinned
  results and exported results are exempt from automatic removal.

## Design documents this discussion may lead to

The concise behaviour now lives in the linked roadmap plans. This note retains
the interaction flows and unresolved schema choices for implementation. The
shared dataset/job/result contracts belong with the analysis runner and
refactoring design. The roadmap overview remains the only priority/completion
list.
