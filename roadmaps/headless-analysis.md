# Headless analysis

Horizon: headless runner after the analysis workflow, CLI after the headless
runner, batch use later. Added: 2026-10-13. Sequencing clarified by Tony;
interface and lifecycle details are draft.
Priority and completion: [overview](_readme.md).

## Purpose

Run HeLab analyses without opening a window, for repeatable command-line work,
batch jobs and agents. The GUI and headless entry point should produce the same
numerical result from the same dataset and effective settings, through the
[shared job runner](analysis-job-runner.md).

## Current foundation and dependency

TXY loading already runs in isolated helpers, but `IOService` coordinates them
with Qt signals and timers. The current script buttons call `execute_action`
without a selected dataset or validated parameter context. The
[single-run analysis workflow](analysis-workflow.md) must first define a real
data/parameter/result interface, source identity, cancellation and export. A
headless entry point can use Qt's core event loop if helpful, without creating
a GUI; the implementation should share loading and analysis rules rather than
maintain a second scientific path.

## First milestone: headless runner, one analysis and one folder

- Run the shared job service without a GUI or display server, accepting an
  explicit folder, analysis and validated settings through its programmatic
  interface. Keep live jobs and results readable from the GUI and a headless
  client through the same local service.
- Return numerical results plus source identity, effective parameters, units,
  included/excluded shots and load warnings in the shared result format.
- Honour the existing settled-file, missing-shot, cache, large-folder and memory
  rules. Keep source I/O and expensive computation bounded and cancellable.
- Verify that headless and GUI results agree on small fixtures with known answers.

## Second milestone: CLI client

Expose the working headless runner through documented commands for analysis
discovery, parameter description, job submission, status, cancellation and
results. Use machine-readable output, stable exit codes and actionable errors.
Human operators may use separately authorized manual controls; automation and
AI agents must not receive override authority. Pause/resume is offered only
when the analysis adapter supports it safely.

A possible command is `helab analyze <folder> --config ... --output ...`; syntax
and file formats are undecided. Verify CLI and GUI agree for the same request.

## Later: batch and agent use

Accept multiple runs with bounded concurrency, per-run outcome and error records,
partial-success export, cancellation and retry semantics. Build on the
[batch analysis plan](run-comparison-and-batch.md#batch-analysis). The local
runner service and its CLI give agents access to shared jobs; remote API access
is a separate decision.

## Open decisions

- First real analysis and its scientific definitions.
- CLI input/configuration format, output schema and supported export formats.
- Whether to reuse the Qt-backed I/O coordinator in a core-only process or
  extract a transport-neutral orchestration layer.
- How headless jobs select cache settings and coexist with a running GUI instance.
- Exit codes, progress/event format, cancellation and batch retry policy.
