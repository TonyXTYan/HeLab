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
A12.1), the I/O helper (`--helab-io-helper`), the script folder probe (`--helab-script-probe FOLDER RESPONSE`,
`helab.scripts.probe`, Q49.3 (b); [plots-and-scripts](plots-and-scripts.md#script-system)), the headless
converter (`convert`, [converter](converter.md)), `helab cache` (read only), `--help`/`-h`, `--version`, then
the GUI. Neither helper entry takes `running.lock`, since `main()` isn't reached. `--help` (A56.7, Quick Fixes 10,
`5a4d863`) prints a short usage (the app with `--geometry`, `--version`, `--help`, `convert` and `cache`, each
pointing at its own `--help`) and exits 0, before Qt, settings, caches, Dash and `running.lock`; after the
`convert`/`cache` dispatch, so `helab convert --help` is still convert's own (`tests/test_versioning.py` runs it
in a subprocess: no PyQt6, `helab.utils.constants`, `dash_server` or `cache_locks` loaded, no `running.lock`).

**The bundled manual** (Q54.3; Docs floor, landed `b0e3aac`): the Python 3.13 Build jobs build the user
manual offline (`HELAB_DOCS_OFFLINE=true`, Material's offline plugin) into `build/manual`, in their own
`build/docs-venv` (both ignored by Git, so the build stamp stays clean; never the app's venv). `HeLab.spec`'s
`user_manual()` bundles it as `helab/manual` (from `HELAB_MANUAL_DIR`, else `build/manual`), appended to
`a.datas` after `Analysis` so `datas=` stays the plain list `test_spec_datas.py` reads; without it the spec says
so and builds without it. "Check the packaged app has the user manual" fails a build that lacks it, so a
strict-build warning in the manual fails the release builds too. A commit from before the manual (a recovery
build of an older tag) builds without it. Compatibility builds ship without it. The source package never holds
`helab/manual` (`test_source_package_has_no_bundled_manual`). **Its search works offline** (`c942613`, Follow-ups,
landed `72ab47a`): Material's offline plugin would load iframe-worker's `file://` shim from unpkg.com, so offline
the search stayed at "Initializing search"; `docs/js/iframe-worker-shim.js` is iframe-worker 1.0.4's
`shim/index.js`, vendored byte for byte after a one-line header naming its source (MIT, `docs/js/LICENSE-iframe-worker.txt`,
copied into the site beside it), and `mkdocs.yml`'s `extra.polyfills` lists it (over http it does nothing). Google
Fonts and the repo badge's GitHub API call stay: offline, the pages use system fonts and no star count.

**The frozen probe step** (`2eac45a`): every Build job, after the backend check and with no `if:`, runs the
packaged app's `--helab-script-probe` on a one-file folder whose script makes a `QLabel` at import, and asserts
exit 0, `ready` (with `application: offscreen`, so the offscreen platform plugin was collected) then `done`,
`sys.frozen` true and no GUI module imported (about 1 s). A commit without `helab/scripts/probe.py` (a recovery
build of an older tag) passes with a line. `tests/test_script_probe.py` checks the step's text.

## Versioning

**Versioning:** `helab/_version.py` is the only editable version source (PEP 440,
no `v` prefix). Branch names need not match it. `helab/build_info.py` writes
`_build_info.json` into PyInstaller/wheel build output; never generate it in the
source package. Runtime uses that stamp, or Git explicitly rooted in the package's
own checkout, never the launch directory. Help → About HeLab shows provenance.
CI stamps record the explicit source branch/build ref (`HELAB_BUILD_BRANCH`,
`HELAB_BUILD_REF`, set by `ci-build.yml`; else GitHub's own ref variables) without
replacing Git HEAD.
`BuildInfo.repository` ("owner/name") is stamped by `write_build_info` at build time only: from
`HELAB_BUILD_REPOSITORY`, else `GITHUB_REPOSITORY` in Actions, else the checkout's GitHub `origin`
(`build_repository`). It is never read from Git at runtime, so a source run has "unknown", and an older or
malformed stamp reads as "unknown". About shows it; Help › User manual uses it to find the build's site
([app-runtime-and-ui](app-runtime-and-ui.md#ui)).
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
`test_convert_split.py`, `test_convert_testdata.py`, and since caching v2's checkpoint 2 `test_raw_layer.py`,
the raw layer's layer-equals-file proof, so cython is proved there only; a new test that runs every
available backend joins the list); "Tests" runs the
whole suite in three groups for the required 3.13 jobs, each a job of its own ("Tests (1/3)", "Tests
(2/3)", "Tests (3/3)"; Quick Fixes 9, `9787e35`; two groups before, Q16.2, A17.2, and still for PRs'
compatibility jobs): `pytest --test-group N/3` (see [testing](testing.md)); the caller's result, which the
release gate needs, fails if any group does, and each macOS group uploads coverage for Codecov to merge.
A Tests job's limit is 30 min on Windows and 20 elsewhere, and pytest runs with `--session-timeout`
1200 s and 720 s (`457debc`), so it stops itself between tests, with its summary, rerun reasons and
junit.xml, before the runner would cancel the job. The
Tests jobs install the lock without Cython, nothing built (a `pip list` guard fails the job if a
backend package is present). The build job builds them (`build.py --ci`) before PyInstaller and checks the
app after (`check_build.py --frozen`); its timeout is 25 min. `HELAB_REQUIRE_BACKENDS` reaches later
steps through `$GITHUB_ENV`, so in the build job it also applies to "Test the older tagged commit
before rebuilding recovery assets" (skipped, and the variable unset, for a tag from before
`native/build.py`). Runners need a C compiler (MSVC on `windows-latest`). Group times on the first
run (40803552596, pytest step): Windows 11:02 and 10:02, macOS 4:09 and 4:52, Ubuntu 2:56 and 5:09; with
three groups (41481668334): Windows 8.9, 10.0 and 9.8 min, macOS 1.6, 6.1 and 4.7, Ubuntu 3.0, 3.5 and 3.4. Shared steps live in `ci-test.yml` and `ci-build.yml`, with
Codecov uploads. Builds are uploaded (`upload`) only in a run that releases, for the release job; test
results go to Codecov, and each Tests job keeps its `junit.xml` as an artifact for 7 days whatever its
outcome (`5324a7f`, `if: always()`; `junit-<os>-py3<minor>-group-index-<N>`, index 0 being group 1). Compatibility matrices expand on pushes, but pass `enabled: false`
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
(`release_name`: "Automated Release <tag>"), and two such matches raise. Each archive needs a regular
`helab/_build_info.json` with the release's version and commit, built clean; a stamp stored as a
symlink is followed and must lead to another stamp (the macOS zip keeps HeLab.app's links, and since
the cython kernel ships, `Contents/Frameworks/helab/` links its data files to `Contents/Resources/`;
0.0.7a1's release job stopped on one, run 41110274554). API
errors fail selection; they never mean "no release". Only authenticated main runs
query release state. Every Python 3.13 build also checks its own archive (`release_draft --check ARCHIVE
--commit SHA`, the stamps against `inputs.build-sha`, no tag or draft; A39.1, `c201c01`): the macOS zip with
`ditto`, Windows and Ubuntu `dist/HeLab` zipped with `python -m zipfile -c`, which follows links as the
artifact's copies do; skipped when `build-sha` isn't `github.sha` (a recovery build of an older tag, which
the release job still validates). Build jobs may target an older tagged SHA during recovery;
the normal test jobs still check the current workflow commit, and recovery builds
add Python 3.13 tests of the tagged commit on each OS.

**The release notes** (A59.1, Quick Fixes 10; `ca0bd61`, `be2f0e5`, `9e06bcb`, landed `20dd672`):
`release_draft.main` writes a new draft's notes (`release_body`): `## Release [<tag>](…/tree/<tag>)`, the date,
the commit link and the Workflow Run link (`--run-url`, built from `github.server_url`, `github.repository` and
`github.run_id`, never `github.event.repository.url`, which is the API's URL); GitHub's generated notes
(`GitHubReleases.generated_notes`, `POST /releases/generate-notes` with `previous_tag_name`, which changes
nothing); the build list and note; one `**Full Changelog**: …/compare/<previous>...<tag>` line (GitHub's own is
replaced; `/commits/<tag>` with no previous tag); then the asset manifest (`manifest_body`). **The previous tag**
(Tony, 2026-11-04: "I think we include alpha full releases too"): the previous **published full** GitHub
release. Of the repository's releases that are published and not marked pre-release (`full_release_tags`, every
page), keep those whose tag is in the commit's history (`tags_in_history`, `git tag --merged`; the release job
checks out with `fetch-depth: 0`) and take the highest PEP 440 version lower than the new one
(`previous_release`). An alpha published as a full release counts, so v0.0.9 compares with v0.0.8a1; drafts and
GitHub pre-releases never do. **Fallbacks:** if the releases can't be listed, the newest earlier `v` + PEP 440 tag
in the history (`previous_tag`; `v.0.0.1i`, `CI-CD-everything-passed` and other non-PEP 440 tags are never
chosen), with a `::warning::`; if the commit's history can't be read (`SubprocessError`, `OSError`; `be2f0e5`),
nothing is in it, so no previous tag, with a warning. If GitHub's notes fail, the draft is made without them, with a warning: the draft matters more than its
notes. `publish_draft` takes the body as a string or a callable, called only when it creates the draft, so a
resumed draft or a published release keeps its notes and never asks GitHub for new ones; bodies are still written
only while drafts (`_guard`). The release job installs `packaging` first (unpinned, as get-version's; A60.2), since
`release_draft` imports it. The job's first real run is v0.0.9's release.

**The Docs job** (A54.1, A54.2; landed `b0e3aac`): one Ubuntu job in `dev-cicd.yml` (10 min), beside the
tests; it needs only `get-version`, nothing needs it, and it is not in the release gate (it does block a
floor's landing, which needs every job green). It installs `requirements-docs.lock` (developer tools only:
ruff, mkdocs-material, mkdocstrings[python], mike; compiled with `-c requirements.lock`, never in the app's
requirements or its PyInstaller build), runs `ruff check` (D1 on the modules `ruff.toml` lists), then
`mkdocs build --strict` into `$RUNNER_TEMP/site`, and checks the install page links the building repo's
releases. Then it builds the offline copy (`HELAB_DOCS_OFFLINE=true`) and runs `docs/publish/check_offline.py`
on it, which fails on any page loading a script from elsewhere (static `<script src>` only). It publishes
nothing.

## App updates

Landed `ba22460` (the App Updates floor; Q65.1 (b), Q65.3, Q68.1–Q68.12; [plan](../../roadmaps/app-updates.md),
`sessions/2026-11-05-claude-app-updates/`). Source checkouts first; a frozen build only checks and links its download.

- **`helab/updates/`:** `versions`, `github` (pure: status, channels, replies, the CI rule, ETag cache, the check as a
  generator) and `updater` (standard library only) are in `PURE`; HeLab's side is `settings`, `settings_rows`,
  `check`, `launch`, `dialog`.
- **The check:** `QNetworkAccessManager` on the event loop, 10 s transfer timeout, GETs to `api.github.com` only
  (`User-Agent: HeLab/<version>`), refused under tests (`HELAB_TEST_SOURCE_GUARD`: give `UpdateCheck` a transport); ETags
  with trimmed replies in `<app folder>/updates/github-cache.json`; the status at start from the cache alone; the
  startup check scheduled by `main` only (never by a test's window), 30 s after show, when the last success is over
  24 h old (`updates_check_at_start`; off, it also serves as "don't offer updates", Q68.10). Requests per mode:
  releases + tag refs + one compare to `main`; branch: a compare and up to 5 check-run lookups.
- **Modes and defaults** (Q65.3, Q68.1): a checkout on a branch updates from that branch, fast-forward only; on a
  tag, from releases; the repository is the one the branch tracks when it is a known one
  (`build_info.upstream_repository`), else `HeBECANU/HeLab`; no free-text repo.
- **Branch mode's candidates** (`github.branch_line`, AU-2): the branch's own first-parent line from its tip down to
  the running commit; never a commit merged in from a side branch; the updater refuses a target not in
  `git rev-list --first-parent <tip> ^HEAD`. The target is the newest commit whose own CI is green (Q68.2).
- **The CI rule** (`github.ci_state`): GitHub Actions' runs only; per OS `<os> + py3.13 / Tests…` and `/ Build`
  present; every `<os> + py3.13 / …` name's newest non-skipped run completed success; a name only skipped, or whose
  newest run was cancelled, is not green; other jobs don't count; the group count isn't fixed.
- **The updater** (`helab/updates/updater.py`, copied to `<app folder>/updates/` and run by the base Python): the
  request fields, `--check`, the handshake (`ready-<token>`); it waits for HeLab's process handle, the locks and any
  process from the checkout or venv (`ps` by folder prefix, and on macOS `ps -E`'s `__PYVENV_LAUNCHER__` for a framework
  Python's venv, both only when the command names `helab`; on Windows image paths plus each Python's loaded modules by
  path); refusals (local changes, untracked files a checkout would overwrite, renames included, SSH or elevated,
  another HeLab, `git` missing, `uv` missing only when the venv must be rebuilt, Q68.11); the venv rebuilt beside the
  old one only when `REBUILD_FILES` (`requirements.lock`, `setup.py`, Q68.5) changed (`uv venv --relocatable`, the
  check in its own bytecode folder, swapped, a `venv` symlink kept), `DELETE_OLDER_VENV` (Q68.8); relaunch with the
  venv's Python, no console (`HELAB_UPDATE_TOKEN`, popped by `mark_started`, Q68.7); roll back if the new version
  exits before confirming, never killing a running HeLab (Q68.3); Restore via `previous.json` (branch mode by
  `git reset --keep`, Q68.4; a restored commit stored as Skip this version); `last.json` written before the older
  venv is deleted and shown once by the new HeLab on its own start (`after_start` polls for its token's outcome,
  AU-1, AU-13); `tidy`. Every child through `_run` (UTF-8, no console window). Not checked: that the base Python is
  outside the checkout (the README's setup), or `git`/`uv` versions.
- **`update.lock`** (R2, block 75, `a0c2c34`) in the app folder (`UpdateLock`; HeLab's side
  `cache_locks.update_in_progress`): held with the run's token from before the ready mark until the code and venv are
  as they will stay; the app (after `running.lock`), `helab convert` (after its instance lock) and the top of
  `helab.main` (before Qt, read only; `app_folder`/`default_app_dir` live in the standard-library
  `helab/utils/app_dirs.py` for it) stop while another process holds it, unless `HELAB_UPDATE_TOKEN` is the token in
  it. Whichever takes its own lock later sees the other. `check_quiet` runs before the code moves and before the
  swap; a HeLab still holding `running.lock` when the venv is ready means nothing is swapped and the code is put
  back. The lock is released before a failed update starts the previous version, and before the older venv is
  deleted. The venv's renames are all or nothing (`_renames`, used by `swap_in`, `swap_back`, `swap_previous`);
  `rollback` returns whether it put everything back; a failed update puts the earlier `previous.json` back. Not
  durable across a kill between two renames (Q75.6); the update's log has a line for each rename.
- **Test seams:** `HELAB_UPDATER_TEST_ROOT` (required under the guard), `HELAB_UPDATER_TEST_ELEVATED` (only under the
  guard; CI's Windows runners run elevated), `UpdateLauncher.start_detached`, `launch.checkout` / `venv_prefix`;
  `tests/test_updates_updater.py`'s `Lab` (bare remote, `insteadOf`, empty global config, `GIT_ALLOW_PROTOCOL=file`,
  fake uv, fake HeLab); `FAKE_UV_PAUSE` (the fake uv stops in `pip install` until that file is deleted).

## The manual's site

`.github/workflows/docs-site.yml` (Q54.2; DM-1 (a), Tony 2026-11-03) is the only workflow that runs mike or
touches `gh-pages` (`tests/test_docs_workflows.py`). It runs only on `release: published`: the release job makes
a draft, which stays private until it is published by hand, so the site follows publishing and an abandoned draft
never deploys. It checks out `refs/tags/<tag>` and runs `docs/publish/site_versions.py <version>` (the tag
without `v`, so `BuildInfo.version`), which publishes to the running repo's `gh-pages` (`github.repository`, so
`HeBECANU/HeLab` publishes its own site). **The versions** (Q56.3, Q58.3; `53ec411`, `e100872`, Follow-ups,
landed `72ab47a`): `site_versions.plan(version, deployed)` reads `mike list --json` (a failing list stops the
deploy, exit 1; no `gh-pages` yet lists `[]`) and runs `mike deploy --push --update-aliases <version>` with
`latest` when it is the newest stable release, or `pre-release` when it is a PEP 440 pre-release newer than
every release, stable ones included; an older release published late gets its version and moves no alias. A
stable release newer than `pre-release`'s target then runs `mike delete --push pre-release` (the alias only;
the next pre-release brings it back). The front page: `mike set-default --push latest` once a stable release
exists, else `mike set-default --push --template <page> pre-release` (the "No stable release yet" page, light
and dark, linking to the newest pre-release). **The rule** (A59.2 (b), Quick Fixes 10, `bfa2b78`): a pre-release
version may be published as a full GitHub release (v0.0.8a1 is GitHub's "Latest"), but the site goes by the
version number: its `latest` stays the newest stable version, and until there is one the front page names the
newest pre-release, "Latest: 0.0.8a1 (alpha)", linked to `pre-release/`. mike's `--template` renders only
`{{href}}`, so `site_versions` fills in `docs/publish/no-stable.html`'s `{{latest}}` first: `no_stable_page`
with `latest_label` ("(alpha)", "(beta)", "(release candidate)", "(development version)" for a `.dev`) of
`newest_pre_release` (the newest of every deployed version and the new one), written to a temporary folder and
passed to `plan(…, page)` exactly when the plan sets it as the front page. No dev channel: a dev manual is built locally
(`mkdocs serve`, the README's User manual section). `mkdocs.yml` excludes `publish/`. Help › User manual opens
`<owner>.github.io/<repo>/<version>/`, a pre-release's own page included ([app-runtime-and-ui](app-runtime-and-ui.md)).
`--dry-run` prints the commands. A commit without `mkdocs.yml`, `requirements-docs.lock` or
`docs/publish/site_versions.py` skips with a notice and stays green. Concurrency group `helab-docs-site`, not
cancelling; 15 min; `contents: write`. A `release` event runs the workflow file of the released tag's commit, so
the first release whose tag contains `docs-site.yml` is the first to deploy. GitHub Pages must be turned on in
the repo's settings, source `gh-pages` (M56.2).

The pages link their own repository: `{repo_url}` in a page becomes `repo_url` (`HELAB_DOCS_REPO_URL`, set to the
building repo in CI; `mkdocs.yml`'s fallback for local builds), through `docs/hooks/repo_links.py`, which
`exclude_docs` keeps out of the site.

## Dependency graph

`.github/workflows/dependency-graph.yml` (weekly, by hand, and on pushes to `main` that
change `requirements.lock`, `helab/dependency_snapshot.py` or the workflow) runs
`python -m helab.dependency_snapshot --submit`, which sends `requirements.lock`'s exact
versions to GitHub's dependency graph through the dependency submission API (standard
library and `gh`; packages the lock marks `via -r requirements.txt` are direct, the rest
indirect), so Dependabot alerts cover what HeLab installs: Dependabot itself reads only the
unpinned `requirements.txt` (Q6.4). Without `--submit` it prints the snapshot.
