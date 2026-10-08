# Windows Python 3.13 pytest failure

Investigated GitHub Actions run 37733918120, Windows job 113169058022,
at commit f68abf909209c73c1480a163a6ced27d8f351965 using gh CLI.
The job's Run Tests step failed with nine metadata restoration failures;
its overall conclusion is cancelled because the workflow cancels on failure.
Use --log (not --log-failed) to retrieve this cancelled job's failures.

Local uv venv: Python 3.13.16. Reproduced the same nine failures
(305 passed, 4 skipped, typing tests excluded for the initial reproduction).
Default pytest temp directory was inaccessible in the sandbox; created
.ai/temp and used an explicit --basetemp under it.

Cause: Windows DirEntry.stat(follow_symlinks=False) returns st_dev/st_ino
as zero, while os.stat returns actual IDs. The details scan compared zero
IDs against saved summaries/history created by os.stat, treating unchanged
folders as replacements and discarding their metadata.

Changed helab/io_helper.py's details scan to use
os.stat(entry.path, follow_symlinks=False), consistent with _summary.
The source stat stays in the isolated helper, outside the GUI thread.

Validation: python -m pytest -q --basetemp=.ai/temp/pytest-fixed
completed with 320 passed, 4 skipped, 1 existing logging.warn deprecation
warning in 97.69 seconds. This includes all six typing tests.
git diff --check passed. No commit or push performed.

Scratch logs: .ai/temp/ci-windows.log and .ai/temp/pytest-fixed.log.
