"""The lock's PID loop, free of hardware and Qt.

The error is the measured frequency minus the setpoint, in MHz. `sign` is the sign of df/dV (+1: more voltage
raises the frequency), so the correction is -sign * (kp * error + ki * integral + kd * d(frequency)/dt). The
output is the integrator plus the P and D terms, so engaging starts from the voltage already applied (no jump).

The D term acts on the measured frequency, not on the error, so a changed setpoint gives no kick; its rate is
low-pass filtered (time constant `d_filter_s`), since the wavemeter's noise differentiates badly. kd = 0 (the
default) is a PI lock.

Safety, per update:
- the output stays within [v_min, v_max] and moves at most `max_step` from the last output. The last output
  is the voltage applied, which the caller passes when it doesn't write every step (the engine writes at
  most every 100 ms and the wavemeter can be faster): the limit then bounds each write, not each reading;
- when either limit cuts the output, the integrator is set to what was applied minus the P term
  (back-calculation), so it never winds up beyond what the output can do;
- no reading, or an error beyond `capture_mhz` (a mode hop, a wrong wavelength): hold the voltage, don't
  integrate.
"""

from __future__ import annotations

from dataclasses import dataclass

C_NM_THZ = 299_792.458  # c in nm·THz: λ(nm) = C_NM_THZ / f(THz)


def thz_to_nm(thz: float) -> float:
    return C_NM_THZ / thz


def nm_to_thz(nm: float) -> float:
    return C_NM_THZ / nm


@dataclass
class LockSettings:
    setpoint_thz: float = 0.0
    kp: float = 0.0  # V per MHz
    ki: float = 0.0  # V per MHz per s
    sign: int = 1  # sign of df/dV
    v_min: float = 0.0
    v_max: float = 7.0
    max_step: float = 0.01  # V per update
    capture_mhz: float = 1000.0  # |error| beyond this: hold
    max_dt: float = 1.0  # s: a longer gap between readings integrates as this
    kd: float = 0.0  # V per (MHz/s)
    d_filter_s: float = 0.5  # s: the D term's low-pass time constant
    lost_after_s: float = 2.0  # s out of capture (or a confirmed hop out of it) and the lock counts as lost


@dataclass
class Step:
    voltage: float
    error_mhz: float | None
    state: str  # "locked", "limited", "no reading", "out of capture"


class PILock:
    def __init__(self, settings: LockSettings) -> None:
        self.s = settings
        self.integral = 0.0  # V, the integrator's share of the output
        self.voltage = 0.0
        self.last_t: float | None = None
        self.last_thz: float | None = None
        self.rate = 0.0  # MHz/s, filtered
        self.d_term = 0.0  # V

    def engage(self, voltage_now: float) -> None:
        """Start from the voltage already applied."""
        self.voltage = self.integral = min(max(voltage_now, self.s.v_min), self.s.v_max)
        self.last_t = self.last_thz = None
        self.rate = self.d_term = 0.0

    def update(self, thz: float | None, t: float, applied: float | None = None) -> Step:
        """One step. `applied` is the voltage on the output now, when that isn't the last step's (None: every
        step was written). The step limit is measured from it and a hold stays at it, so steps that were
        never written don't add up into one large move."""
        s = self.s
        if applied is not None:
            self.voltage = applied
        if thz is None:
            self.last_t = self.last_thz = None
            return Step(self.voltage, None, "no reading")
        err = (thz - s.setpoint_thz) * 1e6
        if abs(err) > s.capture_mhz:
            self.last_t = self.last_thz = None
            return Step(self.voltage, err, "out of capture")
        raw_dt = 0.0 if self.last_t is None else max(t - self.last_t, 0.0)
        dt = min(raw_dt, s.max_dt)
        if self.last_thz is not None and raw_dt > 0:
            rate = (thz - self.last_thz) * 1e6 / raw_dt
            a = raw_dt / (s.d_filter_s + raw_dt) if s.d_filter_s > 0 else 1.0
            self.rate += a * (rate - self.rate)
        self.last_t, self.last_thz = t, thz
        direction = -1.0 if s.sign >= 0 else 1.0
        p = direction * s.kp * err
        self.d_term = direction * s.kd * self.rate
        self.integral += direction * s.ki * err * dt
        wanted = self.integral + p + self.d_term
        out = min(max(wanted, self.voltage - s.max_step), self.voltage + s.max_step)
        out = min(max(out, s.v_min), s.v_max)
        state = "locked"
        if out != wanted:
            self.integral = out - p - self.d_term
            state = "limited"
        self.voltage = out
        return Step(out, err, state)


PIDLock = PILock


def suggest_gains(mhz_per_v: float, update_s: float) -> tuple[int, float, float]:
    """Sign, kp and ki from the tuning slope and the wavemeter's update period.

    P corrects a fifth of an error per update; I closes it with a time constant of about ten updates (at
    least 1 s), well inside the wavemeter's delay of about one update."""
    k = abs(mhz_per_v)
    if k == 0:
        raise ValueError("no tuning slope")
    tau = max(1.0, 10 * update_s)
    return (1 if mhz_per_v > 0 else -1), 0.2 / k, 1.0 / (k * tau)


@dataclass(frozen=True)
class Hop:
    t: float  # when the first reading at the new level came
    from_thz: float
    to_thz: float

    @property
    def jump_mhz(self) -> float:
        return (self.to_thz - self.from_thz) * 1e6


class HopDetector:
    """Finds mode hops in the stream of readings.

    A hop is a jump of at least `min_jump_mhz` from the current level that holds for `confirm` readings in a
    row (all within `min_jump_mhz` of each other) and for at least `min_hold_s`. A lone far reading (the WS8
    gives occasional ones about 19.7 GHz off), or a few lasting under `min_hold_s` (at a 5 ms exposure, three
    readings are 15 ms; the WS8 gave 60 GHz glitches of ~0.1 s, 2026-11-12), is not a hop. The level follows
    slow drift (a running average of readings near it)."""

    def __init__(self, min_jump_mhz: float = 300.0, confirm: int = 3, follow: float = 0.1,
                 min_hold_s: float = 0.2) -> None:
        self.min_jump_mhz, self.confirm, self.follow, self.min_hold_s = min_jump_mhz, confirm, follow, min_hold_s
        self.level: float | None = None
        self._pending: list[tuple[float, float]] = []

    def reset(self) -> None:
        self.level = None
        self._pending = []

    def update(self, thz: float | None, t: float) -> Hop | None:
        if thz is None:
            return None
        if self.level is None:
            self.level = thz
            return None
        jump = self.min_jump_mhz * 1e-6
        if abs(thz - self.level) < jump:
            self.level += self.follow * (thz - self.level)
            self._pending = []
            return None
        if self._pending and abs(thz - self._pending[0][1]) >= jump:
            self._pending = []  # far, but not where the previous far readings were: start again
        self._pending.append((t, thz))
        if len(self._pending) < self.confirm or t - self._pending[0][0] < self.min_hold_s:
            return None
        values = sorted(f for _, f in self._pending)
        new = values[len(values) // 2]
        hop = Hop(self._pending[0][0], self.level, new)
        self.level, self._pending = new, []
        return hop
