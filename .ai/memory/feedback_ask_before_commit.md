---
name: feedback-ask-before-commit
description: "Ask before git commit in Tony's checkout/branches; agents on their own new branch (worktree/floor/cloud) commit freely and push once when done"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 83fa924c-d904-40df-ba15-ec9696cf8992
  modified: 2026-08-17T11:04:40.505Z
---

Never run `git commit` without asking Tony first, even after a fix has been implemented, tested, and verified. Staging, diffing, and reviewing changes (`git add`, `git status`, `git diff`) is fine without asking — only the commit itself requires explicit go-ahead each time.

**Why:** Tony wants a final checkpoint before changes become permanent history, regardless of how confident the work is. This applies even in auto-mode / when otherwise encouraged to act without stopping for clarification.

**How to apply:** After finishing and verifying a change, present the diff/summary and ask whether to commit, rather than committing and reporting after the fact. This is now codified in `.ai/coding-workspace.md` (symlinked from `ai-common/coding-workspace.md`), so it applies across all of Tony's repos, not just this one.

**Scope (Tony, 2026-10-15):** this applies to Tony's checkout and branches. An agent working in its own worktree, Maestri floor or cloud environment, on a new branch started from the commit Tony or the coordinator chose, may commit there freely and pushes that branch once, when its work is done (each push runs the full CI matrix). Merging into Tony's branches, landing a floor and opening a PR still need his approval. HeLab's AGENTS.md and `roadmaps/agent-workflow.md` record this; the shared `.ai/coding-workspace.md` (symlinked from ai-common) says the same.
