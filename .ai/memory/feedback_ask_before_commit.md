---
name: feedback-ask-before-commit
description: "Always ask before running git commit, even when changes are verified and ready"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 83fa924c-d904-40df-ba15-ec9696cf8992
  modified: 2026-08-17T11:04:40.505Z
---

Never run `git commit` without asking Tony first, even after a fix has been implemented, tested, and verified. Staging, diffing, and reviewing changes (`git add`, `git status`, `git diff`) is fine without asking — only the commit itself requires explicit go-ahead each time.

**Why:** Tony wants a final checkpoint before changes become permanent history, regardless of how confident the work is. This applies even in auto-mode / when otherwise encouraged to act without stopping for clarification.

**How to apply:** After finishing and verifying a change, present the diff/summary and ask whether to commit, rather than committing and reporting after the fact. This is now codified in `.ai/coding-workspace.md` (symlinked from `ai-common/coding-workspace.md`), so it applies across all of Tony's repos, not just this one.
