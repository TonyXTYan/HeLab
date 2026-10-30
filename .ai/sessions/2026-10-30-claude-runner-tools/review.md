# Review: runner tools, `9f0b21f..2c5c9ee` (Reviewer, Claude Opus 5.5, 2026-10-30)

Scope: the milestone lines (`load_done`, `plot_done`, Live's `convert_done`), `app_log.milestone` /
`parse_milestone`, `dev/dev_app.py` and their tests. The decisions are taken as settled: `no_hit`
counts only that run's new no-hit shots, a quiet Live run logs nothing, and `helab convert`'s line
comes after TXY Index. Read against the actual diff, the brief and AGENTS.md.

**No High findings.** One Low should be fixed before landing. The Nits are optional.

## Low

**L1. A Live save is logged as a folder check: `load_done … source=check live=false`.**
`helab/utils/folder_cache.py:4042-4046`. Live's save (`explorer_live.py:426`, every 10 new shots,
at Live off and when the tab closes) is a `load` with `save_memory: True` and no `live` key. It
ends in the same accepted `loaded` branch, so it logs `live=false`, and because it reads no files
(`clock.total_bytes` is 0) it logs `source=check`. Seen in `tests/test_live.py -k save` with
`--log-cli-level=INFO`:

```
MILESTONE load_done folder=…/run shots=4 events=8 seconds=0.004 source=folder live=true
MILESTONE load_done folder=…/run shots=4 events=8 seconds=0.006 source=check live=false   ← the save
```

The failure: a runner that turns Live off, or closes the tab, then waits for or counts
`load_done folder=X` matches the save's line as if the user had opened or checked the folder. The
brief asks for a line when "a folder's load is done", and a save is not one. The fix is one of:
- mark it the way the status path already does (`folder_cache.py:3956`:
  `live=bool(job.payload.get("live") or job.payload.get("save_memory"))`);
- give it its own `source=save`;
- don't log saves.

Add a test for the Live lines either way (`live=true` on a new shot, and the save), since none
covers them now.

## Nits

**N1. `parse_milestone` matches any line that ends in ` MILESTONE <word>`.** `app_log.py:56`
(`_MILESTONE_LINE`, `\bMILESTONE`, not tied to the `helab.milestone:` logger). Example:
`parse_milestone("… root: Live on: /data/MILESTONE load_done")` returns `("load_done", {})`. It
also drops text between fields without saying so: `MILESTONE load_done folder=a junk tail` gives
`{"folder": "a"}`. A folder named like that is unlikely, but a runner that parses every log line
would take a `Live on:` line for a milestone. Anchoring on `helab.milestone: MILESTONE ` (or on
`^MILESTONE ` for a bare message) closes it.

**N2. U+2028, U+2029 or U+0085 in a folder name splits the line for `str.splitlines()`.**
`app_log.py:106`. `json.dumps(…, ensure_ascii=False)` writes these characters literally, and
`splitlines()` breaks on them: `Path.read_text().splitlines()`, the way
`test_the_log_file_line_reads_back` reads the log, then cuts the line in two. Reading the file
line by line (`for line in file`) is unaffected. The fix is to escape those three characters (or
every character `splitlines` treats as a line break) before quoting.

A 20,000-case fuzz of random printable, quote, backslash, `=` and non-ASCII strings round-tripped
exactly through `milestone` and then `parse_milestone`.

**N3. `dev_app.is_stub` lets a malformed Info.plist raise.** `dev/dev_app.py:124` catches
`OSError`, `InvalidFileException` and `ValueError`, but malformed XML raises
`xml.parsers.expat.ExpatError`: checked with a truncated plist, the build stops with a traceback
instead of "isn't a stub made by this tool".

**N4. The launcher's edge cases.** `dev/dev_app.py:53-59, 114`.
- (a) If the `--env-file` is gone at launch, the stub exits 1 with only a stderr line (checked:
  `…/e.sh: No such file or directory`, exit 1), and no alert like the missing-venv case gets. Under
  `open`, stderr goes nowhere, so the app silently doesn't start.
- (b) The env file is sourced before `cd "$CHECKOUT"`, so any relative path in it resolves against
  `/` (where `open` starts). `floor-env.sh` uses absolute paths, so today's use is fine.
- (c) The header comment interpolates `{checkout}` unquoted, so a newline in the path would turn
  into a shell line.
- (d) The alert puts `$PYTHON` inside an AppleScript string, so a `"` in the path breaks the alert
  (it fails silently).

Paths with spaces are quoted correctly: `shlex.quote` covers `CHECKOUT` and the env file, the test
uses `check out/` and `floor env.sh`, and `"$@"` is preserved after `-psn_` is filtered out.

## Checked, no finding

- **GUI thread and I/O.** All three sites only call `logging`. `load_done` is in `_job_event` on the
  GUI thread and is O(shots) in memory. `plot_done` runs on the analysis worker thread, before
  `finished.emit`. `convert_done` runs in `_convert_event`. There are no waits and no new I/O, and
  `milestone` can't raise on the types that reach it (typed `MilestoneValue`; `int()`, `float()`
  and `str()` at the Live site).
