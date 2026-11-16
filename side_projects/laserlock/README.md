# Laserlock

Locks a laser's frequency: reads a HighFinesse wavemeter (WS8) channel and steers the laser through a Rigol
DG1022's DC offset, with a PID loop (PI by default). Windows only (the wavemeter's `wlmData.dll`).

| Part | What it does |
|---|---|
| `devices.HighFinesse` | reads one channel's frequency (THz) through `wlmData.dll`. The DLL only talks to the WLM server program (`wlm_ws8.exe`); if it isn't running, laserlock starts it **hidden** (about 15 s) and closes it again on exit. If it was already running, it is left alone. |
| `devices.DG1022` | sets one channel's DC offset, nothing else (never output on/off, waveform or amplitude). Offsets in 0.1 mV steps (its resolution), **hard limit 0–7 V**, at most one command every **100 ms**. |
| `controller.PILock` (`PIDLock`) | the PID loop (pure Python, tested). |
| `engine.Engine` | the loop thread: a PID step on each new measurement, the newest voltage written when the DG1022's turn comes. |
| `gui.MainWindow` | readings, the wavemeter's timing, setpoint, gains, limits, Lock / Calibrate, sweep, plots of the error and the output. |
| `sim` | a simulated laser, wavemeter and DG1022 (`--sim`). |

## The DG1022's limits (measured 2026-11-11)

- Its USB **stops answering** when commands come too close together — always below 5 ms, once at 20 ms —
  and only a power cycle brings it back; it froze twice more in use on 2026-11-11. Laserlock keeps **100 ms**
  between any two commands (configurable as `min_interval_s`; write and verify
  at 50 ms: 50/50 correct, about 18 verified or 20 unverified updates a second).
- Laserlock holds an **exclusive VISA lock** on it while running: another program's commands between
  laserlock's would break the spacing (that hung it on 2026-11-11). Other VISA programs get
  "resource locked"; laserlock won't start while another program holds it.
- The offset keeps 4 decimals in volts (0.1 mV); finer values are rounded.
- While a program controls it, its screen stops updating and its keys are locked (remote mode); it still
  answers over USB. Its **Local** key (on Burst) gives the front panel back.
- Set CH1 up on the front panel (DC, or ARB DC, output on) before locking; laserlock only moves the offset.
  If it stops answering, the window says "fault" and the voltage stays where it was.

## The loop

The error is f − setpoint in MHz; the output is the integrator plus the P and D terms, so engaging starts
from the voltage already applied. The lock runs once per new wavemeter reading.

- **P** (V/MHz) and **I** (V/(MHz·s)) act on the error.
- **D** (V/(MHz/s)) acts on the measured frequency's rate, not the error's, so moving the setpoint gives no
  kick. The rate is low-pass filtered (**D filter**, default 0.5 s), since the wavemeter's noise
  differentiates badly. D = 0 (the default) is a PI lock; with the wavemeter's delay of about one reading,
  start without it and add a little only if the lock rings.

Each update:

- the output stays within **Output min/max** (inside 0–7 V) and moves at most **Max step** from the voltage
  applied. The limit is on each write to the DG1022: the wavemeter can measure faster than the DG1022 takes
  commands (one per 100 ms), and several readings between two writes still move the output by one step;
- when a limit cuts the output the integrator is reset to what was applied (no windup);
- no reading (low signal, …) or an error beyond **Capture range** (a mode hop, a wrong reading: the WS8 here
  gave readings about 19.7 GHz off now and then, 2026-11-11) holds the voltage.

**Release** holds the voltage that is applied: a correction still waiting for the DG1022's turn is dropped,
not written afterwards. The same goes for a lost lock, a fault, and a manual voltage typed just before a
lock, sweep or calibration starts.

