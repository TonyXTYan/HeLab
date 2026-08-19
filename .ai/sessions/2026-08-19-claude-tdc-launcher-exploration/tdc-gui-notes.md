# TDC_GUI.exe / legacy/tdc_launcher — how it works

Read-only exploration notes. `legacy/tdc_launcher/` in the HeLab repo contains only
four **broken macOS alias files** (no real content locally) — see "Local repo state"
below. The actual source/binaries live on the lab's TDC control PC, reached over
Tailscale SMB at `100.123.123.202` (hostname `TDC_user`), mounted locally at
`/Volumes/100.123.123.202` when the Tailscale link is up.

## What TDC_GUI.exe actually is

A thin **C# WinForms launcher** (`WindowsFormsApplication1.frmMain`, "APP_VERSION 1.1")
around a separate C++ console middleware, `my_read_tdc_gui.exe`, which does the actual
HPTDC8 card I/O. TDC_GUI.exe itself never touches the TDC card driver directly.

Source (C#): `Documents/Projects/TDC_GUI-mod/frmMain.cs` on the remote box.
Deployed binary: `ProgramFiles/my_read_tdc_gui_v1.0.1/x64-bin/TDC_GUI.exe`.

### Flow

1. On startup, `btnRestoreFromDefault_Click` reads `tdc_gui_config.xml` (same dir as
   the exe) and populates the form fields: NumberShots, MaxHits, Timeout,
   OutputFileName, StartChannel, DMAEnabled, ReadBufferSize, CleanupPause, StartNumber.
2. User can edit fields and click "Save as Default" to write them back to the XML
   (`btnSaveAsDefault_Click`), or "Restore from Default" to reload.
3. **Run** (`btnRun_Click`) or **Free Run** (`btnFreeRun_Click`) launches
   `my_read_tdc_gui.exe` as a child process (`Process.Start`), passing all 9 config
   values as positional CLI args (space-separated string, order matters):
   ```
   my_read_tdc_gui.exe <NumShots> <MaxHits> <Timeout> <OutputFilename> <StartChannel>
                        <DMAEnabled:0|1> <ReadBufferSize> <CleanupPause> <StartNumber>
   ```
   Free Run passes `NumShots = -1`, which the middleware treats as "repeat one shot
   forever" (`shot_count` doesn't increment).
4. A 200ms timer (`tmrUpdateStatus_Tick`) polls `IsRunning(myTDCProcess)` to
   enable/disable Run/Free Run/Stop buttons and show status text
   (Not Running / Running Normally / Running Free Run).
5. **Stop** (`btnStop_Click`) calls `myTDCProcess.CloseMainWindow()` — a graceful
   close, not a kill, so the middleware can free the card driver handle on exit.

### The middleware: `my_read_tdc_gui.exe`

C++ console app, source at
`Documents/Projects/my_read_tdc_gui-mod/my_read_tdc/my_read_tdc_gui.cpp` on the remote
box. Uses `TDCManager` from `tdcmanager_3.9.4_mod.h` (wraps
`hptdc_driver_3.9.4_x64.dll`, the vendor driver for an HPTDC8 (8-channel,
25ps-resolution) time-to-digital converter card, PCI vendor/device ID `0x1A13,0x0001`).

Per-shot loop (runs `number_of_shots` times, or forever in free-run):
1. Creates/inits a `TDCManager`, sets card parameters (trigger channel fixed at 4,
   falling edge, DMA on/off per arg, VHR/high-res mode on, rollover output on,
   falling-edge detection enabled on channels 0-7).
2. `manager->Start()`, then busy-polls the card waiting for a hit on `start_channel`
   (arg 5) — this is the "master start trigger" for the shot.
3. Once triggered, opens `..\dld_output\<OutputFilename><shot_count>.txt` for writing
   and streams every subsequent hit (channel, absolute timestamp in 25ps bins) as
   `"%u,%llu\n"` lines until either `max_hits` is reached or `timeout_time` ms have
   elapsed since the trigger.
4. Stops/cleans up the card, closes the file, sleeps `CleanupPause` ms (workaround
   for a DMA leak on the card), then proceeds to the next shot.
5. `q` key during acquisition aborts the current wait/hit loop early.

Output directory is always `dld_output/` one level above the exe
(`ProgramFiles/my_read_tdc_gui_v1.0.1/dld_output/`), which is also what's shared out
read-only over SMB as `//TDC_user@100.123.123.202/dld_output`.

### How it's normally triggered per-shot (not manual clicking)

`x64-bin/tdcstart.vbs` automates the whole GUI via `SendKeys` — it launches
`TDC_GUI.exe`, tabs through the form, and types in a fixed sequence of values
(NumShots=99999, MaxHits=1000000, Timeout=4000, OutputFileName="d", StartChannel
unset/defaulted, ReadBuffer=1000000, CleanupPause=1000, StartNumber=`<lastshot+1>`)
before hitting Enter to click Run. `lastshot` is parsed out of a
`log_LabviewMatlab*.txt` file already present in `dld_output/` (last non-blank line,
fixed-offset substring parsing — fragile). This is presumably invoked by the
LabVIEW/Matlab experiment control sequence per shot, not by a person.

Separately, `dir_watch_keysight_update/{start_watch.m, dir_monitor.m}` (MATLAB) watch
`dld_output/` for new `.txt` files (ignoring `_txy_forc*`) to drive a **Keysight
waveform generator** parameter sweep between shots — related lab automation, but not
part of the TDC_GUI.exe launch path itself.

### Config file precedence gotcha

Two XML configs exist with different values — whichever is colocated with the exe
being run wins:
- `x64-bin/tdc_gui_config.xml` (used by the deployed v1.0.1 GUI): NumShots=99999,
  MaxHits=1000000, Timeout=4000, OutputFileName="d", StartChannel=5.
- `x64-bin/global.xml`: NumShots=999999, MaxHits=100, Timeout=100,
  OutputFileName="Results", StartChannel=5. Purpose unclear — not read by
  `frmMain.cs` (which only reads `tdc_gui_config.xml`); possibly a stale/alternate
  profile.

There's also an older standalone variant, `my_read_tdc_mod` (no GUI wrapper, config
read from `my_read_tdc_config.txt` directly) — likely predates the C# launcher +
CLI-args design and is superseded by `my_read_tdc_gui-mod`.

