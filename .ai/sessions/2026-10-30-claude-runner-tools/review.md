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
