---
name: feedback-keep-branches-on-github
description: "Don't delete agent branches or worktrees after use; push them to TonyXTYan/HeLab for the record, and test other machines from GitHub rather than bundles"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 73ff0229-f2c3-41a1-bde6-3d6b3ecfce98
  modified: 2026-10-19T06:23:00.042Z
---

Keep agent branches and worktrees rather than cleaning them up, and push work to GitHub (`TonyXTYan/HeLab`) for the record. To test a branch on another machine (e.g. the RSPE Windows PC), push it and `git fetch`/checkout there over SSH instead of copying a bundle into a temporary worktree.

**Why:** Tony (2026-10-19): "don't need to remove the old gitworktree btw, just throw everything on github for record"; "just push the RSPE branch up to TonyXTYan github, then pull on RSPE machine and start pytest via ssh".

**How to apply:** Pushing an agent branch to test it is fine, even mid-floor. Don't delete remote or local agent branches unless Tony asks. Related: [[feedback_ask_before_commit]].
