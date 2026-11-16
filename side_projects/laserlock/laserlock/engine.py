"""The loop thread: reads the wavemeter, runs the PID step on each new measurement, writes the DG1022.

Writes go out at most every `out.min_interval` (100 ms): the latest wanted voltage is written when its turn
comes, so a fast wavemeter never queues commands. The GUI reads `snapshot()` and `drain()`; it never waits on
an instrument. An instrument that stops answering ends the lock (mode "fault") and leaves the voltage where
it was.

A wanted voltage belongs to the mode that asked for it. It waits in the engine, never inside the device, and
a change of mode (Release, a lost lock, a fault, a sweep starting) withdraws it: nothing the lock computed is
written after the lock has ended. While locked, one write moves the output at most `max_step` from the
voltage applied, however many readings came since the last write.
"""

from __future__ import annotations

import collections
import csv
import logging
import statistics
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from .controller import Hop, HopDetector, LockSettings, PILock, suggest_gains
from .devices import (HARD_V_MAX, HARD_V_MIN, DeviceFault, FrequencySource, Reading, VoltageOutput,
                      WavemeterTiming)

log = logging.getLogger("laserlock.engine")


@dataclass(frozen=True)
class Sample:
    t: float
    thz: float | None
    error_mhz: float | None
    volts: float
    locked: bool
    hop: bool = False  # a mode hop was confirmed at this reading


@dataclass(frozen=True)
class HopEvent:
    t: float  # unix time of the first reading at the new level
    hop: Hop
    volts: float  # the output then
    locked: bool


@dataclass(frozen=True)
class Snapshot:
    mode: str  # "idle", "locked", "calibrating", "sweeping", "fault"
    reading: Reading
    error_mhz: float | None
    volts: float
    state: str  # the last PI step's state, or what the engine is doing
    message: str
    update_s: float | None  # median time between new measurements
    hops: int = 0  # mode hops seen since start
    last_hop: HopEvent | None = None
    wavemeter: WavemeterTiming | None = None  # None: this source's timing can't be read
    lost: int = 0  # times the lock was lost since start (state "lost" until the next engage)
    d_term: float = 0.0  # V, the lock's D share of the output now


