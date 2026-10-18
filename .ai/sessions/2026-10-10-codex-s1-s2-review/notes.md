# S1/S2 implementation review

Reviewed the uncommitted changes against `roadmaps/cache-storage-and-settings.md`.
No implementation files were edited.

## Re-review after Claude's update

The P1 below is **resolved**. `read_saved` reads the underlying shard directly
under the transaction in both `begin_scan` and `write_outcome`, preserving
SQLite read errors instead of treating them as an absent history. Three new
regression cases cover automatic/details scans and outcome writes.

Reran the original reproduction: modes `metadata`, `skipped`; no source status
event; a `disk I/O error` history warning; `blocked=True` afterward.
No further actionable S1/S2 findings identified.

Fresh validation: focused contention/history/import tests 28 passed; full suite
426 passed, 1 skipped, 2 xfailed (same categories of Dash port-in-use and
deprecation warnings); strict mypy, Pyright and `git diff --check` passed.

## Finding

**P1 — S1 still interprets a history read error as an unblocked folder.**
`begin_scan` (`helab/utils/scan_history.py:113`) calls `FanoutCache.get` inside
the transaction. The transaction fixes write contention, but `FanoutCache.get`
also catches `sqlite3.OperationalError` and returns its default, even with
`retry=True`. `parse_history(None)` produces an empty, unblocked history, so
`begin_scan` overwrites the saved failure and allows the automatic scan.

Reproduced with a private temporary two-shard cache:

1. Save a timeout outcome for a folder containing one converted TXY file.
2. Patch the underlying `diskcache.Cache.get` to raise
   `sqlite3.OperationalError("disk I/O error")` only for that folder's history
   key. Leave the FanoutCache wrapper, transactions and writes intact.
3. Call `scan(..., manual=False, automatic=True)`.

Observed: `blocked=True` before; modes `metadata`, `scan`; a source status
event; no history warning; `blocked=False` afterward. This contradicts the
finished-S1 note that nonmanual scans skip unreadable history. The existing
history-error test patches `begin_scan` to raise directly, bypassing the
wrapper that actually swallows the error.

Use an error-propagating history read under the transaction, distinguish an
absent key from a failed read, and skip nonmanual scans on read errors. Add
the underlying-shard error case to the regression tests.

No actionable S2 regression found. The fresh-interpreter import test passes;
the plain report, formatter move and removal of legacy shutdown dependencies
match S2. Remaining cache/Settings rebuild requirements belong to later steps.

## Validation

- Focused S1/S2, scan-history and responsiveness tests: 68 passed.
- `venv/bin/pytest -q -n 4`: 423 passed, 1 skipped, 2 xfailed.
  Seven warnings included Dash server port-in-use thread exceptions.
- `venv/bin/mypy helab tests --strict`: passed, 100 source files.
- `venv/bin/pyright helab tests`: zero errors and warnings.
- `git diff --check`: passed before writing this note.

These checks ran on macOS with Python 3.13; no native UI or real-volume checks
were performed.
