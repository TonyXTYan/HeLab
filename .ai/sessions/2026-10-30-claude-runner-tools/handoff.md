# Handoff: runner tools (`agent/runner-tools`, Worker Kestrel, Claude Opus 5.5, 2026-10-30)

Brief: [brief.md](brief.md). Detail and evidence: [notes.md](notes.md).

## What was built

1. **Milestone log lines** (computer-use notes item 2). One INFO line on the logger
   `helab.milestone`, in HeLab's log file, when a long step ends:
   `MILESTONE <event> key=value …`, keys in a fixed order per event.
   - `app_log.milestone(event, **fields)` writes every line and `app_log.parse_milestone(line)`
     reads one back typed, so the form can't drift. `logging` only: memory, no waits.
   - `load_done` (`FolderCache`, where an accepted `loaded` becomes a `Dataset`):
     `folder shots events seconds source=cache|folder|check|save live` (`save`: Live's save of its new
     shots, `live=true`, never taken for a check of the folder).
   - `plot_done` (`AnalysisRunner._finished`, every job end, worker thread):
     `script version action plot job seconds state=ok|failed|cancelled`.
   - `convert_done` (Live auto-convert, `explorer_live` on `convert_summary`; `helab convert`,
     `convert_cli._Log`): `folder by=live|cli converted no_hit unconvertible waiting kept output seconds`.
     Every count is the run's; a run that changed nothing logs no line (agreed with CoCo).
   - Privacy (block 29): the only path written is the folder, which the log already wrote.
