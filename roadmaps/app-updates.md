# App updates

Added: 2026-10-13. Draft; nothing implemented. Decisions below are Tony's
(2026-10-13) unless marked open.
Priority and completion: [overview](_readme.md). Builds on
[app versioning](app-versioning.md).

## Purpose

Lab PCs should learn about, and later install, new HeLab releases without
anyone logging in to update them by hand. This replaces self-hosted CI runners
on lab PCs: those repos are public, so fork PRs could run code on experiment
machines; a runner service has no desktop or GPU session, so it would miss the
lab's real problems (QtWebEngine rendering, the data volume, cache settings);
and runners compete with data taking and install their own Pythons (as on the
RSPE office PC). Lab-specific checks belong in a self-check run after updating
(see [Later](#later)).

Both ways of running HeLab must work the same way:

- **Source:** a git checkout with a uv venv (all lab PCs today).
- **Frozen:** a PyInstaller build from a CI release (`HeLab-<os>.zip`, onedir;
  `HeLab.app` on macOS).

## Shared rules

- **Repos.** `HeBECANU/HeLab` by default. A hard-coded list of known repos
  (`HeBECANU/HeLab`, `TonyXTYan/HeLab`) can be chosen in Settings → General;
  no free-text repo, so a typo or a stranger's fork can never become the
  update source. Source checkouts find the chosen repo among their remotes by
  URL, never by remote name (Tony's Mac has `HeBECANU` and `TonyXTYan`, no
  `origin`).
- **Channels.** Stable by default. Pre-releases are an opt-in setting
  ("Include pre-releases"), shared by the check and the update button.
- **Version status.** Every run gets one status, shown in Help → About and by
  the check:
  - *Release X* — the running commit is the commit of release tag `vX`.
  - *Pre-release X* — the same, for an alpha/beta/RC release.
  - *Development version (based on X)* — anything else: a branch ahead of the
    newest release, a commit that isn't a release's, a dirty tree, or a local
    build. `build_info` already has the version, commit, branch and dirty flag;
    the release's commit comes from its tag (one extra API call, cached).
  - *Update available: Y* — a newer release on the chosen channel exists. A
    development version is offered only releases newer than its own version.
- **Only releases made by the repo's owners.** Releases and tags in the repo
  need write access, so fork PRs can't create them; but anyone with write
  access (or a leaked token) can, and tags can be moved. So an update also
  checks that the release's tag commit is on that repo's `main`, and that it
  matches the commit in the release's asset manifest (frozen) or the fetched
  tag (source). Proving who built a frozen asset (GitHub artifact attestations,
  or a signing key shipped in HeLab) is still open; see below.

## Release repos (proposed 2026-10-13, Tony to confirm)

**Confirmed by Tony on 2026-10-28** (`.ai/DECISIONS_TODO.md` Q1.4). v0.0.6a1 is not lab-ready,
so `HeBECANU/HeLab` waits for a later version (Q1.4.1). The heading keeps its old name so
that links to it still work.

Both repos run the same `dev-cicd.yml`, with Actions enabled, so a new version
reaching either repo's `main` drafts a release **in that repo**. Today
`TonyXTYan/HeLab` has the releases (v0.0.2e, v0.0.3b, draft v0.0.4a);
`HeBECANU/HeLab` has none, and its `main` (`f44aab0`) is an ancestor of
`TonyXTYan/HeLab`'s.

- **Develop, review and release on `TonyXTYan/HeLab`** for now: PRs, squash
  merges and draft releases there. Its releases are the development and
  pre-release source (a known repo in the update setting).
- **`HeBECANU/HeLab` gets lab-ready versions only.** When a version is ready for
  the lab, fast-forward `HeBECANU/HeLab`'s `main` to the same commit (`git push
  HeBECANU <sha>:main`), which drafts the same version there; publish it after
  checking. Never squash or rebase on `HeBECANU`: the commits must stay
  identical, so both repos' tags name the same commit and update status agrees
  across repos.
- **Stop pushing dev branches to `HeBECANU`**: each push there runs a second
  full CI (runs on 2026-10-08 were cancelled ones).
- The first lab-ready version is when the lab update check (default repo
  `HeBECANU`) starts seeing releases; until then it shows nothing.

## Stage 1: notify only

HeLab asks GitHub for its releases and says when a newer one exists. It never
downloads or changes anything.

- **Source of truth:** published GitHub releases, read from
  `GET https://api.github.com/repos/<owner>/<repo>/releases` without a token.
  Drafts are invisible without a token, so publication stays Tony's manual
  step. `releases/latest` is not enough: it skips pre-releases.
- **Compare versions** with `packaging.version.Version`: the running version
  from `helab/build_info.py` (the same for source and frozen) against the
  newest release on the chosen channel (tag without the `v`).
- **When:** Help → Check for Updates… at any time, and at most once a day at
  startup (on by default; a Settings → General switch turns it off). Send
  `If-None-Match` with the saved ETag: a 304 reply doesn't count against
  GitHub's 60 unauthenticated requests per hour per IP, which a lab sharing one
  address could otherwise reach.
- **No GUI blocking:** `QNetworkAccessManager` (asynchronous on the event loop,
  no worker thread) with a short timeout; or a small `io_helper` request if Qt
  networking misbehaves on the lab PCs. Failures and offline PCs are quiet at
  startup and explained only for the manual check.
- **Display:** no banner and no extra vertical space (see the UI vertical-space
  rule). A small status-bar indicator or a Help menu entry ("HeLab 0.0.6 is
  available"), with release notes and a link to the release page; "Skip this
  version" stops the startup reminder for that version. Help → About shows the
  version status and the last check.
- **Instructions per mode:** frozen builds link to the platform asset; source
  checkouts show the git/uv commands until stage 2 can run them.
- **Nothing else is sent:** GETs to `api.github.com` with a `User-Agent` of
  `HeLab/<version>`; no telemetry.

## Stage 2: self-update button

An "Update and restart" action next to the stage-1 notice, using the same repo
and channel. **Updates are always started by a person; HeLab never installs
anything by itself.** It never runs during a load, cache move or other I/O that
can't be stopped, and only runs when this is the only HeLab running (the
`instances/<pid>.lock` files already say so). HeLab quits cleanly first:
helpers stopped, cache locks released. A **Restore previous version** action
goes back to the one previous version kept on disk.

### The updater process

The same flow on every OS (Windows is the strict case: it locks running
`.exe`, `python.exe` and `.pyd` files):

1. HeLab starts the updater **detached** (`QProcess.startDetached`), so it
   outlives HeLab, with no console window (`pythonw.exe` /
   `CREATE_NO_WINDOW`). It runs from **outside what it replaces**: the
   uv-managed base Python (`sys._base_executable`) for source checkouts, a
   copy in the temp folder for frozen builds.
2. The updater opens a handle on HeLab's process at once (safe against PID
   reuse), then tells HeLab it's ready; only then does HeLab quit.
3. It waits for that handle, and for every `io_helper` (they run from the same
   venv or bundle and lock its files): all `instances/<pid>.lock` released and
   no process still running from the venv or install folder.
4. It updates (below), then relaunches HeLab **detached, as the same user in the
   same desktop session**, and exits.
5. A program can't delete itself on Windows: the next HeLab start removes the
   leftover updater copy.

It refuses to run from an SSH or elevated session: on the Lab Main PC,
launching HeLab over SSH poisons its cache settings, and the new GUI would
start in the wrong session.

**Never change code HeLab is running.** Modules imported later would mix old and
new code, and Windows would fail partway through. So all of the following
happen after HeLab and its helpers have exited.

**Source checkout** (first: it's what the lab uses):

- Check out the release **tag** (detached HEAD), then `git submodule update`.
  Later updates move from tag to tag; to develop on that checkout, switch to a
  branch by hand.
- Build a **new venv beside the old one** (`venv.new`: `uv venv` + `uv pip
  install -r requirements.txt -e .`), check it imports HeLab, then swap the
  folders. Never install into the running venv: a half-installed venv is worse
  than no update. Keep the old venv until the new version has started
  successfully: rolling back may need packages no longer in uv's cache or on
  PyPI.
- Local changes: refuse, or (offered in the dialog) stash them first as
  `git stash push -m "HeLab update <from> → <to>"`, and say how to get them
  back. Stashes are never dropped or popped automatically. Untracked files
  that the new tag would overwrite: refuse with the file names.
- Refuse with a reason when `git` or `uv` is missing, or the release needs a
  different Python minor version (then the venv must be rebuilt by hand).
- Record the previous commit and keep the previous venv for Restore.

**Frozen build:**

- Download the platform zip, check its size and SHA-256 against the release's
  asset manifest (already written by CI), and unpack it beside the current
  install.
- Swap the folders, keeping the previous version for Restore. Versioned
  side-by-side folders plus a stable launcher avoid renaming a folder that
  holds a running `.exe`.
- macOS: files can be replaced while in use, so the same flow is simpler. Updates
  HeLab downloads itself get no quarantine flag; an unsigned first install from
  a browser still meets Gatekeeper, and signing/notarisation needs a paid Apple
  developer account.

### Rolling back, cache and settings

Restoring the app does not restore the cache or settings. Version N may meet a
cache and QSettings written by N+1 (after Restore, or on a PC that runs both a
source checkout and a built app, which share both). Design them to be
**forward and backward compatible, and to recover by themselves on errors**:

- The store records a schema version (today only the folder name `store-v2`
  and each dataset's `DATASET_FORMAT` do; `records.sqlite` has no version).
  Changes are additive where possible
  (new tables/columns/keys that older versions ignore); an older HeLab opening
  a newer, incompatible store refuses it with a clear message (or uses a
  separate folder) rather than guessing, and never rewrites it.
- Migrations never destroy the old format in place until the new version has
  started successfully; a failed migration leaves the old data usable.
- Unreadable or unknown records, datasets and settings values are treated as
  missing (the data is re-read from source) and reported, never fatal; a
  setting outside its valid range falls back to its default.
- The cache can always be rebuilt from source data, so the last resort is
  setting the unreadable part aside (never deleting without asking, as now) and
  starting fresh.

### Releases and unpublishing

Publishing a release makes it one click away for everyone in the lab, not
just Tony. An optional per-PC "Don't offer updates" setting covers a
measurement campaign.

- **Unpublishing** (deleting the release, or marking it a pre-release so the
  stable channel skips it) hides it from PCs that haven't updated. PCs that
  already updated see their version as newer than any release, so they are
  offered nothing: they need Restore previous version, or a fixed release.
- **Fix a bad release with a new version.** CI rejects equal or lower versions
  anyway. Deleting a published release but keeping its tag makes CI's release
  recovery re-draft that version on the next same-version push to `main`
  (harmless, but confusing): bump `_version.py` first.

### Ways to download, apply and restart

Options considered 2026-10-13:

| Option | Covers | Notes |
|---|---|---|
| [Velopack](https://docs.velopack.io/getting-started/python) (`velopack` on PyPI) | Frozen, all three OSes | Official Python SDK and a PyInstaller (`--onedir`) workflow: `App().run()` at startup, `UpdateManager` checks, downloads and applies, restarting into the new version; feeds can be GitHub Releases. Changes packaging: `vpk` (a .NET tool) builds installers, and the app installs into its own folder. Authenticity comes from OS code signing. |
| [tufup](https://pypi.org/project/tufup/) (on python-tuf) | Frozen | Built for PyInstaller bundles; TUF signed metadata gives rollback/freeze protection and key rotation. The newest tufup release found was 0.9.0 (June 2024), so check it's maintained first. |
| Sparkle (macOS) + WinSparkle (Windows) | Frozen, per OS | Mature, EdDSA-signed appcasts, but two native integrations and no Linux. |
| Our own | Source and frozen | Small and fits the existing pieces (asset manifest, `instances` locks, the frozen helper entry point in `main.py`); everything here must then be built and tested by us. |

Safety needs, whichever is chosen:

- **Signed manifest.** CI signs the manifest (version, commit, asset sizes
  and SHA-256) with an Ed25519 key kept as an Actions secret; HeLab ships the
  public key and verifies before unpacking anything. One signature covers both
  modes: a source update checks the fetched tag points at the signed commit.
- **No downgrades** except Restore previous version, or an older version picked
  deliberately.
- **Stage, then swap.** Download into the install's own volume, verify,
  unpack (rejecting paths that leave the folder), then rename into place.
- **Roll back if the new version doesn't start.** The new version marks a
  successful start; without it within a time limit, the updater restores the
  previous version and says why.
- **Refuse where it can't work safely:** a macOS app running translocated
  (from Downloads or a disk image), an install folder that needs admin rights,
  an SSH or elevated session, or the source checkout cases above.

Leaning (not decided): our own updater for source checkouts first, since the
lab runs from source and git + uv do most of the work; then choose Velopack or
our own for frozen builds when lab PCs start using them.

## Risks

- **The first updater can't be fixed by an update.** Version N's updater
  installs N+1; a bug in it strands every PC on N until someone updates by hand.
  Keep it minimal, and test a full N → N+1 update (and Restore) against a fake
  release feed on Windows and macOS before shipping it.
- **The signing key is a way onto lab PCs.** Leaked, anyone can sign code;
  lost, updates stop. Before first use: where it is backed up, how to rotate it
  (ship two public keys, or have the old key sign the new one), and who in the
  group can release after Tony leaves ANU, so `HeBECANU/HeLab` can release
  without him.
- **ANU-managed PCs.** IT policy, AppLocker or antivirus may block programs that
  replace themselves, or unsigned ones; PyInstaller builds often trigger false
  positives. Ask IT before relying on frozen updates.
- **Lab network.** On the RSPE office PC, PowerShell couldn't resolve
  `releases.astral.sh` although `nslookup` could; DNS or proxies may behave
  differently per tool. Test the check on each lab PC; "can't reach GitHub" is a
  quiet, clearly worded state.
- **Reproducibility.** Two analyses of one run can come from different HeLab
  versions; exported results should record the version and commit
  ([reproducible workflows](reproducible-workflows.md)).

## Open decisions

- **Proof of who built a frozen asset.** The manifest comes from the same
  release as the asset, so it proves the download is intact, not who made it.
  GitHub artifact attestations (bound to the repo and workflow) or a signing
  key whose public half ships in HeLab. Needed before stage 2's frozen path.
- **Release repos:** confirm the [proposal](#release-repos-proposed-2026-10-13-tony-to-confirm).
- **Frozen updater:** Velopack, tufup or our own (see the table above).
- **Source and frozen on one PC, and local builds** (separate issue). They
  share QSettings and the cache folder (see
  [Rolling back](#rolling-back-cache-and-settings)). A locally compiled app is
  a development version: notify only, never replaced by a CI build without
  asking.

## Later

- A lab self-check (`helab --self-check` or a Help item): the data volume can
  be read, the cache folder can be written and isn't refused, and a plot pane
  actually paints (a small offscreen render). Run after each update; results
  feed release validation in [MANUAL_TODO](../.ai/MANUAL_TODO.md).

## Acceptance

- Stage 1: source and frozen runs of the same commit give the same status; an
  older version sees the newest published release on its channel; drafts never
  show and pre-releases only when opted in; a dev branch shows "Development
  version"; offline startup shows nothing and doesn't delay the window; tests
  cover version comparison, channels, status, ETag reuse and failures without
  network access.
- Stage 2: an update with local changes (unless stashed), missing tools, other
  instances running, or from an SSH/elevated session is refused with the
  reason; a tag not on `main` or not matching the manifest is refused; the
  updater waits for HeLab and all its helpers before changing files; a failed
  update leaves the previous version working; both modes restart into the new
  version, and Restore previous version brings back the old one.
- Before the first updater ships: an end-to-end N → N+1 update and Restore
  pass on Windows and macOS against a fake feed; the store has a schema
  version, and the previous release opens a newer store safely (refuses or
  ignores what it doesn't know, never corrupts it); key backup and rotation
  are written down.
