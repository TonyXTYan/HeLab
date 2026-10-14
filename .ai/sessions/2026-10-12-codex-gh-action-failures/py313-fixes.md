# Python 3.13 CI test fixes — 2026-10-13

Tony authorized fixes to the Python 3.13 failures identified in `findings.md`.

Changes are confined to four test files:

- `tests/test_hover_menu_button.py`: the screen-edge test aligns the triangle to the right edge of its window and removes layout margins before moving the window. It now exercises both a short and the original menu label, so overflowing the screen does not depend on the original label's platform-specific width.
- `tests/test_cache_first.py`: expected read bytes come from the settled TXY file's actual disk size. The scenario runs with native, LF and CRLF line endings.
- `tests/test_large_folder.py`: expected bytes added to RAM come from the new TXY file's actual disk size. The scenario runs with native, LF and CRLF line endings.
- `tests/test_cache_store.py`: only the `query?mode=rw` parameter is skipped on Windows, with a reason explaining the forbidden filename character. Percent and hash URI-escaping coverage remains active there; all three cases still run on other platforms.

Validation on macOS arm64, Python 3.13.15:

- Four changed test modules: `70 passed in 7.75s`.
- Screen-edge test under `QT_STYLE_OVERRIDE=Fusion`: `2 passed, 8 deselected in 0.61s`.
- Full suite (`venv/bin/pytest -n 4 -q --timeout=120 --timeout-method=thread`): `681 passed, 1 skipped, 2 xfailed, 3 warnings in 19.68s`.
- `venv/bin/mypy helab/ --strict`: no issues in 58 source files.
- `venv/bin/mypy tests --strict`: no issues in 40 source files.
- `venv/bin/pyright helab tests`: 0 errors, 0 warnings.
- `git diff --check`: clean.

The full suite's three warnings are the existing parallel Dash port-8050 contention warnings. No application or workflow implementation changed; the Python 3.14 dependency issue is outside this fix. Native Linux/Windows verification and GitHub CI validation remain for the next run. No commit or push was performed.
