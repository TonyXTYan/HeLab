# Brief: D7 shot times

Worker task from the Coordinator (Tony asleep), branch `agent/dld-d7`, base 1231025
(`agent/dld-front-panel-port`). Worker: Claude Code, Worker role
([agent workflow](../../../roadmaps/agent-workflow.md)). Commit on the branch, no push, no merge.

## Authority

- [DLD front-panel plan](../../../roadmaps/dld-front-panel-port.md), Decided › **Shot times**
  (Tony, 2026-10-20): a shot's time is its raw `d<N>.txt` file's mtime. The TXY's mtime is when
  it was converted, and a converter catching up gives many shots the same time. If the raw file
  is gone, use the TXY mtime and say so.
- D7 in the [review notes](../2026-10-20-claude-dld-front-panel-review/notes.md#d7-shot-times):
  per-shot plots against wall-clock time, gaps between shots; a copied or rewritten file has a
  new mtime (say so in the tooltip).

## Task

1. Plumbing: get each shot's raw mtime from the helper's existing listing with the least extra
   source I/O; carry per-shot times (and which are fallbacks) with the dataset through loaded,
   memory/updated, merged, cached and Live paths and the disk cache; expose them on
   `DatasetView`. Old caches stay readable (unknown → TXY fingerprint mtime, flagged). Raw files
   must not affect fingerprints or reuse.
2. Analysis: a `DatasetAnalysis` in `helab/scripts/standard/` (Basic plots v1, PyQtGraph):
   counts per shot against shot time (date axis) and the gaps between shots, with the shared
   Shots selection, fallback times marked and counted in the dock line.
3. If the plumbing is much bigger than expected, stop at a clean tested intermediate.

## Acceptance

Helper tests with set mtimes (raw times; missing raw → fallback; cache round trip; memory and
updated loads; old-format cache; Live new shots; deleting a raw file doesn't invalidate the
cached shot), the plot's compute and empty cases; mypy --strict helab and tests, pyright, diff
check, full suite (two known root-only failures ignored). AGENTS.md, roadmaps/, .ai/memory/ and
.ai/MANUAL_TODO.md not edited.
