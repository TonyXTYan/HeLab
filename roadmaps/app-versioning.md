# App version and build info

Horizon: now, **after the [cache rebuild](cache-storage-and-settings.md)** (Tony, 2026-10-10).
Added: 2026-10-10. Direction recommended, not yet decided.
Priority and completion: [overview](_readme.md).

## Purpose

HeLab should always know and show its real version and commit, both from a source checkout and
from a packaged build. Git tags, `setup.py`, CI releases and the running app should agree.

## How it works today (checked 2026-10-10 at `dbef54f`)

The only source is `setup.py` (`version="0.0.4a"`).

| Where | How it gets the version | Problem |
|---|---|---|
| Running app (`constants.get_version()`; window title, status bar, startup log) | Opens `setup.py` from the **current working directory**, then `../` and `../../`, and reads it with a regex | Started from another folder, it shows `0.0.0`. The packaged app doesn't bundle `setup.py` (`HeLab.spec` `datas`), and a Finder launch starts in `/`, so builds should always show `0.0.0` (inferred from the code, not yet seen in a build). |
| Commit hash (`get_git_commit_hash()`) | `git rev-parse HEAD` in the current working directory, at startup | Packaged app: `unknown`. Started inside another git repo: that repo's hash. |
| `HeLab.spec` | Reads `setup.py` and git at build time, for the macOS Info.plist only (`CFBundleShortVersionString`, `CFBundleVersion`) | Correct there, but it never reaches the code. |
| CI (`dev-cicd.yml`, `get-version`) | Reads `setup.py`. On `main`, an untagged `v<version>` triggers build and release | The release is a **draft** (`ncipollo/release-action`, `draft: true`), and GitHub creates a draft's tag only when the draft is published. |

Consequences:

- **`v0.0.4a` was never tagged.** Its GitHub release is still a draft, so the newest tag
  anywhere is `v0.0.3b`.
- **Three different answers:** `git describe` says `v0.0.3b-56-gdbef54f`, `setup.py` says
  `0.0.4a`, and the branch is `dev/v0.0.5a`.
- **Not every tag is a valid Python version.** PEP 440 has no `e` or `z` suffix, so
  `v0.0.2e` and `v0.0.1z` are invalid; CI skips them with `InvalidVersion`.
- **Stray tags:** `v.0.0.1i`, `reverted-cicd`, `CI-CD-everything-passed`.
- **Local and remote tags match** on all three remotes (`HeBECANU`, `TonyXTYan`,
  `upstream`), but only through manual `git fetch --tags` / `git push --tags`.

## Options

**A. A version file in the package, plus build info written at build time (recommended
first).**
- `helab/_version.py` holds `__version__ = "0.0.5a1"`.
- `setup.py`, `HeLab.spec`, CI and the app all read it. No regex over `setup.py`, and nothing
  depends on the working directory.
- CI and the PyInstaller build write `helab/_build_info.py`: commit, branch, build date, and
  whether the tree was dirty. The app uses it when present. In a checkout it falls back to
  `git` run in the package's own folder.
- Small, and fixes the `0.0.0` and wrong-hash problems. The version is still bumped by hand.

**B. The installed package's metadata (`importlib.metadata.version("helab")`).**
- The standard approach; works with `pip install -e`.
- The spec file needs `copy_metadata("helab")`.
- Still needs A's build-info step for the commit.

**C. Git tags as the only source (`setuptools-scm` or `hatch-vcs`).**
- Pushing the tag `v0.0.5a1` sets the version. Builds between tags get versions like
  `0.0.5a2.dev56+gdbef54f`.
- Needs:
  - a move to `pyproject.toml`
  - `fetch-depth: 0` in CI
  - a generated `_version.py` for frozen builds
  - **PEP 440 versions only**
- The most automatic option and the largest change.

**D. A bump tool (`bump-my-version` or `commitizen`) on top of A or B.** One command updates
the version, commits and tags, and can write a changelog.

## Fixes needed with any option

- **Tag on release.** Publish the draft release (still marked pre-release), or have CI create
  and push the tag itself, so `v0.0.4a` and later versions exist as tags.
- **A PEP 440 scheme from now on.** For example `0.0.5a1` → `0.0.5b1` → `0.0.5`, or a move to
  `0.5.0`-style numbers. Deleting the old invalid and stray tags is optional.
- **Bump at the start of a dev branch.** `dev/v0.0.5a` should carry `0.0.5a…` from its first
  commit.
- **Show the version and commit in one place**, e.g. Help → About, with the build date and
  dirty flag. The window title and log keep the short form.

## Acceptance

- The version and commit shown are correct when started from any folder, from a source
  checkout, and from a packaged build on macOS and Windows.
- One place to change the version. CI, the spec file and the app all agree with it.
- Every release has a git tag; `git describe` on a release commit names that version.
- Tests: version and build-info reading (present, missing, malformed), and no dependence on
  the working directory.

## Open decisions

- Option A, B or C, with or without D (recommended: A now, C later if wanted).
- Version scheme: PEP 440 alphas on `0.0.x`, or a move to `0.x.0`.
- Publish the existing `v0.0.4a` draft, or skip to `0.0.5a1`.
- Whether to delete the invalid and stray tags.

## Appendix: CI and release workflow for each option

### Branch flow (all options): squash-merge PRs from dev to `main`

