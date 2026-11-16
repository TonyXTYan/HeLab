# Plot a folder with Basic Plots

**Basic Plots** are HeLab's own quick-look plots of a folder's events. They're in the Scripts panel on the
right: choose **Basic Plots** in its group menu. The tree lists each version as a node, newest first:

- **v2**, the current set, open in the tree;
- **v1**, the first set, kept exactly as it was, so the results, presets and plot arrangements saved with it
  still open.

Each version keeps its own presets: a preset saved for a v1 plot isn't offered to its v2 plot.

## Open a plot

1. Load a folder's data in a tab.
2. Click **Plot** beside a script, for example "Counts per shot".

The plot opens in the middle, on the data the tab shows; its settings show in the panel above the Scripts
panel. While a plot of a script is open, its button reads **New**, and its tooltip says how many are open,
for example "Open another Counts per shot plot (1 open)". **New** opens another plot of the same script,
with its own settings, so that you can compare settings side by side.

## The v2 plots

| Plot | What it shows |
|---|---|
| 3D scatter | The events in T, X and Y, cropped to the region holding most of them |
| Counts per shot | The events in each shot, against its shot ID or its time |
| T, X, Y histograms | The distributions of T, X and Y |
| XY, XT, YT histograms | The events binned in the XY, XT and YT planes side by side, each plane's third axis summed |
| Plane projections | The events' velocities in 3D with up to four planes at any angle, and each plane's histogram of the events flattened onto it |
| Transfer fractions | Each shot's share of atoms in each diffraction order, against its shot ID or its time |

Every Basic plot can be drawn with PyQtGraph (the default for 2D plots), Plotly (the default for the 3D
scatter, with **Open in browser**) or Matplotlib: **Drawing › Library** in its settings. Switching library
redraws the plot without running it again. Times are in seconds and lengths in metres, with SI prefixes
(ms, mm, µm).

## Shot ID or shot time

**Counts per shot** and **Transfer fractions** have an **X axis** setting:

- **Shot ID** (the default): the shot number of each `d<N>.txt`.
- **Shot time**: when each shot was taken, on your computer's clock. The axis shows the time of day and,
  zoomed out, the date.

A shot's time is its raw `d<N>.txt` file's modification time. A shot without a raw file takes its TXY file's
time instead, which is when it was converted, so several shots converted together share one time. Those shots
are drawn as **amber triangles**, and the plot's title counts them (`⚠ 3 TXY times (no raw file)`). A shot
with no time at all is left out of a Shot time axis, and the title counts it too. A copied or rewritten file
has a new modification time.

Between runs, or after a stall, the line breaks instead of joining the gap: it stops where the time to the
next shot is over ten times the shots' usual interval.

While Live is on, new shots join either axis in place, and a zoom or pan you made stays.

## Plane projections

This plot turns the chosen shots' events into velocities at release (v_z up, v_x, v_y), as **Velocity
distributions** does: the release time and the trap's origin come from the folder (the Release time plot's
**Use for this folder…**), the lab or this plot's constants, else they are found from the events. The velocities
are drawn in 3D with up to four planes in them, each in its own colour, and below it each plane's histogram of
the events flattened onto it. Every axis is a velocity at the same scale, so a plane can lean at any angle.

- **Planes › Plane 1–4**: **Show** turns a plane on. **Orientation** is **XY** (v_x across, v_y up), **XT**
  (v_x across, v_z up), **YT** (v_y across, v_z up), the XY, XT and YT histograms' planes in velocity, or
  **custom**, set by three angles:
    - **Across axis direction α**: where the plane's across axis points in the horizontal plane, from v_x
      (0°) towards v_y (90°).
    - **Tilt θ**: how far the plane leans up about that axis, 0° flat (like XY) to 90° upright (like XT, YT).
    - **In-plane rotation ψ** (any orientation): turns the histogram's axes, then called u and v.