class Engine:
    def __init__(self, source: FrequencySource, out: VoltageOutput, settings: LockSettings,
                 log_dir: Path | None = None, hops: HopDetector | None = None) -> None:
        self.source, self.out = source, out
        self._settings = settings
        self.pi = PILock(replace(settings))
        self._lock = threading.Lock()
        self._mode = "idle"
        self._state = "idle"
        self._message = ""
        self._target: float | None = None  # wanted voltage not yet written (this mode's: see `_enter`)
        self._session = 0  # +1 at every change of mode: a write that began before one knows it by this
        self._volts = out.get()
        self._reading = source.read()
        self._error: float | None = None
        self._samples: collections.deque[Sample] = collections.deque(maxlen=100_000)
        self.hops = hops or HopDetector()
        self._hop_events: collections.deque[HopEvent] = collections.deque(maxlen=1000)
        self._hop_count = 0
        self._hop_logged_at = 0.0
        self._out_since: float | None = None  # reading time the lock went out of capture
        self._lost = 0
        self._relock: ScanRequest | None = None  # on a lost lock: find a stable range and relock with this
        self._hops_unlogged = 0
        self._recent: collections.deque[tuple[float, float]] = collections.deque(maxlen=32)  # (reading t, volts)
        self._periods: collections.deque[float] = collections.deque(maxlen=50)
        self._last_seq = self._reading.seq
        self._last_cmd = 0.0  # when the last command to the output returned (loop thread)
        self._stop = threading.Event()
        self._cal_request: tuple[float, float, float] | None = None
        self._abort = threading.Event()
        self._cal_seq = -1
        self._sweep_request: SweepRequest | None = None
        self._sweep_points: list[SweepPoint] = []
        self._sweep_choice: LockPoint | None = None
        self._scan_request: ScanRequest | None = None
        self._goto_request: Stretch | None = None
        self._scan: ScanResult | None = None
        self._scan_seq = 0  # +1 whenever the scan's data change (the window redraws then)
        self.log_dir = log_dir
        self._csv: csv.writer | None = None  # type: ignore[valid-type]
        self._csv_file = None
        self._wm_timing: WavemeterTiming | None = None
        self._wm_request: dict[str, int | bool] = {}
        self._wm_read_at = 0.0
        self._thread = threading.Thread(target=self._run, name="laserlock-engine", daemon=True)

    # ---------------------------------------------------------------- commands (any thread)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._abort.set()
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)
        self.set_logging(False)

    def settings(self) -> LockSettings:
        with self._lock:
            return replace(self._settings)

    def update_settings(self, settings: LockSettings) -> None:
        with self._lock:
            self._settings = replace(settings)
            self.pi.s = replace(settings)

    def engage(self) -> None:
        with self._lock:
            if self._mode == "fault":
                return
            if self._settings.setpoint_thz <= 0:
                self._message = "set a setpoint first"
                return
            self.pi.engage(self._volts)
            self._enter("locked")  # starts from the voltage applied: a manual voltage not yet written is dropped
            self._message = "lock engaged"
            self._out_since = None
        log.info("lock engaged at %.4f V, setpoint %.7f THz", self._volts, self._settings.setpoint_thz)

    def release(self) -> None:
        with self._lock:
            if self._mode == "locked":
                self._enter("idle")  # and the correction waiting for the output's turn is never written
                self._state, self._message = "idle", RELEASED.format(self._volts)
                log.info("lock released at %.4f V", self._volts)

    def set_voltage(self, volts: float) -> None:
        """Manual output (only while not locked or calibrating)."""
        with self._lock:
            if self._mode == "idle":
                s = self._settings
                self._target = min(max(volts, s.v_min), s.v_max)

    def calibrate(self, step_v: float, settle_s: float, average_s: float) -> None:
        with self._lock:
            if self._mode == "idle":
                self._cal_request = (step_v, settle_s, average_s)
                self._abort.clear()
                self._enter("calibrating")
                self._message = "calibrating…"

    def abort_calibration(self) -> None:
        self._abort.set()

    def abort(self) -> None:
        """Stops a calibration or sweep (a sweep then returns to where it started)."""
        self._abort.set()

    def sweep(self, v_start: float, v_stop: float, step: float, settle_s: float, dwell_s: float,
              lock_thz: float | None = None) -> None:
        """Steps the output from v_start to v_stop, recording the frequency at each step. With `lock_thz`,
        then goes to where that frequency is crossed without a mode hop and locks there (auto-lock);
        otherwise returns to where it started."""
        with self._lock:
            if self._mode == "idle" and step > 0:
                self._sweep_request = SweepRequest(v_start, v_stop, step, settle_s, dwell_s, lock_thz)
                self._abort.clear()
                self._enter("sweeping")  # at once, so no one sees "idle" in between
                self._message = "sweep: starting"

    def find_stable(self, v_lo: float, v_hi: float, step: float, settle_s: float, dwell_s: float,
                    target_thz: float, margin_v: float = 0.3, hold_s: float = 5.0) -> None:
        """Sweeps v_lo → v_hi → v_lo and finds the stretches that are mode-hop free both ways. If `target_thz`
        lies in one with at least `margin_v` to either side, goes there from below, watches for `hold_s` that
        no hop comes, and locks. Otherwise (or if a hop comes) it stays unlocked, back where it started, and
        `scan_data()` lists the stretches with the shift the laser needs to bring the target to each one's
        centre."""
        with self._lock:
            if self._mode == "idle" and step > 0:
                lo, hi = sorted((v_lo, v_hi))
                self._scan_request = ScanRequest(lo, hi, step, settle_s, dwell_s, target_thz, margin_v, hold_s)
                self._abort.clear()
                self._enter("sweeping")
                self._message = "find stable range: starting"

    def lock_stretch(self, stretch: Stretch) -> None:
        """Goes to the centre of a stable stretch (from below, as the scan's up sweep), takes the frequency
        there as the setpoint, and locks with the output kept inside the stretch."""
        with self._lock:
            if self._mode == "idle":
                self._goto_request = stretch
                self._abort.clear()
                self._enter("sweeping")
                self._message = "going to the stretch"

    def scan_data(self) -> tuple[int, ScanResult | None]:
        with self._lock:
            return self._scan_seq, self._scan

    def sweep_data(self) -> tuple[list[SweepPoint], LockPoint | None]:
        with self._lock:
            return list(self._sweep_points), self._sweep_choice

    def snapshot(self) -> Snapshot:
        with self._lock:
            update = statistics.median(self._periods) if self._periods else None
            last = self._hop_events[-1] if self._hop_events else None
            return Snapshot(self._mode, self._reading, self._error, self._volts, self._state, self._message, update,
                            self._hop_count, last, self._wm_timing, self._lost,
                            self.pi.d_term if self._mode == "locked" else 0.0)

    def set_relock(self, request: ScanRequest | None) -> None:
        """With a request, a lost lock starts a find-stable-range scan (its target the setpoint then) and
        relocks if it finds one; None: a lost lock just stays unlocked, the output held."""
        with self._lock:
            self._relock = request

    def set_wavemeter(self, **changes: int | bool) -> None:
        """Changes the wavemeter's timing (keys of `WavemeterTiming`), on the loop thread."""
        with self._lock:
            self._wm_request.update(changes)

    def hop_events(self) -> list[HopEvent]:
        with self._lock:
            return list(self._hop_events)

    def set_hop_threshold(self, mhz: float) -> None:
        with self._lock:
            self.hops.min_jump_mhz = mhz

    def drain(self) -> list[Sample]:
        with self._lock:
            out = list(self._samples)
            self._samples.clear()
            return out

    def set_logging(self, on: bool) -> Path | None:
        with self._lock:
            if self._csv_file is not None:
                self._csv_file.close()
                self._csv_file, self._csv = None, None
            if not on or self.log_dir is None:
                return None
            self.log_dir.mkdir(parents=True, exist_ok=True)
            path = self.log_dir / time.strftime("laserlock-%Y%m%d-%H%M%S.csv")
            self._csv_file = path.open("w", newline="")
            self._csv = csv.writer(self._csv_file)
            self._csv.writerow(["unix_time", "thz", "setpoint_thz", "error_mhz", "volts", "locked", "status", "hop"])
            return path

    # ---------------------------------------------------------------- the loop thread

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self._cal_request is not None:
                    self._calibrate(*self._cal_request)
                    continue
                if self._sweep_request is not None:
                    self._sweep(self._sweep_request)
                    continue
                if self._scan_request is not None:
                    self._find_stable(self._scan_request)
                    continue
                if self._goto_request is not None:
                    self._lock_stretch(self._goto_request)
                    continue
                self._wavemeter_timing()
                self._tick()
                self._flush_output()
            except DeviceFault as e:
                log.error("%s", e)
                with self._lock:
                    self._enter("fault")
                    self._state, self._message = "fault", str(e)
                self._stop.wait(0.5)
                continue
            except Exception:
                log.exception("engine loop")
                with self._lock:
                    self._enter("fault")
                    self._message = "internal error (see the log)"
            self._stop.wait(POLL_S)

    def _wavemeter_timing(self) -> None:
        """Applies a requested timing change, and reads the timing back about once a second (auto exposure
        changes it by itself)."""
        set_timing = getattr(self.source, "set_timing", None)
        get_timing = getattr(self.source, "timing", None)
        if get_timing is None:
            return
        with self._lock:
            request, self._wm_request = self._wm_request, {}
        now = time.monotonic()
        if request and set_timing is not None:
            set_timing(**request)
            log.info("wavemeter timing: %s", request)
            with self._lock:
                self._periods.clear()  # the update period changes
        elif now - self._wm_read_at < 1.0:
            return
        self._wm_read_at = now
        timing = get_timing()
        with self._lock:
            self._wm_timing = timing

    def _tick(self) -> None:
        r = self.source.read()
        if r.seq == self._last_seq:
            return
        prev_t = self._reading.t
        self._last_seq = r.seq
        with self._lock:
            if r.thz is not None and self._reading.thz is not None:
                self._periods.append(r.t - prev_t)
            self._reading = r
            s = self._settings
            locked = self._mode == "locked"
            lost_why = ""
            if locked:
                # from the voltage applied, not the last step's: several readings can come per write
                step = self.pi.update(r.thz, r.t, self._volts)
                self._target, self._error, self._state = step.voltage, step.error_mhz, step.state
                if step.state == "out of capture":
                    self._out_since = r.t if self._out_since is None else self._out_since
                    if r.t - self._out_since >= s.lost_after_s:
                        lost_why = f"out of capture (±{s.capture_mhz:.0f} MHz) for {r.t - self._out_since:.1f} s"
                elif step.state != "no reading":
                    self._out_since = None
            else:
                self._error = None if r.thz is None or s.setpoint_thz <= 0 else (r.thz - s.setpoint_thz) * 1e6
            self._recent.append((r.t, self._volts))
            hop = self.hops.update(r.thz, r.t)
            now = time.time()
            if hop is not None:
                # the output when the first reading at the new level came, not now (3 readings later)
                volts = next((v for t, v in self._recent if t >= hop.t), self._volts)
                event = HopEvent(now - (time.monotonic() - hop.t), hop, volts, locked)
                self._hop_events.append(event)
                self._hop_count += 1
                if now - self._hop_logged_at >= 1.0:  # at most one line a second: a laser between modes hops often
                    more = f" (+{self._hops_unlogged} more since the last line)" if self._hops_unlogged else ""
                    log.warning("mode hop %+.3f GHz (%.7f -> %.7f THz) at %.4f V%s%s", hop.jump_mhz / 1e3,
                                hop.from_thz, hop.to_thz, volts, " while locked" if locked else "", more)
                    self._hop_logged_at, self._hops_unlogged = now, 0
                else:
                    self._hops_unlogged += 1
                if locked and abs(hop.to_thz - s.setpoint_thz) * 1e6 > s.capture_mhz:
                    lost_why = f"mode hop {hop.jump_mhz / 1e3:+.3f} GHz, out of capture"
            if lost_why:
                self._lose(lost_why)
            sample = Sample(now, r.thz, self._error, self._volts, locked, hop is not None)
            self._samples.append(sample)
            if self._csv is not None:
                self._csv.writerow([f"{sample.t:.3f}", "" if r.thz is None else f"{r.thz:.9f}", f"{s.setpoint_thz:.9f}",
                                    "" if self._error is None else f"{self._error:.3f}", f"{self._volts:.4f}",
                                    int(locked), r.status, int(hop is not None)])

    def _lose(self, why: str) -> None:
        """The lock is gone (called holding the lock): unlock, hold the output, say so; relock if asked."""
        self._enter("idle")
        self._state = "lost"
        self._out_since = None
        self._lost += 1
        when = time.strftime("%H:%M:%S")
        self._message = f"LOCK LOST at {when}: {why}; output held at {self._volts:.4f} V"
        log.warning("lock lost: %s; output held at %.4f V", why, self._volts)
        if self._relock is not None:
            self._scan_request = replace(self._relock, target_thz=self._settings.setpoint_thz)
            self._abort.clear()
            self._enter("sweeping")
            self._message += " — finding a stable range to relock"

    def _enter(self, mode: str) -> None:
        """Changes the mode (called holding the lock). A wanted voltage belongs to the mode that asked for it,
        so one not yet written is withdrawn: a correction of a lock that has ended, or a manual voltage typed
        just before a sweep, is never written later."""
        if mode != self._mode:
            self._mode = mode
            self._session += 1
            self._target = None

    def _set_out(self, volts: float) -> None:
        """One offset command, at once (loop thread; sweeps, ramps and calibration)."""
        applied = self.out.set(volts)
        self._last_cmd = time.monotonic()
        self._volts = applied

    def _output_on(self) -> bool:
        on = self.out.output_on()
        self._last_cmd = time.monotonic()
        return on

    def _flush_output(self) -> None:
        """Writes the wanted voltage once the output's turn has come.

        Until then the target waits here, where a change of mode withdraws it; it never waits inside the
        device (every command of the loop thread is timed in `_last_cmd`, and nothing else talks to the
        output). The mode is checked again, holding the lock, in the same step that hands the voltage to
        the device. While locked the write is held to `max_step` from the voltage applied."""
        if time.monotonic() - self._last_cmd < self.out.min_interval:
            return
        with self._lock:
            wanted, session = self._target, self._session
            if wanted is None:
                return
            target = wanted
            if self._mode == "locked":
                step = self._settings.max_step
                target = min(max(target, self._volts - step), self._volts + step)
            if abs(target - self._volts) < 5e-5:
                return
        applied = self.out.set(target)  # outside the lock: the window never waits on an instrument
        self._last_cmd = time.monotonic()
        with self._lock:
            before, self._volts = self._volts, applied
            if self._session == session:
                if self._target == wanted == target:
                    self._target = None
            elif self._mode == "locked":
                self.pi.engage(applied)  # Lock came while a manual voltage was on its way: start from it
            elif self._message == RELEASED.format(before):
                # Release came while this command was already on its way to the device: say what is held
                self._message = RELEASED.format(applied)

    def _collect(self, seconds: float) -> list[float]:
        values: list[float] = []
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self._abort.is_set():
            self._tick()
            r = self._reading
            if r.thz is not None and r.seq != self._cal_seq:
                values.append(r.thz)
                self._cal_seq = r.seq
            self._stop.wait(POLL_S)
        return values

    def _calibrate(self, step_v: float, settle_s: float, average_s: float) -> None:
        """Measures at V0 and at V0 + step (the step may be negative), fits the slope, returns to V0, suggests
        gains. A one-sided step keeps the laser to one side of where it is (away from a mode hop on the other)."""
        with self._lock:
            self._cal_request = None
            self._enter("calibrating")
            self._state, self._message = "calibrating", "calibrating…"
            s = self._settings
        v0 = self._volts
        lo, hi = v0, min(max(v0 + step_v, s.v_min), s.v_max)
        result = "calibration aborted"
        if abs(hi - lo) < 1e-3:
            with self._lock:
                self._enter("idle")
                self._state = "idle"
                self._message = (f"calibration: no room for a {step_v:+.4f} V step from {v0:.4f} V inside "
                                 f"{s.v_min:g}–{s.v_max:g} V (try the other sign)")
            return
        try:
            means = []
            for v in (lo, hi):
                self._set_out(v)
                self._collect(settle_s)
                vals = self._collect(average_s)
                if self._abort.is_set() or len(vals) < 3:
                    result = "calibration aborted" if self._abort.is_set() else "calibration: too few readings"
                    break
                means.append(statistics.fmean(vals))
            else:
                slope = (means[1] - means[0]) * 1e6 / (hi - lo)
                update = statistics.median(self._periods) if self._periods else 0.1
                try:
                    sign, kp, ki = suggest_gains(slope, update)
                    with self._lock:
                        self._settings = replace(self._settings, sign=sign, kp=kp, ki=ki)
                        self.pi.s = replace(self._settings)
                    result = f"tuning {slope:+.1f} MHz/V → sign {sign:+d}, kp {kp:.3g} V/MHz, ki {ki:.3g} V/(MHz·s)"
                except ValueError:
                    result = "calibration: no frequency change seen"
        finally:
            self._set_out(v0)
            with self._lock:
                self._enter("idle")
                self._state, self._message = "idle", result
            log.info("%s", result)

    # ---------------------------------------------------------------- sweep and auto-lock

    def _set_progress(self, message: str) -> None:
        with self._lock:
            self._message = message

    def _ramp_to(self, v: float, step: float | None = None) -> None:
        """Moves the output to v in steps of at most `step` (RAMP_STEP_V; one per DG1022 turn), reading as it goes."""
        step = RAMP_STEP_V if step is None else step
        v = min(max(v, HARD_V_MIN), HARD_V_MAX)
        while abs(v - self._volts) > 5e-5 and not self._abort.is_set():
            nxt = self._volts + max(min(v - self._volts, step), -step)
            self._set_out(nxt)
            self._tick()

    def _sweep(self, req: SweepRequest) -> None:
        with self._lock:
            self._sweep_request = None
            self._enter("sweeping")
            self._state = "sweeping"
            self._sweep_points = []
            self._sweep_choice = None
            self._scan = None
            self._scan_seq += 1
        v_back = self._volts
        result = "sweep aborted"
        locked = False
        try:
            if not self._output_on():
                result = "the DG1022's output is off: switch it on at the front panel first"
                return
            lo, hi = sorted((min(max(req.v_start, HARD_V_MIN), HARD_V_MAX), min(max(req.v_stop, HARD_V_MIN), HARD_V_MAX)))
            up = req.v_stop >= req.v_start
            n = max(int(round((hi - lo) / req.step)), 1)
            vs = [lo + (hi - lo) * i / n for i in range(n + 1)]
            if not up:
                vs.reverse()
            self._set_progress(f"sweep: ramping to {vs[0]:.3f} V")
            self._ramp_to(vs[0])
            for i, v in enumerate(vs):
                if self._abort.is_set():
                    return
                self._set_out(v)
                self._collect(req.settle_s)
                vals = self._collect(req.dwell_s)
                point = sweep_point(self._volts, vals)
                with self._lock:
                    self._sweep_points.append(point)
                    self._message = f"sweep {i + 1}/{len(vs)}: {v:.3f} V"
            points = list(self._sweep_points)
            if req.lock_thz is None:
                result = f"sweep done: {len(points)} points"
                return
            choice = choose_lock_point(points, req.lock_thz)
            with self._lock:
                self._sweep_choice = choice
            if choice is None:
                got = [p.thz for p in points if p.thz is not None]
                span = f"{min(got):.6f}–{max(got):.6f} THz" if got else "no readings"
                result = f"auto-lock: {req.lock_thz:.7f} THz isn't crossed without a mode hop (sweep reached {span})"
                return
            # approach from the sweep's start side, as the sweep did (piezo hysteresis)
            self._set_progress(f"auto-lock: approaching {choice.volts:.4f} V")
            self._ramp_to(vs[0])
            self._ramp_to(choice.volts)
            self._collect(req.settle_s + 0.3)
            update = statistics.median(self._periods) if self._periods else 0.1
            sign, kp, ki = suggest_gains(choice.mhz_per_v, update)
            with self._lock:
                self._settings = replace(self._settings, setpoint_thz=req.lock_thz, sign=sign, kp=kp, ki=ki,
                                         v_min=choice.v_lo, v_max=choice.v_hi,
                                         capture_mhz=max(self._settings.capture_mhz, 2 * abs(choice.mhz_per_v) * req.step))
                self.pi.s = replace(self._settings)
                self.pi.engage(self._volts)
                self._enter("locked")
                self._state = "locked"
                locked = True
            result = (f"auto-lock engaged at {choice.volts:.4f} V (tuning {choice.mhz_per_v:+.0f} MHz/V, "
                      f"hop-free {choice.v_lo:.3f}–{choice.v_hi:.3f} V kept as the output range)")
        finally:
            if not locked:
                if self._volts != v_back and "output is off" not in result:
                    self._set_progress("sweep: returning")
                    self._abort.clear()
                    self._ramp_to(v_back)
                with self._lock:
                    self._enter("idle")
                    self._state = "idle"
            with self._lock:
                self._message = result
            log.info("%s", result)


    # ---------------------------------------------------------------- find a stable range

    def _scan_leg(self, vs: list[float], req: ScanRequest, name: str, into: list[SweepPoint]) -> bool:
        for i, v in enumerate(vs):
            if self._abort.is_set():
                return False
            self._set_out(v)
            self._collect(req.settle_s)
            point = sweep_point(self._volts, self._collect(req.dwell_s))
            with self._lock:
                into.append(point)
                self._scan_seq += 1
                self._message = f"find stable range: {name} {i + 1}/{len(vs)}: {v:.3f} V"
        return True

    def _hold_test(self, seconds: float, expect_thz: float, limit_mhz: float) -> str | None:
        """Watches the frequency for `seconds`; returns why it isn't known to be stable, or None.

        Stable needs evidence: new valid readings all through the hold, none of them a mode hop and fewer
        than three out of range. Readings that stop for longer than `_hold_gap()` (no signal, or the
        wavemeter repeating its last value), at any time up to the hold's end, fail it at once, also if they
        would have come back; so do fewer than HOLD_MIN_READINGS in all."""
        hops0 = self._hop_count
        far = valid = 0
        gap = self._hold_gap()
        start = last_valid = time.monotonic()
        end = start + seconds
        while not self._abort.is_set():
            left = end - time.monotonic()
            if left <= 0:
                break
            values = self._collect(min(HOLD_CHUNK_S, left))
            now = time.monotonic()
            if values:
                valid += len(values)
                last_valid = now
                far += sum(abs(f - expect_thz) * 1e6 > limit_mhz for f in values)
            if self._hop_count != hops0:
                return "a mode hop came while holding"
            if far >= 3:
                return f"the frequency left ±{limit_mhz:.0f} MHz of the expected while holding"
            if now - last_valid > gap:
                status = self._reading.status
                why = "the wavemeter repeated its last value" if status == "ok" else f"wavemeter: {status}"
                return f"no new valid reading for {now - last_valid:.1f} s while holding ({why})"
            self._set_progress(f"find stable range: holding, {max(end - now, 0):.0f} s left")
        if self._abort.is_set():
            return "aborted"
        if valid < HOLD_MIN_READINGS:
            return (f"only {valid} valid reading{'' if valid == 1 else 's'} in the {seconds:g} s hold "
                    f"(at least {HOLD_MIN_READINGS} needed: hold for longer, or measure faster)")
        return None

    def _hold_gap(self) -> float:
        """The longest a hold goes without a new valid reading: HOLD_GAP_S, or five of the wavemeter's
        update periods if that is longer (a slow wavemeter isn't a lost signal)."""
        with self._lock:
            update = statistics.median(self._periods) if self._periods else 0.0
        return max(HOLD_GAP_S, 5 * update)

    def _engage_in(self, stretch: Stretch, setpoint_thz: float, extra_capture_mhz: float) -> None:
        update = statistics.median(self._periods) if self._periods else 0.1
        sign, kp, ki = suggest_gains(stretch.mhz_per_v, update)
        with self._lock:
            self._settings = replace(self._settings, setpoint_thz=setpoint_thz, sign=sign, kp=kp, ki=ki,
                                     v_min=stretch.v_lo, v_max=stretch.v_hi,
                                     capture_mhz=max(self._settings.capture_mhz, extra_capture_mhz))
            self.pi.s = replace(self._settings)
            self.pi.engage(self._volts)
            self._enter("locked")
            self._state = "locked"

    def _find_stable(self, req: ScanRequest) -> None:
        with self._lock:
            self._scan_request = None
            self._enter("sweeping")
            self._state = "sweeping"
            self._scan = ScanResult(req, [], [], [], None, "")
            self._scan_seq += 1
            scan = self._scan
            self._sweep_points, self._sweep_choice = [], None
        v_back = self._volts
        result = "find stable range: aborted"
        locked = False
        try:
            if not self._output_on():
                result = "the DG1022's output is off: switch it on at the front panel first"
                return
            lo, hi = max(req.v_lo, HARD_V_MIN), min(req.v_hi, HARD_V_MAX)
            n = max(int(round((hi - lo) / req.step)), 2)
            vs = [round(lo + (hi - lo) * i / n, 4) for i in range(n + 1)]
            self._set_progress(f"find stable range: ramping to {vs[0]:.3f} V")
            self._ramp_to(vs[0])
            if not self._scan_leg(vs, req, "up", scan.up) or not self._scan_leg(vs[::-1], req, "down", scan.down):
                return
            stretches = stable_stretches(scan.up, scan.down, req.target_thz)
            choice = next((st for st in stretches if st.target_v is not None and st.room_v >= req.margin_v), None)
            with self._lock:
                self._scan = scan = ScanResult(req, scan.up, scan.down, stretches, choice, "")
                self._scan_seq += 1
            if not stretches:
                result = "find stable range: no mode-hop-free stretch of 3 points or more in the range"
                return
            if choice is None:
                near = [st for st in stretches if st.target_v is not None]
                why = (f"the setpoint is in {near[0].v_lo:.2f}–{near[0].v_hi:.2f} V but only {near[0].room_v:.2f} V "
                       f"from its edge (margin {req.margin_v:.2f} V)") if near else "the setpoint isn't in a stable stretch"
                best = stretches[0]
                result = (f"find stable range: {why}. Widest: {best.v_lo:.2f}–{best.v_hi:.2f} V, "
                          f"{best.width_mhz / 1e3:.1f} GHz; shift the laser {best.shift_mhz / 1e3:+.2f} GHz to centre "
                          f"the setpoint in it (all {len(stretches)} in the table)")
                return
            assert choice.target_v is not None
            self._set_progress(f"find stable range: approaching {choice.target_v:.4f} V from below")
            self._ramp_to(choice.v_lo)
            self._ramp_to(choice.target_v)
            arrived = self._collect(req.settle_s + 0.3)
            limit = max(5 * abs(choice.mhz_per_v) * req.step, HOP_MIN_MHZ)
            if req.hold_s > 0:
                failed = self._hold_test(req.hold_s, req.target_thz, limit)
            elif self._abort.is_set():
                failed = "aborted"
            else:  # a hold of 0 skips the watch, not the reading: the laser must still be measured there
                failed = None if arrived else f"no valid reading there (wavemeter: {self._reading.status})"
            if failed is not None:
                result = f"find stable range: not locked, {failed} at {choice.target_v:.4f} V"
                return
            self._engage_in(choice, req.target_thz, 2 * abs(choice.mhz_per_v) * req.step)
            locked = True
            result = (f"find stable range: locked at {choice.target_v:.4f} V in {choice.v_lo:.2f}–{choice.v_hi:.2f} V "
                      f"({choice.width_mhz / 1e3:.1f} GHz hop-free, {choice.room_v:.2f} V room; tuning "
                      f"{choice.mhz_per_v:+.0f} MHz/V)")
        finally:
            self._finish_scan(locked, v_back, result)

    def _finish_scan(self, locked: bool, v_back: float, result: str) -> None:
        if not locked:
            if abs(self._volts - v_back) > 5e-5 and "output is off" not in result:
                self._set_progress("returning")
                self._abort.clear()
                self._ramp_to(v_back)
            with self._lock:
                self._enter("idle")
                self._state = "idle"
        with self._lock:
            self._message = result
            if self._scan is not None:
                self._scan = replace(self._scan, message=result)
                self._scan_seq += 1
        log.info("%s", result)

    def _lock_stretch(self, stretch: Stretch) -> None:
        with self._lock:
            self._goto_request = None
            self._enter("sweeping")
            self._state = "sweeping"
        v_back = self._volts
        result = "aborted"
        locked = False
        try:
            centre = (stretch.v_lo + stretch.v_hi) / 2
            self._set_progress(f"going to {centre:.3f} V from below")
            self._ramp_to(stretch.v_lo)
            self._ramp_to(centre)
            self._collect(0.5)
            vals = self._collect(1.0)
            if self._abort.is_set():
                return
            if len(vals) < 3:
                result = "lock at stretch: too few readings"
                return
            f = statistics.median(vals)
            expect = stretch.f_at(centre)
            if abs(f - expect) * 1e6 > max(abs(stretch.mhz_per_v) * 0.5, HOP_MIN_MHZ):
                result = (f"lock at stretch: the laser reads {(f - expect) * 1e6:+.0f} MHz from the scan there "
                          f"(another mode, or the hardware moved): scan again")
                return
            self._engage_in(stretch, round(f, 7), 2 * HOP_MIN_MHZ)
            locked = True
            result = f"locked at {centre:.4f} V, setpoint {f:.7f} THz (stretch {stretch.v_lo:.2f}–{stretch.v_hi:.2f} V)"
        finally:
            self._finish_scan(locked, v_back, result)