- **Privacy (block 29; the log is local).** The only path logged is the folder, which the log
  already writes (`Live on: %s` and others). `output` is the output mode
  (`cache`/`temp`/`beside`, `convert.py:273`), not a path. `plot` is the plot's `instance_id`;
  `script` is the analysis ID. No file names, parameters or data.
- **`convert_done`.** `no_hits` only grows, and `AutoConvert` is recreated (`explorer_live.py:752`)
  when auto-convert goes on, which resets both `no_hits_logged` and `logged_counts`, so `no_hit`
  never goes negative. `shot_converted` events arrive before `convert_summary` on the same handler.
  The first run always logs.
- **`load_done` source.** It uses the same `clock.total_bytes` test as `load_seconds`
  (`folder_cache.py:3983`), so `source` agrees with the "took" shown in the UI.
- **`dev/dev_app.py`.**
  - The release ID is refused, and the tag is restricted to `[A-Za-z0-9-]`.
  - Only a stub of this tool's is replaced, through a staging folder in the same parent.
  - Output goes to `.ai/local/` (gitignored, and `*.app` is gitignored too).
  - It is standard library only, and strict mypy on `dev/dev_app.py` is clean.
  - The built stub's Info.plist matches the notes (version 0.0.6a1 = `_version.py`).
- **Local runs on this floor:**
  - `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: **8208 passed,
    669 skipped, no reruns**, in 126.85 s.
  - `mypy helab/ --strict`, `mypy tests --strict` and `mypy helab/ --strict --platform win32`: no
    issues.
  - `pyright helab tests` and `pyright --pythonplatform Windows helab tests`: 0 errors.

## CI run 40977894008 (`2c5c9ee`)

**Green on all three OSes.** The run's conclusion is `success`, and all 13 jobs that ran succeeded:
Detect, Build ×3, Converter backends ×3 and Tests (1/2)/(2/2) ×3. The compat jobs (3.11, 3.12,
3.14) were skipped, as they are on non-PR runs. Each test job's log was read (API job logs) and
none has a RERUN line or "rerun reasons":

| Job | ID | Result |
|---|---|---|
| ubuntu Tests (1/2) | 123810456929 | 4093 passed, 324 skipped |
| ubuntu Tests (2/2) | 123810456847 | 4114 passed, 347 skipped |
| macos Tests (1/2) | 123810456873 | 4095 passed, 322 skipped |
| macos Tests (2/2) | 123810456942 | 4113 passed, 347 skipped |
| windows Tests (1/2) | 123810457250 | 4081 passed, 334 skipped |
| windows Tests (2/2) | 123810457127 | 4096 passed, 362 skipped |
| ubuntu Converter backends | 123810456780 | 662 passed, 516 skipped |
| macos Converter backends | 123810456784 | 662 passed, 516 skipped |
| windows Converter backends | 123810457046 | 661 passed, 517 skipped |

---

# Round 2: `2c5c9ee..f120395` (Reviewer Moss, 2026-10-30)

**Scope.** The review fixes (`8e12052`), the `test_app_log` level fix (`15c907c`), `helab convert`'s
`convert_done` line (`347748e`), the Windows fixes (`89e1ced`) and the two `dev/v0.0.7` merges
(`0a612d3` TXY Index, `09df6ce` Byte Units).

**No High or Low findings. L1 and N1-N4 are fixed.** Two Nits remain, both optional. Nothing blocks
landing.

## Round 1's findings

- **L1 fixed.** `folder_cache.py`: a Live save now logs `source=save live=true`. Python's chained
  conditional reads as `save` if `save_memory`, else `cache`, `folder` or `check`, as intended.
  `test_a_live_shot_and_lives_save_say_so` checks `(folder, False)`, `(folder, True)`,
  `(save, True)`.
- **N1 fixed.** The parser now matches only `^MILESTONE` or ` helab.milestone: MILESTONE`, with the
  whole tail in the form. The new tests reject another logger's line and junk after the fields. A
  pathological input (5,000 fields then an unclosed quote) parsed in 1 ms, so there is no
  backtracking blow-up.
- **N2 fixed.** U+0085, U+2028 and U+2029 are escaped after `json.dumps`. A new 20,000-case fuzz
  (printable, quotes, backslashes, `=`, `\x0b`, `\x1c`, U+0085, U+2028, U+2029, non-ASCII) gave
  0 mismatches, both for the bare message and for the full log line, and every line stayed one line
  under `splitlines()`.
- **N3 fixed.** `is_stub` now catches `ExpatError`, and a test covers it.
- **N4 fixed.**
  - The stub `cd`s to the checkout before sourcing the env file (tested with `$(pwd)` in the env
    file).
  - A missing checkout, env file or venv now goes to stderr, the system log (`logger`) and an
    alert.
  - Paths with a `"`, a control character or a line break (and a backslash on POSIX) are refused
    when the stub is built.
  - `$` and backticks in a path stay literal: `shlex.quote` covers them, and the variables are
    expanded only inside double quotes. The new test uses a checkout named `check $HOME \`out\``.
  - Windows (`89e1ced`): a backslash is refused only where `os.sep == "/"`, which is right
    because the stub is macOS only and Windows builds are only the tests'.
