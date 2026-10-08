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
QtWebEngineWidgets`. Restore the versions `requirements.txt` resolves to (the
uv venvs built on 2026-10-08 had PyQt6-WebEngine 6.11.0 with
PyQt6-WebEngine-Qt6 6.11.2):

```
uv pip install --python venv\Scripts\python.exe --reinstall -r requirements.txt
```

## Working alternative

Generate self-contained Plotly HTML and open it in Edge. `include_plotlyjs=True`
inlines the JS, so no network is needed. This renders correctly on that machine.

## Other gotchas on this box

GPU diagnostics run over SSH report misleading `Failed to create shared context
for virtualization` errors that do not occur at the console. Qt/GPU issues must
be tested by a person sitting at the machine.

Python setup, interpreters, git, SSH/Maestri and RGAData notes for this machine
are in [[lab-side-pc-caveats]].
