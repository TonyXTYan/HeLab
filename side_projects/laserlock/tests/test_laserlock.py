from __future__ import annotations

import math
import os
import time
from typing import Any

import pytest

# Run from side_projects/laserlock with its own environment (`uv run pytest`). HeLab's own pytest
# collects this file too and skips it, since laserlock isn't installed in HeLab's environment.
pytest.importorskip("laserlock")

from laserlock import config
from laserlock.controller import LockSettings, PILock, nm_to_thz, suggest_gains, thz_to_nm
from laserlock.devices import DG1022, HARD_V_MAX, DeviceFault, Reading
from laserlock.engine import Engine
from laserlock.sim import SimDG1022, SimLaser, SimWavemeter

F0 = 276.732


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_units() -> None:
    assert thz_to_nm(nm_to_thz(1083.33)) == pytest.approx(1083.33)
    assert thz_to_nm(299.792458) == pytest.approx(1000.0)


def test_pi_moves_against_the_error_with_sign() -> None:
    for sign in (1, -1):
        pi = PILock(LockSettings(setpoint_thz=F0, kp=0.001, ki=0.0, sign=sign, v_min=0, v_max=7, max_step=1))
        pi.engage(3.0)
        step = pi.update(F0 + 10e-6, 0.0)  # 10 MHz high
        assert step.error_mhz == pytest.approx(10.0)
        assert step.voltage == pytest.approx(3.0 - sign * 0.01)


def test_pi_limits_step_and_range_without_windup() -> None:
    pi = PILock(LockSettings(setpoint_thz=F0, kp=0.0, ki=1.0, sign=1, v_min=0, v_max=3.05, max_step=0.01))
    pi.engage(3.0)
    vs = [pi.update(F0 - 100e-6, t * 0.1).voltage for t in range(20)]  # far low: wants a big rise
    assert all(b - a <= 0.01 + 1e-12 for a, b in zip(vs, vs[1:]))
    assert max(vs) == pytest.approx(3.05)
    # integrator was held at what was applied: the first opposite error turns the output back at once
    assert pi.update(F0 + 1e-6, 2.1).voltage < 3.05


def test_pi_holds_on_no_reading_and_out_of_capture() -> None:
    pi = PILock(LockSettings(setpoint_thz=F0, kp=0.01, ki=0.1, capture_mhz=100))
    pi.engage(2.0)
    assert pi.update(None, 0.0).state == "no reading"
    step = pi.update(F0 + 500e-6, 0.1)
    assert (step.state, step.voltage) == ("out of capture", 2.0)


def test_engage_never_leaves_hard_limits() -> None:
    s = config.clamp(LockSettings(v_min=-3, v_max=12))
    assert (s.v_min, s.v_max) == (0.0, HARD_V_MAX)


def test_closed_loop_on_simulated_laser() -> None:
    clock = Clock()
    laser = SimLaser(f0_thz=F0, mhz_per_v=300.0, noise_mhz=0.3, walk_mhz_per_rt_s=2.0, sine_mhz=20.0,
                     sine_period_s=30.0, clock=clock, seed=1)
    wm, out = SimWavemeter(laser, period=0.03), SimDG1022(laser, volts=3.0)
    setpoint = F0 + 300e-6 * 3.0 + 50e-6  # 50 MHz above where it starts: needs about +0.17 V
    sign, kp, ki = suggest_gains(300.0, 0.03)
    pi = PILock(LockSettings(setpoint_thz=setpoint, kp=kp, ki=ki, sign=sign, max_step=0.02))
    pi.engage(out.get())
    errors, seq, last_write = [], 0, -1.0
    while clock.t < 60.0:
        clock.t += 0.005
        r = wm.read()
        if r.seq != seq:
            seq = r.seq
            step = pi.update(r.thz, r.t)
            if clock.t - last_write >= 0.05:
                out.set(step.voltage)
                last_write = clock.t
            if clock.t > 20:
                errors.append(step.error_mhz)
    rms = (sum(e * e for e in errors) / len(errors)) ** 0.5
    assert rms < 3.0, rms  # free-running it drifts by tens of MHz


def test_engine_locks_and_calibrates_with_sim() -> None:
    laser = SimLaser(f0_thz=F0, mhz_per_v=300.0, noise_mhz=0.2, walk_mhz_per_rt_s=0.5, sine_mhz=0.0, seed=2)
    wm, out = SimWavemeter(laser, period=0.02), SimDG1022(laser, volts=3.0)
    eng = Engine(wm, out, LockSettings())
    eng.start()
    try:
        eng.calibrate(0.05, 0.2, 0.4)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not eng.snapshot().message.startswith(("tuning", "calibration")):
            time.sleep(0.05)
        snap = eng.snapshot()
        assert snap.message.startswith("tuning"), snap.message
        s = eng.settings()
        assert s.sign == 1 and s.ki > 0
        assert out.get() == pytest.approx(3.0)  # back where it started
        eng.update_settings(LockSettings(**{**s.__dict__, "setpoint_thz": F0 + 300e-6 * 3.0 + 20e-6}))
        eng.engage()
        time.sleep(4)
        snap = eng.snapshot()
        assert snap.mode == "locked"
        assert snap.error_mhz is not None and abs(snap.error_mhz) < 3, snap
        assert out.get() == pytest.approx(3.0 + 20 / 300, abs=0.01)
        assert out.writes < 4 / 0.05 + 30  # never faster than one write per 50 ms (+ the calibration's)
    finally:
        eng.stop()


class FakeVisa:
    """Answers like the DG1022, records every command and when it came."""

    def __init__(self) -> None:
        self.log: list[tuple[float, str]] = []
        self.offset = 0.0
        self.reply = ""

    def write(self, cmd: str) -> None:
        self.log.append((time.monotonic(), cmd))
        if cmd.startswith("VOLT:OFFS "):
            self.offset = float(cmd.split()[1])
        self.reply = {"*IDN?": "RIGOL TECHNOLOGIES,DG1022 ,DG1D0,03.03", "APPL?": 'CH1:"ARB,1.0e+03,5.0e+00,0.0e+00"',
                      "OUTP?": "ON", "VOLT:OFFS?": f"{self.offset:e}"}.get(cmd, "")

    def read(self) -> str:
        return self.reply

    def lock_excl(self, timeout: int = 0) -> None:
        self.locked = True

    def unlock(self) -> None:
        self.locked = False

    def close(self) -> None:
        pass


@pytest.fixture
def dg(monkeypatch: pytest.MonkeyPatch) -> tuple[DG1022, FakeVisa]:
    import pyvisa

    fake = FakeVisa()

    class RM:
        def list_resources(self) -> tuple[str, ...]:
            return ("USB0::0x0957::0x5707::X::INSTR", "USB0::0x0400::0x09C4::DG1D0::INSTR")

        def open_resource(self, *a: Any, **k: Any) -> FakeVisa:
            return fake

    monkeypatch.setattr(pyvisa, "ResourceManager", RM)
    return DG1022(), fake