POLL_S = 0.01  # the wavemeter is polled every 10 ms (it measures every ~40 ms here)
RELEASED = "lock released, holding {:.4f} V"
HOLD_GAP_S = 1.0  # a stable-range hold fails after this long without a new valid reading (see `_hold_gap`)
HOLD_MIN_READINGS = 3  # and with fewer valid readings than this in all
HOLD_CHUNK_S = 0.2  # how often a hold checks
RAMP_STEP_V = 0.05  # V per write when ramping (one write per 100 ms: 0.5 V/s)
HOP_MIN_MHZ = 300.0  # a jump between sweep points at least this big (and well off the trend) is a mode hop


@dataclass(frozen=True)
class SweepRequest:
    v_start: float
    v_stop: float
    step: float
    settle_s: float
    dwell_s: float
    lock_thz: float | None  # None: sweep only, then return


@dataclass(frozen=True)
class SweepPoint:
    volts: float
    thz: float | None  # median of the largest group of readings within 1 GHz (drops the far outliers)
    spread_mhz: float | None
    n: int  # readings in the largest group
    total: int = 0  # readings taken (0: unknown)


@dataclass(frozen=True)
class LockPoint:
    volts: float
    mhz_per_v: float
    v_lo: float  # the hop-free stretch around it
    v_hi: float


