# Build size

Added: 2026-10-13. Draft; nothing implemented.
Priority and completion: [overview](_readme.md). Related:
[app versioning](app-versioning.md) (release assets),
[app updates](app-updates.md) (downloads).

## Purpose

Tony's local macOS PyInstaller build is 779 MB, and CI's artifacts are larger
still. Two separate problems: CI packages the build badly (the downloads are
several times the app), and the app collects packages it doesn't use. A Python +
Qt + numpy/scipy app can't be a few MB; the aim is the smallest app that still
does everything, in downloads that hold one copy of it.

## Measurements (2026-10-13)

CI artifacts of run 38267511493: macOS **2152 MiB**, Ubuntu 604 MiB, Windows
337 MiB.

- macOS PyInstaller output has both `dist/HeLab` and `dist/HeLab.app` (779 MB
  each). `ci-build.yml` uploads all of `dist/`, and the release job zips
  `HeLab.app HeLab` together.
- Qt frameworks use symlinks (1403 in `HeLab.app`). `upload-artifact` stores
  each link's target, and the release job's `zip -r` (no `-y`) follows them,
  so frameworks are stored several times. The release job zips the downloaded
  artifact, whose symlinks are already gone.
- `zip -ry` of `HeLab.app` alone: **276 MB**.

Local macOS app (779 MB unpacked), largest parts:

| Part | Size | Why it's there |
|---|---|---|
| QtWebEngine (Chromium) | ~284 MB (216 + 68) | Plot panes (`HelabMainWindow`, `plotly_3d_sactter`). Also pulls QtQuick/QML (`Qt6/qml` 16 MB, plus Quick frameworks). |
| pyarrow | 118 MB | In `requirements.txt`, never imported by HeLab; collected because plotly → narwhals can use it. |
| dash + pydantic + mypy | ~42 MB | mypy via `pydantic.mypy`, imported by dash's `mcp` module. |
| scipy, pandas, matplotlib, PIL | ~73 MB | Used by scripts and `io_helper`. |
| pytablericons + pygame | 35 MB | The whole Tabler icon set, and pygame to render SVGs; HeLab uses 61 icons. |
| Python, Qt widgets, numpy, rest | ~100 MB | The floor. |

The local build also collected PyCharm's matplotlib backend
(`backend_interagg`, `datalore`) because it ran in PyCharm's environment;
build from a plain terminal. CI is unaffected.

## Steps, cheapest first

1. **CI packaging** (no app change). On macOS, ship only `HeLab.app`. Zip
   **in the build job**, keeping symlinks (`ditto -c -k --keepParent` or
   `zip -ry`), and upload that zip; the release job uses it as is instead of
   re-zipping. `release_draft --validate-only` reads each archive's build
   stamp, so its expected paths must follow the new layout. Expected macOS
   artifact: ~2.1 GB → ~280 MB.
2. **Spec excludes:** `pyarrow`, `mypy`, `pydantic.mypy`, `IPython`, `tkinter`
   and the PyCharm backends; drop `pyarrow` from `requirements.txt` if no lab
   script needs it. About −130 MB. Check that plotly figures and the Dash pages
   still work in the built app.
3. **Icons:** keep the 61 SVGs HeLab uses in `helab/resources` and render them
   with QtSvg; drop pytablericons and pygame. About −35 MB.
4. **QtWebEngine** (product decision). Dash already serves Plotly figures to a
   normal browser, and the Lab Side PC can't paint Qt web panes anyway
   ([memory](../.ai/memory/results/lab-pc-qtwebengine-black-render.md)).
   Opening plots in the browser instead saves ~300 MB plus QtQuick/QML.

Rough estimates, not measured: after 1–3, ~600 MB unpacked and ~200 MB zipped
on macOS; with 4, ~300 MB unpacked and ~100 MB zipped.

## Acceptance

- Each release asset holds one copy of the app, with symlinks kept on macOS, and
  still passes the archive stamp validation.
- The built app on macOS and Windows starts, loads data, runs the example
  scripts and shows Plotly/Dash figures after the excludes (native check in
  [MANUAL_TODO](../.ai/MANUAL_TODO.md)).
- Record sizes before and after each step (artifacts and unpacked app) in the
  session notes.
