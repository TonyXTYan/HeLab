# Area review: `plots` (Reviewer 4, Plotter)

Area: `helab/analysis/`, `helab/scripts/`, `helab/views/plots/`, `helab/utils/dash_server.py`, against
`plots-and-scripts.md`, `dld-analyses.md` and AGENTS.md's analysis rules. Base `c3a503f`, read-only.
Scratch scripts: `.ai/temp/plots-review/` (not committed).

**Summary: 4 findings (1 High, 2 Medium, 1 Low) and 2 nits. No data loss or corruption found; the High is
plots silently not following Live (and stale plots not marked) after the folder's data starts a new view
chain.**

## Findings

### plots-1 · High · A folder's views of different data share one `ViewIdentity`, so plots stop following Live

`helab/analysis/dataset_view.py:274` (identity from `dataset.signature`), `helab/analysis/follow.py:78-84`
(`newer`) and `:159`, with the signature set in `helab/io_ops/loading.py:711` and `helab/io_ops/helab_txy.py:305`
(boundary: `io`/`convert` make the signature, this area relies on it).

**What's wrong.** `ViewIdentity` is (path, root key, signature, `identity_source`). A dataset's signature is
**the folder's MATLAB-TXY signature, the same for every TXY choice** (`loading.py:710`: "every source's
dataset of it has this one"; `matlab_signature` drops HeLab's shots). So:
- a folder with **no MATLAB TXY** (raw files converted by HeLab, v0.0.7's main use) has signature
  `sha256("[]")` for every load, whatever shots it holds;
- two choices that `identity_source` maps to "" (HeLab priority / MATLAB priority) or the same mode under
  **another profile** share the signature and the source.

Those views are distinct chains (`revise` refuses another choice, Q18.2, and a load that lost shots), but their
identities are equal. `newer()` then compares revisions only: a new chain starts at rev 1, so a plot that ran
rev N ignores the new chain's revisions 1…N and silently stays on the old data, while its line still says
"following Live" with nothing waiting. `ViewKey` (identity, revision) also collides, so the new chain's rev 2
equals the old chain's rev 2.

**Scenario** (verified: `.ai/temp/plots-review/follow_identity.py`, real `revise`/`view_of`/`Follow`,
output below): a raw-only folder under Live with auto-convert; a plot follows to rev 6 (shots 1–7).
(A) Live restarts on a newly loaded `Dataset` → feed's view is rev 1, same identity → `newer` False, not
offered. (B) Settings › TXY converter: another profile (or HeLab ↔ MATLAB priority) while Live runs → the next
dataset is another choice → rev 1 of an equal identity → not offered, nor its rev 2.
```
plot ran rev 6 shots [1, 2, 3, 4, 5, 6, 7]
A: fresh load rev 1 same identity as plot's: True | newer(): False | offered: False
B: other profile rev 1 same identity: True | offered: False
B: its next revision 2 offered: False (the plot ran rev 6 )
ViewKey of plot's run == ViewKey of other-profile rev? [2]
```
The GUI trigger for (B) is from reading (`ConverterTab.py:462-463` → `FolderCache.set_convert_profile` /
`set_tab_source`: "loads from now on read its TXY"), not run in the app. (A) needs a new `Dataset` object
between Live's stop and start (the feed drops the folder on stop, `workspace.py:203`); unverified how often
the tab gives one.

**Same root, also verified by reading:**
- `workspace.py:305-309` (`_update_plot_source_label`): a plot not following Live counts as current when the
  dock's `dataSourceSignature` equals the folder node's. For a raw-only folder both are always `sha256("[]")`,
  so a plot of 5 shots says "Data source" (not "Showing previously loaded data") after the folder has 50, and
  after a profile change.
- `shot_trends.py:394-405` (`newer_than_drawn`): low-count notifications stay quiet for a new chain until its
  revision passes the old one.
- `tests/test_live_plots.py:307` gives each "another input" its own fake signature (`"sig-again"`,
  `"sig-changed"`), so the suite never sees two chains with one identity.

**Fix direction.** Give each view chain its own identity: e.g. a `chain` token (or the choice text plus a
per-`build_view` id) in `ViewIdentity`, carried by `with_shots`, so `newer` treats any other chain as newer;
keep the reuse key's fields as they are (its coverage already holds fingerprints and origins). The source
label should compare the shown view's coverage/fingerprints, not the MATLAB signature. Add a test with two
datasets of one raw-only folder (equal signatures).

### plots-2 · Medium · Two HeLabs overwrite each other's "plots open at quit", and the second reopens the first's

`helab/views/plots/arrangement.py:445-462` (`PlotReopen.record`), `:383-405` (`restore`), `:464` (`quit`); boundary `app`
(settings store).

**What's wrong.** `OPEN_PLOTS_SETTING` is one key in the shared settings store. Each HeLab rewrites it whole on
every plot open/close and at quit, with only its own plots. HeLab allows several instances (`cache_locks`
counts "Another HeLab is running (N windows)").

**Scenario** (read the code path; not run with two apps): HeLab A has plots P1, P2. Start HeLab B: `restore`
reads A's record and opens P1, P2 in B as well (same instance ids, `keep_ids=True`). In B the user closes them
and opens P3 (record = {P3}). Quit B, then quit A: A's `quit()` writes {P1, P2}; B's P3 is gone at the next
start. Whichever quits last wins; the other's arrangement is lost with no message. The "Keep for later" list
(`kept`) has the same last-writer race.

**Fix direction.** Either reopen only in the first instance (and have later instances neither restore nor
record), or record per instance and merge at start (or ask). User-visible, so a decision for Tony
(`DECISIONS_TODO`, provisional Q~1 below).

### plots-3 · Medium · Velocity distributions' Live-kept detection and crop box aren't keyed by the TXY data

`helab/scripts/dld/velocity_distributions.py:532-535` (`kept_key`), used at `:740-741`.

**What's wrong.** A Live rerun reuses the plot's last t_r detection and auto-crop box when `kept_key` matches:
the path, root key, parameters and constants. The key has no TXY source, profile or view identity. An "as the
tab" plot's next Live run after the tab's TXY choice changes (another profile, e.g. a recalibration that
moves X/Y; or another source mode) gets `context.live=True` (`instance.py:1079`) and keeps the **other
data's** t_r and box. Combined with plots-1 this happens once the new chain's revision passes the old one; on
its own fix, at the first Live run of the new choice.

