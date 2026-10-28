# Versioning, building and CI

Reference detail for agents working in this area. It moved here verbatim from `AGENTS.md` on
2026-10-28, when AGENTS.md was cut to rules and a map ([index](README.md)). AGENTS.md keeps the
rules every task must follow; this file keeps the mechanics, names and behaviour. Keep it true:
on Ground, update it in the same commit as the code; on a floor, propose the change in your handoff. Settled decisions and Tony's wording live in
`.ai/memory/results/`; feature plans in `roadmaps/`.

The `.spec` file produces `HeLab.app` on macOS (bundle ID `au.edu.anu.he-bec-lab`).

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

`.github/workflows/dev-cicd.yml` runs required Python 3.13 test/build matrices on
macOS, Windows and Ubuntu for every branch push and PR to `main`. A push to a
branch with an open PR to `main` runs only the detection job, since the PR's own
run tests the same commit (if the PR lookup fails, everything runs). Separate
Python 3.11, 3.12 and 3.14 compatibility matrices run only on PRs to `main`,
with soft failures. Shared steps live in `ci-test.yml` and `ci-build.yml`, with
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

`.github/workflows/dependency-graph.yml` (weekly, by hand, and on pushes to `main` that
change `requirements.lock`, `helab/dependency_snapshot.py` or the workflow) runs
`python -m helab.dependency_snapshot --submit`, which sends `requirements.lock`'s exact
versions to GitHub's dependency graph through the dependency submission API (standard
library and `gh`; packages the lock marks `via -r requirements.txt` are direct, the rest
indirect), so Dependabot alerts cover what HeLab installs: Dependabot itself reads only the
unpinned `requirements.txt` (Q6.4). Without `--submit` it prints the snapshot.
