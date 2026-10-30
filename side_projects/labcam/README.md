# Labcam

Watches the lab rack camera (an MJPEG stream, e.g. the Raspberry Pi's ustreamer at `:8081`) and checks each instrument:

| Instrument | Kind | Says |
|---|---|---|
| Left top / left middle scope | `trace` | where the signal sits on the screen (0 top, 1 bottom); `ok` within `tolerance` of the middle |
| Wavemeter, Power | `wavemeter` | the wavelength (nm) or frequency (GHz), and the power, by OCR; unsure digits show as `?` |
| Lock-in needle | `needle` | the needle's offset from the centre (-1 … 1); `ok` within `tolerance` |
| Scope dot | `dot` | whether the spot moved more than `still_px` in the last `window` s (`ok` = moving) |
| People | `motion` | movement outside the instruments' regions (`off` = someone moving) |

It serves a page with the overlay stream, a table of every reading (with how sure it is), the log, and a
region editor. Statuses: `ok`, `off` (amber), `unknown` (grey: couldn't tell; never a guess). A new status
counts only after `settle` (3) analyses in a row, so a flickering signal doesn't flip it.

## Set up (once)

Needs [uv](https://docs.astral.sh/uv/) and, for the wavemeter, Tesseract (everything else works without it).

macOS:

```bash
brew install tesseract
cd side_projects/labcam
uv venv --python 3.13 .venv && uv pip install -p .venv -e '.[test]'
```

Windows (PowerShell or cmd):

```bat
winget install UB-Mannheim.TesseractOCR
cd side_projects\labcam
uv venv --python 3.13 .venv
uv pip install -p .venv -e .[test]
```

Labcam finds Tesseract on the PATH, in `Program Files\Tesseract-OCR` or `%LOCALAPPDATA%\Programs\Tesseract-OCR`,
or wherever `LABCAM_TESSERACT` names. Its startup line says which it uses ("tesseract not found" turns the
wavemeter off).

Then tell it where the camera is: create `config.local.json` beside this README (not in Git, so the lab's
addresses stay out of the repository):

```json
{ "source": "http://<camera host>:8081/stream" }
```

## Run

```bash
.venv/bin/python -m labcam                 # Windows: .venv\Scripts\python -m labcam
```

Open `http://localhost:8090/`. Other machines (the tailnet, the lab network) open `http://<this machine>:8090/`
once the system's firewall lets the venv's Python accept connections: macOS and Windows both ask the first
time. If that is refused on a Mac, `tailscale serve --bg --http=8090 http://127.0.0.1:8090` proxies the
tailnet to it instead (open it by the machine's tailnet name then; the bare IP gets the proxy's 404). Stop
labcam with Ctrl+C.

Options: `--port` (8090), `--host` (0.0.0.0; `127.0.0.1` keeps it to this machine), `--source` (a stream URL,
or a JPEG to try it without the camera), `--debug` (DEBUG lines, e.g. every OCR read, also in the log file).

Tests: `.venv/bin/python -m pytest` (two of them need a camera frame at `tests/sample_mirrored.jpg`, kept out of
Git, and skip without it). HeLab's own pytest skips this folder: its environment has no OpenCV.

## First use

1. Open the page and check each instrument's outline sits on its screen or meter.
2. If one doesn't, press its **Edit region** and click the four corners, or drag a box.
3. Watch the table for a minute: each row says what it sees and how sure it is; `unknown` rows say why.
4. After moving the camera on purpose, press **Set reference frame**, then check the outlines again.

## The page

- **Overlay stream** (`/stream`), every reading (`/state.json`), the log (`/log`), today's readings
  (`/readings.csv`, one row per analysis), the un-mirrored camera frame (`/raw.jpg`).
- **Edit region**: click an instrument's four corners (top-left, top-right, bottom-right, bottom-left) on the
  picture, or drag a rectangle. Four corners follow a screen seen at an angle: the region is straightened
  before it is read, so "middle" is the middle of the screen itself. Edits go to `config.local.json` (not in
  Git); `config.json` holds the defaults.
- **Set reference frame**: regions are drawn on a reference frame (`reference.jpg`, taken at the first start).
  Every 5 s the frame is matched to it (ORB features), and the regions follow a nudged camera. The page says
  when the camera moved, or when matching failed (then the last regions are kept). After moving the camera
  on purpose, set the reference again and check the regions.

## Files

`logs/labcam.log` (rotated, 2 MB × 10), `data/readings-<date>.csv`, `reference.jpg`, `config.local.json`, all
beside this README and ignored by Git.

## Limits (2026-10-30)

- **Wavemeter OCR is not reliable at 720p.** The digits are about 13 px tall, with glare. Tesseract confuses
  8, 6, 5, 3 and 2 and drops the decimal point, sometimes the same way in every read of a frame. Each frame
  is read six ways and every digit is voted on over five frames; a digit without 60 % agreement shows as `?`
  and the reading is `unknown`. A digit can still be wrong *and* agreed on. The wavemeter's own data port,
  or a camera closer to it, is the real fix; a reader taught this display's digits from labelled frames is
  the next software step.
- **Lock-in needle:** the needle is faint at this resolution; check the region covers the meter you mean.
- **People** is movement, not person recognition: a moving cable or a light change counts too.
- **On the Pi:** the Pi 2 (4 × 900 MHz) could run it at `analysis_hz` 1 and `stream_fps` 2, with
  `apt install python3-opencv tesseract-ocr`, reading ustreamer at `http://localhost:8081/stream`. Untested;
  the wavemeter's OCR (about 0.3 s per field on an M-series Mac) would be the slowest part there.
- **Windows:** checked 2026-10-30 on a lab Windows 11 PC (Python 3.13 via uv): tests pass, a live run reads the
  stream (decode 8 ms, analysis 30 ms a frame) and serves the page. Tesseract wasn't installed there, so the
  wavemeter's OCR is untested on Windows.