**Calibrate tuning** (unlocked only) averages the frequency at the output now (V) and at V + **Cal. step**,
returns to V, and sets the tuning sign and the P and I gains from the slope (D is left alone): P corrects a
fifth of an error per update, I closes it in about 10 updates (at least 1 s). Start there, then tune by
hand. The step may be **negative** (step down: at the top limit, or with a mode hop just above); a step with
no room inside Output min/max is refused. It moves the laser by `slope × step`: keep it small enough not to
hop modes.

## The wavemeter's timing

**Exposure** (ms, CCD 1; **auto**: the wavemeter picks it from the signal) and **Measure every** (ms; **on**:
one measurement per interval instead of as fast as the exposure allows) are the WLM server's own settings,
read back about once a second; changing them here changes them in the WLM program too, and they stay after
laserlock exits. A new reading comes about every max(exposure + readout, interval): that is the lock's sample
rate ("new value every … ms" shows it). Setting an exposure turns auto off.

## Setpoints and the window

**Saved** lists saved setpoints, each as frequency and vacuum wavelength; choosing one sets the setpoint.
**Save setpoint** adds the one typed above, **Remove** drops the chosen one. They start as 276.767676768 THz
(also the default setpoint) and 1083.33064456 nm (vacuum), and are kept in `config.local.json` with the
rest. The setpoint holds 9 decimals in THz (1 kHz) and 8 in nm.

**Nudge** − / + moves the setpoint by the nudge (MHz), also while locked.

**The plots.** **Show** picks the time span (or All); the time plots scroll with the newest reading.
**Pause** freezes them to pan and zoom with the mouse (dragging the time axis pauses too); the readings keep
being recorded. **Time** labels the axis with the clock time or the seconds since the window opened.
**Clear** forgets the plotted readings (not the CSV log). **Plot** puts the error and the output on two plots
or on one with two y axes (error left, output right); **Line** sets the traces' width. Each plot's **y** range is **auto** or fixed
between the two boxes (MHz or V). The error axis's auto fits the **newest 20 s** of readings, so it follows the
laser: after a mode hop it would otherwise stay stretched over the jump for the whole span, flattening the
lock's trace (2026-11-12). The output's auto fits the whole span. Buttons set common ranges: error **±1 / ±10 / ±100 / ±1000 MHz**, output **0–7 V**; zooming a y axis with the mouse switches it to fixed and fills the boxes,
and the plot's own "A" button returns to auto. Span, time labels, ranges, layout, line width and hop lines are remembered between runs.

**Show: Time plots / Sweep plot** hides either plot panel (both: the window is just the controls); remembered
between runs.

**Number boxes.** The mouse wheel never changes a value or a drop-down (it scrolls the panel). While a box
is being edited, **↑ / ↓** step the digit just left of the text cursor (at the decimal point, the units),
and the cursor stays on that digit; the box's arrow buttons, without the cursor in it, step by the usual
amount.

## Mode hops

While running, laserlock watches the readings for **mode hops**: a jump of at least **Mode hop ≥** (Loop;
default 1000 MHz, since the free-running laser here scatters by up to ~300 MHz) from the current level that
holds for 3 readings in a row and at least 0.2 s (`hops.min_hold_s`). A lone far reading (the WS8 gives
occasional ones about 19.7 GHz off) or a short glitch (60 GHz for ~0.1 s, 2026-11-12) isn't one, and the
level follows slow drift and tuning. Each hop:

- is drawn as a red dot on the output trace (at the output when the hop came). **Hop lines** (off by
  default) also draws dashed lines across the time plots, for the newest 30 in the shown span, and the
  sweep's hops on the sweep plot; redrawn at most once a second (a laser sitting between two modes hops
  twice a second, and redrawing hundreds of lines froze the window, 2026-11-12);
