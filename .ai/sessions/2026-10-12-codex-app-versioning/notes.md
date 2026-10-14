# Package version and build provenance

Tony chose option A and authorized implementation: a package version, build stamp,
and explicit CI tags/drafts on new versions merged to main. Version bumps belong
on the PR branch before final approval; a branch name need not match the version.

Implemented `_version.py` (`0.0.5a1`), pure build-provenance helpers, wheel/spec
stamping, About/log display, and tested CI version/release selection. The stamp is
JSON in build output rather than a generated source module, avoiding stale stamps
after local builds. CI adds PR checks, preserves the 3.13-only required gates,
serializes release jobs, refuses tag collisions and sets the pre-release flag from
the selected version. No tags or GitHub releases were created in this session.

Validation (Python 3.13.15, macOS arm64; GUI tests offscreen):

- Versioning/main-window tests: **36 passed**.
- Wider suite (`-n 4 --ignore=tests/test_typing.py`): **651 passed, 1 skipped,
  2 xfailed**. Three existing Dash fixed-port collision warnings; no failures.
- Strict mypy (`helab tests`): clean in 96 files; Pyright: 0 errors/warnings.
- Built a wheel and the full PyInstaller macOS app. Wheel metadata and app plist
  agree with `0.0.5a1`; the embedded JSON agrees with commit/build-date plist fields.
- Ran both source and actual frozen `--version` from `/private/tmp`: both reported
  the package version and `e507dcd` commit; the frozen executable reported its UTC
  build stamp and modified source state. No GUI/services are started by this query.
- `setup.py --version` works from an unrelated directory. CI selection reports no
  release for a PR ref. Workflow YAML parses, trigger/gate assertions and diff
  whitespace checks pass. The workflow has not been executed on GitHub yet.

Build artifacts: `.ai/temp/versioning/dist/HeLab.app` and
`.ai/temp/versioning/wheels/helab-0.0.5a1-py3-none-any.whl` (gitignored).
The stamp identifies the pre-existing HEAD plus modified state until these changes
are committed and rebuilt. No commit or push was performed.

Native Windows/About and real GitHub release execution remain in MANUAL_TODO.

## P2 review fixes

Terminal #1 identified skipped recovery after early tag creation and detached PR
stamps reporting `HEAD`. Tony authorized both fixes separately.

Release selection now reads draft/asset completion, not tag existence. Full reruns
and later same-version main pushes select the existing tag's own SHA, validate its
version/main ancestry and rebuild/test that SHA. All clean archive stamps are checked
before tagging. A commit/size/digest manifest makes draft uploads resumable while
preserving completed assets and human notes; remote tag checks precede mutations,
and published releases are left alone. Read/API errors are not absence.

CI stamps now retain the actual Git HEAD plus explicit source branch/build ref.
Tests cover a real detached checkout, PR merge context and a fake context SHA that
must not replace the checked-out commit.

Final validation: **55 focused tests passed**; wider suite **670 passed, 1 skipped,
2 xfailed** (three existing Dash fixed-port warnings). Strict mypy: clean in 98 files;
Pyright: 0 errors/warnings; workflow YAML/recovery-order/gate checks and diff checks
pass. API mutations were tested with a fake backend, including interrupted uploads,
lost responses, starter/wrong-digest assets, moved tags, publication during recovery,
later-head recovery and API failures. No live release or tag operations were run.

Rebuilt the wheel and macOS app; plist/stamp branch/ref agree, and the actual frozen
`--version` query works from `/private/tmp`. Finder re-added attributes to the bundle
in this synced checkout and blocked ad-hoc signing. A metadata-free copy outside the
checkout was signed and passed strict/deep signature verification, then the query:
`/var/folders/d7/m1p9gxmx4_jd5fdwxhddhnvm0000gn/T/helab-versioning-sign-zhhwla0d/HeLab.app`.

Live GitHub token/API/rerun behavior and native Windows/About remain manual checks.
All implementation changes remain uncommitted; no push was performed.

## Release concurrency follow-up

Terminal #1's follow-up review identified that GitHub's default single pending-job
queue replaces an earlier pending release when another becomes ready. Tony authorized
adding `queue: max` to the release job, retaining `group: helab-release` and
`cancel-in-progress: false`. The versioning roadmap now records the 100-pending-job
limit, overflow cancellation and ordering by when jobs start waiting.

Validation: Ruby parsed the workflow YAML and asserted the exact three concurrency
properties, unchanged release dependencies and absence of other job/workflow-wide
concurrency blocks. `git diff --check` passed. Current official GitHub concurrency
documentation confirms this combination. No application code changed, so application
tests were not repeated. Live GitHub queue execution remains unverified. No commit
or push was performed.

Terminal #1 independently reviewed the concurrency change: no findings, exact YAML
mapping/dependencies/isolation and diff checks passed. Tony subsequently authorized
committing and pushing all pending changes and preparing a PR dry run. The package
remains `0.0.5a1`; opening/merging a PR and selecting final `0.0.5` are deferred until
Tony returns after branch CI. The earlier validation and no-commit/no-push statements
above describe the implementation/review phase.
