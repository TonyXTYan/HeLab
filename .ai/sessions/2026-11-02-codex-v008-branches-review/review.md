# v0.0.8 and feature-branch review, 2026-11-02

This is a bug and security re-review. The review made no application changes.
Its report and evidence were subsequently archived on
`agent/codex-v008-security-review` at Tony's request. The original reviewed
checkouts and previous review were retained.

## Snapshots and scope

| Branch | Reviewed commit | Checkout |
| --- | --- | --- |
| `dev/v0.0.8` | `a5f129b8066f77d567149c0119b691a3506c31eb` | `/workspace/HeLab-v008-recheck` |
| `agent/caching-v2` | `d76a90e6ef5a69d6c2e1520bb1a4bee53a26828d` | `/workspace/HeLab-caching-v2-review` |

Fetched the repository's heads and checked ancestry. The only unmerged feature
code branching from v0.0.8 is `agent/caching-v2`. Its merge base with current dev
is `c3f645045f315e16201c3faa11c454229110d095`; it has 38 unique commits and dev has
6 since that base. `agent/area-review` has one unmerged documentation commit
(six area-review Markdown files), not a separate application implementation.
Older agent branches were not treated as new feature branches merely because
their names still exist.

Current dev still declares package version `0.0.7a1`. This reviews the named
development snapshots, not a published v0.0.8 executable. Store-v4 remains off
by default; the four new cache findings below require it to be enabled.

`git merge-tree --write-tree` reports no textual conflicts between the two
snapshots (tree `91695e30b80a2210eb59b1c0d6d1efd8c3783014`). No branch was merged.
A clean textual merge does not resolve the findings below.

## New findings

### N1 — P1 — A different TXY kind hides an only copy from budget trimming

Branch: `agent/caching-v2`.
Locations: `helab/utils/cache_store.py:3588–3591`,
`helab/io_ops/txy_cache.py:269–270`, and the combined MATLAB/HeLab shot list
passed from loading.

The source-presence map contains a single `txy` set of shot numbers for all
layers. `mark_txy_seen` checks only the entry's kind and shot number, not whether
the actual MATLAB file or the HeLab file for the layer's profile still exists.
Consequently a current HeLab TXY for shot 1 makes a cached MATLAB shot 1 appear
recoverable even after `d_txy_forc1.txt` was deleted. Its `gone_at` stays null.
The layer is put in the ordinary seen-data eviction group, bypassing the
only-copy protection and warning.

Reproduction uses real temporary files and loads: cache MATLAB shot 1, delete
its MATLAB TXY, create a valid current beside HeLab TXY for the same shot, then
load HeLab priority. The MATLAB cache remains unmarked as an only copy.
`store.trim(1)` then deletes it, although this unplanned trim path is supposed
to retain only copies. The source is gone and the store retires its last
segment, making the loss permanent after housekeeping. No real lab data was
used.

Fix direction: carry source presence per layer/profile (and the entry's source
identity) rather than a union of TXY shot IDs. Only a matching source may clear
the only-copy mark. Test the MATLAB/HeLab and two-HeLab-profile collisions,
including purge/trim/Make room.

Evidence: `new-repros.py::test_a_helab_file_cannot_make_a_missing_matlab_file_recoverable`
and `new-repros.log`.

### N2 — P2 — A saved view can return newer data under its old fingerprint

Branch: `agent/caching-v2`.
Location: `helab/io_ops/txy_cache.py:174–186`; related write behavior in
`CacheStore._apply_txy_unit`.

Views of different source modes share a mutable layer. Updating a shot in one
view replaces the layer's current entry, but leaves another view's older
fingerprint and signature intact. `_read_data` retrieves the layer's latest
shot by number without checking that it still represents the saved view.
Thus a cached read can label new arrays with an old file fingerprint. Analysis
cache keys then describe different data from the arrays actually supplied.