This matches what happened before: PR #4 (`dev` → `main`, v0.0.4a) was squash-merged as
`59550a8`.

1. **Start:** branch `dev/vX.Y.Z` from the current `main`. The **first commit bumps the
   version** (for A, B or D; for C, see below).
2. **Develop:** push freely. Every push runs CI (tests and builds, no release). Builds name
   their commit.
3. **Open a PR to `main`.** Add a `pull_request` trigger so the PR shows the test results, and
   make them required.
4. **Before merging:** set the final version for the release, e.g. `0.0.5a3`.
5. **Squash-merge.** `main` gets one commit, e.g. "Release 0.0.5a3: cache rebuild, Folder
   details … (#N)".
   - Edit the squash message to a summary. GitHub's default concatenates every commit message
     (50+ on this branch).
   - The detailed messages stay in the PR.
6. **CI on `main`:** tests, builds, then **creates and pushes the tag** on the squash commit
   and publishes the release.
7. **Abandon the dev branch:**
   - Delete it, or turn on GitHub's "Automatically delete head branches" (currently off).
   - Never keep committing to it. Its commits aren't ancestors of `main`, so a later squash
     would bring them in again or conflict.
   - Builds made from it stay traceable: GitHub keeps a merged PR's commits
     (`refs/pull/N/head`).
8. **Next cycle:** `git fetch --tags` and a new branch from `main` (step 1).

**Hotfix on `main`** (like `ca45e22` after #4): bump the version in the same commit, so CI
tags and releases it. Later dev branches start from `main` and include it.

**Two repos:** the tag and release belong to the repo whose `main` received the merge. To have
the tag in both, push it to the other remote (`git push HeBECANU v0.0.5a3`), or let CI mirror it.

### Option A: version file plus build info

| Stage | What happens |
|---|---|
| Dev push | `get-version` reads `helab/_version.py`, and fails if it's lower than the newest tag or not PEP 440. Tests run. `build` writes `helab/_build_info.py` (commit, branch, date, dirty, run ID), then PyInstaller. No tag, no release. |
| PR to `main` | Same checks, shown on the PR. |
| Squash-merge to `main` | `get-version` sees an untagged version on `main`, so tests and builds run, then the release job tags the squash commit `vX.Y.Z` and publishes the release with the zips. If the version wasn't bumped (tag exists), CI builds without a release. |
| Local | `git fetch --tags`. A checkout shows `_version.py` plus `git` run in the package folder. |
| Packaged app | Version from `_version.py`, commit, branch and date from `_build_info.py`. |
| You do by hand | Bump `_version.py` at branch start and before merging. |

### Option B: installed package metadata

| Stage | What happens |
|---|---|
| Dev push / PR | As A, but `get-version` reads the version from `setup.py` (or `pyproject.toml`), and the app reads `importlib.metadata.version("helab")`. The spec file adds `copy_metadata("helab")`. Build info is still written as in A. |
| Merge to `main` | As A: tag and release. |
| Local | Correct only after `pip install -e .` (already in the setup guide). After a version bump, reinstall, or the metadata is stale. |
| Packaged app | Version from the bundled metadata; commit from build info. |
| You do by hand | Bump `setup.py` / `pyproject.toml`, and reinstall locally after bumping. |

### Option C: git tags as the version (`setuptools-scm`)

| Stage | What happens |
|---|---|
| Dev push / PR | No version file to bump. CI checks out with `fetch-depth: 0` (already set in `get-version`; needed in `build` too). The version comes from the nearest tag, e.g. `0.0.5a2.dev12+g1a2b3c4`, and is written to a generated `_version.py` before PyInstaller. |
| Squash-merge to `main` | CI can't tell from a file that a release is wanted. Either (a) you push a tag `vX.Y.Z` on the squash commit and the tag push builds and releases it, or (b) a release label or PR title tells CI which tag to create. |
| Local | `pip install -e .` or a build regenerates the version from git. Without the tags fetched, versions are wrong, so always `git fetch --tags`. |
| Packaged app | Version from the generated `_version.py`. |
| You do by hand | Push a tag to release. Every dev branch must start from `main` after the last squash, or the tag isn't in its history. |
| Prerequisites | `pyproject.toml`; PEP 440 tags only (old invalid tags ignored or deleted). |

### Option D: bump tool on top of A or B

| Stage | What happens |
|---|---|
| Branch start / before merging | `bump-my-version bump pre_n` (or `minor`, `patch` …) edits the version file and commits; commitizen can also write `CHANGELOG.md` from commit messages. |
| Dev push / PR / merge | Exactly as A or B. CI still creates the tag on `main`, so configure the tool **not** to tag locally (otherwise local and CI tags can disagree). |
| You do by hand | Run one command instead of editing the file. |

### Summary

| | A | B | C | D (with A) |
|---|---|---|---|---|
| Source of the version | `_version.py` | package metadata | git tag | `_version.py` via a tool |
| Release trigger | version bump merged to `main` | same | pushing a tag | same as A |
| Works with squash merges | yes | yes | yes, if dev branches always start from `main` | yes |
| Changes to CI | read the new file, write build info, push the tag | copy metadata, write build info, push the tag | full history in every job, tag-triggered release | none beyond A |
| Effort | small | small | medium | small, on top of A |
