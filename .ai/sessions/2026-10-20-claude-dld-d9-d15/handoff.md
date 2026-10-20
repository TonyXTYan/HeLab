# Handoff: D9 hot-spot masks and the D15 finder placeholder

Branch `agent/dld-d9-d15` (from `3957415`), one commit. Not pushed or merged. Details, the
presets' source and transform, and the choices for Tony: [notes.md](notes.md).

## Done

- **Mask group on every bundled event plot** (Counts per shot, Shot times, T/X/Y histograms,
  Density images, Mean X/Y against T, T spectrum, 3D scatter, Transfer fractions; versions
  bumped): none / preset / custom circles `x, y, r[, keep|cut]` in mm. Applied before binning
  or cropping; in the reuse key and record; "mask: 3 cut circles" in the dock line; "N masked
  out" in titles. Bad circles fail the run with the reason (the last plot stays).
- **Presets:** "earlier detector (2020)", Core's `hotspot_mask.m` 2020-06-14 list (1 keep r 38 mm,
  13 cuts), turned back from the lab's 0.61 rad rotation; "current detector" empty (TODO D15).
- **Density XY draws the mask** dashed (keep white, cut red).
- **Density images › Find hot spots** (D15 placeholder): summed XY image, bins > 5 × median (and a
  Poisson floor) grouped into amber circles, listed in the record, **Copy circles** to paste into
  any plot's Mask › custom. Never applied by itself.

## On-screen checklist (native UI)

1. Load a folder; open **Density images**: Settings show a **Mask** group (Mask: none) after View
   range. Choose **preset** → Preset "earlier detector (2020)" appears; Rerun: XY shows a white
   dashed 38 mm circle and 13 red dashed circles at the edge; the title adds "N masked out"; the
   dock's second line says "mask: earlier detector (2020), 1 keep and 13 cut circles".
2. Switch Projection to XT: no circles drawn; the mask still applies (count unchanged from XY).
3. Mask **custom**: a multi-line text box appears. Type `0, 0, 10, keep` and Rerun: only the
   centre remains. Type `1, 2` and Rerun: status "Failed: Mask circle “1, 2”: needs x, y and r …",
   the last image stays; the settings tab shows the same as a warning.
4. Preset **current detector**: Rerun works unmasked, with "⚠ Mask preset “current detector” has no
   circles yet: nothing masked" in the dock line and status.
5. Run **Find hot spots** (second button of Density images) on a flat-field or atom-free T window
   (set View range › manual T): amber dashed circles on the bright spots; the dock line says
   "N hot spots found"; the dock tooltip lists each spot and "As mask circles …".
6. Click **Copy circles**, open another plot (e.g. T, X, Y histograms), Mask › custom, paste,
   Rerun: the spots' events are gone ("N masked out"). Nothing changed in any plot before pasting.
7. Check each other plot's Mask group exists and its title/dock line mention the mask:
   Counts per shot, Shot times, Mean X/Y against T, T spectrum, 3D scatter, Transfer fractions.
8. Live: with a mask on, Live reruns keep masking (zoom kept in Density images and histograms).
9. Narrow dock (560 px): titles with "masked out" and the finder's second line still wrap.

## For Tony

The choices marked "proposed, for Tony" in [notes.md](notes.md): k = 5 and the √median noise
floor; failing a run on unreadable circles; preset names; keep circles ANDed and the boundary as
the lab's; the preset recorded by name in the reuse key; a later "use as this plot's mask"
button. Also a correction to the review notes: the active 2020 list has 13 cut circles, not the
commented-out 2019 list of nine.
