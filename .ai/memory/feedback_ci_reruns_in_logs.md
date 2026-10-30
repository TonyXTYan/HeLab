---
name: feedback-ci-reruns-in-logs
description: "A green CI job can hide RERUNs: read every Tests and Converter backends job's log before reporting a CI run"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 9f95099f-0394-47b6-9616-b7bd3de498e0
  modified: 2026-10-31T00:00:00.000Z
---

A HeLab CI job that passed only after `--reruns` still shows `success` in `gh run view`, so job conclusions
alone can't support "no RERUN". Before reporting any CI run (to the Coordinator, Tony, a handoff or a PR),
fetch each Tests and Converter backends job's log (`gh api repos/TonyXTYan/HeLab/actions/jobs/<id>/logs`)
and grep it for `RERUN`, `rerun reasons` and `N rerun`; quote each rerun's reason and check it against
`roadmaps/known-issues.md`.

**Why:** On Quick Fixes 7 (2026-10-31) two CI runs were reported as passing from their job conclusions; their
logs held three RERUNs, one of them new (`test_accessible_names` "QTabBar … no ID"). AGENTS.md requires every
RERUN to be reported. Kept as a shared rule by Tony (2026-10-31).

**How to apply:** Every time a run is reported, read all its test jobs' logs first. If the jobs API fails
(HTTP 502), retry later rather than reporting from conclusions.