def test_dg1022_finds_rounds_clamps_and_paces(dg: tuple[DG1022, FakeVisa]) -> None:
    d, fake = dg
    assert d.resource.startswith("USB0::0x0400::0x09C4")
    assert d.output == "ON"
    assert fake.locked  # no other VISA program can interleave commands
    assert d.set(1.234567) == 1.2346
    assert d.set(9.0) == HARD_V_MAX
    assert d.set(-1.0) == 0.0
    sets = [c for c in fake.log if c[1].startswith("VOLT:OFFS ")]
    assert [c for _, c in sets] == ["VOLT:OFFS 1.2346", "VOLT:OFFS 7.0000", "VOLT:OFFS 0.0000"]
    times = [t for t, _ in fake.log]
    assert min(b - a for a, b in zip(times, times[1:])) >= 0.05 - 0.002
    assert all(not c.startswith(("OUTP ", "APPL:", "FUNC", "VOLT ")) for _, c in fake.log)  # only the offset


def test_dg1022_hang_is_a_fault(dg: tuple[DG1022, FakeVisa]) -> None:
    import pyvisa

    d, fake = dg

    def hang(cmd: str) -> None:
        raise pyvisa.errors.VisaIOError(-1073807339)

    fake.write = hang  # type: ignore[method-assign]
    with pytest.raises(DeviceFault):
        d.set(1.0)


def test_window_runs_with_sim(tmp_path: Any) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from laserlock.gui import MainWindow

    app = QApplication.instance() or QApplication([])
    laser = SimLaser(f0_thz=F0, seed=3)
    eng = Engine(SimWavemeter(laser), SimDG1022(laser), LockSettings(), log_dir=tmp_path)
    saved: list[Any] = []
    win = MainWindow(eng, {"step_v": 0.05, "settle_s": 0.5, "average_s": 0.5}, lambda s, c: saved.append(s))
    eng.start()
    try:
        win.show()
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)
        win._use_current()
        win.lock_btn.setChecked(True)
        assert eng.snapshot().mode == "locked"
        win.log_box.setChecked(True)
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)
        assert win.freq_label.text().endswith("THz")
        win.close()
        assert saved and saved[0].setpoint_thz > 0
    finally:
        eng.stop()
    assert list(tmp_path.glob("laserlock-*.csv"))


# ---------------------------------------------------------------- sweep and auto-lock

from laserlock.engine import SweepPoint, choose_lock_point  # noqa: E402


def _points(slope: float, hop_every: float, hop: float, f0: float = F0) -> list[SweepPoint]:
    import math

    pts = []
    for i in range(71):
        v = i * 0.1
        mhz = slope * v - (hop * math.floor(v / hop_every) if hop_every else 0)
        pts.append(SweepPoint(v, f0 + mhz * 1e-6, 1.0, 5))
    return pts


def test_choose_lock_point_avoids_hops_and_picks_most_room() -> None:
    pts = _points(300.0, 2.0, 600.0)  # a sawtooth: each 2 V stretch spans 600 MHz
    target = F0 + 300e-6  # crossed at 1.0, 3.0, 5.0 V (and near the hop edges)
    choice = choose_lock_point(pts, target)
    assert choice is not None
    assert choice.mhz_per_v == pytest.approx(300.0, rel=0.05)
    assert choice.volts == pytest.approx(round(choice.volts), abs=0.06)  # the middle of a stretch
    assert choice.v_hi - choice.v_lo == pytest.approx(1.9, abs=0.11)  # never across a hop
    assert choose_lock_point(pts, F0 + 5000e-6) is None  # never reached


def test_choose_lock_point_negative_slope_and_gaps() -> None:
    pts = _points(-500.0, 0, 0)
    pts[10] = SweepPoint(1.0, None, None, 0)  # a missing reading splits the stretch
    choice = choose_lock_point(pts, F0 - 2000e-6)  # at 4.0 V
    assert choice is not None and choice.volts == pytest.approx(4.0, abs=0.01)
    assert choice.mhz_per_v == pytest.approx(-500.0, rel=0.02)
    assert choice.v_lo == pytest.approx(1.1)


