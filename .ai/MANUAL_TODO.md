# HeLab Manual To-do

The ongoing list of work requiring manual action, including native UI checks,
real-volume testing and release validation. Product features and known issues
belong in the [roadmap overview](../roadmaps/_readme.md).

Keep items concise and tick them when completed. Record detailed results, tested
commit, OS/build and reproductions in `.ai/sessions/`, linked from the item.
New confirmed product issues go in `roadmaps/_readme.md` with a link to the evidence.

The v0.0.5a checks below were added on 2026-10-08 and remain pending.

## v0.0.5a: real data volume and cache

- [ ] In the full app on `/Volumes/dld_output`, exercise cache-first display,
  two-step browse and names-only Refresh. Confirm reselecting a RAM-held folder
  shows data immediately; decide whether the older "keep the previous signature"
  concern is resolved.
- [ ] Restart the app and confirm disk-cache reuse, unchecked cached display,
  subsequent verification and data/count agreement.
- [ ] Observe new shots during writing: unsettled files are excluded, counted
  honestly and included on a later explicit check/load after settling. Live
  updates remain deferred.
- [ ] On a disposable fixture, interrupt an original TXY write, then complete or
  repair it. Verify an explicit check/load detects the recovery and replaces any
  partial result. Record the actual required action; toolbar Refresh only
  relists names. Do not modify real experiment files for this check.
- [ ] Switch and close tabs during shared listings/checks/loads; remaining tabs
  retain their subscriptions, data and truthful progress.
- [ ] Cancel and retry during active I/O; verify responsiveness, retained usable
  data and no replacement attempt starting alongside a still-stopping helper.
- [ ] Disconnect/unmount the source volume during I/O using a disposable source
  where practical; verify responsive navigation, cancellation, usable cached
  data and clear failure/retry state. Reconnect and retry.

- [ ] Load a large folder on `/Volumes/dld_output` and judge the Folder details
  time-left estimate (settles within a few seconds, stays steady, excludes
  paused time) and the short status bar. Added 2026-10-09.

- [ ] Check whether `/Volumes/dld_output`'s `st_dev` changes across unmount/
  remount (`python -c "import os;print(os.stat('/Volumes/dld_output').st_dev)"`
  before and after). If it changes, saved summaries and failure history are
  dropped on every remount ([audit](sessions/2026-10-10-claude-cache-audit/notes.md), finding 9). Added 2026-10-10.

## v0.0.5a: cache rebuild (native checks, added 2026-10-11)

Built in S6–S10 of the [cache plan](../roadmaps/cache-storage-and-settings.md#sessions) and
tested offscreen only. Check on native macOS (and once on a Windows lab PC):

- [ ] Settings → Cache: the inventory appears, Clear by kind and Clear all ask first and the
  tab refreshes; both purges show estimates; lowering the disk budget below use asks and
  trims; the RAM budget spin box shows "16.0 GB (1/8 of 128 GB)"-style values.
- [ ] The disk cache dialogs with a small disk budget: the 80% warning (Open purge settings
  opens the Cache tab at Remove old entries; Ignore this time), Make room / Don't cache this
  folder now, Save update / Don't cache this update now; one at a time, never behind Settings.
- [ ] Large-folder warning on `/Volumes/dld_output` with a low RAM budget: the amber summary
  line, Load anyway… dialog (tick box enables Load anyway), No auto-load, Folder details and
  the status bar; a folder over 30% of RAM is refused.
- [ ] Cache move: Change… to a folder on the same disk (instant), then to another disk
  (progress, Cancel during the copy keeps the source), a refused target (network, synced or
  non-empty) with Show in Finder; quit during a copy and confirm the next start finishes or
  undoes it. Start a second HeLab during a move: it waits.
- [ ] Folder flags: right-click toggles, row badges and tooltips, "Auto-load off for this
  folder · Load", the Remove its cached data question, and the Folder preferences row.

## v0.0.5a: native UI and packaged application

- [ ] On native macOS (and a Windows lab PC), start a large manual recursive basic
  scan, resize once and repeatedly, and confirm painting, progress and Cancel work
  before scans finish ([resize fix](sessions/2026-10-11-codex-resize-during-scan/notes.md#implementation)). Added 2026-10-11.
- [ ] Build the PyInstaller app and confirm the right-pointing SVG triangle
  renders (including Qt's SVG icon plugin), helper operations run and native
  folder/volume icons appear.
- [ ] On native macOS, check triangle hover, click, keyboard opening, Escape,
  delayed dismissal, pointer reentry and the accepted hover-then-click
  close/reopen flicker. Check the independent main-icon check/cancel target.
- [ ] Run the folder-browser smoke checks on a Windows lab PC, including native
  popup behavior, cached data, source loading and packaged helper execution.

## v0.0.5a: release evidence

- [ ] Versioning (added 2026-10-12): on native macOS and Windows, launch the packaged
  app from outside the checkout; Help → About must match its version, commit and
  UTC build stamp. On the first release PR, verify PRs only check/build, the new
  main version gets an explicit tag on the squash commit plus a draft, alpha/final
  pre-release flags agree, publishing is manual, and tag pushes do not release twice
  ([implementation](sessions/2026-10-12-codex-app-versioning/notes.md)).
- [ ] Release recovery (added 2026-10-12): in a disposable test release, fail after
  tag creation and after a partial upload; rerun all jobs, then try a later same-version
  main push. Confirm tagged-SHA rebuild/tests, preservation of completed uploads,
  correct asset stamps/digests and refusal to change a moved tag/published release.
  Check PR stamps show the source branch and merge ref plus the actual merge SHA.

- [ ] Release repos (added 2026-10-13): confirm the
  [proposal](../roadmaps/app-updates.md#release-repos-proposed-2026-10-13-tony-to-confirm).
  If confirmed, stop pushing dev branches to `HeBECANU`. For the first lab-ready
  version, fast-forward `HeBECANU` `main` to the released `TonyXTYan` commit
  (`git push HeBECANU <sha>:main`; no squash or rebase there), check the draft
  appears there with the same tag commit and assets, then publish it.
- [ ] Self-update prerequisites (added 2026-10-13), before the first updater ships:
  ask ANU IT whether managed lab PCs allow self-replacing/unsigned programs;
  test reaching `api.github.com` from each lab PC; decide where the signing key
  is backed up and who can release after Tony leaves
  ([risks](../roadmaps/app-updates.md#risks)).
- [ ] Cached-data check (added 2026-10-13): on `/Volumes/dld_output`, time selecting a
  cached folder at each Settings → General → Check of cached data level; move an older
  folder into a cached folder's path and confirm the mismatched-folders window (rows, button
  tooltips, status-bar "⚠ N mismatched") for the shown folder, a background load and a
  folder status check; with two or more moved folders confirm loads and scans pause with the
  banner, then Resume / Cancel all, and from 8 Skip; return to a folder after adding a TXY
  and confirm the new shot loads.
- [ ] macOS release zip (added 2026-10-13): download the macOS CI artifact, check
  `HeLab-macos.zip` is ~300 MB and holds only `HeLab.app`, unzip it in Finder and
  open the app (right-click › Open for the ad-hoc signature)
  ([build size step 1](../roadmaps/build-size.md#steps-cheapest-first)).
- [ ] Record the required Python 3.13 suite/type-check and build results for the
  release commit. This is validation evidence, not a new testing feature.
- [ ] Observe hover-menu tests in CI: real timers have approximately 200 ms of
  slack and may flake on slow machines. If a failure is reproducible, add a
  concrete test-reliability item to `roadmaps/_readme.md` with logs.
