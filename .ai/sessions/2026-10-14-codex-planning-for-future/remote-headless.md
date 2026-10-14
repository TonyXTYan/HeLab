# Headless runner, remote results and cache-only browsing

2026-10-14. Working notes from the Maestri blue thread. These record Tony's
direction and open interaction rules; the existing
[headless](../../../roadmaps/headless-analysis.md),
[network](../../../roadmaps/network-runners-and-web.md) and
[cache-only](../../../roadmaps/cache-only-browsing.md) plans now summarize the
agreed direction. This note holds the detailed flows and open design choices.
No implementation has started.

## Direction Tony confirmed

- `helab` remains the GUI entry point. `helab --headless` should start a
  long-running local runner without a window. `helab analyze` is a one-shot
  CLI request that places an analysis job in that runner service.
- The GUI and CLI should use the same analysis, QC, dataset and result
  definitions. A headless service provides computation and state, not a
  text copy of every GUI panel. Additional CLI clients can expose discovery,
  jobs, results, QC and cache operations as they are designed.
- HeLab machines exchange result metadata over a channel still to be
  selected. During ordinary folder browsing, a row can indicate locally
  cached analysis, remotely available analysis, or both. Metadata arrives
  asynchronously into the browser's memory model; model rendering does not
  perform a network call.
- Remote artifacts are fetched when opened. A user can keep a local copy,
  and a user setting can automatically download completed copies smaller
  than a configured MB threshold. The origin machine and result revision
  remain visible on downloaded copies.
- Offline/cache-only browsing means truly offline, such as on an airplane:
  show local cached results and remote results only when their artifacts
  were downloaded already. Do not show merely last-known remote availability.
- Machines may run different HeLab and script versions. They need a way to
  exchange compatible metadata, capabilities and results without assuming
  identical installations.
- HeLab should retain separately installable script versions. A repository
  may bundle several scripts with independent script IDs and versions.
  Initially, compatibility is a strict compatible/incompatible decision;
  conversion of old results and parameters is deferred.
- “Sync machines” means sharing metadata about available results and QC/
  folder status for deliberately mapped shared network folders, with optional
  validation of folder equivalence. It does not mean automatically installing
  HeLab or scripts on another machine. New remote updates get a soft status-bar
  notice by default, not a popup.
- The initial phone web page is a read-only list of recent compatible results.
  Opening one shows a supported interactive view or static image. The same
  server may separately offer an authenticated job API to authorized clients;
  the web page does not expose job controls.
- A far-future Apple-platform client may live in a separate repo and offer a
  result viewer plus job-request client on iOS, iPadOS, visionOS or watchOS.
  macOS could use either the PyQt app or an Apple client. Keep the result/job
  contract independent of the first desktop transport.
- The staged use case begins with one machine monitoring new raw `d*` files,
  converting settled input to TXY and running several fast analyses in RAM
  for local use. Connect other machines for metadata/result access next;
  notify/push remote Live revisions after those connections work. The first
  phone page only views recent compatible results.

## Agreed delivery order (2026-10-14)

1. Build the local dataset, job/result record and Live-update behaviour with
   no remote dependency. The local acquisition/conversion/QC/quick-analysis
   path exercises these contracts.
2. Connect machines for compatible metadata and result discovery/viewing,
   mapped-root status and on-demand artifact fetch. Keep the first phone page
   view-only, with a service boundary that can later support an authorized API.
3. Share completed Live revisions and notifications across those connections.
   Receiving clients choose manual or automatic updates/downloads under policy.
4. Add remote job requests/controls and richer mobile clients after identity,
   authorization and disconnection handling are proven.

These are dependency stages, not a commitment to a transport or release date.

## Process and command boundaries (proposed)

`helab --headless` means a service that can outlive a GUI/CLI client and owns
active jobs and result records. `helab analyze ...` submits one request to
that service and returns a stable job ID; whether it waits and streams
progress by default is open. Both use the same local runner contract as the
GUI. Starting headless mode must dispatch before `QApplication` or GUI
imports. Today's I/O coordinator uses Qt signals and timers, so a
`QCoreApplication` event loop may still be useful. The frozen executable's
windowed/console packaging is a separate decision.