def _wait(eng: Engine, until: Any, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end and not until(eng.snapshot()):
        time.sleep(0.05)


def test_auto_lock_on_simulated_laser_with_hops() -> None:
    laser = SimLaser(f0_thz=F0, mhz_per_v=300.0, noise_mhz=0.3, walk_mhz_per_rt_s=0.3, sine_mhz=0.0, seed=4,
                     hop_every_v=1.5, hop_mhz=400.0)
    wm, out = SimWavemeter(laser, period=0.02), SimDG1022(laser, volts=2.0)
    eng = Engine(wm, out, LockSettings())
    target = F0 + (300 * 4.0 - 400 * 2) * 1e-6  # crossed at 4.0 V (the 3.0-4.5 V stretch) and elsewhere
    eng.start()
    try:
        eng.sweep(2.5, 5.5, 0.1, 0.05, 0.1, lock_thz=target)
        _wait(eng, lambda s: s.mode in ("locked", "idle", "fault") and not s.message.startswith("sweep"), 40)
        snap = eng.snapshot()
        assert snap.mode == "locked", snap.message
        points, choice = eng.sweep_data()
        assert len(points) == 31 and choice is not None
        s = eng.settings()
        assert s.setpoint_thz == target and s.sign == 1
        assert 3.0 <= s.v_min < s.v_max <= 4.5  # kept inside the hop-free stretch
        time.sleep(3)
        snap = eng.snapshot()
        assert snap.error_mhz is not None and abs(snap.error_mhz) < 5, snap
        assert out.get() == pytest.approx(4.0, abs=0.05)
    finally:
        eng.stop()


def test_sweep_refuses_with_output_off_and_returns_after_plain_sweep() -> None:
    laser = SimLaser(f0_thz=F0, seed=5, output=False)
    out = SimDG1022(laser, volts=1.0)
    eng = Engine(SimWavemeter(laser, period=0.02), out, LockSettings())
    eng.start()
    try:
        eng.sweep(0.0, 1.0, 0.1, 0.0, 0.05)
        _wait(eng, lambda s: "output is off" in s.message, 5)
        assert "output is off" in eng.snapshot().message
        assert out.writes == 0  # nothing was written
        laser.output = True
        eng.sweep(1.0, 1.5, 0.1, 0.0, 0.05)
        _wait(eng, lambda s: s.message.startswith("sweep done"), 15)
        assert eng.snapshot().mode == "idle"
        assert out.get() == pytest.approx(1.0)  # back where it was
        assert len(eng.sweep_data()[0]) == 6
    finally:
        eng.stop()


def test_sweep_point_takes_the_largest_group() -> None:
    from laserlock.engine import sweep_point

    p = sweep_point(1.0, [F0, F0 + 1e-6, F0 - 11e-3, F0 - 11e-3 + 2e-6])  # two far groups of 2: median in neither
    assert p.thz is not None and p.n == 2
    p = sweep_point(1.0, [F0, F0 + 2e-6, F0 + 1e-6, F0 + 19.7e-3])
    assert p.thz == pytest.approx(F0 + 1e-6) and p.n == 3


def test_presets_and_hiding_plots(tmp_path: Any) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from laserlock.gui import MainWindow, preset_label, preset_thz

    assert preset_thz({"nm": 1083.33064456}) == pytest.approx(299792.458 / 1083.33064456)
    assert "THz" in preset_label({"thz": 276.767676767677}) and "nm" in preset_label({"thz": 276.767676767677})
    cfg = config.load(tmp_path)  # defaults only
    assert cfg["lock"]["setpoint_thz"] == pytest.approx(276.767676767677)
    app = QApplication.instance() or QApplication([])
    laser = SimLaser(f0_thz=F0, seed=6)
    eng = Engine(SimWavemeter(laser), SimDG1022(laser), config.lock_settings(cfg))
    win = MainWindow(eng, cfg["calibration"], lambda s, c: None, presets=cfg["presets"], ui={"show_sweep": False})
    win.show()
    app.processEvents()
    assert win.preset_box.count() == 2 and win.preset_box.currentIndex() == 0  # the default setpoint is preset 1
    assert win.set_thz.value() == pytest.approx(276.767676768, abs=1e-9)
    win._preset_chosen(1)
    assert win.set_nm.value() == pytest.approx(1083.33064456, abs=1e-8)
    assert eng.settings().setpoint_thz == pytest.approx(299792.458 / 1083.33064456, abs=1e-9)
    win.set_thz.setValue(276.5)
    assert win.preset_box.currentIndex() == -1
    win._add_preset()
    assert win.preset_box.count() == 3 and win.preset_box.currentIndex() == 2
    win._remove_preset()
    assert len(win.presets()) == 2
    assert not win.sweep_panel.isVisible() and win.time_panel.isVisible()
    win.show_plots.setChecked(False)
    assert not win.right.isVisible()
    win.show_sweep.setChecked(True)
    assert win.right.isVisible() and win.sweep_panel.isVisible()
    state = win.ui_state()
    assert state["show_plots"] is False and state["show_sweep"] is True
    win.close()


def test_history_keeps_newest_in_order() -> None:
    from laserlock.engine import Sample
    from laserlock.gui import History

    h = History(cap=10)
    for start in range(0, 37, 3):  # batches of 3
        h.add([Sample(float(i), 276.0 + i, None, 0.1 * i, i % 2 == 0) for i in range(start, start + 3)], 0.0)
    t, thz, volts, locked = h.since(-1.0)
    assert list(t) == sorted(t) and t[-1] == 38.0 and h.n <= 10
    assert thz[-1] == 276.0 + 38 and locked[-1] and not locked[-2]
    t2, *_ = h.since(36.0)
    assert list(t2) == [36.0, 37.0, 38.0]
    h.add([Sample(100.0 + i, 1.0, None, 0.0, False) for i in range(25)], 0.0)  # more than cap at once
    assert h.n == 10 and h.t[h.n - 1] == 124.0


# ---------------------------------------------------------------- mode hops

from laserlock.controller import HopDetector  # noqa: E402


def test_hop_detector() -> None:
    import random

    rng = random.Random(7)
    d = HopDetector(min_jump_mhz=1000, confirm=3)
    t = 0.0
    hops = []

    def feed(mhz: float, n: int) -> None:
        nonlocal t
        for _ in range(n):
            t += 0.04
            h = d.update(F0 + (mhz + rng.gauss(0, 150)) * 1e-6, t)  # 150 MHz scatter, like the free laser
            if h:
                hops.append(h)

    feed(0, 200)
    assert not hops  # noise alone
    d.update(F0 + 19.7e-3, t + 0.01)  # one far reading (the WS8's odd ones)
    feed(0, 50)
    d.update(None, t)  # a lost reading is ignored
    feed(0, 1)
    d.update(F0 + 19.7e-3, t + 0.01)
    d.update(F0 + 19.7e-3, t + 0.02)  # two in a row: still not a hop
    feed(0, 50)
    assert not hops
    t_jump = t + 0.04
    feed(15_800, 100)  # a real hop, +15.8 GHz
    feed(0, 100)  # and back
    assert len(hops) == 2
    assert hops[0].t == pytest.approx(t_jump)
    assert hops[0].jump_mhz == pytest.approx(15_800, abs=300)
    assert hops[1].jump_mhz == pytest.approx(-15_800, abs=300)


def test_hop_detector_follows_slow_tuning() -> None:
    d = HopDetector(min_jump_mhz=300, confirm=3)
    for i in range(2000):  # 100 MHz/s ramp, 25 readings/s: 4 MHz per reading, 8 GHz in all
        assert d.update(F0 + i * 4e-6, i * 0.04) is None


def test_engine_records_hops_and_holds_lock() -> None:
    laser = SimLaser(f0_thz=F0, mhz_per_v=300.0, noise_mhz=0.3, walk_mhz_per_rt_s=0.2, sine_mhz=0.0, seed=8)
    wm, out = SimWavemeter(laser, period=0.02), SimDG1022(laser, volts=3.0)
    sign, kp, ki = suggest_gains(300.0, 0.02)
    eng = Engine(wm, out, LockSettings(setpoint_thz=F0 + 900e-6, kp=kp, ki=ki, sign=sign, capture_mhz=500),
                 hops=HopDetector(1000, 3))
    eng.start()
    try:
        eng.engage()
        time.sleep(1.5)
        v_before = out.get()
        laser.extra_mhz = 15_800.0  # the laser hops
        time.sleep(1.0)
        snap = eng.snapshot()
        assert snap.hops == 1 and snap.last_hop is not None
        assert snap.last_hop.locked and snap.last_hop.hop.jump_mhz == pytest.approx(15_800, abs=50)
        # a confirmed hop out of capture: the lock is lost, the output held
        assert snap.mode == "idle" and snap.state == "lost" and snap.lost == 1, snap
        assert snap.message.startswith("LOCK LOST") and "mode hop" in snap.message
        assert out.get() == pytest.approx(v_before, abs=0.02)  # held, didn't chase it
        laser.extra_mhz = 0.0  # back
        time.sleep(1.0)
        assert eng.snapshot().hops == 2
        assert eng.snapshot().mode == "idle"  # stays unlocked until engaged again
        eng.engage()
        time.sleep(0.5)
        assert eng.snapshot().state == "locked"
        assert sum(s.hop for s in eng.drain()) == 2
    finally:
        eng.stop()


def test_sweep_hops_lists_the_jumps_only() -> None:
    from laserlock.engine import sweep_hops

    pts = _points(300.0, 2.0, 600.0)  # hops between 1.9 and 2.0 V, 3.9 and 4.0 V, 5.9 and 6.0 V
    assert sweep_hops(pts) == pytest.approx([1.95, 3.95, 5.95])
    pts[30] = SweepPoint(3.0, None, None, 0)  # a missing reading is a gap, not a hop
    assert sweep_hops(pts) == pytest.approx([1.95, 3.95, 5.95])


def test_window_draws_hops(tmp_path: Any) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from laserlock.gui import MainWindow

    app = QApplication.instance() or QApplication([])
    laser = SimLaser(f0_thz=F0, noise_mhz=0.3, walk_mhz_per_rt_s=0.2, sine_mhz=0.0, seed=9)
    eng = Engine(SimWavemeter(laser, period=0.02), SimDG1022(laser), LockSettings(), hops=HopDetector(1000, 3))
    win = MainWindow(eng, {"step_v": 0.05, "settle_s": 0.5, "average_s": 0.5}, lambda s, c: None)
    eng.start()
    try:
        win.show()

        def pump(sec: float) -> None:
            end = time.monotonic() + sec
            while time.monotonic() < end:
                app.processEvents()
                time.sleep(0.02)

        def shown() -> int:
            return sum(a.isVisible() for a, _ in win._hop_pool)

        win.hop_lines.setChecked(True)
        pump(0.6)
        laser.extra_mhz = 12_000.0
        # The window redraws hops at most once a second, counted from its last redraw, so how long the line
        # takes depends on when the first redraw fell: wait for it, not for a fixed time.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not shown():
            pump(0.05)
        assert "Mode hops: 1" in win.hop_label.text()
        assert shown() == 1  # one line on each time plot
        xs, ys = win.hop_dots.getData()
        assert xs is not None and len(xs) == 1 and ys[0] == pytest.approx(eng.snapshot().volts)
        win.hop_mhz.setValue(20_000)
        assert eng.hops.min_jump_mhz == 20_000
        win.close()
    finally:
        eng.stop()


# ---------------------------------------------------------------- PID, calibration step, wavemeter timing, axes


def test_d_term_opposes_the_rate_and_kd_zero_is_pi() -> None:
    s = LockSettings(setpoint_thz=F0, kp=0.0, ki=0.0, kd=0.01, d_filter_s=0.0, max_step=1.0)
    pid = PILock(s)
    pid.engage(3.0)
    pid.update(F0, 0.0)
    step = pid.update(F0 + 10e-6, 1.0)  # rising 10 MHz/s, sign +1: the D term lowers the output
    assert step.voltage == pytest.approx(3.0 - 0.01 * 10)
    # the setpoint moving gives no kick (D on the measurement)
    s.setpoint_thz = F0 + 100e-6
    step = pid.update(F0 + 10e-6, 2.0)
    assert step.voltage == pytest.approx(3.0)
    pi = PILock(LockSettings(setpoint_thz=F0, kp=0.01, ki=0.0, max_step=1.0))
    pi.engage(3.0)
    pi.update(F0 + 5e-6, 0.0)
    assert pi.update(F0 + 10e-6, 1.0).voltage == pytest.approx(3.0 - 0.1)


def test_d_filter_smooths_the_rate() -> None:
    pid = PILock(LockSettings(setpoint_thz=F0, kd=1.0, d_filter_s=1.0, max_step=10.0, v_max=7.0))
    pid.engage(3.0)
    pid.update(F0, 0.0)
    pid.update(F0 + 10e-6, 1.0)
    assert pid.rate == pytest.approx(10 * 0.5)  # a = dt / (tau + dt) = 0.5


def _calibrate(eng: Engine, step: float) -> str:
    eng.calibrate(step, 0.2, 0.4)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and eng.snapshot().mode == "calibrating":
        time.sleep(0.05)
    return eng.snapshot().message


def test_calibration_with_a_negative_step_and_no_room() -> None:
    laser = SimLaser(f0_thz=F0, mhz_per_v=-200.0, noise_mhz=0.2, walk_mhz_per_rt_s=0.0, sine_mhz=0.0, seed=4)
    out = SimDG1022(laser, volts=7.0)
    eng = Engine(SimWavemeter(laser, period=0.02), out, LockSettings())
    eng.start()
    try:
        msg = _calibrate(eng, 0.05)  # at the top: no room upwards
        assert msg.startswith("calibration: no room"), msg
        msg = _calibrate(eng, -0.05)
        assert msg.startswith("tuning -2"), msg  # about -200 MHz/V
        assert eng.settings().sign == -1
        assert out.get() == pytest.approx(7.0)
    finally:
        eng.stop()


def test_engine_sets_and_reads_wavemeter_timing() -> None:
    laser = SimLaser(f0_thz=F0, seed=5)
    wm = SimWavemeter(laser, period=0.02)
    eng = Engine(wm, SimDG1022(laser), LockSettings())
    eng.start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and eng.snapshot().wavemeter is None:
            time.sleep(0.02)
        assert eng.snapshot().wavemeter is not None
        eng.set_wavemeter(interval_ms=200, interval_on=True)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not (eng.snapshot().wavemeter or wm.timing()).interval_on:
            time.sleep(0.02)
        timing = eng.snapshot().wavemeter
        assert timing is not None and timing.interval_on and timing.interval_ms == 200
        assert wm.period == pytest.approx(0.2)
        eng.set_wavemeter(exposure_ms=50)
        time.sleep(0.3)
        assert not wm.timing().auto and wm.timing().exposure_ms == 50
    finally:
        eng.stop()


def test_window_axes_pause_and_nudge(tmp_path: Any) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from laserlock.gui import MainWindow, TimeAxis

    app = QApplication.instance() or QApplication([])
    laser = SimLaser(f0_thz=F0, seed=6)
    eng = Engine(SimWavemeter(laser), SimDG1022(laser), LockSettings(setpoint_thz=F0 + 1e-3))
    ui = {"span": "30 s", "clock": False, "err_y": {"auto": False, "lo": -20.0, "hi": 30.0}}
    win = MainWindow(eng, {"step_v": -0.05, "settle_s": 0.5, "average_s": 0.5}, lambda s, c: None, ui=ui)
    eng.start()
    try:
        win.show()
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)
        assert win.cal_step.value() == pytest.approx(-0.05)
        lo, hi = win.err_plot.getViewBox().viewRange()[1]
        assert (lo, hi) == (pytest.approx(-20e6), pytest.approx(30e6))
        x0, x1 = win.v_plot.getViewBox().viewRange()[0]
        assert x1 - x0 == pytest.approx(30.0, abs=0.5)
        assert win.wm_interval.isEnabled()  # the sim's timing was read
        win.v_range.auto.setChecked(False)
        win.v_range.hi.setValue(5.0)
        assert win.v_plot.getViewBox().viewRange()[1][1] == pytest.approx(5.0)
        win.pause.setChecked(True)
        frozen = win.v_plot.getViewBox().viewRange()[0]
        end = time.monotonic() + 0.5
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)
        assert win.v_plot.getViewBox().viewRange()[0] == pytest.approx(frozen)
        before = win.set_thz.value()
        win.nudge.setValue(5.0)
        win._nudge(+1)
        assert win.set_thz.value() == pytest.approx(before + 5e-6, abs=1e-9)
        assert eng.settings().setpoint_thz == pytest.approx(before + 5e-6, abs=1e-9)
        state = win.ui_state()
        assert state["span"] == "30 s" and state["clock"] is False and state["v_y"]["hi"] == 5.0
        win._clear()
        assert win._hist.n == 0
        win.close()
    finally:
        eng.stop()
    axis = TimeAxis(3600.0 * 10, 3600.0 * 10 + 5)
    assert axis.tickSpacing(0, 120, 900)[0][0] in (10, 15)
    assert axis.tickStrings([65.0], 1.0, 30)[0] == time.strftime("%H:%M:%S", time.localtime(36065.0))
    axis.set_clock(False)
    assert axis.tickStrings([65.0], 1.0, 30) == ["60"]


