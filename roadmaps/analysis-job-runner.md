# Shared analysis job runner

Horizon: foundation for the near-term analysis workflow, then shared GUI/agent
operation and batch use. Added: 2026-10-13. Direction requested by Tony;
protocol, storage and lifecycle details are draft. **Local runner first**
(Tony, 2026-10-15): build stages 1–2 for the 3D scatter, and keep the design
open to remote coordination later (versioned protocol, job IDs not PIDs,
results with origin identity) without building the service, ownership or
override machinery before a second client needs it.
Priority and completion: [overview](_readme.md).

## Purpose

One runner accepts analysis jobs from the GUI and headless clients, reports
their progress, and keeps results readable by both. It supports analyses written
in Python, MATLAB, Julia, C or other languages through registered adapters.
Existing lab scripts may remain in their own projects behind thin wrappers.
The GUI, CLI and agents use the same job, result and provenance definitions.

## Job contract

- Register an analysis with a stable ID, optional managed version, exact source
  hash, runtime/adapter and declared parameters (defaults, constraints and
  units), input requirements, result
  schema, and execution environment identity. Discovery must not run arbitrary
  analysis code in the GUI process.
- Submit an immutable request with the selected dataset snapshot, shot selection
  and effective parameters. Record input fingerprints and load warnings; a folder
  path or cache hit alone does not identify the data used.
- Give every job a stable ID and explicit queued, running, paused, completed,
  failed or cancelled state, progress/events, timestamps, structured errors
  and references to available result artifacts. Keep numerical values, units,
  script identity (version when managed, filename and hash when unmanaged),
  environment identity and input provenance together. Store large arrays
  and figures as artifacts rather than embedding them in status messages.
- Version the request, event and result protocols so GUI, CLI and adapters can
  evolve without silently misreading older results.

## Execution adapters

The runner schedules bounded work outside the GUI thread. Each registered
adapter receives the same validated request and returns the same result/event
contract. A Python adapter may call Python analysis code; MATLAB and Julia
adapters launch their configured runtimes; a C adapter launches a built program
or wrapper. Thin wrappers can translate older scripts' inputs and outputs
without rewriting their numerical core. Launch only installed/trusted analyses
from an explicit catalogue; an agent request cannot provide an arbitrary
command or code path. Record runtime versions, dependencies and executable or
script identity for reproducibility. Define time, memory, concurrency, logging
and cancellation limits per job without assuming computation uses the source-I/O
queue's limits. MATLAB licensing and installed runtime availability are
capabilities reported by the adapter, not assumed on every lab PC.

## Script catalogue and compatibility direction (2026-10-14)