**Scenario** (read the code path): Live + auto-convert, Velocity distributions as the tab; switch the
conversion profile to a recalibrated one. The next Live rerun converts the new profile's events with the old
profile's t_r and crops them with the old box ("kept from rev N"), until the user reruns by hand.

**Fix direction.** Put `view.identity.source`, `view.txy_choice` and the covered origins' profile hashes (or
the chain token of plots-1) in `kept_key`. Correlations' kept box and detection (`correlations_plot.py:540-565`)
are compared against a fresh detection, so less exposed; worth the same key for consistency.

### plots-4 · Low · On macOS the Dash server can share port 8050 with another program instead of moving

`helab/utils/dash_server.py:131-147` (`_bind`, lines 135-137).

**What's wrong.** `SO_REUSEADDR` is set everywhere but Windows, whose comment says that there it "would let us
share a port another program is using". On macOS (BSD semantics) it does that too: it lets `127.0.0.1:8050` bind while another program listens on `0.0.0.0:8050` (Dash's own
default port), and connections to 127.0.0.1 then go to HeLab. The code's intent ("another free port when
it's in use") fails silently: the other app's localhost users reach HeLab's pages, and HeLab never moves.

**Scenario** (verified: `.ai/temp/plots-review/reuseaddr.py` on this Mac): wildcard listener first, then a
127.0.0.1 bind with `SO_REUSEADDR` → bound, and a connection to 127.0.0.1 is accepted by the second socket.
Two HeLabs (both 127.0.0.1) are still refused (EADDRINUSE), so they don't collide with each other. Linux
refuses the wildcard case anyway.

**Fix direction.** Drop `SO_REUSEADDR` on macOS too (TIME_WAIT on a listening port only matters after a
restart within a minute, and port 0 is the fallback), or probe by binding `0.0.0.0:8050` without it first.

## Nits

- `helab/views/plots/cached_results.py:83`: `reuse_on`'s docstring says Reuse saved analysis results is "on
  by default"; it is off by default since Q27.1 (`settings_defaults.py:113`).
- `cached_results.py:_show` / `instance.py:_cached_found`: an outdated saved result shown while the run goes on
  doesn't set `_shown_view`, and if that run then fails the amber line keeps "saved result … is outdated:
  rerunning" beside the failure. Cosmetic.

## Checked and fine

- **Read-only shared arrays:** `dataset_view.read_only` freezes the `.base` chain; views are never copied;
  `with_shots` and `budget_core.restore` keep that.
