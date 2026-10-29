"""Check that every converter backend gives the reference's bytes on ``tests/data/convert/``.

    python native/check_build.py [--require cython]
    python native/check_build.py --frozen dist/HeLab/HeLab [--require …]

Every case of ``tests/data/convert/cases/`` under both built-in profiles, each backend against
``reference``: the TXY bytes (``pipeline.convert_shot``), or the same error. A backend that says it
can't run here (``unavailable``, or "can't run" from a packaged app) is listed with its reason;
one named in ``--require`` (default: the ``HELAB_REQUIRE_BACKENDS`` variable, as the tests read
it) fails the check, and so do ``reference`` and ``numpy``, which are always required. A
difference fails, and so does a crash (a check that raises, or a packaged run that fails for any
other reason). Exit 0 when every backend that runs matches, 1 otherwise.

``--frozen APP`` runs a packaged HeLab instead (``APP convert --watch … --once --output temp``,
one run per backend and profile, in a scratch folder with its own app, cache, temp folders and
settings file), so the check covers what PyInstaller collected: the backend modules and cython's
compiled kernel (numba, mlx and rust's module don't ship, A9.1: unavailable there, with the reason).
The expected bytes still come from this Python's reference.

Run it from the checkout (it reads the cases there). It sets HeLab's folder overrides to a scratch
folder before importing helab, as any script outside pytest must.
"""
from __future__ import annotations

import argparse
import glob
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import NamedTuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CASES = ROOT / "tests" / "data" / "convert" / "cases"
PROFILES = ("matlab-2019", "matlab-2023-lab-edit")
FROZEN_TIMEOUT = 600.0  # seconds per packaged run

FOLDERS = (("HELAB_APP_DIR_OVERRIDE", "app"), ("HELAB_DIR_CACHES_OVERRIDE", "caches"),
           ("HELAB_DIR_TEMPS_OVERRIDE", "temps"))


def isolate() -> Path:
    """A scratch folder, and HeLab's folders and settings file in it unless already set: before
    helab is imported (``main`` only; a test's own conftest has set them)."""
    scratch = Path(tempfile.mkdtemp(prefix="helab-check-build-"))
    for variable, name in FOLDERS:
        os.environ.setdefault(variable, str(scratch / name))
    os.environ.setdefault("HELAB_TEST_SETTINGS_FILE", str(scratch / "settings.ini"))
    sys.path.insert(0, str(ROOT))
    return scratch


class Case(NamedTuple):
    shot: int
    name: str
    data: bytes


def cases() -> list[Case]:
    names = sorted(path.name for path in CASES.iterdir() if (path / "d1.txt").is_file())
    return [Case(shot, name, (CASES / name / "d1.txt").read_bytes()) for shot, name in enumerate(names, 1)]


def outcome(data: bytes, profile: str, backend: str) -> bytes | str:
    """The TXY bytes HeLab writes for this shot, or the error's type (no TXY)."""
    from helab.convert.pipeline import convert_shot
    from helab.convert.profile import BUILTIN_PROFILES
    try:
        return convert_shot(data, BUILTIN_PROFILES[profile], backend).txy
    except Exception as error:  # the same error as the reference's is a match
        return type(error).__name__


def required(option: str | None) -> list[str]:
    text = os.environ.get("HELAB_REQUIRE_BACKENDS", "") if option is None else option
    return [name.strip() for name in text.split(",") if name.strip()]


def check_here(all_cases: list[Case]) -> dict[str, str | None]:
    """Each backend's problem in this Python (None: matches the reference on every case)."""
    from helab.convert.reconstruct import _MODULES, get_backend
    expected = {(case.shot, profile): outcome(case.data, profile, "reference")
                for case in all_cases for profile in PROFILES}
    results: dict[str, str | None] = {}
    # The reference is what the others are held to: it must run and convert the shots that have rows.
    converted = sum(isinstance(value, bytes) for value in expected.values())
    results["reference"] = (None if converted >= len(expected) // 2 else
                            f"failed: the reference converted only {converted} of {len(expected)}")
    for backend in _MODULES:
        if backend == "reference":
            continue
        try:
            why = get_backend(backend).unavailable(None)
        except Exception as error:  # unavailable() never raises: one that does is broken
            results[backend] = f"failed: unavailable() raised {type(error).__name__}: {error}"
            continue
        if why is not None:
            results[backend] = f"unavailable: {why}"
            continue
        differ = [f"{case.name} ({profile})" for case in all_cases for profile in PROFILES
                  if outcome(case.data, profile, backend) != expected[(case.shot, profile)]]
        results[backend] = f"differs on {', '.join(differ)}" if differ else None
    return results


