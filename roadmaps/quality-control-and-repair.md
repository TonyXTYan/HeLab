# Quality control and repair

Horizon: after the shared analysis/data boundaries. Added: 2026-10-14.
Behaviour agreed with Tony; aggregation and file-selection rules are draft.
Priority and completion: [overview](_readme.md).
Detailed design and open cases:
[planning notes](../.ai/sessions/2026-10-14-codex-planning-for-future/analysis-behaviour.md#qc-design-questions).

## Purpose and scope

Introduce a QC script catalogue. Migrate the existing quick raw `d*.txt` and
TXY status scan as its first provider while preserving the current status icon
behaviour. Combine multiple QC findings into one icon; a top-left count can show
completed checks, and the tooltip shows individual findings. Keep browser
rendering memory-only.

A QC provider may offer a user-initiated **Try auto fix** action bound to a
compatible repair script. Repairs create a new derived file, never modify raw
`d*.txt` or an existing `d_txy*.txt`, and record provenance. Analyses use the
repaired variant by default for that shot while retaining access to the
original. A future HeLab-run TDC converter is a separate file-generation
capability.

## Acceptance and open decisions

The migrated first provider gives the same initial status and icon meaning as
today. Additional checks can report separately and aggregate without duplicate
source scans. A repair cannot overwrite source data; its new variant is selected
once for analysis. Mark saved results that used the original as
invalidated/outdated and ineligible for current-result reuse until that analysis
reruns against the repaired variant. Their result payloads remain immutable and
viewable.

Define QC severity/freshness aggregation, count semantics, repair naming and
collision rules, selection among several repaired variants, and how the
existing TXY filename matcher recognizes derived files without double-counting
shots. The session note tracks these decisions in detail.
