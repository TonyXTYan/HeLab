🎓Tony, the [latest CI run](https://github.com/TonyXTYan/HeLab/actions/runs/38245359149) (`e7009af`, October 12) was **cancelled after required Python 3.13 tests failed**.

| Configuration | Failure | Diagnosis |
|---|---|---|
| Ubuntu 3.13 | Menu-placement test timed out; 675 tests passed | The test never reaches opening the menu. Its setup assumes the menu is wide enough to overflow the screen—an assumption sensitive to Qt styling. |
| Windows 3.13 | Two byte-count assertions | Tests expect 6 bytes; Windows CRLF produces 7. The helper reports the actual file size correctly. |
| Windows 3.13 | Cache URI-path test | Its fixture contains `?`, which Windows forbids in folder names. |
| All six Python 3.14 jobs | Dependency installation | `pytablericons` pulls in `pygame`, whose source build fails on missing SDL/MSYS2 tooling. These failures are non-blocking. |

The Ubuntu menu failure also affects Python 3.11/3.12 and occurred in the preceding run, so it predates the latest provenance/release changes. I reproduced both Windows line-ending failures locally.

The immediate fixes are to make the menu-test placement deterministic, derive expected bytes from file sizes, and skip the Windows-invalid path parameter. Python 3.14's dependency issue is separate. Cancelled builds provide no completed build validation.

[Detailed findings and saved evidence](/Users/tonyyan/Documents/_ANU/_He_BEC_Group/HeLab/.ai/sessions/2026-10-12-codex-gh-action-failures/findings.md). No application, test, or workflow source changes were made.
