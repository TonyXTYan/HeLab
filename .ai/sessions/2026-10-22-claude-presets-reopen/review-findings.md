# Review findings: Flint (Codex), `a74fd07` against `c3d4b50`

Request changes: four reproduced issues; 1 is the blocker. Fix all four with a regression test each
(Flint's probes are below in outline), alongside Follow-up 1. Reply to CoCo with the fix commits.

1. **[P1] `helab/views/plots/arrangement.py:107-114`: `FolderWait._in_ram` accepts pinned RAM for a
   known mismatched folder.** `FolderCache._mismatch` drops datasets but leaves tab pins until
   released (`folder_cache.py:1467-1485`). `FolderWait` scans pins without testing
   `cache.mismatched`, emits `found` and runs on data known not to match the folder. Probe:
   `cache.retain("existing-tab", dataset)`, `cache._mismatch(dataset.path, {"missing": [1]})`, then
   `FolderWait.look()` emits `found` with that dataset. Applying an arrangement while another tab pins
   old data bypasses the Review / Load as it is now protection. Guard the RAM path as the cached
   path already does, until a normal load resolves the mismatch.
2. **[P2] `arrangement.py:149-172` and `:119`: an `unverified=True` cached-read error becomes a
   permanent cache miss.** `_read_tried` stays true and nothing retries on `volumesVerified`, so a
   startup reopen on an external volume can race verification and wait for ever despite local
   cached data. `FolderExplorer._cached_event` / `_volumes_verified` handle this (as `read_cached`
   documents). Probe: send an unverified error to the wait's request, emit `cache.volumesVerified`:
   no cached read is resubmitted. Retry this transient failure through the local lane; disconnect on
   stop.
3. **[P2] `helab/views/plots/presets.py:512-514` / `:352-353`: applying a Live-off preset to the
   current folder leaves Live on.** `open_to_path` (which stops Live) is skipped when `selected_path`
   and `view_path` already match; `PresetFolder` just finishes for `live=False`. Probe (real window,
   offscreen): apply an empty-folder arrangement with `live=True`, wait for Live, apply `live=False`
   for the same folder: `explorer.live` stays active. Reconcile the existing Live with the saved
   choice explicitly.
4. **[P2] `arrangement.py:273`: a malformed `dock_state` aborts reopening/applying instead of being
   recovered.** The parser accepts any string; a valid JSON record with a non-ASCII `dock_state`
   reaches `encode("ascii")` and raises `UnicodeEncodeError` (confirmed with U+2603).
   `PlotReopen.restore` and `ArrangementPresets.apply` don't catch it around `open_arrangement`, so
   Apply aborts before `PresetFolder` is installed, losing the folder-load / Live phase. Validate and
   decode defensively, name the bad layout, keep compatible plots in fallback tab groups.

Flint's checks at `a74fd07` (detached worktree): full suite 2531 passed, 2 skipped, 2 xfailed,
1 RERUN (`tests/test_cache_first.py::test_a_folder_changed_within_its_mtime_tick_is_listed[cached]`,
`assert 1792659756000000000 is None`, `:841`, already in known-issues); strict mypy (helab, tests)
and pyright clean. Doc note: that RERUN stays in `roadmaps/known-issues.md` (CoCo handles).