The runner is the authority for the jobs it executes. Two GUI/headless
processes must not bypass cache locks or independently write the same
analysis result index. Establish clear service ownership and local IPC
before adding remote clients. Quick Live intermediate results remain in RAM.
Ordinary one-off caching, Live updates and Live cache updates are separate
script capabilities. Only the third permits Auto-update cache to advance a
saved result during Live, with bounded/coalesced writes and a final flush at
Live stop. See the [Live capability model](analysis-behaviour.md#live-update-capability-to-design).

## Remote browsing and results (proposed)

The network plan currently proposes SSH between HeLab machines but leaves
SSH forwarding versus a small remote command bridge open. It also proposes
logical data-root IDs mapped to local directories on each machine, with
shot/file validation before a remote result is called equivalent to the
selected local folder. A remote result can still be viewed without such a
mapping, labelled with its origin and input snapshot.

Tree badges should distinguish local saved results and remote available
results, including both at once. Their tooltip/detail view needs analysis ID,
origin machine, input coverage, result age/revision and whether local
equivalence was validated. Results are indexed in memory for rendering.
Opening a remote result fetches only its needed artifacts with integrity
checks. An auto-download size threshold is based on the total artifact
bytes and should not turn every Live revision into a write. Downloaded
copies keep origin provenance and follow local retention settings; machines
never open each other's SQLite/TXY cache directories.

## Version and capability synchronization (proposed)

Do not require every HeLab to run the same app or script version. On
connection, exchange protocol and result-schema versions, machine/root IDs,
analysis/QC IDs and versions, runtime capabilities, and available
result revisions. The origin executes with its installed script version and
records that exact version in each result. A recipient can display a result
whose schema it understands even if it cannot run that script locally.
Unsupported records remain labelled as such; do not reinterpret them with
the recipient's newer/older script or treat them as locally reproducible.

Record compatibility for HeLab's wire protocol, record schemas and each
script's input, parameter and result schemas separately. For the first phase,
each version declares strict direct compatibility or incompatibility with
the preceding version, in both reading directions where relevant. A chain
of adjacent compatible flags alone does not prove that distant versions are
compatible: advertise or verify the supported version pairs/ranges before
opening or reusing a result. Unknown compatibility is incompatible. Preserve
the original result, its parameters and its producer version. If no direct
read is supported, show limited metadata and an incompatible status rather
than guessing or rerunning with a different script.

Leave an extension point for later converters, but do not require or expose
them in the first phase. A future converter must migrate the complete saved
analysis record, including result artifacts **and** parameters, while
preserving the original and recording conversion provenance. Its semantics,
trust model and user workflow remain to be designed.

Use ordered event/revision IDs so a subscriber can reconnect and ask what
changed after its last acknowledged update. Exchange metadata first, then
fetch chosen artifacts subject to size and integrity checks. A local copy
preserves origin and version provenance. Result reuse against a local folder
still needs source-root mapping and input validation; matching names or app
versions alone are insufficient.

This synchronizes knowledge of jobs and results; installation remains a
separate operation. A recipient lacking the producer's script can still view
a supported result schema, but cannot rerun that version locally until the
appropriate trusted script/runtime is installed.

## Script bundles and versioned installation (proposed)

A managed script repository/bundle can publish multiple scripts, each with a
stable script ID, its own version series, compatibility declarations and
runtime requirements. An optional, simple HeLab manifest in the repository
declares each script and **how its versions are identified and located**:
for example, repository tags, a version file, or another declared resolver.
The convention belongs to the script/bundle, not to a single hardcoded Git
tag pattern. It should be possible to add older conventions through manifest
schema revisions or trusted adapters without rewriting each legacy script.
The manifest also identifies compatibility records per script version; do
not infer compatibility from a version number or repository tag alone.

`helab/_version.py` versions the HeLab application. A script's declared
version is separate, and its repository commit/content hash records exact
source provenance, including development runs. One bundle commit may contain
different versions of different scripts. Install managed script versions side
by side so an older result can be traced to, and when permitted rerun with,
its exact producer version. An individual Git submodule checkout pins one
commit, so it cannot itself expose every historical version concurrently.
Side-by-side immutable checkouts or packages and isolated runner processes/
environments will be needed, especially when versions have conflicting Python
dependencies. Support published historical versions and installation of a
needed older version on demand; decide the default preinstallation/retention
policy later.

Plain script files and scripts in repositories without the HeLab version
manifest remain supported through compatible files or explicit wrappers.
They are **unmanaged**: HeLab identifies each by filename (scoped by its
installed source) and content hash, plus runtime identity for provenance.
It cannot infer compatibility or a managed version from a filename such as
`abc_v123.py`. If a file's hash changes, warn the user that its code changed;
older cached results remain historical and viewable but are not trusted as
current or eligible for reuse with the changed file. One repository without
the contract is handled like a collection of plain files. Current
`ScriptsManager` imports
and instantiates discovered Python files in the GUI process; versioned
installation and discovery should move execution into isolated workers
before loading many versions or untrusted bundles.

For unmanaged scripts, a result may still be rendered when its standard
result schema is directly supported. Its recorded hash identifies the exact
producer; it does not establish that another file or revision accepts old
parameters or inputs. An initial runner can support unmanaged files first,
then add manifest-backed installation without changing job/result identity.
Managed resolution should read declared metadata before executing script code,
separate repository-level provenance from each bundled script's version, and
allow a manifest schema or trusted resolver to describe older conventions.

For deliberately mapped copies of a shared network folder, sync reported
folder/QC status with source machine, observation time, logical root ID and
relative path. Another machine may optionally verify source fingerprints
before treating that report as current for its own mapped folder. Without
verification, label it as remotely reported; a matching folder name alone
does not prove equivalence. Send these summaries asynchronously into the
browser's memory model. A new update raises a short status-bar message by
default, with details available on request and no popup.

## Live acquisition machine (proposed near-term scenario)

The source machine is the authority for an ordered per-shot path:

1. Detect and settle a new raw `d*` file without blocking browsing.
2. Submit one versioned converter job; publish a new TXY file atomically and
   never overwrite an existing raw or TXY file. Record converter version and
   input/output identity. Handle restarts and duplicate notifications without
   converting one shot twice.
3. Run applicable QC and several fast analyses on the resulting RAM data for
   local use. Keep intermediate Live results in RAM. Record completed revisions
   with shot coverage, exact script identity, parameters and warnings.
   Live-cache-capable scripts may advance a saved result under the bounded
   write policy when Auto-update cache is enabled.
4. At the remote-access stage, serve the completed job/result model to an
   authenticated, read-only phone web page. The phone need not speak SSH
   or access raw/TXY files.
5. After remote connections are available, notify subscribed HeLabs that new
   Live revisions are available. A recipient may show a notification/manual
   refresh, auto-update an open result view, or auto-download under its
   configured size limit. These are distinct choices; receiving a result does
   not mean rerunning the analysis locally.

The first web page lists recent results that the web viewer can render.
Opening one shows a supported static image or interactive result. Its viewer
credential can only read records and artifacts. The same server can later expose
a separate, versioned private GET/POST API for authenticated Apple/Android or
other clients to request and manage jobs. Hiding controls in the page is not
authorization: enforce client roles and per-operation permissions on the
server. Job-request clients do not inherit repair or human override rights.
Unsupported result formats are omitted from the web list and are never
silently converted in the phone browser.

Persistent subscriptions should be initiated by each receiving HeLab, so
the source machine need not open connections to every client. On reconnect,
clients use ordered revisions to catch up. Keep conversion, QC, computation,
remote transfers and phone serving bounded so they do not starve the source
machine's foreground browsing. The exact transport and web authentication
remain design decisions.

This scenario should guide the refactoring seams: one source-I/O owner,
one converter/repair distinction, a shared dataset view, a versioned
job/result catalogue, and UI/web clients that observe completed revisions
without reading the source folder.

## Offline/cache-only interaction

The current cache-only plan explicitly says its tests should deny
source-folder **and network** access. Tony confirmed a strict interpretation:
offline mode does not advertise remote results whose artifacts are absent.

| Source state | Result metadata shown | Opening a result |
|---|---|---|
| Normal browsing | Local cached and asynchronously queried remote summaries | Fetch remote artifact on demand; optional small-result auto-download |
| Offline/cache-only mode | Local cached results and downloaded remote results only | Open local artifacts; no SSH request, download or remote-only badge |

This works on an airplane. A distinct **source unavailable but network
allowed** workflow, if wanted later, would be a different mode. Do not
silently relax offline mode's no-network promise. Headless/CLI offline
requests need the same source and network gates rather than an alternate
path that can accidentally touch either.

In connected modes, an old remote result can be opened as historical provenance.
It is not labelled current for a local folder merely because root/path
names match. Without source validation, the UI reports that current
equivalence is unknown. If a local artifact is missing or evicted, cache-only
mode reports that honestly instead of loading from source or remote.

## Transport independence and later Apple clients

Define versioned request, event, result and metadata operations independently
of the connection mechanism. A desktop HeLab may initially use an SSH bridge
or forwarding, while the authenticated HTTPS server can expose authorized
operations to future Apple/Android clients. The phone web page remains
read-only. A client app that requests jobs has a distinct role and
authorization, not the web viewer's credential or human manual-override
rights.

This is a long-term compatibility constraint, not a commitment to build
four Apple apps now. A macOS PyQt client and a macOS Apple client could both
use the same service contract. Keep machine-specific directories and SSH/
web credentials in local settings; shared records use logical roots and
relative paths.

## Open choices

- May the optional small-result auto-download run during normal background
  browsing, or only after a user opens a folder/result? What exact size and
  disk-budget defaults apply?
- Does `helab analyze` return after submission by default, or wait for the
  result unless given a detach flag?
- How is the long-running runner started on login, discovered by GUI/CLI,
  stopped and recovered after crashes? Can a GUI start it on demand?
- SSH forwarding versus bridge; pairing/authentication; result metadata
  sync cadence and compatibility policy for older result schemas. Which
  job API operations should client roles get, and how are credentials issued?
- Which result types count toward the auto-download threshold, especially
  a result with several large plots/arrays or a stream of Live revisions?
- Does a receiving HeLab auto-update an open result view, only notify, or
  choose per script/view? What is the default?
- How does the producer recover a converter job interrupted between settled
  raw input and atomic TXY publication? Which machine is allowed to convert
  a given logical root?
- What minimal manifest schema and trusted version resolvers cover tagged,
  file-declared and older script conventions? Which published versions should
  HeLab preinstall and retain by default? How are version-specific dependencies
  isolated and removed safely?
- Which result/parameter schema forms the first strict compatibility contract?
  Later, who authors and tests complete result-plus-parameter converters?
- How long to retain remotely reported folder/QC statuses and how the user
  opts into source-fingerprint verification for a mapped network volume.