Reproduction: save a MATLAB-only view whose shot is `[11, 2, 3]`, size 10,
mtime 100; save the priority view's replacement in the same layer as
`[99, 2, 3]`, size 20, mtime 200. Reading the MATLAB-only view returns
fingerprint `[[1, 10, 100]]` with array `[[99, 2, 3]]`.

Fix direction: invalidate affected views when shared entries are replaced, or
record and verify the layer-entry version/segment each view describes. Read a
coherent view/layer snapshot and treat a mismatch as incomplete rather than
attaching old metadata to new arrays.

Evidence: `new-repros.py::test_a_view_cannot_return_changed_layer_data_with_its_old_fingerprint`
and `new-repros.log`.

### N3 — P2 — TXY source overrides survive a data-root replacement

Branch: `agent/caching-v2`.
Locations: `helab/utils/folder_cache.py:1017–1019` and `_root_prefs_gone`.

Stage 2 adds `folder_choices`, keyed by the visible filesystem path. Root
identity changes clear the old folder/converter flags but leave these new
choices behind. A subsequent empty choice from the replacement root has
`source_set_at=0` and loses to the old root's timestamp, so it cannot correct
the stale in-memory override. The next load can therefore use the old root's
TXY source or profile instead of the new root's setting.

Reproduction: set a MATLAB-only folder override under root A, deliver a real
`root_changed` event replacing it with root B, then deliver B's empty choice.
`with_txy` still selects `matlab-only`, although the global default/new root is
`helab-priority`.

Fix direction: invalidate these choices with the existing root-aware preference
cleanup, preserving nested roots and any explicitly tracked in-flight choice
writes. Also scope late responses by root/store identity, not timestamp alone.

Evidence: `new-repros.py::test_replacing_a_root_drops_its_txy_source_override`
and `new-repros.log`.

### N4 — P2 — Malformed segment indices silently change shot contents

Branch: `agent/caching-v2`.
Location: `helab/convert/txy_layer.py:74–81`.

The segment reader checks array shapes and `np.diff` signs but does not enforce
the specified index dtypes or absolute offset bounds. It then casts shot IDs
and offsets with `int` and slices arrays. Two CRC-valid malformed containers
were accepted instead of raising `HlbError`:

- Float64 shot IDs `[1.1, 1.9]` become the same dictionary key `1`; the second
  shot silently overwrites the first.
- Correct int64 offsets `[0, INT64_MAX, INT64_MIN, -1, 2]` pass the monotonicity
  check because `np.diff` overflows. NumPy's clamped/negative slices then
  duplicate and reassign two rows across four shots.

These are deliberately malformed files, not random damage that evades CRC or
evidence of code execution. The new public `.hlb` reader/export path should
reject such files, rather than silently changing scientific data.

Fix direction: enforce int64 shots/offsets, float64 hits, uint8 flags, valid
shot IDs and flags, and `0 <= offsets <= len(hits)` before slicing; check
monotonicity without subtraction overflow. Normalize invalid input to
`HlbError`.

Evidence: the fractional-ID and offset-bounds probes in `new-repros.py`,
`new-repros.log`, and `offset-bounds.log`.

### N5 — P2 — Labcam accepts cross-origin persistent settings writes

Branch: `dev/v0.0.8` (the settings handler is also inherited by the feature
branch). This is the separate `side_projects/labcam` service, not HeLab's
desktop GUI or its local Dash server.
Location: `side_projects/labcam/labcam/server.py:190–210`.

The new `/api/settings` route changes and persists power mode and OCR settings
without authentication, an Origin check or a CSRF token. Labcam listens on
`0.0.0.0` by default. Even if editing from trusted LAN/tailnet clients is
intentional, the handler also accepts a foreign-origin `text/plain` POST,
which is a browser simple-request content type. CORS response restrictions
alone do not stop the write. Browser local-network restrictions can limit
which pages can reach the service; this test establishes the server-side
acceptance, not exploitation in every browser.