## Local repo state (`legacy/tdc_launcher/`)

The four files present locally are **macOS alias files**, not real content:

| Local file | Resolves to (on TDC_user PC) |
|---|---|
| `my_read_tdc_gui_v1.0.1` | `C:\Users\TDC_user\ProgramFiles\my_read_tdc_gui_v1.0.1` |
| `TDC_GUI-mod` | `C:\Users\TDC_user\Documents\Projects\TDC_GUI-mod` |
| `my_read_tdc_gui-mod` | `C:\Users\TDC_user\Documents\Projects\my_read_tdc_gui-mod` |
| `my_read_tdc_mod` | `C:\Users\TDC_user\Documents\Projects\my_read_tdc_mod` |

These aliases only resolve when the TDC PC is reachable over Tailscale and mounted
via Finder/SMB (`/Volumes/100.123.123.202`); `git status`/`ls` on them locally shows
plain small files, and the content is invisible unless that mount is live. `TDC_GUI-mod`
on the remote box is itself a git repo but on branch `master` with **no commits yet**
(working tree only) — so there's no history to pull from there either.

If this legacy tooling is ever meant to be properly vendored into the HeLab repo
(e.g. as another git submodule like `legacy/tdc_autoconverter`), these aliases should
be replaced with either a real submodule pointing at `TDC_GUI-mod`'s remote (once it
has commits) or a plain copy — aliases don't survive being committed to git in any
useful form.
