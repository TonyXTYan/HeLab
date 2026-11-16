# Keep HeLab up to date

HeLab can tell you when a newer version is available, and a HeLab run from source (a git checkout with
its venv, as on the lab PCs) can update itself and start again with one button. A compiled HeLab (the
`HeLab-<os>.zip` from a release) only checks: it links the download.

## See whether there is an update

HeLab asks GitHub once a day, 30 s after it starts, and at any time from **Help › Check for Updates…**.
When something newer is available:

- the status bar shows a small mark, `⬆ 0.0.9` (or `⬆ dev/v0.0.9 +3` when following a branch);
- the Help menu has an entry above Check for Updates…, `HeLab 0.0.9 is available…`.

Both open the update window. Nothing is downloaded or changed until you ask for it. If GitHub can't be
reached, the startup check says nothing and tries again at the next start; Check for Updates… says why.

**Help › About HeLab** shows the version status, where updates come from and when HeLab last checked.
The status is one of:

| Status | Means |
|---|---|
| Release 0.0.9 | This is exactly release 0.0.9, unchanged. |
| Pre-release 0.0.9a1 | The same, for an alpha, beta or release candidate. |
| Development version (based on 0.0.9) | Anything else: a branch ahead of a release, local changes, a local build. |
| … update available: 0.0.10 | Something newer is offered (below). |

## What HeLab updates to

Settings › General, **Updates from:**

- **The repository**: `HeBECANU/HeLab` (the lab's) or `TonyXTYan/HeLab` (where HeLab is developed).
  **Default** follows the repository the checkout's branch comes from, else `HeBECANU/HeLab`.
- **What to follow** (a checkout only):
  - **The branch HeLab runs from** (the default on a branch): HeLab moves forward along that branch, only
    to a commit whose automatic tests passed on macOS, Windows and Ubuntu. It never skips back, never
    rewrites history, and never moves to a commit whose tests failed or haven't finished. It moves only to
    the branch's own commits, never to one that came in from another branch by a merge: after a merge,
    it waits for the merge's own tests.
  - **Releases**: HeLab moves from release to release (the default when the checkout is on a release, not
    a branch). The checkout leaves its branch; to work on a branch there again, check it out by hand.
  A compiled HeLab always follows releases.
- **Include pre-releases**: offer alpha, beta and release-candidate versions too.

**Check for updates at start (once a day)** turns the startup check off; Check for Updates… still works.
In the update window, **Skip this version** stops the startup reminder for that version (or commit); a
newer one is offered again.

## Update and restart (a checkout)

1. Open the update window and click **Update and restart…**. HeLab first checks the checkout and fetches
   the update, without changing anything, and shows what will happen, or why it can't.
2. Click **Quit and update**. HeLab quits as File › Quit does: Live stops and its new shots are saved,
   and saves still running are finished first (the quit window shows them).
3. HeLab's updater, a small separate program, waits until HeLab and all its helper processes have
   exited, updates the checkout, and starts HeLab again. Only when the new version needs different
   packages (`requirements.lock` or `setup.py` changed) does it build a new venv first, beside the old one,
   which takes a few minutes; otherwise the venv is kept.

While the updater works, HeLab can't be started: started by hand, HeLab (or `helab convert`) says it is being
updated and stops, and the update goes on. HeLab starts by itself when the update has finished.

When HeLab starts again, the status bar says it was updated. If anything went wrong, HeLab is put back as
it was and starts again, and a message says what happened, with the updater's log. (If the new version
couldn't start and its helper processes still ran two minutes later, it is left in place instead, and the
message says how to go back.)

HeLab won't update, and says why, when:

- it was started from an SSH session, or with administrator rights;
- the checkout has changes you haven't committed (the window offers **Stash my changes first**: they go
  into a git stash named `HeLab update <from> → <to>`, which HeLab never deletes; `git stash list` and
  `git stash apply` bring them back), or untracked files the update would overwrite;
- `git` isn't installed, or `uv` isn't when the venv must be rebuilt;
- the new version needs another Python version;
- another HeLab (a `helab convert`), a cache move or another update is running;
- the checkout isn't on the branch it follows, has commits the repository's branch doesn't, or the release
  isn't on the repository's `main`.

## Restore the previous version

**Help › Restore previous version…** goes back to the version HeLab had before its last update, and to its
previous venv when that update built a new one. It quits and starts again the same way. Restoring again
undoes it. The version it left isn't offered again at start (as with **Skip this version**); a newer one
is. HeLab keeps one previous version; when a later update builds a new venv, the venv from before the
previous one is deleted once the new version has started.

The disk cache and the settings stay as they are: an older HeLab reads what a newer one wrote, and treats
anything it doesn't know as missing.

## What HeLab sends

Only `GET` requests to `api.github.com` (its releases, tags, branch comparisons and test results), saying
`HeLab/<version>`, and, when you update, `git fetch` from the repository. No account, token or telemetry.
GitHub allows 60 requests an hour from one network address; HeLab reuses its previous answers, which don't
count, so a lab sharing one address stays well below that.

## Do it by hand

From the checkout, with HeLab closed:

```bash
git fetch HeBECANU                 # or the remote that names the repository
git checkout v0.0.9                # a release; or: git merge --ff-only HeBECANU/dev/v0.0.9
uv pip install -r requirements.lock -e .   # only if requirements.lock changed
```