2. **A bundle ID for source runs on macOS** (item 7). `dev/dev_app.py` builds
   `.ai/local/HeLab-dev.app` (gitignored): bundle ID `au.edu.anu.he-bec-lab.dev`, name `HeLab-dev`,
   an executable `sh` script that `exec`s the checkout's `venv/bin/python -m helab "$@"`. Shown
   working on this Mac (lsappinfo, osascript, CGWindowList; [notes](notes.md#evidence-macos-26-darwin-256-this-floor-2026-10-30)).
   No app code changed.

## Files

| File | Change |
|---|---|
| `helab/utils/app_log.py` | `milestone`, `parse_milestone`, the form's constants |
| `helab/utils/folder_cache.py` | the `load_done` line (and the `app_log` import) |
| `helab/analysis/runner.py` | the `plot_done` line (and the import) |
| `helab/views/explorer_live.py` | the `convert_done` line, with two `AutoConvert` fields (`no_hits_logged`, `logged_counts`) for this run's no-hit count and the quiet-run rule (CoCo OK'd the counter) |
| `helab/convert_cli.py` | the `convert_done` line (`by=cli`) in `_Log`, with its two counters (`no_hits`, this run's, reset on `convert_plan`; `logged_counts`), after TXY Index landed (`347748e`) |
| `dev/dev_app.py` | new: the stub builder |
| `tests/test_milestones.py`, `tests/test_dev_app.py` | new |
| `tests/test_app_log.py` | `test_each_helab_writes_its_own_log_file` raises the root level with `setLevel` (CoCo's OK; see RERUN below) |

## Review (Moss, [review.md](review.md))

No High. Fixed in `8e12052`: **L1** (a Live save logged as `source=check live=false`: now
`source=save live=true`, with tests for a Live shot and the save), **N1** (the parser matches only
the bare message or a `helab.milestone:` line, every field in the form), **N2** (U+0085, U+2028,
U+2029 escaped), **N3** (`is_stub` on a malformed plist), **N4** (cd before the env file; a missing
checkout, env file or venv said on stderr, in the system log and an alert; a path with a quote,
backslash (in a POSIX path) or control character refused at build; the env file's path through a variable).

## RERUN (for known-issues' Fixed section)

**`tests/test_app_log.py::test_each_helab_writes_its_own_log_file`**, once in seven `-n 4` runs of
the touched test files (gw0), failing all 5 reruns. Rerun reasons, each the same:

```
E           AssertionError: assert 'from 101' in ''
E            +  where '' = read_text(encoding='utf-8')
tests/test_app_log.py:134: AssertionError
```

- **Cause:** the test raised the root level with `monkeypatch.setattr(root, "level", INFO)`, which
  skips `Logger.setLevel`'s cache clear. After any INFO line logged at WARNING earlier in the same
  worker, the root logger's cached "INFO is off" held, so the log file came out empty. It is
  order-dependent and predates this branch: two full suites here, Moss's and CI's never hit it.
  Reproduced every time with a one-line test (`setLevel(WARNING); logging.info(…)`) run just
  before it.
- **Fix** (`15c907c`): `root.setLevel(INFO)`, and the old level restored in its `finally`. The
  repro is kept as `tests/test_milestones.py::test_the_log_file_tests_hold_after_an_info_line_at_warning`.
  It fails without the fix and passes with it.

## Checks

Branch at `347748e` (`dev/v0.0.7` `c492242`, TXY Index, merged in `0a612d3` with no conflicts), macOS 26 (Darwin 25.6):

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest`: **8275 passed, 669 skipped,
  2 warnings in 156.09 s**, no reruns (the 2 warnings: pyqtgraph's NumPy 2.5 `arr.shape` deprecation
  in `test_t_spectrum.py`, not this branch's).
- The same without `--basetemp`: **8275 passed, 669 skipped, 2 warnings in 176.37 s**, no reruns.
- `mypy helab/ --strict`: Success, 191 files; `mypy tests --strict`: Success, 162 files;
  `pyright helab tests`: 0 errors, 0 warnings; `mypy helab/ --strict --platform win32`: Success,
  191 files; `pyright --pythonplatform Windows helab tests`: 0 errors, 0 warnings.
- CI run **40989399407** (`bf7a3a5`): red on Windows only, both Tests jobs (macOS, Ubuntu and every
  Converter backends and Build job green, no reruns in them). Two causes, both this branch's, neither
  flaky (each failed all 5 reruns), and one known RERUN:
  - `tests/test_dev_app.py` (4 tests): N4's `plain()` refused every backslash, Windows' separator
    (`The checkout 'C:\Users\…\check out': a quote, backslash or control character in it`). Now
    a backslash is refused only where `os.sep` is `/` (a POSIX name; the stub is macOS only), and the
    backslash case of the refusal test is skipped on Windows.
  - `tests/test_milestones.py::test_helab_convert_once_writes_its_line_in_its_log_file`:
    `FileNotFoundError: …\app\logs\helab-3484.log`. A venv's `python.exe` on Windows runs Python
    as a child, so `Popen.pid` isn't HeLab's; the test now reads the one log file in its own app folder.
  - One RERUN not this branch's, passed on its rerun: `tests/test_io_service_run.py::test_writing_held_data_out_counts_as_progress`
    (`assert (2 == 1)`, `where 2 = len([0.0015683999999964726, 0.0016781000000491986])`,
    `tests\test_io_service_run.py:40`), already in known-issues.
- CI after the fix: the run of its push; its ID and jobs are in the report to CoCo (a docs-only push would run CI again).

## Proposed doc changes (for the Coordinator)

**`.ai/architecture/app-runtime-and-ui.md`, Logging** (append to the paragraph):

> Milestones: when a folder's load, a plot's compute or a conversion ends, HeLab logs one INFO line
> on `helab.milestone`, `MILESTONE <event> key=value …` (`app_log.milestone` writes every one,
> `parse_milestone` reads it back): `load_done` (`folder shots events seconds source=cache|folder|check|save live`,
> from `FolderCache`), `plot_done` (`script version action plot job seconds state=ok|failed|cancelled`,
> from `AnalysisRunner`), `convert_done` (`folder by=live|cli converted no_hit unconvertible waiting kept
> output seconds`, Live auto-convert and `helab convert`; not for a run that changed nothing). A
> runner (the smoke pass) waits on them in the log file; the only path in them is the folder.

**`.ai/architecture/testing.md`** (or the smoke runbook's setup), a line:

> On macOS a source run can be driven by computer use through `python dev/dev_app.py
> [--env-file .ai/local/floor-env.sh]`, which builds `.ai/local/HeLab-dev.app` (bundle ID
> `au.edu.anu.he-bec-lab.dev`, its own `--tag` for a second checkout); `open` it, never
> `venv/bin/helab`, and quit it before opening it again (`open` while it runs drops the new
> arguments; `open -n` makes a second instance with the same ID).

**README, Setup step 4 (Run), a note** (proposed wording):

> - On macOS, to drive a source run with computer-use tools (which need a bundle ID), build a small
>   app stub once: `python dev/dev_app.py`, then `open .ai/local/HeLab-dev.app --args …`. It runs
>   this checkout's `venv/bin/python -m helab` as "HeLab-dev" (`au.edu.anu.he-bec-lab.dev`).

**Smoke runbook** (`.ai/sessions/2026-10-28-claude-smoke-automation/plan.md`):

- `START_COMMAND` on macOS may be `open <checkout>/.ai/local/HeLab-dev.app` (after
  `python dev/dev_app.py --env-file …`) instead of the built `dist/HeLab.app`; the target is then
  bundle ID `au.edu.anu.he-bec-lab.dev`, so a running release HeLab never answers for it.
- Waits: instead of reading the summary line from screenshots, wait for the log's
  `MILESTONE load_done folder=<FOLDER>` (and `plot_done … plot=<id> state=ok`,
  `convert_done … by=live`), in the newest `helab-<pid>.log` of the app folder (Help › Show log
  folder; the pid is `lsappinfo info -only pid -app au.edu.anu.he-bec-lab.dev`).
- A source run ignores arguments it doesn't know, so `--geometry` works once the Smoke ready floor
  lands it: `open …/HeLab-dev.app --args --geometry 1600x928+0+39`.

**`roadmaps/smoke-automation.md`**: item 6's "a bundle ID for source runs on macOS" done
(`dev/dev_app.py`); the milestone lines as a new done item.

## Follow-ups (provisional IDs)

- **M~1** A computer-use screenshot of HeLab-dev's window: `python dev/dev_app.py --env-file
  .ai/local/floor-env.sh`, `open .ai/local/HeLab-dev.app`, then a computer-use screenshot that
  targets `au.edu.anu.he-bec-lab.dev` shows the main window (this floor's shell has no Screen
  Recording grant, so the window was shown only by CGWindowList: on screen, 1600×928, owner
  HeLab-dev). Also check the menu bar's app name (Qt may say "Python" or "HeLab").
- **A~1** A small `dev/` wait helper for runners (`wait_milestone.py EVENT [key=value …] --log
  <file> --timeout S`, built on `parse_milestone`), if the runbook's waits want more than `grep`.
- **A~2** When Beacon's `--geometry` lands, check it through the stub
  (`open …/HeLab-dev.app --args --geometry …`).

## Open

None for Tony.
