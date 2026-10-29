# Quick Fixes 6: notes (Rivet, Claude Code)

Base `4132e36` (`dev/v0.0.7`), branch `agent/quick-fixes-6`. Brief: [brief.md](brief.md).

## Job 1: the slow `test_typing.py` tail

### Cause

`tests/test_typing.py` (mypy soft and strict on `helab` and `tests`, pyright on each) holds the six
slowest tests of the suite, and sorts near the end of the collection. xdist's default `load`
scheduling first sends each worker one batch of consecutive tests (a quarter of its share: about 550
of 8800 with `-n 4`), then hands out the rest in small pieces as workers run low; the six were in the
last pieces and went to one worker, which ran them one after another after the other three had gone
idle. Per-worker tails from the CI logs (`[gwN]` result lines; seconds after the first worker's last
result):

| Run | OS | Typing tests on | Their worker's tail |
|---|---|---|---|
| 40790912863 (02cda86) | Windows | gw1, serially, 30-40 s each | ≥126 s, then cancelled at the 30-min limit (30:13) with `test_pyright_tests` running |
| 40790912863 | Ubuntu | gw1, serially, 26-33 s each | 172 s |
| 40790912863 | macOS | gw2, serially, 30-48 s each | 219 s |
| 40793460604 (4132e36) | macOS | gw1 and gw2 (the tail split) | 42 s |

Locally (macOS, `-n 4`): 7-10 s each, serially on gw3, 41 s after the first worker went idle; suite
179 s.

Moving them to the front alone doesn't spread them: they would all sit in gw0's first batch.

### A second cause found on the way (mypy's cache)

Run at once, the mypy tests crashed: mypy 2.4 keeps its cache in SQLite by default
(`.mypy_cache/3.13/cache.db`) and runs `PRAGMA journal_mode=WAL` on every connection
(`mypy/metastore.py:174`); two processes doing that at once give one of them
`sqlite3.OperationalError: database is locked`, reported as `error: INTERNAL ERROR` (exit 2).
Reproduced with four `mypy ... --show-traceback` started together on an empty cache, and through
pytest: `pytest -n 6 tests/test_typing.py` on an empty cache failed 2 rounds of 3
(`test_mypy_helab_strict`). CI always starts with an empty cache. The split tail in 40793460604
already ran two at once; with the typing tests spread, it would have crashed most runs (a RERUN at
best).

### Fix (test-only; no `--dist`, CI or time-limit change)

- `tests/conftest.py`: `pytest_collection_modifyitems` moves the tests of `SLOW_FIRST_MODULES`
  (`test_typing.py`) to where xdist's `load` scheduling starts them on different workers at once:
  slow test `j` at the start of worker `j % workers`'s first batch (`slow_first_positions`, which
  mirrors `LoadScheduling.schedule`: batch = share // 4, at least 2, at most `--maxschedchunk`;
  round robin under 2 tests per worker). With 4 workers: one each on gw0-gw3, then the two pyright
  tests second on gw0 and gw1. The rest keep their order. Workers collect, and read the command
  line's `--dist`: `"no"` with `-n` alone (the controller runs that as `load`), so both count; other
  modes, and runs without xdist, just put them first.
- `tests/test_typing.py`: each mypy test has its own cache folder
  (`.mypy_cache/test_typing/<name>`, ignored through mypy's own `.gitignore` in each), and the type
  checkers run with `cwd=ROOT` instead of `os.chdir(ROOT)` (harmless when they ran last; first, it
  would have moved every later test on that worker into the checkout's root, where a helper started
  meanwhile can refuse sources, as `test_window_icon_is_found_from_any_launch_folder` explains).

### Checks

- Placement: `pytest -n 4 tests/test_typing.py tests/test_uncertainty_format.py tests/test_velocity.py -v`
  ran them on gw3, gw1, gw2, gw0, gw1, gw0 (before: all six on gw0); 50 s → 20 s. `--dist loadfile`
  and a run without xdist pass.
- Cache: 12 rounds of `pytest -n 6 tests/test_typing.py` on an empty `.mypy_cache`: 12 passed
  (before: 2 crashes in 3).
- Full suite, `-n 4 --reruns 5 --reruns-delay 1`, empty mypy cache: before 8465 passed, 353 skipped in
  179 s; after 8465 passed, 353 skipped in 137 s (`--basetemp=.ai/temp/pytest`), the six typing
  results all within 12 s of the first result; and 124 s with the default basetemp outside the
  checkout. No RERUN in any run.
- `--durations=12`, after: the six typing tests are still the slowest (7.8-11.3 s), then
  `test_g2_zero_error_matches_its_scatter` 5.3 s.
- `mypy helab/ --strict`, `mypy tests --strict`, `pyright helab tests`, and with `--platform win32`
  / `--pythonplatform Windows`: clean.
- CI: see the report below.

### CI

(filled in after the push)

### Proposed `roadmaps/known-issues.md` line (fixed)

- CI's Windows test job reached its 30-min limit at 99% (run 40790912863): the six
  `tests/test_typing.py` tests ran last, serially on one xdist worker (2-4 min tail on every OS).
  Fixed in Quick Fixes 6: a conftest collection hook starts them first, one per worker; each mypy
  test has its own cache folder, since mypy runs sharing one SQLite cache crash ("database is
  locked").

### Follow-ups

- A~1: if another module becomes as slow, add it to `SLOW_FIRST_MODULES` (conftest).
