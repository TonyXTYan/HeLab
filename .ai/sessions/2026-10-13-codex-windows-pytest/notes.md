# Windows pytest investigation

Tony reported plain `pytest` crashing at session finish with WinError 5 for
`%TEMP%\pytest-of-XinTong\pytest-current`.

## Findings

- Python is the checkout's uv venv, Python 3.13.16; HeLab imports from this checkout.
- `python -m pip check`: no broken requirements.
- `pytest -x -q` outside the Codex sandbox reached 100%, with no test failures,
  then reproduced the reported cleanup traceback (exit 1).
- pytest 9.1.1's `cleanup_dead_symlinks()` calls `resolve().exists()` without
  catching PermissionError. The inaccessible link makes session cleanup fail.
- `pytest-current` has Directory/ReparsePoint attributes. Even outside the
  sandbox, Python `os.readlink()` and `icacls /L` get Access denied. Its target
  and ACL could not be inspected. The parent is owned by XinTong and grants
  OWNER RIGHTS, SYSTEM and Administrators FullControl. Origin of the link's
  access restriction is unconfirmed; no permission repair or deletion attempted.
- Sandbox-only first attempt could not access the parent directory at setup;
  this is separate from the reproduced user error outside the sandbox.

## Workaround and validation

`pytest -q --basetemp=.ai/temp/pytest-investigation-20261013` finished normally:
676 passed, 5 skipped, 2 xfailed, 1 failed, in 158.48 s. There was no cleanup crash.
Use a fresh scratch path: pytest clears an explicit basetemp on reuse.

The separate failure was
`test_a_crash_at_any_step_is_recovered_at_the_next_start[copy-setting_updated]`:
Windows denied `os.rename(staging, target)` in `cache_move.py:357`. This test
passed in the first run. A focused fresh-directory rerun of the entire
`tests/test_cache_move.py` passed all 39 tests in 3.77 s. This suggests an
intermittent rename/locking problem; the process holding a lock was not identified.
Do not attribute this to antivirus without further evidence.

CI uses `-n 4 --reruns 5 --reruns-delay 5`, which may mask transient failures,
and hosted runners lack this machine's old temp-directory state.

No application code, dependencies, system ACLs or Git commits changed.