- **Result reuse key** (`AnalysisResult.reuse_key`, `result_cache.lookup_key`): includes the analysis id,
  version, file hash, action, both signatures, `txy_source` (non-priority), parameters in use (not `unused`),
  coverage with fingerprints **and origins** (so profiles and priority modes differ), the constants record of
  the run's keys, mask circles, and the environment; `found` and the root key are left out as documented.
  Exact match restamps job id/input/owner. Despite plots-1, saved and RAM results can't be mixed up: their
  keys and `Coverage.diff` compare fingerprints and origins, not the identity alone.
- **Disk-cached results' guard and verification paths** (`CachedRuns`): no save without a guard; a Clear
  cached analysis after a late or state-holding run fences its save; unverified volume retried once, then
  `VERIFY_WAIT` / `SAVE_VERIFY_WAIT`; closed plots finish their saves, then disconnect.
- **Released-plot reload** (`instance.reload`, `_in_ram`, `budget_core.restore`): only the plot's own TXY
  choice's data, by fingerprint and origin; the disk cache only for "as the tab" plots; another source loads
  from the folder only on a deliberate Reload; shots changed or missing are named.
- **Reopen and arrangement presets** (`FolderWait`): RAM (cache-owned datasets only, never a tab pin) or one
  `cached` read; nothing while mismatched; another data root's folder only on a deliberate Rerun.
- **Runner** (`runner_core.AnalysisQueue`): one worker, FIFO, cooperative cancellation, `stop` refuses new
  jobs until the worker exits, results packed on the worker, job references dropped between jobs.
- **Per-plot script state:** Correlations' `PairCounts` and in-shot cache match shots by fingerprint (another
  TXY file recounts), dropped on close/release; Shot trends' `ShotCache` keys by identity, shot, fingerprint and
  settings; per-owner states dropped in `plot_closed`.
- **Hooks that raise:** `_hook` wraps the slot-time hooks; others are covered by `app_log`'s `sys.excepthook`.
- **Dash:** per-plot `PlotSnapshot` read atomically under a lock; plot ids are `uuid4`; `weakref.finalize`
  removes a figure; nothing connects Python to `destroyed` in this area.
- **Rules:** no `pyplot`, PyVista or VisPy; results without pickle (`allow_pickle=False`); no
  `ScatterPlotItem` on a log axis (Shot trends' has none; Shot times uses `PlotDataItem`).

## Checks run (this floor, `c3a503f` + reviewers' session files)

- `pytest -n 4 --reruns 5 --reruns-delay 1 --basetemp=.ai/temp/pytest-review-plots`: **8510 passed, 672
  skipped, 12 warnings in 421 s; no RERUN** (the summary lists none). Two `faulthandler` 100 s dumps were
  printed with no failure: `test_typing.py::test_pyright_helab` and `::test_pyright_tests` waiting on pyright
  while the five reviewers shared the CPU; both passed on their first try. Warnings: pyqtgraph's NumPy 2.5
  `arr.shape` deprecation (`test_accessible_names.py`, `test_t_spectrum.py`), unrelated. Log:
  `.ai/temp/plots-review/suite.log`.
- `mypy helab/ --strict`: no issues in 195 files; `mypy tests --strict`: no issues in 175; `pyright helab tests`:
  0 errors, 0 warnings (`.ai/temp/plots-review/types.log`).

## Proposed doc changes (for CoCo)

- `plots-and-scripts.md`, Dataset analyses: after "identity = source path, `root://` key and signature": "(the
  signature is the folder's MATLAB-TXY signature, the same for every TXY choice and `sha256([])` for a folder
  without MATLAB TXY: the identity alone doesn't tell two loads apart; see plots-1)" until plots-1 is fixed.
- `roadmaps/known-issues.md`: plots-1 (plots stop following Live after a new view chain of one identity;
  stale plots of raw-only folders not marked), plots-2, plots-3, plots-4, unless fixed first.

## Provisional items

- **Q~1** (Tony): plots reopened at start with two HeLabs running (plots-2). (a) **Proposed:** only the first
  HeLab reopens and records them; a later one says "plots open in another HeLab aren't reopened here". (b) Each
  records its own; at start, reopen the newest record and keep the others for later. (c) Leave as is.
- **A~1** (may do without asking): fix plots-1 with a chain token in `ViewIdentity` plus the raw-only test;
  plots-3's `kept_key` and plots-4's `SO_REUSEADDR` follow from it in the same branch.