def test_hop_needs_to_hold_and_many_hops_reuse_few_lines(tmp_path: Any) -> None:
    det = HopDetector(1000.0, confirm=3, min_hold_s=0.2)
    det.update(F0, 0.0)
    for k in range(5):  # a 60 GHz glitch of 5 readings over 0.1 s, then back
        assert det.update(F0 - 60e-3, 0.01 + 0.025 * k) is None
    assert det.update(F0, 0.2) is None and det.level == pytest.approx(F0, abs=1e-6)
    hop = None
    for k in range(12):  # a jump that holds for 0.3 s
        hop = hop or det.update(F0 - 11.8e-3, 1.0 + 0.025 * k)
    assert hop is not None and hop.t == pytest.approx(1.0)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from laserlock import gui
    from laserlock.controller import Hop
    from laserlock.engine import HopEvent

    app = QApplication.instance() or QApplication([])
    laser = SimLaser(f0_thz=F0, seed=7)
    eng = Engine(SimWavemeter(laser), SimDG1022(laser), LockSettings(setpoint_thz=F0))
    win = gui.MainWindow(eng, {"step_v": 0.05, "settle_s": 0.5, "average_s": 0.5}, lambda s, c: None)
    now = time.time()
    win.hop_lines.setChecked(True)
    for k in range(300):
        eng._hop_events.append(HopEvent(now - 60 + k * 0.2, Hop(0.0, F0, F0 + 0.01), 3.0, False))
    win._draw_hops(300, -math.inf)
    shown = [a for a, _ in win._hop_pool if a.isVisible()]
    assert len(shown) == gui.HOP_LINES_MAX
    assert len(win.hop_dots.getData()[0]) == 300
    win._draw_hops(301, -math.inf)  # within a second: not redrawn
    assert win._hops_drawn[0] == 300
    win.close()
    app.processEvents()


