---
date: 2026-10-11
status: settled
name: disk-cache-and-budgets
description: "The rebuilt disk cache (S1–S11, commits fe5a5b7…eafcf4b): store-v2 (SQLite records + Blosc dataset files, helpers only), nothing removed without asking, disk budget with the 80% pause and its dialogs, RAM budget in 1/128 steps, large-folder warning (unscaled TXY size; 10%/budget warn, 30% refuse), cache-folder move with crash recovery, per-folder Don't cache / Don't auto-load flags; Tony's wording"
metadata:
  node_type: memory
  type: result
---
The disk cache, its budgets and the Settings → Cache tab, as rebuilt in sessions S1–S11 of
`roadmaps/cache-storage-and-settings.md` (that plan holds the full design and per-session notes;
AGENTS.md has the code map). Decided with Tony on 2026-10-10, built 2026-10-10…11, each
session reviewed by Codex until clean.

## What was decided, and why

- **Old cache dropped, not migrated** (early development). Records are plain JSON text in SQLite
  (`store-v2/records.sqlite`, WAL); datasets stay Blosc-compressed pickles in files (a
  pickle-free format is an unchosen roadmap idea). **Only helper processes open the store.**
- **Nothing is removed without the user asking.** Records are kept forever and never removed
  to make room. Removals go through one store function that bumps generations/epochs, so a
  save already running can't bring removed data back.
- **Disk budget**, default 8 GB, counts live data only. At **80%** automatic loads of folders
  without cached data pause ("Auto-load paused — disk cache 80% full"); the warning comes once
  per crossing (Open purge settings / Ignore this time, which lasts the session until usage
  rises another 10% of the budget). A save that doesn't fit asks **Make room / Don't cache this
  folder now**; an update that grows a cached folder over 80% asks **Save update / Don't cache
  this update now**. One question at a time; the data stays in RAM either way.
- **RAM budget**: steps of 1/128 of RAM, default 1/8, minimum 1 GB; evicts datasets no tab
  shows, least recently used first.
- **Large folders**: estimate = TXY files' size on disk, used directly, **unscaled**. A loaded
  dataset takes about 0.69× that in RAM (measured on Tony's 19 cached folders), so the estimate
  is about 1.45× the dataset's RAM: an overestimate, the safe side (Tony's choice, no
  calibration). A load's peak can still be higher (the dialog says up to 2–3×). Above the RAM
  budget or 10% of RAM, automatic loads never start (amber "Large folder · ~X in RAM" with
  **Load anyway…** and **No auto-load**); deliberate ones ask (tick "I understand this may slow
  down or stop HeLab" to enable Load anyway). Above 30% of RAM nothing loads. Replaced the old
  1 GiB limit.
- **Cache folder move** (Settings → General → Change…) while HeLab runs: target checked
  (empty or new, writable, space, never network or synced), I/O held, rename or
  copy+verify, setting saved and synced before the switch, old folder deleted last. A
  `cache-move.json` record lets the next start finish or undo any interrupted step. Failures
  say why with Show in Finder/Explorer.
- **Folder flags** (right-click): **Don't cache this folder**, **Don't auto-load this folder**,
  that folder only. Tooltip lines "Not cached: your choice" / "Not auto-loaded: your choice";
  "Auto-load off for this folder · Load data". Kept through Clear all and purges; the Cache
  tab's Folder preferences row clears them.

## Lessons from the reviews (keep these when changing the code)

- Order measurements and choices by the store's own counters or saved times (`usage_seq`,
  `budget_set_at`, prefs `set_at`, `prefs_cleared_at`), never by when a result arrives.
- Anything a user approved (a large load, a budget change) travels with the one request it
  covers; nothing stays in tab-wide state.
- A change the user makes is saved before it takes effect where a race matters (disk budget:
  the store records it before Settings saves it).
- Destructive steps act only on what they can prove is theirs (a move's marked copy, its own
  record id, a lock holder's token).

## Plot RAM budget (Tony, 2026-10-19/20)

- Plots count toward the existing RAM budget (a fraction of the machine's RAM). 50 % of it: status-bar warning only; 75 %: a non-modal window, once per crossing (re-armed below 70 %); 80 %: release plots, least recently shown first, after datasets no tab shows. Never close a plot; never release the shown, running or Live plot.
- A released plot keeps a static picture with Reload; it reloads automatically when shown again (Settings → Cache, default on), only from RAM or the local disk cache, never the source folder (no "Reload from folder"), exactly the shots it drew.