def sweep_point(volts: float, vals: list[float]) -> SweepPoint:
    if not vals:
        return SweepPoint(volts, None, None, 0, 0)
    # the largest group of readings within 1 GHz of each other (the median of two far groups is in neither)
    groups = [[w for w in vals if abs(w - v) < 1e-3] for v in vals]
    near = max(groups, key=len)
    med = statistics.median(near)
    spread = statistics.pstdev(near) * 1e6 if len(near) > 1 else 0.0
    return SweepPoint(volts, med, spread, len(near), len(vals))


def split_sweep(points: list[SweepPoint]) -> tuple[list[SweepPoint], list[tuple[int, int]], list[float], float]:
    """The sweep's points by voltage, its hop-free stretches (index ranges), the voltages of its mode hops
    (midway between the two points), and the typical step (MHz). A stretch ends at a missing reading or at a
    jump well off the trend (more than 5x the typical step and at least HOP_MIN_MHZ)."""
    pts = sorted(points, key=lambda p: p.volts)
    steps = [(b.thz - a.thz) * 1e6 for a, b in zip(pts, pts[1:]) if a.thz is not None and b.thz is not None]
    if not steps:
        return pts, [], [], 0.0
    typical = statistics.median(steps)
    limit = max(5 * abs(typical), HOP_MIN_MHZ)
    stretches: list[tuple[int, int]] = []
    hops: list[float] = []
    start = 0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        if a.thz is None or b.thz is None or abs((b.thz - a.thz) * 1e6 - typical) >= limit:
            stretches.append((start, i))
            start = i + 1
            if a.thz is not None and b.thz is not None:
                hops.append((a.volts + b.volts) / 2)
    stretches.append((start, len(pts) - 1))
    return pts, stretches, hops, typical


