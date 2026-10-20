# Brief: D2 per-shot trends (Worker)

From the Coordinator, 2026-10-20. Branch `agent/dld-d2` from `6a9671e` (merge of
agent/dld-decisions). Authority: [roadmaps/dld-front-panel-port.md](../../../roadmaps/dld-front-panel-port.md)
(D2; Decided: Low counts, Hooks, units) and the review notes' D2
([notes](../2026-10-20-claude-dld-front-panel-review/notes.md#d2-per-shot-trends)).

A new DatasetAnalysis "Shot trends" (group "Basic plots v1", PyQtGraph), x axis shot number or
shot time (`DatasetView.shot_times()`, fallbacks marked as in `shot_times.py`):

1. Per shot: counts in the plot's own View range (shared `range_specs`), and per axis (T, X, Y) the
   centre and width: fitted Gaussian centre/σ (± SE; T from σ via physics with the run's
   `ResolvedConstants`, `constant_keys` like basic_plots) or a threshold-edge estimate
   (`find_dist_cen` style) — a choice.
2. Moving mean ± SD over a window (default N) as a band; low-count shots in amber by two rules
   (absolute count and/or fraction of the last N shots' mean, each a checkbox; proposed 50 and
   50 %, N = 100).
3. Opt-in desktop notification during Live (off by default, a plot setting) when the newest shot
   is low: `QSystemTrayIcon.showMessage` if available, else status bar / log; once per shot,
   rate limited; through ONE central event point (e.g. `helab/utils/events.py`), with Live errors
   routed there if small and safe. Never outside Live or for historical shots.
4. Per-shot results cached by (shot, fingerprint, settings), thread-safe and bounded; LivePolicy if
   needed.
5. Records: per-shot summary in `found` (`record_lines`), constants once, notes.

Others are editing plots' titles/UI and fits/profiles/release/velocity/bootstrap: keep changes in
new files plus minimal registration. Acceptance: tests for all of the above, mypy --strict,
pyright, `git diff --check`, full suite clean except the two root-only failures. Do not push or
merge.
