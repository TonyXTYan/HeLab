# Versioning, building and CI

Reference detail for agents working in this area. It moved here verbatim from `AGENTS.md` on
2026-10-28, when AGENTS.md was cut to rules and a map ([index](README.md)). AGENTS.md keeps the
rules every task must follow; this file keeps the mechanics, names and behaviour. Keep it true:
on Ground, update it in the same commit as the code; on a floor, propose the change in your handoff. Settled decisions and Tony's wording live in
`.ai/memory/results/`; feature plans in `roadmaps/`.

## Building

The `.spec` file produces `HeLab.app` on macOS (bundle ID `au.edu.anu.he-bec-lab`).

`helab/main.py` dispatches in this order, each before anything that starts GUI services, caches
or Dash: `multiprocessing.freeze_support()` (frozen only, so the converter's worker pool can spawn,
A12.1), the I/O helper (`--helab-io-helper`), the headless converter (`convert`, [converter](converter.md)),
`--version`, then the GUI.

## Versioning

**Versioning:** `helab/_version.py` is the only editable version source (PEP 440,
no `v` prefix). Branch names need not match it. `helab/build_info.py` writes
`_build_info.json` into PyInstaller/wheel build output; never generate it in the
source package. Runtime uses that stamp, or Git explicitly rooted in the package's
own checkout, never the launch directory. Help → About HeLab shows provenance.
CI stamps record the explicit source branch/build ref (`HELAB_BUILD_BRANCH`,
`HELAB_BUILD_REF`, set by `ci-build.yml`; else GitHub's own ref variables) without
replacing Git HEAD.
Put a release-version bump on the PR branch before final approval. A squash merge
to `main` with a new version triggers CI tagging and a draft release after required
checks pass; publication remains manual. An existing tag with an incomplete draft
is recoverable: rebuild/test that tagged SHA, validate clean archive stamps before
tagging/uploading, preserve manifest-verified assets and never modify a published
release or force-move a tag. See `roadmaps/app-versioning.md`.

## CI

`.github/workflows/dev-cicd.yml` runs required Python 3.13 test/build matrices on
macOS, Windows and Ubuntu for every branch push and PR to `main`. A push to a
branch with an open PR to `main` runs only the detection job, since the PR's own
run tests the same commit (if the PR lookup fails, everything runs). Separate
Python 3.11, 3.12 and 3.14 compatibility matrices run only on PRs to `main`,
with soft failures. `ci-test.yml` has two independent jobs per OS and Python (converter stage 4,
2026-10-29): "Converter backends" (20 min) builds and requires cython (`native/build.py --ci`,
`HELAB_REQUIRE_BACKENDS=cython`) and runs the converter tests that use a backend, listed by hand
(`tests/test_convert_backend_*.py`, `test_convert_required_backends.py`, `test_convert_helab.py`,
`test_convert_split.py`; a new test that runs every available backend joins the list); "Tests" runs the
whole suite in two groups, each a job of its own ("Tests (1/2)", "Tests (2/2)", Q16.2, A17.2):
`pytest --test-group N/2` (see [testing](testing.md)); the caller's result, which the release gate
needs, fails if either group does, and each macOS group uploads coverage for Codecov to merge. The
Tests jobs install the lock without Cython, nothing built (a `pip list` guard fails the job if a
backend package is present). The build job builds them (`build.py --ci`) before PyInstaller and checks the
app after (`check_build.py --frozen`); its timeout is 25 min. `HELAB_REQUIRE_BACKENDS` reaches later
steps through `$GITHUB_ENV`, so in the build job it also applies to "Test the older tagged commit
before rebuilding recovery assets" (skipped, and the variable unset, for a tag from before
`native/build.py`). Runners need a C compiler (MSVC on `windows-latest`). Group times on the first
run (40803552596, pytest step): Windows 11:02 and 10:02, macOS 4:09 and 4:52, Ubuntu 2:56 and 5:09. Shared steps live in `ci-test.yml` and `ci-build.yml`, with
Codecov uploads. Runs keep no artifacts: builds are uploaded (`upload`) only in a
run that releases, for the release job; test results go to Codecov only. Compatibility matrices expand on pushes, but pass `enabled: false`
to the called jobs, recording individual skips without starting runners. All
matrices disable fail-fast; required failures do not cancel
other OS tests/builds. All four matrices depend on branch/version selection;
release waits for all four, but only required matrices and version selection
must succeed (compatibility skips/failures are non-blocking). A new package
version on `main` creates an explicit tag and a draft
release; tag pushes do not
trigger releases. `python -m helab.release` validates/selects the version in CI.
`python -m helab.release_draft` validates archives and resumes draft uploads; GitHub lists
a draft under tag `untagged-<hash>`, so `get_release` also matches a draft by its name
(`release_name`: "Automated Release <tag>"), and two such matches raise. API
errors fail selection; they never mean "no release". Only authenticated main runs
query release state. Build jobs may target an older tagged SHA during recovery;
the normal test jobs still check the current workflow commit, and recovery builds
add Python 3.13 tests of the tagged commit on each OS.

## Dependency graph

`.github/workflows/dependency-graph.yml` (weekly, by hand, and on pushes to `main` that
change `requirements.lock`, `helab/dependency_snapshot.py` or the workflow) runs
`python -m helab.dependency_snapshot --submit`, which sends `requirements.lock`'s exact
versions to GitHub's dependency graph through the dependency submission API (standard
library and `gh`; packages the lock marks `via -r requirements.txt` are direct, the rest
indirect), so Dependabot alerts cover what HeLab installs: Dependabot itself reads only the
unpinned `requirements.txt` (Q6.4). Without `--submit` it prints the snapshot.
