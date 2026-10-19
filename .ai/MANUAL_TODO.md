# HeLab Manual To-do

The ongoing list of work requiring manual action, including native UI checks,
real-volume testing and release validation. Product features and known issues
belong in the [roadmap overview](../roadmaps/_readme.md).

Keep items concise and tick them when completed. Record detailed results, tested
commit, OS/build and reproductions in `.ai/sessions/`, linked from the item.
New confirmed product issues go in `roadmaps/_readme.md` with a link to the evidence.

The v0.0.5a checks below were added on 2026-10-08 and remain pending.

## Data roots (v0.0.5a1, added 2026-10-18)

Native checks of the data-roots stages D1–D4 ([plan](sessions/2026-10-16-claude-data-roots/plan.md)).
Use disposable folders or shares where possible; never place a `.helab-root` on
real experiment data without deciding where its top should be.

- [ ] Place .helab-root here… from macOS on an SMB share: the marker is hidden in
  Windows Explorer on the lab PCs (`UF_HIDDEN`), and from Windows it gets the
  hidden attribute. The folder's cache works after the relisting.
- [ ] A read-only share (or write-protected USB disk): the manual dialog's Copy and
  Save to folder… (writes `.helab-root`, hidden; ⌘⇧. shows it in Finder) give the
  exact file; moved into place by hand, Retry / Refresh finds it.
- [ ] The placement checks: a share's subfolder offers "Place at <top>", Return
  cancels, a nested root and a home folder warn.
- [ ] Windows, a tab at a mapped drive's top (e.g. `Z:\`), nothing selected:
  File › Place .helab-root in “Z:\”… writes `Z:\.helab-root`; with a subfolder
  selected the item names it instead. A tab at `C:\` gets the system-folder
  warning with Cancel as default.
- [ ] One folder through two mounts (e.g. `C/.../dld_output` and the separate
  `dld_output` share): "Same folder or a copy?" opens once; Same folder shares
  one cache; Later reopens at the next sighting; Remind me next session stays
  quiet; "⚓ N to confirm" reopens it.
- [ ] A copied folder or cloned USB disk: It's a copy… keeping either side; the
  other gets a new marker and an empty cache; the original keeps its data.
- [ ] Two same-named USB disks used in turn at `/Volumes/USB`: each keeps its own
  cache; at startup a restored tab on the second disk doesn't show the first
  disk's cached data.
- [ ] The macOS startup disk: a marker in `~/data` works through the firmlinked
  `/Users` path; Windows `C:\` refuses, a data folder works.
- [ ] Folder details shows ⚓ with the marker in use, or RAM only; the tree's ANCHOR
  badge; greyed disk-cache menu items on RAM-only folders; Settings → Data roots
  lists and forgets locations.
- [ ] Settings → Data roots, a mounted row: Show in Finder (macOS) and Show in
  File Explorer (Windows) open the folder with the hidden `.helab-root`
  selected (visible after Cmd+Shift+. / View › Show › Hidden items); Copy path
  gives the file's path. Delete .helab-root… removes it (on Windows too, with
  its hidden attribute), and the folder turns RAM only in Folder details; on a
  read-only share it names the file instead.
- [ ] Settings → Data roots › Clear cached data… on a root with cached folders:
  the confirmation names the label and size; afterwards those folders show
  no cached data (a load reads the source), another root's folders keep
  theirs, and Don't cache / Don't auto-load flags stay.
- [ ] A location answered Later (one folder through two mounts): its folder and
  subfolders show the amber warning triangle beside their status icons, the
  row tooltip names the other location, the selected folder's summary says
  "RAM only · this .helab-root is also at another location" with Review…,
  and Settings → Data roots' Review… opens the window (usable while Settings
  stays open); after Same folder they all go.
- [ ] The TDC converter and the lab MATLAB scripts ignore `.helab-root`.
- [ ] Before using this build: `store-v3` starts empty; move the old `store-v2`
  folder to the Trash by hand once you no longer need it.


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

- [x] Confirm `/Volumes/dld_output`'s `st_dev` changes across mounts. A read-only
  comparison of saved identities with the mounted folders found hundreds of
  device-only differences; the cache no longer uses those IDs for status
  validity ([investigation](sessions/2026-10-15-codex-status-remount/notes.md)).
- [ ] Before first launching the account-independent SMB-key build, quit HeLab
  and move `store-v2` from the active cache directory to the Trash for a fresh
  store. Alternatively, launch the new build, answer Don't cache to any old
  pending-save prompts, then use Settings → Cache → Clear all and the separate
  Folder preferences Clear action. Repeat on each lab PC being upgraded;
  HeLab does not remove the old cache itself.
- [ ] Restart the native GUI with `/Volumes/dld_output` mounted: after one
  completed check has saved share-keyed records, saved status icons and
  blocked-scan badges should remain across a remount, changed folder mtimes
  should show an amber clock, and automatic visible scanning should not recheck
  those saved statuses ([investigation](sessions/2026-10-15-codex-status-remount/notes.md)).
- [ ] Remount two disposable SMB shares in opposite orders on a test volume and
  restart the native GUI: each share should retain only its own status, scan
  history, preferences and datasets. After the cache clear, each share's first
  visit should build its own saved records.
  Also remount while HeLab stays open: when the saved records can be read,
  toolbar Refresh should replace the shown branches' saved badges and mark RAM
  data unchecked; restart still refreshes paths outside those branches and
  other tabs' loaded data.
- [ ] On a Windows lab PC, verify a mixed-case mapped folder and its UNC spelling
  resolve to the same cache record and that Clear, Make room and pending-save
  dialogs return the folder's original path spelling. With a disconnected mapped
  drive, time mount lookup and print `_windows_mounts()` with the drive both
  connected and disconnected (Explorer red X). Confirm WNetGetConnectionW gives
  the share name or fails safely, browsing does not block or record a scan
  failure, and repeated cache warnings do not flood the tab line or tooltip.
  On a disposable NFS/AFP/WebDAV mount, confirm one short Disk cache off line
  with the mount type and full tooltip detail, while browsing still works.

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
  and confirm the new shot loads. Added 2026-10-14: hold ↓ across cached folders with
  auto-load on (Finish mode) and confirm nothing loads until you stop, then the last
  folder loads within 1 s; a single click on an idle app loads at once; Review… on a
  mismatched folder opens the list on it.
- [ ] macOS release zip (added 2026-10-13): download the macOS CI artifact, check
  `HeLab-macos.zip` is ~300 MB and holds only `HeLab.app`, unzip it in Finder and
  open the app (right-click › Open for the ad-hoc signature)
  ([build size step 1](../roadmaps/build-size.md#steps-cheapest-first)).
- [ ] Record the required Python 3.13 suite/type-check and build results for the
  release commit. This is validation evidence, not a new testing feature.
- [ ] Observe hover-menu tests in CI: real timers have approximately 200 ms of
  slack and may flake on slow machines. If a failure is reproducible, add a
  concrete test-reliability item to `roadmaps/_readme.md` with logs.