def sweep_hops(points: list[SweepPoint]) -> list[float]:
    return split_sweep(points)[2]


def choose_lock_point(points: list[SweepPoint], target_thz: float) -> LockPoint | None:
    """Where the sweep crosses `target_thz` inside a hop-free stretch, choosing the crossing with the most room
    to either side."""
    if len(points) < 3:
        return None
    pts, stretches, _, typical = split_sweep(points)
    if not stretches:
        return None
    best: tuple[float, LockPoint] | None = None
    for a, b in stretches:
        if b - a < 2:
            continue
        for i in range(a, b):
            f1, f2 = pts[i].thz, pts[i + 1].thz
            assert f1 is not None and f2 is not None
            if not (min(f1, f2) <= target_thz <= max(f1, f2)) or f1 == f2:
                continue
            v = pts[i].volts + (target_thz - f1) / (f2 - f1) * (pts[i + 1].volts - pts[i].volts)
            lo_i, hi_i = max(a, i - 3), min(b, i + 4)  # local slope over a few points
            fa, fb = pts[lo_i].thz, pts[hi_i].thz
            assert fa is not None and fb is not None
            slope = (fb - fa) * 1e6 / (pts[hi_i].volts - pts[lo_i].volts)
            if slope == 0 or (slope > 0) != (typical > 0):
                continue
            room = min(v - pts[a].volts, pts[b].volts - v)
            cand = LockPoint(v, slope, pts[a].volts, pts[b].volts)
            if best is None or room > best[0]:
                best = (room, cand)
    return None if best is None else best[1]



