# Notes: D2 per-shot trends

## Where things are

- `helab/analysis/trends.py` (no Qt, no I/O): one shot's estimate (`estimate_axis`,
  `estimate_shot`, `threshold_edges`, `gaussian_equivalent`), the per-shot cache (`ShotCache`,
  `CACHE`), the box's rounding (`nice_step`, `snapped`, `ShotCache.stable_range`), moving
  statistics (`moving_stats`), the low-count rules (`previous_means`, `low_flags`, `LowFlags`).
- `helab/scripts/standard/shot_trends.py`: the plot (`ShotTrends`, `compute_trends`, `Trends`,
  `TrendsWidget`), its record, and the notification decision (`low_alert`, `notify_low`).
- `helab/utils/events.py`: the one event point (`notify`, `EventHub`, `DesktopNotifier`).
- Registration: `helab/scripts/standard/__init__.py` (`MODULES`), one line each in
  `helab/analysis/follow.py` (`LiveFeed` registers with the hub), `helab/views/FolderExplorer.py`
  (`_live_halt` raises `live_error`) and `helab/views/HelabMainWindow.py` (the status-bar sink).
- Tests: `tests/test_shot_trends.py`; the shared lists in `test_script_system.py`,
  `test_analysis.py`, `test_live_plots.py` (coverage/reuse key, empty plots, Live policy) and
  `test_display_units.py` (ms/mm settings).

## Design

### Per shot

- **Box.** Counts are the events inside all three axes' ranges. The ranges are the View range's:
  manual bounds as set; otherwise (auto-crop, or a manual axis left at its full extent) found in
  all chosen shots' events. A range found in the data is rounded out to `nice_step(width/20)`
  plus one step each side, and kept from the plot's previous run while the data's range stays
  inside it and fills at least 2/3 of it (`ShotCache.stable_range`). Without that, auto-crop's
  99 % range moves a little with every Live shot, which changes the box, which invalidates every
  shot's cached estimate. The record and the dock's record line give the box used.
- **Estimates.** Each shot's histogram per axis of its events inside the box, over that axis's
  range; bins 0 = Freedman–Diaconis per shot. Shots with fewer than "At least" events (20) get
  no estimate (counted per axis in the title's notes).
  - Gaussian fit: `fits.fit_histogram(..., "gaussian")`, Poisson weights: centre and σ ± SE.
    (Not `profiles.fit_axis`: it needs the constants and draws a curve; the cache keeps only
    centre/σ, and temperatures are derived after, with the same formulas as `fit_axis`.)
  - Threshold edges: the outermost bins at or above f × peak; each edge interpolated linearly
    between that bin's centre and the next one out (the histogram's edge if it is the first or
    last bin). Centre = midpoint, width = distance; no SE. The legacy `find_dist_cen`'s one-bin
    offset and overwritten `centre_OK` are not copied (core-update.md).
  - Temperatures (when shown): σ_v = g σ along T, σ/t_f along X and Y, T = m σ_v²/k_B
    (`physics`), SE by first order. Threshold edges use the Gaussian-equivalent σ =
    width / (2√(2 ln 1/f)), and a note says so.
- **Cache.** `trends.CACHE` (module level, 50,000 entries, LRU, a lock): key = (root key or
  source path, shot, fingerprint, (method, fraction, bins, min events, box)). Shared across plot
  instances: the key holds everything the estimate depends on, so sharing is safe. Shots without a
  fingerprint aren't cached. The data reports `computed` / `reused`; the record line says
  "Per-shot estimates: N computed, M reused".

### Over the shots

- Moving mean ± SD: trailing window of the last N shots by shot number, the shot itself
  included; non-finite values (failed estimates) skipped; SD with n − 1, nan below 2 values.
  Sums of offsets from the first value, so a T centre of 20,450 ms with µs spreads stays exact.
  In time mode the band is drawn in time order.
- Low counts: `fewer than C` (strict) and/or `below p × mean of the N shots before` (the shot
  itself left out; the first shot never flags by the fraction). Either rule flags (OR). Flagged
  shots are amber in every panel, so low-count shots' bad estimates are easy to tell.
- One "Window N" (default 100) serves both the band and the fraction rule.

### Notifications and the hub

- `events.notify(kind, message, *, title, key, desktop, rate_key, **data)`: records an `Event`
  (history of 256), calls every hook (exceptions logged, never raised), and with `desktop=True`
  delivers through the notifier unless rate limited.
- Once per key (the last 4,096 keys); rate limit per (kind, rate_key) of `RATE_SECONDS` = 60 s.
  A held-back notification is still an event for hooks (`shown=False`), and the next shown one
  says "(N more since the last notification)".
- `DesktopNotifier`: a `QSystemTrayIcon` made on first use (the app's window icon, else Qt's
  warning icon) where `isSystemTrayAvailable()` and `supportsMessages()`; else a WARNING log line
  and the main window's `show_status_notice` (held by `WeakMethod`).
- "During Live": `notify_low` runs on the GUI thread in `render`/`update` and needs all of
  - Notify during Live on, at least one rule on, the newest chosen shot low;
  - the newest shot is in the view's `added_shots` (Live's revision added it): a plot opened on
    shots already there, a rerun of revision 1 or a reload never notifies them;
  - `events.hub().is_live(path)`: some `LiveFeed` (each registers itself) currently has the
    folder, i.e. a tab's Live is checking it (not stopped by an error).
  The key is (kind, path, shot, fingerprint), so a rerun, a second plot or a reload of the same
  shot notifies nothing more.
- Live errors: `FolderExplorer._live_halt`, the one place Live stops on an error, calls
  `events.notify(LIVE_ERROR, …, path=…, error=…)` with no desktop notification (record and hooks
  only; the tab's amber line is unchanged).

## Proposed, for Tony

1. **Default method: threshold edges** (fast, the legacy per-shot method). The Gaussian fit costs
   about 15 ms per shot and axis here (≈ 45 ms per shot; a 1,000-shot folder's first run ≈ 45 s,
   cancellable; Live then fits only new shots). Its tip says so.
2. **Both low-count rules on by default for the amber flags**; the notification off (as decided).
   Defaults 50 events and 50 %, N = 100 (open decision 2).
3. **One window N** for the band and the fraction rule (could be two settings).
4. **Rules combine with OR**; the fraction rule's mean includes earlier low shots (a run of empty
   shots lowers the reference; an "exclude flagged shots" option is possible).
5. **The box is rounded out and kept** while the data stays inside it (above), so Live's per-shot
   results are reused; a run's box can depend on the previous run of the same folder and settings.
   The record says the box used, and a note says it was rounded/kept.
6. **Rate limit 60 s per folder**, once per shot; held-back ones counted in the next.
7. **Tray icon**: shown on first notification and left in the tray/menu bar for the session.
8. **Only the newest shot notifies**: when one Live revision adds several shots, an earlier low one
   among them doesn't (as specified: "when the newest shot is low").
9. **Temperatures off by default** (three more panels); threshold edges give them from the
   Gaussian-equivalent σ, with a note.
10. **Live errors go to the hub without a desktop notification**; a hook or a later setting can
    make them notify.

## Checks

See [handoff.md](handoff.md#checks).