def frozen_run(app: str, folder: Path, backend: str, profile: str, work: Path) -> tuple[int, str]:
    """One packaged ``convert --once`` with folders of its own; (exit code, its output and log)."""
    env = dict(os.environ)
    for variable, name in FOLDERS:
        env[variable] = str(work / name)
    env["HELAB_TEST_SETTINGS_FILE"] = str(work / "settings.ini")
    command = [app, "convert", "--watch", str(folder), "--once", "--backend", backend, "--profile", profile,
               "--output", "temp", "--workers", "1"]
    try:
        finished = subprocess.run(command, env=env, capture_output=True, text=True, errors="replace",
                                  timeout=FROZEN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return -1, f"timed out after {FROZEN_TIMEOUT:.0f} s"
    # The windowed Windows exe has no console: its lines are only in the log.
    logs = "".join(Path(log).read_text(errors="replace") for log in sorted(glob.glob(str(work / "app" / "logs" / "*.log"))))
    return finished.returncode, finished.stdout + finished.stderr + logs


def check_frozen(app: str, all_cases: list[Case], scratch: Path) -> dict[str, str | None]:
    from helab.convert.profile import BUILTIN_PROFILES
    from helab.convert.raw import not_done
    from helab.convert.reconstruct import _MODULES
    folder = scratch / "raw"
    folder.mkdir()
    settled = time.time() - 600  # --once converts files unmodified for a minute
    for case in all_cases:
        path = folder / f"d{case.shot}.txt"
        path.write_bytes(case.data)
        os.utime(path, (settled, settled))
    results: dict[str, str | None] = {}
    for backend in _MODULES:
        problems: list[str] = []
        for profile in PROFILES:
            work = scratch / f"run-{backend}-{profile}"
            started = time.perf_counter()
            code, text = frozen_run(app, folder, backend, profile, work)
            print(f"  {backend} {profile}: exit {code} ({time.perf_counter() - started:.1f} s)", flush=True)
            if code != 0:
                # "Backend 'x' can't run: …" (BackendError) is the backend saying why; anything else
                # (a crash, a missing module, a timeout) is a failure even for an optional backend.
                said = [line for line in text.splitlines() if f"Backend '{backend}' can't run:" in line]
                lines = said or [line for line in text.splitlines() if "ERROR" in line or "Traceback" in line]
                kind = "unavailable" if said else "failed"
                problems.append(f"{kind}: exit {code}: {lines[-1] if lines else text[-800:]}")
                break
            differ = []
            for case in all_cases:
                written = glob.glob(str(work / "temps" / "converted-txy" / "*" / f"d_txy_helab_{case.shot}.txy"))
                ours: bytes | str = Path(written[0]).read_bytes() if len(written) == 1 else f"{len(written)} TXY"
                theirs = outcome(case.data, profile, "reference")
                if isinstance(theirs, str) or not_done(case.data, BUILTIN_PROFILES[profile].channel_trigger):
                    # An error (the shot is unconvertible), or a file HeLab takes for one still being
                    # written (it waits): no TXY.
                    theirs = "0 TXY"
                if ours != theirs:
                    differ.append(f"{case.name} ({profile})")
            if differ:
                problems.append(f"differs on {', '.join(differ)}")
        results[backend] = "; ".join(problems) or None
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--require", help="backends that must run, comma-separated (default: $HELAB_REQUIRE_BACKENDS)")
    parser.add_argument("--frozen", metavar="APP", help="a packaged HeLab's executable to check instead")
    parser.add_argument("--keep", action="store_true", help="keep the scratch folder (its path is printed)")
    args = parser.parse_args()
    scratch = isolate()
    must = sorted({"reference", "numpy", *required(args.require)})  # these two always run
    all_cases = cases()
    where = f"packaged {args.frozen}" if args.frozen else sys.executable
    print(f"{len(all_cases)} cases x {len(PROFILES)} profiles, each backend against reference ({where}; "
          f"scratch {scratch})")
    try:
        results = check_frozen(args.frozen, all_cases, scratch) if args.frozen else check_here(all_cases)
    finally:
        if not args.keep:
            shutil.rmtree(scratch, ignore_errors=True)
    failed = False
    for backend, problem in results.items():
        if problem is None:
            print(f"{backend}: identical on all {len(all_cases) * len(PROFILES)}")
            continue
        unavailable = problem.startswith("unavailable")
        bad = not unavailable or backend in must
        failed |= bad
        print(f"{backend}: {problem}{'  <- FAIL' if bad else ''}")
    from helab.convert.reconstruct import _MODULES
    unknown = [name for name in must if name not in _MODULES]
    if unknown:
        print(f"--require names unknown backends: {', '.join(unknown)}  <- FAIL")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