# ---------------------------------------------------------------- find a stable range

from laserlock.engine import stable_stretches  # noqa: E402


def _leg(vs: list[float], f: Any) -> list[SweepPoint]:
    return [SweepPoint(v, f(v), 1.0, 5, 5) for v in vs]


def test_stable_stretches_need_both_directions() -> None:
    vs = [round(0.1 * i, 4) for i in range(71)]

    def up(v: float) -> float:  # 100 MHz/V; hops of -800 MHz at 2.0 V and 5.0 V going up
        return F0 + (100 * v - 800 * ((v >= 2.0) + (v >= 5.0))) * 1e-6

    def down(v: float) -> float:  # coming down the hops come lower (hysteresis): 1.6 V and 4.6 V
        return F0 + (100 * v - 800 * ((v >= 1.6) + (v >= 4.6))) * 1e-6

    target = F0 + 150e-6  # in mode 0 near 1.5 V, mode 1 near 9.5 V (not reached), mode 2 not
    st = stable_stretches(_leg(vs, up), _leg(vs[::-1], down), target)
    spans = sorted((s.v_lo, s.v_hi) for s in st)
    # 1.6-1.9 and 4.6-4.9 differ between the directions: not stable
    assert spans == [(0.0, 1.5), (2.0, 4.5), (5.0, 7.0)]
    first = next(s for s in st if s.v_lo == 0.0)
    assert first.target_v == pytest.approx(1.5) and first.room_v == pytest.approx(0.0)
    assert all(s.mhz_per_v == pytest.approx(100.0) for s in st)
    mid = next(s for s in st if s.v_lo == 2.0)
    assert mid.target_v is None and mid.shift_mhz == pytest.approx(150 - (100 * 3.25 - 800))
    # a point with two modes in its readings breaks a stretch
    noisy = _leg(vs, up)
    noisy[30] = SweepPoint(3.0, up(3.0), 1.0, 3, 5)
    spans = sorted((s.v_lo, s.v_hi) for s in stable_stretches(noisy, _leg(vs[::-1], down), target))
    assert (2.0, 2.9) in spans and (3.1, 4.5) in spans


def _run_scan(eng: Engine, target: float, margin: float = 0.3, hold: float = 0.5) -> str:
    eng.find_stable(0.0, 7.0, 0.25, 0.0, 0.1, target, margin, hold)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and eng.snapshot().mode == "sweeping":
        time.sleep(0.05)
    return eng.snapshot().message


def test_find_stable_locks_inside_a_stretch_or_proposes() -> None:
    laser = SimLaser(f0_thz=F0, mhz_per_v=300.0, noise_mhz=0.2, walk_mhz_per_rt_s=0.0, sine_mhz=0.0, seed=8,
                     hop_every_v=2.0, hop_mhz=1500.0)
    out = SimDG1022(laser, min_interval=0.01, volts=1.0)
    eng = Engine(SimWavemeter(laser, period=0.01), out, LockSettings())
    eng.start()
    try:
        far = F0 + 5000e-6  # never reached (the laser spans f0 ... f0 + 600 MHz)
        msg = _run_scan(eng, far)
        assert msg.startswith("find stable range: the setpoint isn't in a stable stretch"), msg
        assert eng.snapshot().mode == "idle" and out.get() == pytest.approx(1.0)
        _, scan = eng.scan_data()
        assert scan is not None and len(scan.stretches) == 4
        assert all(abs(s.mhz_per_v - 300) < 20 for s in scan.stretches)
        target = F0 + 300e-6  # crossed at 1 V only
        msg = _run_scan(eng, target)
        assert msg.startswith("find stable range: locked"), msg
        snap = eng.snapshot()
        assert snap.mode == "locked"
        s = eng.settings()
        assert s.setpoint_thz == pytest.approx(target) and s.v_max - s.v_min < 2.0
        assert s.v_min <= out.get() <= s.v_max
        eng.release()
        # lock at a chosen stretch: its centre's frequency becomes the setpoint
        _, scan = eng.scan_data()
        assert scan is not None
        st = max(scan.stretches, key=lambda x: x.v_lo)
        eng.lock_stretch(st)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and eng.snapshot().mode == "sweeping":
            time.sleep(0.05)
        assert eng.snapshot().mode == "locked", eng.snapshot().message
        assert eng.settings().setpoint_thz == pytest.approx(st.f_at((st.v_lo + st.v_hi) / 2), abs=20e-6)
    finally:
        eng.stop()


def test_window_lists_stretches(tmp_path: Any) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from laserlock.engine import ScanRequest, ScanResult

    from laserlock.gui import MainWindow

    app = QApplication.instance() or QApplication([])
    laser = SimLaser(f0_thz=F0, seed=10)
    eng = Engine(SimWavemeter(laser), SimDG1022(laser), LockSettings(setpoint_thz=F0))
    win = MainWindow(eng, {"step_v": 0.05, "settle_s": 0.5, "average_s": 0.5}, lambda s, c: None)
    vs = [round(0.1 * i, 4) for i in range(71)]

    def f(v: float) -> float:
        return F0 + (100 * v - 800 * (v >= 3.0)) * 1e-6

    up, down = _leg(vs, f), _leg(vs[::-1], f)
    stretches = stable_stretches(up, down, F0 + 2000e-6)
    with eng._lock:
        eng._scan = ScanResult(ScanRequest(0, 7, 0.1, 0, 0.1, F0, 0.3, 1), up, down, stretches, None, "")
        eng._scan_seq += 1
    win._refresh()
    assert win.scan_table.rowCount() == 2
    assert win.scan_table.item(0, 1).text().startswith("shift ")
    assert len(win._stretch_regions) == 2
    win.scan_table.selectRow(0)
    assert win.stretch_btn.isEnabled()
    win.close()
    app.processEvents()