- **Centre** (v_x, v_y, v_z, in mm/s): a point the plane passes through; the histogram's axes start there.
- **Thickness**: 0 flattens every event onto the plane; above 0 only the events within half of it, either side,
  are kept: a slice (a thin slice through a halo's centre shows its ring).
- **Images**: **Range: keep** (each histogram spans the shortest range holding this share), or a **Half-width**
  that gives every histogram the same span; **Bins per axis**; the colour scale (sqrt, log, power γ). A
  histogram of more than 1,000 bins a side is drawn from the mean of blocks of bins, at most 1,000 a side (its
  title says so); the counts keep every bin. Many bins on several planes take a lot of memory: the settings
  page warns when the plot would take half of HeLab's RAM budget, as it does for the XY, XT, YT histograms.
- **3D view**: point size, opacity, the display cap and how solid the planes are drawn.

It is drawn with Plotly (turn the 3D view with the mouse; it keeps its camera as Live adds shots) or Matplotlib.

## XY, XT, YT histograms

This plot bins the chosen shots' events in up to three planes, side by side, and sums each plane's third axis
over them: XY sums T, XT and YT sum Y or X. XY has X across and Y up; XT and YT have X or Y across and T up. Every space axis
shown has the same scale, so a cloud is as wide in XT as in XY, and zooming or panning one plane moves the others
with it (X shared by XY and XT, Y by XY and YT, T by XT and YT).
The planes share one set of settings. With counts per bin they share one colour bar, right of the last plane,
over the same range: from 0 to the highest bin of the planes shown. A rate per shot is per mm² in XY but per mm·ms
in XT and YT, so then XY has its own colour bar, left of the planes, and XT and YT share one on the right, each
from 0 to the highest bin of its own planes. (Dots coloured by the summed axis have one bar for it; dots without
colour have none.) The settings:

- **Planes**: turn XY, XT and YT on or off. Only the planes that are on are computed.
- **View range.** With **auto-crop**, each shown axis covers the shortest range holding the share of events
  you keep (99 % by default), and the summed axis isn't cut. With **manual**, the bounds you set cut the
  events: a T range on the XY histogram images one cloud. An axis left unset (min = max), or with its min
  above its max, covers all its events. Turn on **Sum the whole summed axis** to leave the
  summed axis's bounds out, so that they cut only the two shown axes.
- **Draw**: **histogram** (the events in bins) or **dots** (each event as a dot, no bins drawn, over the same
  view range). With dots:
    - **Dot colour**: **none** (one colour; overlaps look darker), **summed axis** (each dot's own third
      coordinate: T on XY, Y on XT, X on YT, over its range in that plane, which the plane's title gives) or
      **local density** (the value of the dot's bin in the image, after any blur, on the colour scale below;
      the densest dots are drawn on top).
    - **Max dots**: at most this many dots in each plane (200,000 by default). Beyond it a fixed random sample
      is drawn, and the plane's title says so. The bins and the local density still count every event.
    - **Background**: white or black behind the dots (the titles, axes and colour bar stay on white). Black
      brings out faint dots; uncoloured dots are then white.
- **T bins**, **X bins** and **Y bins**: each axis's bins wherever it is shown, up to 20,000; 0 picks the
  count from the data (at most 1,000). Fine bins take a lot of memory (20,000 × 20,000 is about 6 GB a
  plane). When the memory the settings would take reaches half of HeLab's RAM budget (Settings › Cache), a
  line above **Rerun with these settings** says so as you change them, with **Undo** (puts back the
  settings as they were before it) and **Cancel** (stops the run in flight). If you press neither, the plot
  still runs, and its title says so too.
- **Blur**: six filters, each in its own section with an **On** switch; its settings show once it's on. They
  run one after another, in increasing **Order** (filters with the same number run in the order listed), and
  each plane's title lists the ones that ran:
    - **Median**: each bin becomes the median of the square of bins around it (**Size**), which takes out lone
      hot bins and keeps edges sharp. It's the only one that doesn't keep the total.
    - **Denoise (counts)**: made for counts. It evens out the counting noise (the Anscombe transform), blurs by
      **σ** bins and transforms back. Best first, on the counts themselves.
    - **Adaptive KDE**: an adaptive kernel density estimate. Faint regions are smoothed more and bright cores
      less: each bin's own σ is between ¼ and 4 times **σ**, set by how bright it is (**α**: 0 is a plain
      Gaussian, ½ the usual choice).
    - **Gaussian (σ in bins)**: a Gaussian blur, **σ** in bins.
    - **Gaussian (σ in m, s)**: a Gaussian blur with **σ on X, Y** in metres and **σ on T** in seconds, so
      it's the same size in every plane whatever their bins.
    - **Box**: the mean over the square of bins around each bin (**Size**).

  The two Gaussians and the box commute: their order among themselves changes nothing. The median, denoise
  and the adaptive KDE don't, so where they sit in the order matters. A σ is at most a quarter of the
  image's side on each axis, and the plot says when it was capped.
- **Show**: counts per bin, or a rate per shot (counts per shot per bin area: events / mm² / shot for XY,
  events / (mm·ms) / shot for XT and YT, whatever units the axes show).
- **Colour scale**: linear, sqrt, log (spanning **Decades** below the maximum) or power γ. Only the colours
  are compressed: the colour bar still reads the real values.

## Plot info

The top of each plot's settings is **Plot info**. Closed, it's one line naming the plot's input, its
revision and whether it follows Live; its tooltip gives the folder's full path. Click **Plot info** to open
it. It then lists:

- the source line;
- the shots used, the analysis and its version, and whether the result came from the disk cache;
- the settings in short;
- the data's TXY;
- the full record: the data root, the signature, the shots covered, and every parameter.

Long folder names wrap, and a long record scrolls.

The line above each plot is kept short: `Data source: <folder> · rev N · following Live`, or
`Showing previously loaded data: …` when the tab now shows other data than the plot ran on. It ends with
**outdated** while a saved result that no longer matches its data or script shows, and with **⚠ N** when the
run has N warnings (for example a manual range with its min above its max). Hover over it for the warnings in
full and the full record; Plot info lists them too.