- is counted under the wavemeter readings (the last one's jump, time and output), logged as a WARNING in
  `logs/laserlock.log` (at most one line a second, with a count of the others), and marked in the CSV's
  `hop` column.

While locked, a reading beyond the capture range holds the output for a moment ("locked (out of capture)":
it doesn't chase a far reading). The lock is **lost** when a confirmed mode hop lands out of the capture
range, or the readings stay out of it for **Lost after** (Loop, default 2 s): laserlock lets go, holds the
output where it was, says **LOCK LOST** (red) with the time and why, and logs it. It stays unlocked until
you lock again. With **If the lock is lost: find stable range → relock** (Sweep box) it runs Find stable
range with the box's settings instead and relocks if the setpoint is in a stable stretch (once per loss;
otherwise the table proposes). "locked: rms" above the plots leaves out readings beyond the capture
range and says how many. The sweep plot marks the sweep's mode hops (the jumps that split it into
stretches) the same way.

## Sweep and auto-lock

**Sweep** ramps gently (50 mV per write, 0.5 V/s) to *From*, steps to *To*, and plots the frequency at each step (the
median of the largest group of readings within 1 GHz of each other, so far outliers drop out); then
ramps back.

**Auto-lock to setpoint** sweeps the same way, then:

1. splits the sweep into hop-free stretches (a stretch ends at a missing reading or a jump well off the
   trend: more than 5× the typical step and at least 300 MHz);
2. picks where the setpoint is crossed inside a stretch with the most room on both sides;
3. ramps back to *From* and up to that voltage (the sweep's direction, for the piezo's hysteresis);
4. sets the sign and gains from the local slope, **limits the output to that stretch** (so the loop can't
   push it over a mode hop), and locks.

Both refuse (and write nothing) while the DG1022's output is off. Abort stops them and ramps back.

## Find a stable range

For after the laser's hardware has been touched: **Find stable range → lock** sweeps *From* → *To* and back
(*Step*, *Settle / dwell* as for a sweep) and keeps the output ranges that were mode-hop free **both ways**.
A voltage counts when each direction read one mode there (most readings in one group, no mode competition)
and both read the same one (the hysteresis between up and down is fine, another mode isn't), and neither
direction jumped next to it. Then:

- if the setpoint lies in a stable stretch at least **Margin** (default 0.3 V) from its ends, it ramps there
  from below (as the up sweep came), **holds** (default 5 s) and watches for mode hops; no hop: it sets the
  gains from the stretch's slope, keeps the output inside the stretch, and locks. The hold needs readings:
  it fails when no new valid reading comes for 1 s (or five of the wavemeter's update periods, if that is
  longer), also if the signal then comes back, and when fewer than 3 valid readings came in all;
- otherwise (not in one, too near an edge, a hop or no readings while holding) it returns to where it started and the
  table lists every stable stretch, widest in frequency first: its output range, where the setpoint falls
  in it or the **shift** the laser needs (+ raises its frequency) to put the setpoint at its centre, its
  width, slope and frequencies. Tweak the hardware by about that shift and press it again.

**Lock at selected** locks at a chosen stretch instead: it goes to the stretch's centre from below, makes the
frequency there the setpoint (if it still reads the scan's mode), and keeps the output inside the stretch.
The sweep plot shows the up and down sweeps and shades the stable stretches (the chosen one darker).

## Set up (once)

Needs [uv](https://docs.astral.sh/uv/), NI-VISA (or Keysight VISA) and the HighFinesse software installed.

```bat
cd side_projects\laserlock
uv venv --python 3.13 .venv
uv pip install -p .venv -e .[test]
```

## Run

```bat
.venv\Scripts\python -m laserlock          :: the lab's wavemeter channel 1 → DG1022 CH1
.venv\Scripts\python -m laserlock --sim    :: try it without the lab
```

Options: `--wm-channel N`, `--out-channel 1|2`, `--resource <VISA resource>` (default: the DG1022 found on
USB). Defaults are in `laserlock/config.py`; a `config.json` beside this README overrides them, and the
window saves its last setpoint, gains and limits to `config.local.json` (not in Git). Closing the window
releases the lock and leaves the output where it is. **Log to CSV** writes `logs/laserlock-<time>.csv`; the
log is `logs/laserlock.log`.

## Tests

```bat
.venv\Scripts\python -m pytest
```

They use the simulator and a fake VISA session, never the instruments.