def test_lock_lost_after_time_out_of_capture_and_relock() -> None:
    from laserlock.engine import ScanRequest

    laser = SimLaser(f0_thz=F0, mhz_per_v=300.0, noise_mhz=0.2, walk_mhz_per_rt_s=0.0, sine_mhz=0.0, seed=11,
                     hop_every_v=2.0, hop_mhz=1500.0)
    out = SimDG1022(laser, min_interval=0.01, volts=1.0)
    sign, kp, ki = suggest_gains(300.0, 0.01)
    target = F0 + 300e-6  # crossed at 1 V only (each 2 V stretch spans 0 ... +600 MHz minus 1.5 GHz per hop)
    eng = Engine(SimWavemeter(laser, period=0.01), out,
                 LockSettings(setpoint_thz=target, kp=kp, ki=ki, sign=sign, capture_mhz=500, lost_after_s=0.5),
                 hops=HopDetector(1000, 3))
    eng.start()
    try:
        eng.engage()
        time.sleep(1.0)
        assert eng.snapshot().state == "locked"
        laser.extra_mhz = 700.0  # out of capture but under the hop threshold: lost after 0.5 s
        time.sleep(0.3)
        assert eng.snapshot().mode == "locked"  # not yet
        time.sleep(0.6)
        snap = eng.snapshot()
        assert snap.state == "lost" and "out of capture" in snap.message, snap
        # with relock on, a loss scans and locks again
        laser.extra_mhz = 0.0
        eng.set_relock(ScanRequest(0.0, 7.0, 0.25, 0.0, 0.1, 0.0, 0.3, 0.3))
        eng.engage()
        time.sleep(0.8)
        laser.extra_mhz = 700.0
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and eng.snapshot().lost < 2:
            time.sleep(0.005)
        laser.extra_mhz = 0.0  # the hardware is back as the scan starts
        assert eng.snapshot().mode == "sweeping", eng.snapshot().message
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and eng.snapshot().mode == "sweeping":
            time.sleep(0.05)
        snap = eng.snapshot()
        assert snap.mode == "locked" and snap.lost == 2, snap
        assert snap.message.startswith("find stable range: locked")
    finally:
        eng.stop()


def test_window_combined_plot_and_lost_label(tmp_path: Any) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from laserlock.gui import MainWindow

    app = QApplication.instance() or QApplication([])
    laser = SimLaser(f0_thz=F0, seed=12)
    eng = Engine(SimWavemeter(laser), SimDG1022(laser), LockSettings(setpoint_thz=F0 + 1e-3))
    win = MainWindow(eng, {"step_v": 0.05, "settle_s": 0.5, "average_s": 0.5}, lambda s, c: None,
                     ui={"combined": True, "line_width": 2.0})
    eng.start()
    try:
        win.show()
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)
        assert win.comb_widget.isVisible() and not win.sep_widget.isVisible()
        assert win.c_v.getData()[0] is not None and len(win.c_v.getData()[0]) > 5
        assert win.c_v.opts["pen"].widthF() == 2.0
        win.v_range.auto.setChecked(False)
        win.v_range.hi.setValue(5.0)
        assert win.comb_vb.viewRange()[1][1] == pytest.approx(5.0)
        with eng._lock:
            eng._mode, eng._state, eng._message = "idle", "lost", "LOCK LOST at 12:00:00: test"
        win._refresh()
        assert win.mode_label.text() == "LOCK LOST"
        win.layout_kind.setCurrentIndex(0)
        assert win.sep_widget.isVisible() and not win.comb_widget.isVisible()
        state = win.ui_state()
        assert state["combined"] is False and state["line_width"] == 2.0 and state["hop_lines"] is False
        win.close()
    finally:
        eng.stop()


def test_number_boxes_step_the_digit_at_the_cursor_and_ignore_the_wheel() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QApplication

    from laserlock import gui

    app = QApplication.instance() or QApplication([])
    box = gui.spin(0.0, 2000.0, 9, 1e-6, 276.767676768, " THz")
    box.show()
    box.setFocus()
    app.processEvents()
    le = box.lineEdit()
    assert le.text() == "276.767676768 THz"
    le.setCursorPosition(len("276.76"))  # just right of the 2nd decimal: steps 0.01
    box.stepBy(1)
    assert box.value() == pytest.approx(276.777676768)
    assert le.cursorPosition() == len("276.77")
    le.setCursorPosition(len("276"))  # at the point: the units digit
    box.stepBy(-1)
    assert box.value() == pytest.approx(275.777676768)
    box.setValue(99.5)
    le.setCursorPosition(len("99"))  # 99.5 -> 100.5: the cursor stays left of the point
    box.stepBy(1)
    assert box.value() == pytest.approx(100.5) and le.cursorPosition() == len("100")
    ints = gui.IntSpin()
    ints.setRange(1, 9999)
    ints.setValue(250)
    ints.show()
    ints.setFocus()
    app.processEvents()
    ints.lineEdit().setCursorPosition(2)  # the tens
    ints.stepBy(1)
    assert ints.value() == 260
    before = box.value()
    wheel = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(box, wheel)
    assert box.value() == before and not wheel.isAccepted()
    combo = gui.Combo()
    combo.addItems(["a", "b", "c"])
    app.sendEvent(combo, wheel)
    assert combo.currentIndex() == 0
    for w in (box, ints, combo):
        w.close()


def test_error_axis_follows_the_newest_readings_after_a_hop() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import numpy as np
    from PyQt6.QtWidgets import QApplication

    from laserlock import gui

    app = QApplication.instance() or QApplication([])
    laser = SimLaser(f0_thz=F0, seed=13)
    eng = Engine(SimWavemeter(laser), SimDG1022(laser), LockSettings(setpoint_thz=F0))
    win = gui.MainWindow(eng, {"step_v": 0.05, "settle_s": 0.5, "average_s": 0.5}, lambda s, c: None)
    win.show()
    app.processEvents()
    now = time.time() - win._t0
    t = np.arange(now - 60, now, 0.1)
    err = np.where(t < now - 30, -12e9, np.sin(t) * 5e6)  # a hop 30 s ago, then +-5 MHz
    win.err_range.fit(err[t >= now - gui.FOLLOW_S])
    lo, hi = win.err_plot.getViewBox().viewRange()[1]
    assert -7e6 < lo < -5e6 and 5e6 < hi < 7e6
    win.close()
    app.processEvents()



def test_range_presets(tmp_path: Any) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from laserlock.gui import MainWindow

    app = QApplication.instance() or QApplication([])
    laser = SimLaser(f0_thz=F0, seed=14)
    eng = Engine(SimWavemeter(laser), SimDG1022(laser), LockSettings(setpoint_thz=F0))
    win = MainWindow(eng, {"step_v": 0.05, "settle_s": 0.5, "average_s": 0.5}, lambda s, c: None)
    win.show()
    app.processEvents()
    labels = [b.text() for b in win.err_range.preset_buttons]
    assert labels == ["±1", "±10", "±100", "±1000"]
    win.err_range.preset_buttons[2].click()
    assert not win.err_range.auto.isChecked()
    assert win.err_plot.getViewBox().viewRange()[1] == [pytest.approx(-100e6), pytest.approx(100e6)]
    win.v_range.preset_buttons[0].click()
    assert win.v_plot.getViewBox().viewRange()[1] == [pytest.approx(0.0), pytest.approx(7.0)]
    win.err_range.auto.setChecked(True)
    assert win.err_range.auto.isChecked()
    win.close()
    app.processEvents()


# ---------------------------------------------------------------- whose voltage, the step per write, the hold's readings


