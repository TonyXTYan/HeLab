# App updates discussion

The plan itself is [roadmaps/app-updates.md](../../../roadmaps/app-updates.md); this
records how it was reached.

- Self-hosted runners on lab PCs were rejected: both repos are public (fork PRs
  could run code on experiment PCs), a runner service has no desktop/GPU session
  (misses the QtWebEngine black render), and runners compete with data taking
  and install their own Pythons (RSPE office PC: every `py` Python was a
  runner's; six runners `RSPE-064759-1..6` registered, not running on 2026-10-08).
- Tony's decisions: notify-only check first, from source and frozen alike;
  "Update and restart" later for both. Default repo `HeBECANU/HeLab`, with a
  hard-coded list of known repos (`TonyXTYan/HeLab`); stable by default,
  pre-releases opt-in for the check and the update; dev branches show a
  "Development version" status; source updates check out the tag, with an
  optional stash of local changes; only releases from the repo owners.
- Checked 2026-10-13: both repos run `dev-cicd.yml` with Actions enabled, so a
  new version on either `main` drafts a release in that repo. `TonyXTYan/HeLab`
  has v0.0.2e, v0.0.3b (latest) and draft v0.0.4a; `HeBECANU/HeLab` has no
  releases, its `main` (`f44aab0`) is an ancestor of `TonyXTYan` `main`, and it
  still has `dev/v0.0.5a`, `dev/v0.0.old` and old `v0.0.1*` tags.
- Proposed (Tony to confirm): develop and release on `TonyXTYan`; fast-forward
  `HeBECANU` `main` only for lab-ready versions and let its CI tag them (push
  `main` only, no tags, never squash/rebase there); stop pushing dev branches
  to `HeBECANU`. Suggested final versions only on `HeBECANU`, since the lab
  checks stable releases by default; not yet decided.
- Updater options surveyed: Velopack (official Python SDK, PyInstaller
  `--onedir`, GitHub Releases feeds; `vpk` installers change packaging), tufup
  (python-tuf; newest release found 0.9.0, June 2024), Sparkle + WinSparkle (no
  Linux), or our own. Leaning: our own for source checkouts first. Sources:
  [Velopack Python](https://docs.velopack.io/getting-started/python),
  [tufup](https://pypi.org/project/tufup/),
  [tufup releases](https://data.safetycli.com/packages/pypi/tufup/).
- Docs only: roadmap doc, `_readme.md` items (Now: release repos; Near term:
  update check; Medium term: self-update) and a MANUAL_TODO release-repos step.
  Uncommitted.

## Caveats added (Tony asked, after review)

- Added to the roadmap doc: the updater process (detached, run from outside
  what it replaces, waits on a process handle plus all `io_helper`s, relaunches
  detached as the same user, refuses SSH/elevated sessions); source updates
  build `venv.new` and swap instead of installing into the running venv;
  Restore previous version; rollback, cache and settings compatibility with
  self-recovery; releases and unpublishing; a Risks section; acceptance for
  the first shipped updater.
- Tony: updates are always manual (no auto-install); a bad release can be
  unpublished on GitHub. So the earlier "blocked versions" idea was dropped in
  favour of Restore previous version: unpublishing helps only PCs that haven't
  updated. Deleting a published release but keeping its tag makes CI recovery
  re-draft that version on the next same-version `main` push, so fix bad
  releases with a new version.
- Found: the store has no schema version (only `store-v2` in the folder name
  and `DATASET_FORMAT` per dataset; `records.sqlite` has none). Needed before
  rollback can be safe.
