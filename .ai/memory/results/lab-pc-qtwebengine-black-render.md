---
date: 2026-08-20
status: settled
name: lab-pc-qtwebengine-black-render
description: "The Lab Side PC cannot render QtWebEngine (Sandy Bridge / no D3D11); use browser HTML export instead"
metadata:
  node_type: memory
  type: result
---
The Lab Side PC (RGA machine, `C:\GitHub\HeLab`) cannot render any QtWebEngine
content. Its Plotly plot pane is permanently black. This is a hardware limit,
not a bug in HeLab — do not attempt to fix it in code.

## The machine

Intel 2nd-gen (Sandy Bridge, ~2011) forced onto Windows 11. Intel never shipped
a Win11 driver for HD 3000, so it runs on Microsoft Basic Display Driver with no
hardware acceleration. HD 3000 is Direct3D 10.1 hardware; modern Chromium
requires D3D11 feature level 11_0. QtWebEngine embeds Chromium, so it can never
composite there.

## Symptom

`QWebEngineView` loads content fine (`loadFinished` fires `True`) and paints the
correct first frame — resizing briefly shows real content in newly exposed
regions — then every subsequent frame is black.

## What was tested and ruled out (2026-08-20)

Not the data, not Plotly, not page loading. The parser reads real Analog files
correctly, and the identical Plotly HTML renders perfectly in Edge on the same
machine.

Every rendering backend was tested with a minimal red-page `QWebEngineView`
(no Plotly involved):

| Backend | Minimal page | Real app (4.9 MB Plotly) |
|---|---|---|
| default ANGLE D3D11 | black | black |
| `--use-angle=gl` | red ✅ | black — GL context lost under load |
| `--use-angle=d3d9` | red ✅ | black |
| `--use-angle=swiftshader` | black | — |
| `QT_OPENGL=angle` | black | — |
| `QT_OPENGL=software` | black | — |
| `--disable-gpu --disable-gpu-compositing` | red ✅ | black |

Backends that pass a trivial page still fail on a real one
(`context is marked as lost` / `Failed to make current`). Downgrading to
PyQt6-WebEngine 6.7.x is **not** a workaround: 6.7.3 splits into a subwheel and
the install breaks with `ImportError: DLL load failed while importing
QtWebEngineWidgets`. Restore with:

```
venv\Scripts\python.exe -m pip install --force-reinstall "PyQt6==6.11.0" "PyQt6-Qt6==6.11.1" "PyQt6-WebEngine==6.11.0" "PyQt6-WebEngine-Qt6==6.11.1"
```

## Working alternative

Generate self-contained Plotly HTML and open it in Edge. `include_plotlyjs=True`
inlines the JS, so no network is needed. This renders correctly on that machine.

## Other gotchas on this box

- Bare `python` is **Python 2.7.12** from `C:\Python27`, which shadows the real
  3.12.10 install at
  `C:\Users\helium\AppData\Local\Programs\Python\Python312\python.exe`.
  Always invoke `venv\Scripts\python.exe` explicitly; never rely on `python`,
  and `py` is not installed.
- GUI apps launched over SSH run in a non-interactive session and are invisible
  on the console desktop — they appear to hang. GPU diagnostics run over SSH
  also report misleading `Failed to create shared context for virtualization`
  errors that do not occur at the console. Qt/GPU issues must be tested by a
  human sitting at the machine.
- The lab's `RGAData` share lives here: `C:\Users\helium\Documents\RGAData`,
  with `Analog/` (432+ sweep files), `Histogram/`, `LeakTest/`,
  `PressurevsTime/`. The README's default `/Volumes/100.123.123.201*` path is
  macOS-only and will not resolve on Windows.
- The RGA visualiser only parses mass-sweep files. `LeakTest/` and
  `PressurevsTime/` use `mode: 4` configs with no
  `startMass`/`stopMass`/`pointsPerAmu`, so `_expected_points` in
  `side_projects/rga_visualiser/rga_visualiser.py` rejects them. Both folders
  hold recent data; supporting them is unimplemented work, not a bug.
