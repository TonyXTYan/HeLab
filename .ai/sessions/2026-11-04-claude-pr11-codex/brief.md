# Brief: PR #11's Codex review fixes (`agent/pr11-codex`)

Coordinator: CoCo, 2026-11-04. Tony (Chat): "please address codex reviewer and reply to @codex once your fixes are
pushed". PR TonyXTYan/HeLab#11 (`release/v0.0.8a1` → `main`). Codex reviewed `f0bb9f9`
([review 5753393176](https://github.com/TonyXTYan/HeLab/pull/11#pullrequestreview-5753393176)) and left three
findings, all in caching v2 (store-v4, on by default since `92f9d1a`). One Worker; one Reviewer at landing. CoCo
replies on the PR, not you.

## The findings (verbatim, then what to do)

**C-1 (P1), `helab/io_ops/txy_cache.py`: "Validate each view's layer version before returning its shots".**
> When two source choices have views referencing the same layer, updating a shot through one view replaces the layer
> entry without updating the other view's fingerprint. `_read_data` then reads the latest layer data by shot number
> alone and returns it under the older view's fingerprint and signature. For example, after Live rereads an extended
> MATLAB TXY and saves the priority view, a previously saved External-only view returns the new arrays with the old
> fingerprints. `read_cached` propagates that combination, allowing analysis-result reuse keys to match results
> computed from different data. Preserve or validate the layer-entry version referenced by each view, and treat
> mismatched shots as unavailable rather than returning them with stale provenance.

**C-2 (P1), `helab/utils/cache_store.py`: "Distinguish TXY sources when marking layers as recoverable".**
> If a MATLAB TXY disappears but HeLab's TXY for the same shot remains, loading the HeLab source passes that shot in
> `Access.mark_seen`'s combined TXY set. This predicate consequently marks the cached MATLAB layer as seen, even
> though its own source is gone and the HeLab conversion is not an equivalent copy. `purge_cached` and
> `clear_folder_data` then select it through `gone_at IS NULL`, and Make room no longer identifies it as an only
> copy. Track presence per layer/source rather than just fingerprint kind and shot number, so another profile's TXY
> cannot make the only cached copy eligible for ordinary removal.

**C-3 (P2), `helab/io_ops/txy_cache.py`: "Apply completion checks before converting cached raw pulses".**
> For a raw file whose first channel is not the requested profile's trigger channel, `raw_fill` deliberately permits
> caching because it has no profile with which to perform that check. This path subsequently reconstructs those pulses
> without calling `raw_layer.not_done(layer.facts, profile.channel_trigger)`. The same file loaded without a raw-cache
> hit is rejected as late or damaged by `convert_raw_file`, but with a cache hit it becomes an apparently valid shot
> and can be persisted in a TXY layer; reconstruction uses the incorrect first row as time zero. Apply the
> profile-dependent completion check before reconstruction and fall back to the normal rejection path when it fails.

For each finding, in this order:
1. **Confirm or refute it with a failing test first**, in a temp store with store-v4 on (`switch_on`/`v4_live`
   fixtures). If the finding is wrong, show why in the handoff, with the test that proves the code right; CoCo
   decides.
2. **Fix it.** Keep the identity, guard and housekeeping rules in AGENTS.md:
   - every store write checks its save guard;
   - nothing the user hasn't been asked about is removed;
   - an only copy is never offered as ordinary removal.
3. **One commit per finding**, with the test that fails without the fix.

If a fix needs a schema column or table, it goes through `store_v4.migrate` (AGENTS.md), and older stores of this
alpha's layout keep opening.

## Read first

- `AGENTS.md`, the cache and I/O rules;
- `.ai/architecture/cache-store.md`, the store-v4 sections: views, TXY layers, `gone_at`, Make room's order and only
  copies, convert on read;
- `.ai/architecture/io-and-browsing.md`, "Loads with TXY layers" and "Loads under a TXY list";
- the caching v2 design notes in `.ai/sessions/2026-10-31-claude-caching-v2/` (`design-stage2.md`, `design-stage3.md`);
- `helab/io_ops/txy_cache.py`, `helab/utils/cache_store.py`, `helab/utils/store_v4.py`, `helab/io_ops/raw_fill.py`,
  `helab/convert/raw_layer.py`.

## Base and branch

Base: `dev/v0.0.8` at `ded2f3b` (the PR's head minus the version bump). Branch: `agent/pr11-codex`. CoCo lands it on
`dev/v0.0.8` and merges that into `release/v0.0.8a1`.

## Rules

Owned paths:
- `helab/io_ops/txy_cache.py`, `helab/utils/cache_store.py`, `helab/utils/store_v4.py`, `helab/io_ops/raw_fill.py`,
  `helab/convert/raw_layer.py` (only where the fixes need them);
- their tests.

Ask CoCo before any other file.

- Strict typing, including `--platform win32` and `pyright --pythonplatform Windows`.
- Tests never touch real data.
- Before the handoff: the full suite (`-n` with `--reruns 5 --reruns-delay 1`) and the five type checks, with every
  RERUN reported.
- Handoff in `.ai/sessions/2026-11-04-claude-pr11-codex/handoff.md`: per finding, confirmed or not, the cause, the
  fix and its commit, and the test. Add doc proposals for `cache-store.md`, and a short reply text CoCo can post to
  each Codex comment.
- Push when done. Before reporting a CI run, read every job's log for RERUN.
- No version bump, release, tag or PR comment.

When done: `maestri ask "CoCo" "PR11 fixes: done at <hash>, C-1 <…>, C-2 <…>, C-3 <…>, suite <N>, RERUNs <…>, CI <run>"`.
