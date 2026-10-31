# Brief: I/O fixes, the area review's io findings (`agent/io-fixes`)

Coordinator: CoCo, 2026-10-31. Tony (Chat, via Side; Q28.1): the area review's I/O fixes land **before
caching v2's stage 1 reaches `folder_cache.py`**, so this floor is on the critical path. The findings,
with scenarios, scratch tests and fix directions, are in the area review's `io.md` (branch
`agent/area-review`, `573361f`: `git show 573361f:.ai/sessions/2026-10-31-claude-area-review/io.md`).
One Worker; one Reviewer at landing. Hybrid floor (`roadmaps/agent-workflow.md`, "Feature floors with named areas").

**Areas:** `io` (owner). Boundary with `cache` (io-5 touches `CacheStore.confirm_dataset`).

## Read first

`AGENTS.md` (I/O and threads: slots held until exit, no GUI waits, bounded queues, settle time);
`.ai/architecture/io-and-browsing.md`, `live.md`, `cache-store.md` (save guards); the area review's
`io.md` and `cache.md`.

## Base and branch

Base `0571ff2` (`dev/v0.0.8`). Branch `agent/io-fixes`. Running beside you: Plot Identity (`plots`) and
Caching v2 (`cache`; its first steps are new store-v4 modules and stay out of `folder_cache.py` until you
land). Merge `dev/v0.0.8` when CoCo says, before your final push.

## Objective (in this order; commit each separately)

1. **io-1: the mismatch hold** holds only what it must: not saves or Live checks; quitting lifts it.
2. **io-2: `load:<choice>` jobs** are forgotten when they end, so the next load of that choice runs and
   its arrays are freed.
3. **io-3: a Live save isn't cancelled** because another listing moved the folder's snapshot ahead of RAM.
4. **io-4: a shot Live found unreadable** that the writer then finished doesn't halt Live or drop the
   folder's data.
5. **io-5: a load that finds the cache whole** also checks the signature (the review's first direction,
   in `loading.py`, is preferred: it keeps you out of `cache_store.py`; if you need `confirm_dataset`
   to take the signature, say so and keep the change minimal).
6. **A39.2 (Q38.2, Tony 2026-10-31): Live takes HeLab's TXY for a shot held from MATLAB's**: under HeLab
   priority, a HeLab TXY converted during Live replaces the shot held from MATLAB's TXY, read again as a
   changed shot (as a HeLab-held shot converted again is), instead of waiting for the folder's next load
   (`fefe6ab`; `.ai/AI_TODO.md` A39.2).
7. **io-6, io-7, io-8 (Low)**, each where the fix is small; otherwise a known-issues proposal.
8. **The four "Unverified notes"**: confirm each with a test or show it can't happen; fix what's real
   and small, propose the rest for known-issues.
9. **Docs proposals** in the handoff (`io-and-browsing.md`, `live.md`, known-issues), provisional
   `Q~`/`A~`/`M~`.

Each fix gets a test that fails before it (the review's scratch tests are a start).

## Rules

Owned paths: `helab/utils/folder_cache.py` (jobs, lanes, Live, mismatch hold, RAM budget),
`helab/utils/io_service.py`, `helab/io_helper.py`, `helab/io_ops/` except `convert.py`, `helab_txy.py`,
`stores.py`, `admin.py`; `helab/views/explorer_live.py`; their tests. Ask CoCo before any other file
(`cache_store.py` included). Strict typing (incl. `--platform win32`, `pyright --pythonplatform
Windows`); tests never touch real data; the full suite (`-n` with `--reruns 5 --reruns-delay 1`) before
the handoff, every RERUN reported with its reason. Docs only in `.ai/sessions/2026-10-31-claude-io-fixes/`.
Push at checkpoints only; before reporting a CI run, read every Tests and Converter backends job's log for
RERUN (`.ai/memory/feedback_ci_reruns_in_logs.md`). The landing needs the Reviewer with no open findings
and CI green on 3 OSes by run ID. No version bump, release, tag or PR.

When done: `maestri ask "CoCo" "I/O Fixes: done at <hash>, suite <N> passed, RERUNs <…>, CI <run>"`.