A repository may bundle several scripts with independent IDs and versions. An
optional HeLab manifest declares each script's version source (such as tags or
files), runtime needs and strict compatibility records. Keep older managed
versions available side by side; record both declared script version and exact
source commit/hash. Plain files, wrappers and repositories without the manifest
remain usable as unmanaged scripts, identified by filename and content hash,
without inferred managed compatibility. If the file's hash changes, warn that
the script changed and its older cached results cannot be trusted as current
or reused for the changed script. Keep those historical results viewable with
their original identity. Discovery and execution must allow this initial path.
Initially, treat compatibility as explicit compatible/incompatible; defer
converters, reserving a future path that covers results **and** parameters.
See [detailed planning](../.ai/sessions/2026-10-14-codex-planning-for-future/remote-headless.md#script-bundles-and-versioned-installation-proposed).

## Shared ownership and reuse

A local runner service is the authority for live jobs when GUI and agents must
observe the same work across processes. Each job records the submitting client,
session and process for display and audit. A control lease/token, rather than
PID alone, determines who may cancel or change it; other clients may attach
read-only to progress and results. Define what happens to a job if its owner
exits before enabling takeover or automatic cancellation.

## Manual control

Both the GUI and CLI may offer human operators the same start, pause, resume and
cancel controls. Keep ordinary job submission and owner cancellation separate
from **manual override** of queue order or another owner's job. Automation and
AI agents must not receive override authority. The service enforces distinct
client capabilities; a CLI flag, terminal prompt or displayed warning alone
cannot prove a human is operating it. Define a human authorization path that an
agent's credentials cannot use, with short-lived grants and an audit record of
operator, reason and action. Overrides never bypass hard memory, concurrency,
source-I/O or cache-safety limits.

Pause is cooperative: the adapter must acknowledge that it reached a safe
boundary before the job becomes `paused`. An external runtime without pause
support reports that capability as unavailable; do not claim success merely
because a pause was requested. Define resource-slot handling and restart
semantics for a paused job before enabling pause for each adapter.

## GUI shutdown with active jobs

When the GUI controls queued, running or paused jobs, closing it asks the user
to choose:

- **Keep jobs running and quit HeLab:** detach the GUI. The service continues
  those jobs and keeps their results available when a client reconnects.
- **Stay and view jobs:** cancel the window close and open the normal Jobs/Runner
  viewer with progress and controls.
- **Stop my jobs and quit:** request graceful cancellation of this GUI's jobs,
  wait for their worker exits and final states, then close. Preserve completed
  results. The runner stays alive if another client still has jobs.

The dialog names the affected jobs and shows other clients watching them before
cancellation. Dismissing it leaves the GUI open. Jobs the GUI only watches do
not trigger this prompt or become its cancellation targets. The service must
have an explicit control-lease policy for jobs left running after their GUI
owner exits; it cannot silently transfer control to a read-only subscriber.

## Reuse

Before starting work, compute a reuse key from the validated input snapshot,
analysis ID and exact managed version or unmanaged source hash, effective
parameters, shot selection and execution
environment. An identical request may attach read-only to a running job or reuse
a completed result; changed input or code must not reuse it. Keep job IDs distinct
from reuse keys, and make an explicit rerun possible. Coordinate data loading
with HeLab's existing helper/cache safeguards so a second client does not start
duplicate source reads or bypass cache-move and large-folder protections.

Keep a submission idempotency key separate from the reuse key: retrying a
submission after a lost reply returns its original job ID, while an explicit
rerun gets a new job ID even when the inputs match.

## Result retention and caching

Retention policies (RAM only, cache on disk, export/keep), script capabilities,
reuse rules and Live result updates are defined once in
[analysis result caching](result-caching.md). The runner enforces them: it
records the policy that took effect, validates capability declarations, computes
the reuse key above and supplies missing shots to Live scripts.

## Staged delivery and acceptance

Progress (2026-10-19): stage 1 partly done in-process (request, result and
identity contract, no adapters); stage 2's worker, cancellation and "selection
can't change input" done in-process (`helab/analysis/runner.py`).

1. Define and test the language-neutral request, event, result and adapter
   contract around one real analysis and known TXY fixtures, including RAM-only
   and disk-retained result policies.
2. Run that analysis through a bounded worker and show its job state/result in
   the GUI, including errors and cancellation; selection changes cannot change
   its input.
3. Run the service without GUI initialization and add persistent job metadata,
   a result index and local IPC. GUI and a programmatic headless client can watch the
   same job; ordinarily only its controller can cancel it. Attach/reuse an identical
   request only after input/version validation. Add role-checked manual controls
   to the service and GUI, with supported pause reported per adapter. Add the
   three GUI shutdown choices and verify that closing one client cannot stop
   another client's jobs. Verify numerical parity.
4. Add a CLI as a client of that working headless service, with machine-readable
   discovery, submission, status, cancellation and result commands. Give human
   operators the same manual controls through a separate authorization path;
   automated clients lack override capability. Wrap one non-Python analysis
   to prove the adapter boundary before claiming broad
   language support.
5. Build [batch analysis](run-comparison-and-batch.md#batch-analysis) on the
   same runner, with per-run outcomes, bounded concurrency and partial results.

Remote runners and a read-only mobile results view build on this local service
in the separate [network extension](network-runners-and-web.md).

## Open decisions

- First real analysis and representative legacy script/runtime for the adapter
  proof.
- Exact dataset snapshot and environment identities, and when a reused result
  must be revalidated.
- Runner process lifetime, owner-exit policy, takeover, and whether GUI and CLI
  use the same service from the first milestone.
- Local IPC transport, result/artifact location and retention policy.
- Result-cache questions: see [result caching](result-caching.md#open-decisions).
- Cancellation guarantees for external runtimes, including their child processes.
- Human authorization for manual override, owner-exit control, and what happens
  to attached readers when an operator pauses or cancels a shared job.
