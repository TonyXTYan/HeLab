🎓Tony, the Python 3.13 fixes are in place:

- The menu test places the triangle at the window's right edge and checks short and normal menu labels.
- Both byte-count tests use actual file sizes and cover native, LF and CRLF line endings.
- Only the filename case containing `?` is skipped on Windows; the other URI-path cases remain covered.

Validation: **70 focused tests passed**, both menu cases passed under Qt's Fusion style, and the full Python 3.13 suite finished with **681 passed, 1 skipped, 2 xfailed**. Strict mypy, Pyright and diff checks passed. The suite still emits the existing Dash port-contention warnings.

These are test-only changes, uncommitted. Windows/Linux confirmation still needs the next CI run.

[Changes and validation](/Users/tonyyan/Documents/_ANU/_He_BEC_Group/HeLab/.ai/sessions/2026-10-12-codex-gh-action-failures/py313-fixes.md).
