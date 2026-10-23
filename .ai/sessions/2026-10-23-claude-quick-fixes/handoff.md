# Quick fixes, batch 1: handoff (Rivet, 2026-10-23)

Branch `agent/quick-fixes` from `2994870`, not pushed (CoCo pushes the batch). Details, evidence
and the proposed known-issues lines: [notes.md](notes.md).

| Job | Outcome | Commit |
|---|---|---|
| 1 presets window "worker crashed" | **Fixed.** A hang, not a crash: a still-quitting app-wide FolderCache left by an earlier test refused the presets, and `apply` waited on a modal warning. Reproduced in a Linux container | `66b771a` |
| 2 scatter teardown `TypeError` | **Open, diagnostics.** Raised by Qt from C, with no traceback; not reproduced. Such errors now name the code running Qt's event loop | `e326fdf` |
| 3 Live I/O pause, Windows | **Fixed (probable timing).** The wait fails only on 10 s without progress, and says where | `6dcf8f2` |
| 4 dead helper "Broken pipe" | **Fixed in code.** A helper gone before its request was written is reported as exited, with its stderr logged | `6597740` |
| 5 mtime tick (R-23) | **Fixed.** R-23 confirmed and applied | `73ec41b` |
| 6 `test_activation_sources` | **Open, nothing new.** No rerun in 23 runs; covered by the job 1 and 2 diagnostics | — |
| 7 `presets.py` blank line | **Fixed** | `3a529cd` |

Notes commit: `7394e1b`.

## For the CI push

- `pytest.ini` now has `faulthandler_timeout = 100`: any test running over 100 s dumps every
  thread's stack, which xdist shows, before CI's 120 s timeout kills its worker ("node down: Not
  properly terminated" was a timeout all along for job 1). It doesn't fail the test.
- Two small autouse fixtures in `tests/conftest.py`: `no_quitting_cache` (job 1) and
  `where_qt_raised` (job 2).
- At the next CI rerun of job 2 or 6, the rerun reason should end with "(No traceback: raised by
  Qt outside Python code, while this ran its event loop:)" and the frames.

## Proposed doc changes (for CoCo)

- `roadmaps/known-issues.md`: the lines in notes.md, per job. The summary line under "Tests and CI"
  ("note these four…") could add that a "worker crashed" on CI with no traceback is usually CI's
  120 s timeout, whose stacks `faulthandler_timeout` now prints.
- AGENTS.md › Testing could add one line: "A worker 'crashed' under xdist with no traceback is
  usually `--timeout` (CI: 120 s): look for the faulthandler dump at 100 s."

## Linux repro (Docker)

Docker Desktop is installed on this Mac but was stopped; I started it for this batch (still
running). `linux-container/`: `Dockerfile` (Ubuntu 24.04 arm64, CI's apt packages plus the
libraries the arm64 QtWebEngine wheel needs, `requirements.lock`), `run.sh <loops> <pytest args>`
and `suite.sh <loops> <pytest args>` (the full suite, `-n 4`, CI's timeout). Use:

```bash
docker build -t helab-ci-linux .ai/sessions/2026-10-23-claude-quick-fixes/linux-container   # after copying requirements.lock there
git ls-files -z | grep -z -v '^legacy/' | COPYFILE_DISABLE=1 tar --null -T - -czf <dir>/src.tgz
docker run --rm --shm-size=2g -e QTWEBENGINE_DISABLE_SANDBOX=1 -v "<dir>:/in:ro" -v "<out>:/out" \
    helab-ci-linux /in/suite.sh 3 -q -rfE
```

Root in the container needs `QTWEBENGINE_DISABLE_SANDBOX=1`. Five tests always fail there (they
need `.git` or pyright, which the copy lacks): `test_typing.py`'s two pyright tests,
`test_versioning.py`'s two provenance tests and `test_release_recovery.py`'s PR-stamp test.
