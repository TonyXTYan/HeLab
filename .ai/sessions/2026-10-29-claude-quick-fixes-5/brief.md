# Brief: Quick Fixes 5, the cache_saved summary flake (`agent/quick-fixes-5`)

Coordinator: CoCo, 2026-10-29 (overnight build; Side approves on Tony's behalf within the
[mandate](../2026-10-29-claude-v0.0.7-overnight/mandate.md): the v0.0.7 PR needs clean CI). One
Quick Fixer, then a Reviewer. Base `e064a53` (`dev/v0.0.7`).

## Job

`tests/test_folder_summary.py::test_disk_cache_summary_tracks_shared_save_completion[cache_saved]`
reruns on macOS CI: `assert 'Cached data loaded · Cached just now · Freshness unknown' ==
'Cached data loaded · Cached just now'` (line ~413). Occurrences: 2026-10-26 run 40279097363;
2026-10-28 run 40679555921 (3x); 2026-10-29 runs 40753079487, 40754538456, 40758706117 (once each).
The known-issues entry (Tests and CI) guesses a timing race: the second tab's row has no folder
modified time yet when the save completes, so its freshness is unknown. Find the actual cause
(reproduce it: load, slow listings, `-p xdist` with neighbours, a stress loop), then fix the test if
the test is wrong or the app if a user can see "Freshness unknown" wrongly. Keep any app change
small; if it isn't, stop and ask CoCo.

## Rules

As your role says, plus: no converter paths (`helab/convert/`, `helab/io_ops/convert.py`, `native/`,
`dev/txy/`, `tests/test_convert_*`). Notes in `.ai/sessions/2026-10-29-claude-quick-fixes-5/notes.md`
(cause, evidence, fix, checks, the known-issues line). Before the report: the full suite (inside and
once with `--basetemp` outside the checkout), the fixed test in a stress loop, `mypy helab/ --strict`,
`mypy tests --strict`, `pyright helab tests`, and also `mypy --platform win32` and
`pyright --pythonplatform Windows`; report every RERUN. Push once when done and report the CI run
(all three OSes); the landing waits for it.