Reproduction starts the actual handler only on loopback with a fake engine and
a private settings file. An unauthenticated request carrying
`Origin: https://untrusted.invalid`, `Content-Type: text/plain`, and
`{"power_mode":"low"}` receives 200 and persists the low-power setting. No
camera, real Labcam instance or other host was contacted.

Fix direction: protect state-changing routes with same-origin/CSRF checks and
an appropriate authentication boundary for network clients. Preserve intended
LAN access rather than relying on CORS to prevent mutations.

Evidence: `dev-evidence/labcam-repro.py`
and [dev-evidence/labcam-security.log](dev-evidence/labcam-security.log).

## Previous findings: still open on both snapshots

The prior ten probes were rerun on **both** branches. All ten still fail their
safety/correctness assertions on each snapshot; these are expected regression
probe failures, not failures of the repository's ordinary tests.

| Previous finding | Status on dev and feature |
| --- | --- |
| R1: export overwrite/symlink race without `--force` | Still reproducible for NPZ, MAT and CSV |
| R2: literal folder export keys miss percent-encoded cache keys | Still reproducible for spaces, percent signs and Unicode |
| R3: unreadable kept store-v3 becomes `missing` | Still reproducible; no legacy read error returned |

Evidence: `previous-repros.py`, [feature results](previous-findings.log), and
[dev results](dev-evidence/previous-findings.log).
The original report is retained at
[the first review](../2026-11-01-codex-v0.0.8-review/review.md).

## Validation and limits

- Feature focused pytest run: **102 passed**, no RERUN
  (`feature-tests.log`, 4.95 s). Covers the new layer store, loading, UI,
  fixes, folder cache record, integration session, CLI and container reader.
  The command listed `test_txy_layers_store.py` twice, so this count is test
  executions rather than a claim of 102 distinct tests.
- Dev focused pytest run: **68 passed, 2 skipped**, no RERUN
  (`dev-tests.log`, 7.39 s in the dev checkout). The two skips are native
  platform-specific checks.
- Labcam existing tests on dev: **23 passed, 3 skipped** (missing private
  sample camera frame), no RERUN (`labcam-tests.log`, 0.64 s in dev).
  OpenCV was installed in the isolated `/workspace/helab-review-extras`
  dependency directory and supplied only to Labcam test commands; no camera
  or OCR model was downloaded.
- Type-check tests: **7 passed on dev**, **6 passed on the feature branch**,
  no reruns (`typing.log` in each checkout). The extra dev test checks the
  checker timeout markers. Strict/non-strict mypy and pyright all pass.
- New targeted probes: four expected failures in `new-repros.log`, one
  expected failure in `offset-bounds.log`, and one expected failure in the
  dev checkout's `labcam-security.log`, establishing the five findings above.
- Negative probes were temporarily placed under `tests/` to use its private
  source/cache/settings fixtures, then moved into the session directories.
  They are retained evidence, not production test additions.
- `git diff --check` passes on both snapshots; tracked worktrees are clean.
- A full suite and packaged/native macOS or Windows checks were not repeated.
  The preceding review's Linux `/tmp` mount and orphan-zombie limitations
  remain relevant; focused results above do not establish a clean release
  validation on every platform.

## Handoff proposals

Coordinator: record N1–N4 and the still-open R1–R3 in the caching-v2 known
issues, and N5 separately under Labcam. Fix N1 before enabling stage 2 for
retained data. Re-review only-copy classification, coherent view reads and
root-specific choices before landing the feature. Keep the malformed-file
probes with the reader tests. No fixes or publication are authorized by this
review alone.

## Archive layout

Feature-branch logs and probes are beside this report. Dev-branch logs and
the Labcam probe are in [dev-evidence/](dev-evidence/). The original local
checkout paths above record where the checks ran; they are not prerequisites
for reading this archive. See [README.md](README.md) for the index and replay
notes. The archive branch adds records only.
