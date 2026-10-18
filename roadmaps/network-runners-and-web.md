# Network runners and mobile results

Horizon: after the shared local runner and result records. Added: 2026-10-13.
Direction requested by Tony; transport, path mapping and access design are draft.
Priority and completion: [overview](_readme.md).

## Purpose and sequence

Let one HeLab read results produced by another machine, then share completed
Live revisions and optionally submit new work to that machine's runner. The
initial phone page only views recent compatible results; richer job progress
and controls can follow later. Reuse the
[shared runner's](analysis-job-runner.md) versioned jobs, results, ownership and
adapter protocol. Build local Live updates and result records first, then
remote metadata/result connections, then remote Live updates. Add remote job
submission after data identity, access and failure handling are proven. This
does not expose the current Plotly Dash page, which binds to
loopback and has no job/result or remote-access contract.

## Read-only web view

Start with an authenticated phone page listing recent compatible results;
opening one shows a supported interactive view or static image. The page is
read-only and sends no job commands. The same server may separately expose a
versioned private GET/POST job API to authorized future Apple/Android clients.
Design the read-only routes and service boundary so this can be added without
replacing the result model; the first web milestone need not enable job routes.
Hiding controls in the page is not authorization: enforce read and job-control
roles server-side, without granting repair or manual override by default.
Network exposure, authentication and transport encryption need design before
serving outside the machine. See the [detailed scenario](../.ai/sessions/2026-10-14-codex-planning-for-future/remote-headless.md#live-acquisition-machine-proposed-near-term-scenario).

## Cross-machine result sharing

The machine running an analysis is the authoritative source for its job and
result records. Other HeLabs may search and read permitted results and artifacts
through the same service, or subscribe to job/result updates, without mounting
the source folder or repeating the calculation. A remote result is identified
by its origin machine ID, job ID and result revision, with analysis/version,
effective settings, units, validated input snapshot, warnings and completion
state. Downloaded copies retain that origin and show when the source machine is
offline; they do not silently become locally computed results.

For Live analysis, publish a monotonically ordered result revision or shot
watermark. Readers see the last **completed** revision while the next update
runs, with its shot coverage and age; an in-progress update must not replace a
complete result. Choose publication cadence and retention during design rather
than writing a large result for every incoming shot. RAM-only Live results are
available to remote readers while the origin service retains them; offline
availability requires an explicit saved copy. A machine with the same
dataset may reuse a result only after root mapping and input-snapshot validation.
A machine without that mapping may still view the remote result by job ID, but
must not claim it matches a local folder. Sharing results does not require
copying raw TXY files or sharing the origin machine's SQLite cache.

Normal folder browsing should distinguish local, remote and both result
availability. Exchange metadata and mapped-folder/QC status asynchronously;
offer optional source verification for mapped network volumes. Fetch artifacts
when opened, with Keep local copy and a user-set size threshold for automatic
downloads. New results give a soft status-bar notice by default. Strict
[offline/cache-only browsing](cache-only-browsing.md) shows only local artifacts,
including remote ones already downloaded; it makes no network request.

Peers exchange app protocol, result-schema and managed-script compatibility
capabilities. The first phase uses explicit compatible/incompatible decisions;
unsupported results are labelled, not silently reinterpreted. Conversion of
saved results and parameters is a later extension. The application contract
must be transport-independent so desktop SSH access and later mobile clients
can share its semantics. [Working design](../.ai/sessions/2026-10-14-codex-planning-for-future/remote-headless.md#version-and-capability-synchronization-proposed).

## HeLab-to-HeLab access over SSH

A HeLab client may connect on demand over SSH to another machine's local runner
service, either by forwarding its local protocol or through a small remote
command bridge. The choice is open. Verify the SSH host identity and authorize
the remote client; do not treat a machine name or ID as a credential. The remote
runner owns jobs it executes and reports its capabilities (installed adapters,
runtime versions, limits and data roots). Network loss leaves a truthful
disconnected state; reconnect uses the job ID rather than starting it again.
Remote cancellation and ownership follow the same role checks as local jobs.

## Dispatch and failure handling

Configure a preferred runner for each logical data root so other HeLabs first
look there for an existing job or result. The preference is local per-user
configuration, not an assumption that every mounted copy is equivalent. On
connection, exchange machine identity, protocol/schema versions, available
analysis adapters and resource limits; reject an incompatible request before
starting work.

Remote submission uses a persisted idempotency key. If SSH drops after the
remote runner accepted a request but before it replied, reconnecting with that
key returns the original job ID. A network partition cannot guarantee one job
globally across independent machines: if the preferred runner is unreachable,
show the state as unknown and require an explicit decision before running a
separate job elsewhere. Do not automatically fail over and call it the same
run. After a runner restart, mark uncertain workers as interrupted and check
their outcome before retrying; never silently replay a script with side effects.

Remote jobs obey per-client resource limits and must not starve local browsing
or the machine owner's work. Automation cannot use human manual override to
jump the queue. Transfer result artifacts on demand with size limits and
integrity checks; list metadata before downloading large files.

## Machine, data-root and path identity

The current `cache_paths.py` SMB URL is a **machine-local disk-cache key** for
surviving mount-order changes. It is neither the logical root ID below nor
proof that two machines see the same physical folder: one machine may use a
local path while another uses SMB, and aliases, accounts or shares may differ.
The key includes the server address, so it must not be placed in shared result
metadata either. Do not publish or synchronize SQLite rows by that key. Use
the configured root mapping and validated input snapshot for cross-machine
equivalence.

The share-root identity is the normalized `smb://server/share` URL, without the
account or the local mount-point suffix. Future alias support will reuse the root-equivalence
mapping below for aliases on the **same machine** as well as across machines.
A nested mount whose source URL is a path inside that share maps directly to
the parent share plus that relative path; several mount paths may bind to the
same folder. Separately exported shares can also point to the same physical
directory: for example, `smb://example-server/dld_output` may be the same
folder as `smb://example-server/C/path/to/dld_output`. Their URLs alone do not
prove that. Different server spellings and such separate exports need an
explicit, validated equivalence mapping, not a guessed match.

- Give each HeLab installation a persistent machine ID, separate from its
  changeable hostname, IP address and runner-process ID. Show a friendly name
  and verified SSH identity when pairing machines.
- Give each configured dataset root an explicit logical root ID. Each machine
  maps that root ID to its own local path. Jobs carry the root ID and path
  relative to that root, plus the validated input snapshot; they do not assume
  absolute paths match across machines.
- Configure root equivalence deliberately, including aliases on one machine,
  and verify it against source metadata
  or shot fingerprints before reusing results. A missing or ambiguous mapping
  is an error, not a guessed path. Reject `..` escapes and verify that a
  resolved target stays inside its configured root in an isolated helper.
- Keep source-I/O deadlines and cancellation for remote paths. The current
  browser skips directory symlinks; remote browsing should preserve that
  default. Bound any future recursive traversal with visited directory
  identities, depth and mount-boundary rules so symlink, junction or mounted
  share cycles cannot circulate indefinitely. Alias paths to the same data
  must not create duplicate jobs.

## Browser integration for mapped folders

The folder browser can attach known remote jobs and results to a local row when
its configured root ID and relative path map to the remote source. Show origin
machine, analysis, shot coverage and whether local equivalence has been checked.
Remote result summaries arrive through the runner service into the browser's
memory model; rendering never queries a mount or network endpoint. On selection,
an isolated check validates the current folder snapshot before offering to use
the result as current. Users may view a historical remote result even if that
check fails, but it stays labelled as belonging to the remote snapshot. Offer
the existing remote run/result before starting equivalent local work; handle
multiple machines or revisions explicitly rather than choosing one silently.

Run analysis near the data where possible. Transfer job metadata and result
artifacts by default; copying a large input dataset is an explicit operation
with size and integrity checks. Each machine keeps its own cache store; never
open another machine's SQLite cache over a network mount.

## Local-only settings and portable records

Persist the machine ID, friendly names, paired endpoints, root-to-path maps,
web access choices and user result-retention overrides in durable per-user
application settings outside the Git checkout. Never write real mount paths,
hostnames, IP addresses, SSH usernames or ports into tracked configuration,
roadmap examples, tests or session notes. If the app writes any local file under
the checkout, ignore it from Git. Keep SSH private keys and credentials with
the user's SSH/OS credential facilities, never in a project file.

Portable job/result records use logical root IDs and relative paths for data
provenance; machine-local absolute paths and network addresses stay in local
settings. Shared or exported records omit those local details by default while
retaining the input fingerprints needed to validate a match. A local UI may
still show its own configured path. Tests use invented hosts and paths, verify
settings survive restart, and verify creating connections or root mappings
does not change tracked files.

## Open-source precedents (reviewed 2026-10-13)

These are design references, not selected dependencies. Keep HeLab's runner
contract independent of a particular scheduler so a later compute backend can
be added behind an adapter.

- [Prefect work pools and workers](https://docs.prefect.io/v3/concepts/work-pools)
  ([source](https://github.com/PrefectHQ/prefect)) separate the run service
  from the workers that execute jobs, with queue priority and concurrency
  limits. Borrow the separation of authoritative job records from execution
  and the explicit per-machine capacity model. A full orchestration server is
  more deployment machinery than the first local/SSH HeLab milestone needs.
- [Ray Jobs](https://docs.ray.io/en/latest/cluster/running-applications/job-submission/index.html)
  exposes CLI, SDK and REST clients for submission, status and logs; its
  [REST API](https://docs.ray.io/en/master/cluster/running-applications/job-submission/api.html)
  also exposes stop and version information. Borrow stable submission IDs,
  inspectable status/logs and explicit runtime requirements. Its submitted
  jobs outlive a disconnected client but remain tied to the Ray cluster's
  lifetime; specify HeLab's GUI-exit, network-loss and runner-restart semantics
  independently. A Ray cluster is optional only if later workloads need it.
- [CWL CommandLineTool](https://www.commonwl.org/v1.2/CommandLineTool.html)
  and its [cwltool implementation](https://github.com/common-workflow-language/cwltool)
  describe language-neutral command inputs, invocation and outputs. Borrow a
  small versioned manifest and wrapper boundary for existing MATLAB, Julia,
  Python and compiled analyses; do not require a whole CWL workflow initially.
- [Dask Futures](https://docs.dask.org/en/stable/futures.html) and its
  [dashboard](https://docs.dask.org/en/stable/dashboard.html) show useful
  Python task submission and live diagnostics. Treat Dask as a possible
  compute adapter, rather than HeLab's durable cross-language job/result index.
- [Nextflow resume](https://docs.seqera.io/nextflow/cache-and-resume) and
  [Snakemake between-workflow caching](https://snakemake.readthedocs.io/en/v7.25.3/executing/caching.html)
  motivate explicit cache eligibility and provenance covering inputs,
  parameters, code and software environment. HeLab's validated result-reuse
  key remains distinct from the idempotency key used to recover a submission
  after a lost reply. Do not apply a batch-workflow cache policy to changing
  Live results without revision and shot-coverage checks.

## Acceptance

- First, a phone web page can browse recent compatible results read-only through
  an authorized connection. Later, a separately authorized API client can
  request jobs only within its server-enforced role and cannot call manual
  override.
- Another HeLab can read and subscribe to the origin machine's completed
  results without re-running the analysis or mounting its source folder. A Live
  update shows the last retained completed revision and the shots it covers.
  Reconnection reports explicitly when a RAM-only revision is no longer held.
- Two machines with different mount paths can identify the same configured
  dataset root and validated snapshot. Retrying a submission after a lost SSH
  reply returns the same remote job ID; an unreachable runner never triggers
  automatic execution on another machine.
- A mapped local folder shows available remote results from memory, then
  validates its source in a helper before offering them as matching current
  data. Selecting it can attach to the remote job or read its result without
  triggering an equivalent new analysis.
- Missing/ambiguous roots, changed source files, inaccessible volumes,
  symlink or mount cycles and a disconnected runner produce bounded, explicit
  outcomes. No result is reused solely because paths have matching names.
- Remote work respects owner/read-only permissions and leaves completed local
  jobs and artifacts intact when another client disconnects.
- Machine pairing, root mapping and retention preferences persist locally
  without introducing real paths or network addresses into Git-tracked files
  or default shared/exported result records.
- Incompatible versions or unavailable adapters fail before launch; remote
  jobs respect per-client limits and downloaded artifacts pass integrity checks.

## Open decisions

- Web access path on lab/mobile networks, authentication model and job API
  permissions for future clients.
- SSH forwarding versus a remote command bridge; pairing and key management.
- How roots are registered and verified across machines, especially when a
  shared volume has several aliases or no stable filesystem IDs.
- When to transfer input data instead of executing on the machine that has it.
- Which remote job controls, if any, are available to separately authorized
  mobile clients.
- Live-result publication cadence, retained revisions, artifact download limits
  and when connected clients automatically keep local copies for later offline use.
- Preferred runner selection per data root, resource quotas and the explicit
  fallback offered when that runner is unreachable.