class StepSource:
    """A wavemeter whose every read is a new measurement (`fresh` off: it repeats the last one)."""

    def __init__(self, thz: float | None = F0 - 100e-6) -> None:
        self.thz, self.status, self.fresh, self.seq = thz, "low signal", True, 0
        self._reading = Reading(time.monotonic(), None, "no value", 0)

    def read(self) -> Reading:
        if self.fresh:
            self.seq += 1
            self._reading = Reading(time.monotonic(), self.thz, "ok" if self.thz is not None else self.status, self.seq)
        return self._reading

    def describe(self) -> str:
        return "step source"

    def close(self) -> None:
        pass


class FakeOut:
    """An output that takes every command at once and keeps `digits` decimals, as the DG1022 keeps 4."""

    min_interval = 0.1

    def __init__(self, volts: float = 3.0, digits: int = 4) -> None:
        self.volts, self.digits = volts, digits
        self.writes: list[float] = []
        self.on_set: Any = None  # called while the device takes a command

    def get(self) -> float:
        return self.volts

    def set(self, volts: float) -> float:
        if self.on_set is not None:
            self.on_set()
        self.volts = round(min(max(volts, 0.0), HARD_V_MAX), self.digits)
        self.writes.append(self.volts)
        return self.volts

    def readback(self) -> float:
        return self.volts

    def output_on(self) -> bool:
        return True

    def describe(self) -> str:
        return "fake output"

    def close(self) -> None:
        pass


NOT_YET = 1e12  # as `Engine._last_cmd`: the output's turn never comes (0.0: it has come)


def _fake_engine(lock: bool = True, **settings: Any) -> tuple[Engine, StepSource, FakeOut]:
    """An engine on fakes, its loop thread not started: the test calls `_tick` and `_flush_output` itself.
    The source reads 100 MHz low, so a locked engine wants more voltage than `max_step` gives at once."""
    src, out = StepSource(), FakeOut()
    values: dict[str, Any] = {"setpoint_thz": F0, "kp": 0.001, "ki": 0.1, "v_min": 0, "v_max": 7, "max_step": 0.01}
    eng = Engine(src, out, LockSettings(**{**values, **settings}))
    if lock:
        eng.engage()
    return eng, src, out


def test_release_withdraws_the_correction_waiting_for_the_outputs_turn() -> None:
    eng, src, out = _fake_engine()
    eng._last_cmd = NOT_YET
    eng._tick()
    eng._flush_output()
    assert eng._target == pytest.approx(3.01) and out.writes == []  # a correction waits for its turn
    eng.release()
    eng._last_cmd = 0.0  # its turn comes, after Release
    eng._tick()
    eng._flush_output()
    snap = eng.snapshot()
    assert out.writes == [] and (snap.mode, snap.volts) == ("idle", 3.0)
    assert snap.message == "lock released, holding 3.0000 V"
    # a manual voltage after Release is still written
    eng.set_voltage(3.2)
    eng._flush_output()
    assert out.writes == [3.2]
    # and a new lock starts from the voltage applied
    eng._last_cmd = NOT_YET
    eng.engage()
    eng._tick()
    eng._flush_output()
    assert out.writes == [3.2]
    eng._last_cmd = 0.0
    eng._flush_output()
    assert out.writes == [3.2, pytest.approx(3.21)]


def test_a_lost_lock_and_a_fault_withdraw_the_waiting_correction() -> None:
    eng, src, out = _fake_engine(capture_mhz=500, lost_after_s=0.0)
    eng._last_cmd = NOT_YET
    eng._tick()
    assert eng._target is not None
    src.thz = F0 + 2000e-6  # out of capture: lost at once (lost_after_s = 0)
    eng._tick()
    assert eng.snapshot().state == "lost" and eng._target is None
    eng._last_cmd = 0.0
    eng._flush_output()
    assert out.writes == []

    eng, src, out = _fake_engine()
    eng._last_cmd = NOT_YET
    eng._tick()
    with eng._lock:
        eng._enter("fault")
    eng._last_cmd = 0.0
    eng._flush_output()
    assert out.writes == []


@pytest.mark.parametrize("start", ["engage", "sweep", "find_stable", "calibrate"])
def test_a_manual_voltage_not_yet_written_is_dropped_when_the_mode_changes(start: str) -> None:
    eng, src, out = _fake_engine(lock=False)
    eng._last_cmd = NOT_YET
    eng.set_voltage(4.0)
    eng._flush_output()
    assert eng._target == 4.0 and out.writes == []
    if start == "engage":
        eng.engage()
    elif start == "sweep":
        eng.sweep(3.0, 3.1, 0.05, 0.0, 0.01)
    elif start == "find_stable":
        eng.find_stable(3.0, 3.2, 0.05, 0.0, 0.01, F0)
    else:
        eng.calibrate(0.05, 0.0, 0.01)
    assert eng.snapshot().mode != "idle" and eng._target is None  # nothing left to write after the sweep either
    eng._last_cmd = 0.0
    eng._flush_output()
    assert out.writes == []


def test_release_or_lock_while_a_command_is_on_its_way() -> None:
    # Release lands while the DG1022 is taking the correction: it is applied, and the window says what is held
    eng, src, out = _fake_engine()
    out.on_set = eng.release
    eng._tick()
    eng._flush_output()
    snap = eng.snapshot()
    assert out.writes == [pytest.approx(3.01)] and (snap.mode, snap.volts) == ("idle", out.volts)
    assert snap.message == "lock released, holding 3.0100 V"
    out.on_set = None
    eng._last_cmd = 0.0
    eng._tick()
    eng._flush_output()
    assert len(out.writes) == 1  # and nothing follows it
    # Lock lands while a manual voltage is on its way: the lock starts from that voltage
    eng, src, out = _fake_engine(lock=False)
    out.on_set = eng.engage
    eng.set_voltage(3.5)
    eng._flush_output()
    assert eng.snapshot().mode == "locked" and eng.pi.voltage == eng.pi.integral == 3.5
    out.on_set = None
    eng._last_cmd = 0.0
    eng._tick()
    eng._flush_output()
    assert out.writes == [3.5, pytest.approx(3.51)]


def test_a_correction_never_waits_inside_the_dg1022(dg: tuple[DG1022, FakeVisa]) -> None:
    d, fake = dg

    def offsets() -> list[str]:
        return [c for _, c in fake.log if c.startswith("VOLT:OFFS ")]

    eng = Engine(StepSource(), d, LockSettings(setpoint_thz=F0, kp=0.001, ki=0.1, max_step=0.01))
    eng.engage()
    assert eng._output_on()  # a query has just taken the DG1022's turn
    eng._tick()
    began = time.monotonic()
    eng._flush_output()
    assert time.monotonic() - began < d.min_interval / 2  # it came back at once: no command waits in the device
    assert eng._target is not None and offsets() == []
    eng.release()
    time.sleep(d.min_interval + 0.02)  # the turn comes
    eng._tick()
    eng._flush_output()
    assert offsets() == []  # nothing of the released lock is written
    eng.engage()  # control: a lock's correction is written when the turn has come
    eng._tick()
    eng._flush_output()
    assert offsets() == ["VOLT:OFFS 0.0100"]


def test_pi_measures_the_step_from_the_voltage_applied() -> None:
    pi = PILock(LockSettings(setpoint_thz=F0, kp=0.0, ki=1.0, sign=1, v_min=0, v_max=7, max_step=0.01))
    pi.engage(3.0)
    # far low for 20 readings, and nothing was written between them: still one step from the 3 V applied
    vs = [pi.update(F0 - 100e-6, t * 0.1, 3.0).voltage for t in range(20)]
    assert max(vs) == pytest.approx(3.01) and vs[-1] == pytest.approx(3.01)
    assert pi.update(F0 + 1e-6, 2.1, 3.0).voltage < 3.01  # no windup: the first opposite error turns it back
    assert pi.update(None, 2.2, 3.0).voltage == 3.0  # a hold stays at the voltage applied
    assert pi.update(F0 + 1.0, 2.3, 3.0).voltage == 3.0


