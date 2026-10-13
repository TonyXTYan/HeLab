# Network runners and mobile results

Horizon: after the shared local runner and result records. Added: 2026-10-13.
Direction requested by Tony; transport, path mapping and access design are draft.
Priority and completion: [overview](_readme.md).

## Purpose and sequence

Let HeLab users see job progress and completed analyses on a phone, let one
HeLab read results produced by another machine, and optionally submit new work
to that machine's runner. Reuse the
[shared runner's](analysis-job-runner.md) versioned jobs, results, ownership and
adapter protocol. Deliver read-only web and cross-machine result access first;
add remote execution after data identity, access and failure handling are
proven. This does not expose the current Plotly Dash page, which binds to
loopback and has no job/result or remote-access contract.

## Read-only web view

Serve an authenticated, phone-sized view of job state, progress, provenance,
warnings, numerical results and available plot/artifact previews. It reads the
runner's stored results and live events; a phone need not load TXY data or run
an analysis. Start with read-only access. Network exposure, authentication,
transport encryption and access scopes must be designed before serving it
outside the machine. The web view does not grant manual override controls to
automated clients.

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

- Give each HeLab installation a persistent machine ID, separate from its
  changeable hostname, IP address and runner-process ID. Show a friendly name
  and verified SSH identity when pairing machines.
- Give each configured dataset root an explicit logical root ID. Each machine
  maps that root ID to its own local path. Jobs carry the root ID and path
  relative to that root, plus the validated input snapshot; they do not assume
  absolute paths match across machines.
- Configure root equivalence deliberately and verify it against source metadata
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

- A phone can view an active job and its completed result read-only through an
  authorized connection, and cannot call manual override operations.
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

- Web access path on lab/mobile networks and its authentication model.
- SSH forwarding versus a remote command bridge; pairing and key management.
- How roots are registered and verified across machines, especially when a
  shared volume has several aliases or no stable filesystem IDs.
- When to transfer input data instead of executing on the machine that has it.
- Which remote job controls, if any, are available to human operators on mobile.
- Live-result publication cadence, retained revisions, artifact download limits
  and whether offline readers keep a local copy.
- Preferred runner selection per data root, resource quotas and the explicit
  fallback offered when that runner is unreachable.