@dataclass(frozen=True)
class ScanRequest:
    v_lo: float
    v_hi: float
    step: float
    settle_s: float
    dwell_s: float
    target_thz: float
    margin_v: float
    hold_s: float


@dataclass(frozen=True)
class Stretch:
    """A range of output that was mode-hop free sweeping both up and down."""

    v_lo: float
    v_hi: float
    f_lo: float  # THz, over both directions
    f_hi: float
    mhz_per_v: float  # fitted tuning slope
    f_mid: float  # THz, the fit at the stretch's centre
    target_v: float | None  # where the target is crossed (up sweep), if it is
    room_v: float  # from target_v to the nearer end (0 if not crossed)
    shift_mhz: float  # the laser shift that would put the target at the stretch's centre

    @property
    def width_mhz(self) -> float:
        return (self.f_hi - self.f_lo) * 1e6

    def f_at(self, v: float) -> float:
        return self.f_mid + self.mhz_per_v * (v - (self.v_lo + self.v_hi) / 2) * 1e-6


@dataclass(frozen=True)
class ScanResult:
    request: ScanRequest
    up: list[SweepPoint]
    down: list[SweepPoint]  # in the order measured (high to low)
    stretches: list[Stretch]  # widest first
    choice: Stretch | None
    message: str


def _cross(pts: list[SweepPoint], target: float) -> float | None:
    for a, b in zip(pts, pts[1:]):
        if a.thz is None or b.thz is None or a.thz == b.thz:
            continue
        if min(a.thz, b.thz) <= target <= max(a.thz, b.thz):
            return a.volts + (target - a.thz) / (b.thz - a.thz) * (b.volts - a.volts)
    return None