def test_ten_readings_before_one_write_move_the_output_one_step() -> None:
    eng, src, out = _fake_engine(kp=0.0, ki=1.0)
    eng._last_cmd = NOT_YET
    for _ in range(10):  # the wavemeter measures while the DG1022's turn hasn't come
        time.sleep(0.002)
        eng._tick()
        eng._flush_output()
    assert out.writes == []
    eng._last_cmd = 0.0
    eng._flush_output()
    assert out.writes == [pytest.approx(3.01)]  # one max_step, not ten
    src.thz = F0 + 1e-6  # the integrator didn't wind up meanwhile: the first opposite error turns it back
    time.sleep(0.002)
    eng._tick()
    assert eng._target is not None and eng._target < 3.01


@pytest.mark.parametrize("digits", [4, 3])
def test_every_write_stays_within_max_step_of_the_last(digits: int) -> None:
    """A source faster than the output, integral action, an error that changes sign, long waits for the
    output's turn, a device that rounds (to 1 mV with digits = 3) and that is slow enough to miss readings."""
    eng, src, out = _fake_engine(kp=0.0005, ki=2.0)
    out.digits = digits
    out.on_set = lambda: [src.read() for _ in range(3)]  # readings come and go while it takes the command
    steps: list[float] = []
    for i in range(600):
        src.thz = F0 + 90e-6 * math.sin(i / 40)
        time.sleep(0.0005)
        eng._tick()
        waiting = i % 4 != 0 or 200 <= i < 260  # one turn per four readings, and none at all for a while
        eng._last_cmd = NOT_YET if waiting else 0.0
        before = out.volts
        eng._flush_output()
        if out.volts != before:
            steps.append(out.volts - before)
    assert len(steps) > 50 and min(steps) < 0 < max(steps)  # it moved, both ways
    assert max(abs(x) for x in steps) <= 0.01 + 1e-9, max(abs(x) for x in steps)
    assert all(0.0 <= v <= HARD_V_MAX for v in out.writes)


def test_a_stable_range_hold_needs_new_valid_readings(monkeypatch: pytest.MonkeyPatch) -> None:
    from laserlock import engine

    monkeypatch.setattr(engine, "HOLD_GAP_S", 0.15)
    monkeypatch.setattr(engine, "HOLD_CHUNK_S", 0.05)
    eng, src, out = _fake_engine(lock=False)
    src.thz = F0
    assert eng._hold_test(0.4, F0, 100.0) is None  # new readings all through, all in range: stable
    src.thz = None  # the signal disappears
    why = eng._hold_test(0.4, F0, 100.0)
    assert why is not None and why.startswith("no new valid reading") and "low signal" in why
    src.thz = F0
    eng._tick()
    src.fresh = False  # the wavemeter repeats its last value
    why = eng._hold_test(0.4, F0, 100.0)
    assert why is not None and why.startswith("no new valid reading") and "repeated its last value" in why
    src.fresh = True
    monkeypatch.setattr(eng, "_collect", lambda seconds: [])  # nothing at all is collected
    why = eng._hold_test(0.4, F0, 100.0)
    assert why is not None and why.startswith("no new valid reading")
    monkeypatch.undo()
    # readings that are out of range still fail it, and an abort is an abort
    src.thz = F0 + 500e-6
    assert "left ±100 MHz" in (eng._hold_test(0.4, F0, 100.0) or "")
    eng._abort.set()
    assert eng._hold_test(0.4, F0, 100.0) == "aborted"


def test_a_hold_fails_when_the_signal_is_lost_for_too_long_even_if_it_comes_back(monkeypatch: pytest.MonkeyPatch) -> None:
    from laserlock import engine

    monkeypatch.setattr(engine, "HOLD_CHUNK_S", 0.05)

    class Dropout(StepSource):
        """No signal from `lost[0]` to `lost[1]` seconds after `began`."""

        began, lost = 0.0, (0.0, 0.0)

        def read(self) -> Reading:
            since = time.monotonic() - self.began
            self.thz = None if self.lost[0] <= since < self.lost[1] else F0
            return super().read()

    src, out = Dropout(), FakeOut()
    eng = Engine(src, out, LockSettings())
    monkeypatch.setattr(engine, "HOLD_GAP_S", 0.2)
    src.began, src.lost = time.monotonic(), (0.1, 0.6)  # lost for 0.5 s, back for the last 0.4 s of the hold
    why = eng._hold_test(1.0, F0, 100.0)
    assert why is not None and why.startswith("no new valid reading")
    monkeypatch.setattr(engine, "HOLD_GAP_S", 2.0)
    src.began, src.lost = time.monotonic(), (0.1, 0.2)  # a dropout shorter than the limit is not a lost signal
    assert eng._hold_test(0.6, F0, 100.0) is None


def test_a_hold_with_too_few_readings_fails() -> None:
    class Slow(StepSource):
        """A new measurement every 0.4 s."""

        due = 0.0

        def read(self) -> Reading:
            self.fresh = time.monotonic() >= self.due
            if self.fresh:
                self.due = time.monotonic() + 0.4
            return super().read()

    src = Slow(F0)
    eng = Engine(src, FakeOut(), LockSettings())
    why = eng._hold_test(0.5, F0, 100.0)  # one or two readings in the hold: no gap over the limit, but too few
    assert why is not None and why.startswith("only ") and "at least 3 needed" in why


def test_find_stable_doesnt_lock_when_the_signal_goes_after_the_scan() -> None:
    class Wavemeter(SimWavemeter):
        lost = False

        def read(self) -> Reading:
            r = super().read()
            return Reading(r.t, None, "low signal", r.seq) if self.lost else r

    laser = SimLaser(f0_thz=F0, mhz_per_v=300.0, noise_mhz=0.2, walk_mhz_per_rt_s=0.0, sine_mhz=0.0, seed=15,
                     hop_every_v=2.0, hop_mhz=1500.0)
    out = SimDG1022(laser, min_interval=0.01, volts=1.5)
    wm = Wavemeter(laser, period=0.01)
    eng = Engine(wm, out, LockSettings())
    eng.start()
    try:
        eng.find_stable(0.0, 7.0, 0.25, 0.0, 0.1, F0 + 300e-6, 0.3, 4.0)  # the target is crossed at 1 V
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and "holding" not in eng.snapshot().message:
            time.sleep(0.01)
        assert "holding" in eng.snapshot().message
        wm.lost = True  # the scan was fine; the signal goes during the hold
        while time.monotonic() < deadline and eng.snapshot().mode == "sweeping":
            time.sleep(0.05)
        snap = eng.snapshot()
        assert snap.mode == "idle", snap
        assert snap.message.startswith("find stable range: not locked, no new valid reading"), snap.message
        assert "low signal" in snap.message
        assert out.get() == pytest.approx(1.5)  # back where it started, unlocked
        _, scan = eng.scan_data()
        assert scan is not None and scan.message == snap.message
    finally:
        eng.stop()
