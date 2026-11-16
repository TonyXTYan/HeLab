"""The review's eight probes (its new_findings_probes.py and previous_findings_probes.py), run against the fixed
code: each prints what it now finds. Fake devices and temporary folders only, as the originals.

    PYTHONPATH=.:<a folder with pyvisa, for laserlock> venv/bin/python <this file>      (from the checkout's root)
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "side_projects" / "laserlock"))
from laserlock.controller import LockSettings  # noqa: E402
from laserlock.devices import Reading  # noqa: E402
from laserlock.engine import Engine  # noqa: E402

F0 = 276.732


class Source:
    def __init__(self):
        self.seq = 0

    def read(self):
        self.seq += 1
        return Reading(self.seq * 0.01, F0 - 100e-6, "ok", self.seq)


class Output:
    min_interval = 0.1

    def __init__(self):
        self.volts = 3.0
        self.writes = []

    def get(self):
        return self.volts

    def set(self, voltage):
        self.volts = voltage
        self.writes.append(voltage)
        return voltage


def make():
    out = Output()
    engine = Engine(Source(), out, LockSettings(setpoint_thz=F0, kp=0.001, ki=0.1, v_min=0, v_max=7, max_step=0.01))
    engine.engage()
    return engine, out


# N1: release while a correction waits for the output device's next slot.
engine, out = make()
engine._last_cmd = 1e12  # the slot isn't open
engine._tick()
engine._flush_output()
waiting = engine._target
engine.release()
engine._last_cmd = 0.0  # it opens
engine._flush_output()
assert waiting is not None and engine.snapshot().mode == "idle" and not out.writes and out.volts == 3.0
print(f"N1 not reproduced: the {waiting:.4f} V correction that waited is withdrawn by Release; the output stays "
      f"{out.volts:.4f} V ({engine.snapshot().message})")

# N2: readings arrive faster than writes.
engine, out = make()
engine._last_cmd = 1e12
for _ in range(10):
    engine._tick()
    engine._flush_output()
assert not out.writes
engine._last_cmd = 0.0
engine._flush_output()
assert abs(out.volts - 3 - 0.01) < 1e-9
print(f"N2 not reproduced: ten readings before one write move the output {out.volts - 3:.4f} V with max_step=0.0100 V")

# N3: the hold with its collection seam returning nothing.
engine, out = make()
with patch.object(engine, "_collect", return_value=[]):
    result = engine._hold_test(0.005, F0, 100)
assert result is not None
print(f"N3 not reproduced: a hold with no readings fails: {result!r}")

with tempfile.TemporaryDirectory(prefix="helab-review-") as temporary:
    root = Path(temporary)
    for name, subdir in (("HELAB_APP_DIR_OVERRIDE", "app"), ("HELAB_DIR_CACHES_OVERRIDE", "cache"),
                         ("HELAB_DIR_TEMPS_OVERRIDE", "temps")):
        os.environ[name] = str(root / subdir)
    import numpy as np
    from helab.analysis.histogram2d import cell_edges, cell_mean, display_shape
    from helab.updates import updater as u
    from helab.utils.cache_locks import take_running, update_in_progress

    def job_at(base):
        base.mkdir()
        venv = base / "venv"
        venv.mkdir()
        (venv / "original").touch()
        return u.Job("12345678", u.UPDATE, base, venv, base / "app", 1, u.BRANCH, "TonyXTYan/HeLab", "main", "",
                     "a" * 40, False, ["git"], [], "python", [], {"helab": 5, "others": 1, "started": 5, "ready": 5})

    # R1: the last rename fails, after the current venv has already moved.
    job = job_at(root / "swap")
    new = Path(str(job.venv) + ".new")
    new.mkdir()
    log = u.Log(job.updates / "probe.log")
    real_rename = u._rename

    def failing_rename(source, destination, logger):
        if source == new:
            raise OSError("injected failure installing the new venv")
        real_rename(source, destination, logger)
    try:
        with patch.object(u, "_rename", failing_rename):
            u.swap_in(job, new, log)
    except OSError:
        u.rollback(job, u.Plan(), False, False, None, {}, log)
    assert (job.venv / "original").exists() and not Path(str(job.venv) + ".previous").exists()
    print("R1 not reproduced: the failed swap undid its first rename; the venv is the original, nothing is stranded")

    # R2: a HeLab takes running.lock while build_venv runs.
    job = job_at(root / "race")
    log = u.Log(job.updates / "probe.log")
    locks, seen, swapped = [], [], []
    found = u.Plan(previous="b" * 40, previous_branch="main", target="a" * 40, rebuild=True)

    def build(j, commit, logger):
        seen.append(update_in_progress(str(j.app_dir)))  # what a HeLab starting now finds
        lock, _ = take_running(str(j.app_dir))  # one that ignores it, and stays
        locks.append(lock)
        made = Path(str(j.venv) + ".new")
        made.mkdir()
        return made
    with patch.object(u, "ProcessHandle"), patch.object(u, "wait_for_helab"), patch.object(u, "plan", return_value=found), \
         patch.object(u, "move_code"), patch.object(u, "move_code_back"), patch.object(u, "build_venv", build), \
         patch.object(u, "swap_in", lambda *a: swapped.append(a)), patch.object(u, "relaunch"), \
         patch.object(u, "running_from", return_value=[]):
        code = u.update(job, log)
    for lock in locks:
        lock.unlock()
    assert seen == [True] and code == 1 and not swapped and not update_in_progress(str(job.app_dir))
    print("R2 not reproduced: a start during the build finds update.lock held and stops; with running.lock held "
          f"all the same, the updater swaps nothing ({u.read_json(job.updates / 'last.json')['reason'][:60]}…)")

    # R3: 2,049 bins drawn as 1,025 cells.
    shape = (2049, 4)
    drawn = display_shape(shape)
    edges = cell_edges(np.arange(shape[0] + 1, dtype=float), drawn[0])
    raster = np.linspace(0, shape[0], drawn[0] + 1)
    image = np.zeros(shape)
    image[-1, 0] = 1.0
    cells = cell_mean(image, drawn)
    assert np.allclose(edges, raster) and cells[-1, 0] > 0 and edges[-2] <= 2048
    print(f"R3 not reproduced: the last drawn cell starts at {edges[-2]:.6f}, where the even raster puts it "
          f"({raster[-2]:.6f}), and holds the last bin")

    # R4: the estimate for four planes of 10,000 bins.
    from helab.scripts.standard_v2.plane_projections import PlaneProjections
    estimate = PlaneProjections().estimated_bytes("", {"panel_bins": 10000, "plane1_on": True, "plane2_on": True,
                                                       "plane3_on": True, "plane4_on": True})
    assert estimate > 3_200_000_000
    print(f"R4 not reproduced: Plane projections estimates {estimate / 1e9:.2f} GB for four planes of 10,000 bins")

    # R5: the stuck teardown, with this interpreter.
    import ast
    import subprocess
    module = ast.parse((ROOT / "tests" / "test_quit_confirms.py").read_text())
    script = next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "STUCK_TEARDOWN" for t in n.targets))
    folder = root / "teardown"
    folder.mkdir()
    done = subprocess.run([sys.executable, "-c", script, str(folder)], capture_output=True, text=True, timeout=60,
                          cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)})
    crash = Path(done.stdout.strip().splitlines()[0]).read_text()
    assert done.returncode == 1 and "__del__" in crash
    print(f"R5 not reproduced on Python {sys.version.split()[0]}: the timer's crash file names the stuck __del__")