def stable_stretches(up: list[SweepPoint], down: list[SweepPoint], target_thz: float,
                     min_points: int = 3) -> list[Stretch]:
    """The ranges that are mode-hop free in both directions, widest (in frequency) first.

    A voltage is stable when both sweeps read one mode there (most readings in one group) and the same one
    (up and down within a hop of each other: hysteresis is fine, another mode isn't); two neighbours are
    joined when neither sweep jumped between them (more than 5x the typical step and at least HOP_MIN_MHZ
    off the trend)."""
    by_v = {round(p.volts, 4): p for p in down}
    pairs = [(u, by_v.get(round(u.volts, 4))) for u in sorted(up, key=lambda p: p.volts)]
    steps = [(b.thz - a.thz) * 1e6 for leg in (up, down) for a, b in zip(sorted(leg, key=lambda p: p.volts),
                                                                         sorted(leg, key=lambda p: p.volts)[1:])
             if a.thz is not None and b.thz is not None]
    if not steps:
        return []
    typical = statistics.median(steps)
    limit = max(5 * abs(typical), HOP_MIN_MHZ)

    def one_mode(p: SweepPoint | None) -> bool:
        return p is not None and p.thz is not None and (p.total == 0 or p.n >= 0.8 * p.total)

    def good(i: int) -> bool:
        u, d = pairs[i]
        return one_mode(u) and one_mode(d) and abs((u.thz or 0) - (d.thz or 0)) * 1e6 < limit  # type: ignore[union-attr]

    def joined(i: int) -> bool:
        for k in (0, 1):
            a, b = pairs[i][k], pairs[i + 1][k]
            assert a is not None and b is not None and a.thz is not None and b.thz is not None
            if abs((b.thz - a.thz) * 1e6 - typical) >= limit:
                return False
        return True

    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(pairs):
        if not good(i):
            i += 1
            continue
        j = i
        while j + 1 < len(pairs) and good(j + 1) and joined(j):
            j += 1
        if j - i + 1 >= min_points:
            runs.append((i, j))
        i = j + 1
    out: list[Stretch] = []
    for a, b in runs:
        ups = [pairs[k][0] for k in range(a, b + 1)]
        downs = [pairs[k][1] for k in range(a, b + 1)]
        vs = [p.volts for p in ups]
        mids = [((u.thz or 0) + (d.thz or 0)) / 2 for u, d in zip(ups, downs)]  # type: ignore[union-attr]
        fit = statistics.linear_regression(vs, [(m - mids[0]) * 1e6 for m in mids])
        v_lo, v_hi = vs[0], vs[-1]
        vc = (v_lo + v_hi) / 2
        f_mid = mids[0] + (fit.intercept + fit.slope * vc) * 1e-6
        every = [p.thz for p in ups + downs if p is not None and p.thz is not None]
        tv = _cross(ups, target_thz)
        down_crosses = _cross(sorted((d for d in downs if d is not None), key=lambda p: p.volts), target_thz)
        if tv is not None and down_crosses is None:
            tv = None  # only one direction reaches it: too close to the edge
        room = min(tv - v_lo, v_hi - tv) if tv is not None else 0.0
        out.append(Stretch(v_lo, v_hi, min(every), max(every), fit.slope, f_mid, tv, room,
                           (target_thz - f_mid) * 1e6))
    out.sort(key=lambda st: -st.width_mhz)
    return out
