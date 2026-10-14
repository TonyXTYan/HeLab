---
name: feedback-ui-vertical-space
description: "HeLab UI: vertical space is precious — no padding above/below panel blocks; keep status rows single-line, details in tooltips"
metadata:
  node_type: memory
  type: feedback
---

When adding UI to HeLab's panels, don't add vertical padding above or below
blocks, keep rows the same height, and keep status rows single-line. Exact
dates, histories, and explanations go in tooltips. Small horizontal indents for
looks are fine (the folder summary text has 8 px).

**Why:** Tony, 2026-10-07, on the folder summary block: "no need for pixel
above and below the block (vertical spacing is precious)". He also flagged a
row-height mismatch caused by the Deselect button as a defect.

**How to apply:** For any new label, row, or indicator in the folder explorer
or dock panels, use zero vertical margins, check row heights match with buttons
present, and move long text into tooltips. See [[folder-summary-indicators]].
