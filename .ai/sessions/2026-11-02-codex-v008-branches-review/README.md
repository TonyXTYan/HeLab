# Codex v0.0.8 bug and security reviews

Archived on `agent/codex-v008-security-review` at Tony's request. This branch
starts at the reviewed `dev/v0.0.8` commit and adds review records only; it does
not merge the caching-v2 implementation or apply fixes.

- [Latest review: five additional findings and the status of the previous three](review.md)
- [First review: three original findings](../2026-11-01-codex-v0.0.8-review/review.md)
- [Feature regression probes](new-repros.py), [their results](new-repros.log),
  and [the additional malformed-offset result](offset-bounds.log)
- [Previous-finding probes](previous-repros.py), [feature results](previous-findings.log),
  and [dev results](dev-evidence/previous-findings.log)
- [Labcam security probe](dev-evidence/labcam-repro.py) and [result](dev-evidence/labcam-security.log)
- [Feature focused tests](feature-tests.log) and [type checks](typing.log)
- [Dev focused tests](dev-evidence/dev-tests.log), [Labcam tests](dev-evidence/labcam-tests.log),
  and [type checks](dev-evidence/typing.log)

Reviewed source snapshots:

| Source | Commit |
| --- | --- |
| Latest `dev/v0.0.8` | [a5f129b8](https://github.com/TonyXTYan/HeLab/tree/a5f129b8066f77d567149c0119b691a3506c31eb) |
| `agent/caching-v2` | [d76a90e6](https://github.com/TonyXTYan/HeLab/tree/d76a90e6ef5a69d6c2e1520bb1a4bee53a26828d) |
| First review's `dev/v0.0.8` | [3c8cfa1a](https://github.com/TonyXTYan/HeLab/tree/3c8cfa1ad4b6c7f0046d313fa2ab305d34f9ded2) |

The regression probes intentionally fail against the affected snapshots. To
replay one, use a disposable checkout of its reviewed source commit and copy
the probe into its `tests/` directory so `tests/conftest.py` provides private
data, cache and settings fixtures. Activate that checkout's Python 3.13
environment and run pytest on the copied file. The feature probes require the
caching-v2 snapshot; that implementation is not part of this archive branch.
The Labcam probe additionally needs OpenCV and imports `side_projects/labcam`.

Do not interpret the negative-probe failures as ordinary suite failures or
the focused passes as a complete release validation. The reports explain the
checks, skipped cases, interrupted broad runs and environment limitations.
The first report preserves its original description of the read-only review;
committing and pushing these records was authorized afterward.