- **`15c907c`.** `setLevel` instead of setting the attribute is the right cause and fix (setting
  the attribute skips `Logger.setLevel`'s cache clear). The regression test reproduces the order
  dependence.

## `helab convert`'s `convert_done` (`347748e`, `convert_cli.py:148-196`)

- **Same fields and the same quiet-run rule as Live's line.** The rule is `converted`, or
  `no_hit`, or `(unconvertible, waiting, kept)` changed since the last line; the first run always
  logs.
- `--watch` takes one folder (`main`, line 304), so the `_Log`'s `logged_counts` is never compared
  across folders.
- `seconds` is a float (`time.monotonic()` difference, `io_ops/convert.py:717`), and `output` is
  the output mode, not a path. Both match the GUI line.
- The lazy `from helab.utils import app_log` follows the module's lazy-import pattern (the log file
  is started through the same module at line 278).
- `test_each_helab_convert_run_says_what_it_did` covers the in-process counts and the no-line
  quiet runs. `test_helab_convert_once_writes_its_line_in_its_log_file` reads the real command's
  log file.

**N5. `no_hit` means something slightly different in the CLI line than in the GUI line.**
`convert_cli.py:168` vs `explorer_live.py:818`. The CLI adds one for every `shot_converted` with
`hits == 0` in the run. Live counts the growth of the `AutoConvert.no_hits` *set*.
- **Re-converted shot:** a raw file that changes and is converted again (`redo="stale"`) with no
  hits again counts in the CLI line but not in Live's.
- **Failed or cancelled run:** its no-hit shots are dropped in the CLI line (reset at the next
  `convert_plan`, and there's no summary, so no line). In Live they are carried into the next line.

Both are edge cases, and both fit "that run's no-hit shots" loosely. Either align them or say in
the proposed doc that the CLI counts conversions and Live counts new shots.

## The merges

- `git diff 09df6ce^2 f120395` (Byte Units' `b9be661`, the merge's second parent, against the tip)
  touches only this branch's 13 files: the session docs, `dev/dev_app.py`, `app_log.py`,
  `runner.py`, `convert_cli.py`, `folder_cache.py`, `explorer_live.py`, `test_app_log.py`,
  `test_dev_app.py` and `test_milestones.py`.
- In the shared modules the hunks are only the milestone lines, their imports and the two
  `AutoConvert` fields. The merges changed nothing else.
- `origin/dev/v0.0.7` has moved since, to `e74a5cf`. The landing merges onto that tip.

## The handoff's proposals

- The proposals are accurate against the code: the field lists, `source=cache|folder|check|save`
  and the quiet-run rule. The stub's README, testing and runbook notes match the round-1 evidence.
  The RERUN and Windows-cause accounts match CI 40989399407 and the fix.
- **N6.**
  - The `app-runtime-and-ui.md` paragraph could add N5's counting difference if it isn't aligned.
  - `converter.md`'s `helab convert` section could get one line that the command logs
    `convert_done by=cli`.
  - The runbook's "newest `helab-<pid>.log` of the app folder" should say that with
    `--env-file .ai/local/floor-env.sh` the app folder is the floor's (`HELAB_APP_DIR_OVERRIDE`),
    not `~/Library/Caches/HeLab/`.

## Checks (rerun here at `f120395`)

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review`: **8300 passed, 669
  skipped, 2 warnings in 149.06 s, no reruns.** The 2 warnings are pyqtgraph's NumPy 2.5 one.
- `mypy helab/ --strict`: no issues in 191 files.
- `mypy tests --strict`: no issues in 162 files.
- `mypy helab/ --strict --platform win32`: no issues in 191 files.
- `pyright helab tests` and `pyright --pythonplatform Windows helab tests`: 0 errors, 0 warnings.
- `mypy --strict dev/dev_app.py`: no issues.

## CI run 40992860349 (`f120395`)

**Green on all three OSes.** The conclusion is `success`, and all 13 jobs that ran succeeded:
Detect, Build ×3, Converter backends ×3 and Tests (1/2)/(2/2) ×3. The compat jobs were skipped,
as they are on non-PR runs. I read each test job's log, and none has a RERUN line or "rerun
reasons":

| Job | ID | Result |
|---|---|---|
| ubuntu Tests (1/2) | 123859167162 | 4135 passed, 324 skipped |
| ubuntu Tests (2/2) | 123859167148 | 4163 passed, 347 skipped |
| macos Tests (1/2) | 123859167058 | 4138 passed, 322 skipped |
| macos Tests (2/2) | 123859167054 | 4162 passed, 347 skipped |
| windows Tests (1/2) | 123859167073 | 4123 passed, 335 skipped |
| windows Tests (2/2) | 123859166974 | 4144 passed, 363 skipped |
| ubuntu Converter backends | 123859167093 | 693 passed, 516 skipped |
| macos Converter backends | 123859167068 | 693 passed, 516 skipped |
| windows Converter backends | 123859166997 | 692 passed, 517 skipped |
