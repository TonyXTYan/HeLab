# Smoke pass on Tony's Mac (partial), 2026-10-30

Runner: Claude Sonnet 5.5 via computer use (background `app_*` tools; full-screen control once, for the settings table). Supervisor: Tony.
Build: `.ai/local/HeLab-dev.app` (`python dev/dev_app.py`), started with `--geometry 1600x928+0+39`. About: HeLab 0.0.6a1, commit 6dec236a8d96…, dev/v0.0.7, source clean.
Config: DATA_ROOT=/Volumes/dld_output; CACHED=20260625_Ramsey_weak_trap (519 shots); OTHER=none used; PHYSICS=20260625_Ramsey_weak_trap (RingBEC is too slow, see the 10-28 run); RAM_ONLY=none; ACQUIRING=no; OLD_BUILD=none; RECORD_TRACE=no.
Log: `helab-77020.log` (this folder; no error, exception or traceback lines).

Not a clean first start: the 10-28 and 10-30 provisional state was still there (preset `smoke`, arrangement `smoke-arrangement`, floating plots restored). Preset saved as `smoke-final` so `smoke` was not overwritten.

| Check | Verdict | Seen / note | Shot |
|---|---|---|---|
| M1.1-1 | PASS | Window with folder tree, restored plots | |
| M1.1-3 | PASS | About: HeLab 0.0.6a1, commit 6dec236a…, dev/v0.0.7, source clean (the stub's app menu says "About __main__.py", not a HeLab bug) | |
| M1.1-4 | PASS | Settings › Cache: 793 MB of 8.6 GB, rows and sizes, no error | |
| M1.2-1 | PASS | Ramsey selected by row click: "519 TXY found", ⚓, Loaded, source memory | |
| M1.2-3 | PASS | After File › Quit and restart, Ramsey: "Cached data loaded", 519 loaded within seconds | |
| M1.2-2, 2-4 | SKIP | OTHER not used; RAM_ONLY=none | |
| M1.3 | SKIP | no run acquiring | |
| M1.4-1 | REVIEW | Two T, X, Y plots; Bins 50 + Return committed (see note 1); Save… as `smoke-final` OK. Could not open the Preset combo to read its list (popup refused) | |
| M1.4-2 to 4 | NOT RUN | needs clicks the background tools can't do reliably (Log Y tick, double-click float, Replace/Add) | |
| M1.5 | NOT RUN | step 3 needs Tony's yes first | |
| M1.6-1 | PASS | "Offline · cached data only" in the status bar; Folder details "Loaded from cache · not checked (offline)" (consistent now) | shots/M1.6-1.png |
| M1.6-2 | PASS | Counts per shot drew offline (`plot_done`, state=ok) | |
| M1.6-4 | PASS | Work Offline off: "Work Offline off", then `load_done … source=check` | |
| M1.6-3 | NOT RUN | not tried | |
| M1.7 | PASS (REVIEW physics) | All 13 DLD plots on Ramsey `plot_done state=ok`: T/X/Y 0.2 s, Mean X,Y 1.2 s, T spectrum 0.9 s, Density 1.1 s, Shot times 0.0 s, Shot trends 0.6 s, Release time 48.4 s, Velocity 1.7 s, Correlations 31.8 s, Transfer fractions 0.2 s. Transfer fractions shows an amber note ("3 shots with ≤ 50 counts left out; no side peak found beyond order 0's width…"). Physics, T like `20,450`, clipped titles not judged | shots/M1.7-transfer-fractions.png |
| M1.8 | NOT RUN | | |
| M1.9 | NOT RUN | | |
| M1.10 | SKIP | OLD_BUILD=none | |

## Notes (for Tony and dev)
1. **Return now commits a typed value** (Bins 50 stayed, editor closed): the first provisional finding is fixed.
2. **The plot settings table opens with its Value column off the right edge** for the DLD histogram plot (panel about 281 px wide; "Parameter" column is wider than the panel). A person sees names and no values until they scroll right; the plot/settings splitter would not move with a real mouse drag either (full-screen drag from the splitter at the plot's right edge did nothing). Transfer fractions shows its values at the same width, so it depends on the longest parameter name.
3. The Debug menu has the runner items (Run Plot, Script Group, Show/Close Plot Tab, Save Window Screenshot…, Dump State…); the placeholders are gone. It has no "Settings Tab" item, so the older route (gear button) was used.
4. Settings › General: the label reads "Temp folder", not "DIR_TEMPS" (fixed).
5. Two floating plots restored on top of each other at the same place after the restart (the provisional finding about stacking still holds; two plots left floating from the earlier pass).
6. Tooling: Return in the path bar can't be sent in the background, so folders were selected by clicking the tree row. Full-screen clicks did not reach the window in this session while scroll did.

## Stops, RERUNs, crashes
No unknown dialogs. No crash or hang. No tests were run (UI pass only). No RERUN applies.
