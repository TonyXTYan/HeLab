"""Build the TXY converter's compiled backends for the running Python.

    python native/build.py [--only cython|rust] [--force]
    python native/build.py --out DIR          # build both, save the kernel and the wheel in DIR
    python native/build.py --ci [--prebuilt DIR]

- ``cython``: ``native/cython/build.py`` compiles ``_kernel.pyx`` in place as
  ``helab/convert/backends/cython/_kernel<EXT_SUFFIX>`` (needs Cython, setuptools and a C
  compiler: Xcode's clang, GCC or clang, MSVC from VS 2022 17.0 or later).
- ``rust``: maturin builds ``native/rust/`` as an abi3 wheel (``helab-convert-rs``, one per OS and
  architecture for CPython 3.11 and later) and pip installs it into this Python (needs maturin and
  a Rust toolchain; MSVC's on Windows).

Both are part of HeLab's build (Q9.2), not of ``pip install -e .``: HeLab and its tests work
without them, so a lab PC with no compiler can still install it. CI runs ``--ci`` before the tests
and before PyInstaller (``.github/workflows/``): both built, ``HELAB_REQUIRE_BACKENDS`` set for the
later steps, and ``native/check_build.py`` checking every backend against the reference. The test
job takes what a build job of its own made with ``--out`` (``--prebuilt``: the kernel copied into
place, the wheel installed), so it doesn't pay for the compilers. Nothing it builds is committed.
The flags that keep the doubles exact (no FMA contraction, no fast-math, no ``target-cpu=native``)
are in the two builds' own files.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUST = HERE / "rust" / "Cargo.toml"
TARGETS = ("cython", "rust")
KERNEL = ROOT / "helab" / "convert" / "backends" / "cython" / f"_kernel{sysconfig.get_config_var('EXT_SUFFIX')}"


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def build_cython(force: bool) -> None:
    run([sys.executable, str(HERE / "cython" / "build.py"), *(["--force"] if force else [])])


def rust_wheel(out: Path) -> Path:
    """maturin's abi3 wheel of ``native/rust/``, built into ``out``."""
    if "target-cpu" in os.environ.get("RUSTFLAGS", ""):
        # The lab's Windows PC is a Sandy Bridge (no AVX2): a wheel for this CPU only won't load there.
        raise SystemExit("RUSTFLAGS sets target-cpu; build for the default target instead")
    # maturin's own entry point is a binary beside this Python's scripts; the module form finds it
    # from any shell, activated or not.
    run([sys.executable, "-m", "maturin", "build", "--release", "-m", str(RUST), "--out", str(out),
         "--interpreter", sys.executable])
    return one_wheel(out)


def one_wheel(folder: Path) -> Path:
    wheels = sorted(folder.glob("helab_convert_rs-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one helab_convert_rs wheel in {folder}, found {[wheel.name for wheel in wheels]}")
    return wheels[0]


def install_wheel(wheel: Path) -> None:
    install = [sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", str(wheel)]
    if subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True).returncode != 0:
        uv = shutil.which("uv")  # a venv made by uv without --seed has no pip
        if uv is None:
            raise SystemExit("neither pip nor uv can install the rust wheel into this Python")
        install = [uv, "pip", "install", "--python", sys.executable, "--no-deps", "--reinstall", str(wheel)]
    run(install)


def build_rust() -> None:
    with tempfile.TemporaryDirectory(prefix="helab-rust-wheel-") as out:
        install_wheel(rust_wheel(Path(out)))


def save(out: Path) -> None:
    """Build both into ``out`` (the kernel for this Python's version, the wheel), installing neither."""
    for tool in (["rustc", "--version"], ["cargo", "--version"]):
        run(tool)
    out.mkdir(parents=True, exist_ok=True)
    build_cython(force=True)
    shutil.copy2(KERNEL, out / KERNEL.name)
    rust_wheel(out)
    print(f"saved {', '.join(sorted(path.name for path in out.iterdir()))} in {out}", flush=True)


def install_prebuilt(folder: Path) -> None:
    """What ``save`` made, for this Python: the kernel copied into place, the wheel installed."""
    kernel = folder / KERNEL.name
    if not kernel.is_file():
        raise SystemExit(f"no {KERNEL.name} in {folder} (built for another Python?): "
                         f"{sorted(path.name for path in folder.iterdir())}")
    shutil.copy2(kernel, KERNEL)
    print(f"+ copied {kernel} -> {KERNEL.relative_to(ROOT)}", flush=True)
    install_wheel(one_wheel(folder))


def ci_required() -> list[str]:
    """The backends a CI job must have: the compiled ones and numba everywhere, mlx where Metal is
    (GitHub's macOS runners are VMs that may have none: then its GPU tests skip with the reason)."""
    required = ["cython", "rust", "numba"]
    if sys.platform == "darwin":
        probe = subprocess.run([sys.executable, "-c", "import mlx.core as mx; print(mx.metal.is_available())"],
                               capture_output=True, text=True)
        metal = probe.stdout.strip() if probe.returncode == 0 else (probe.stderr.strip().splitlines() or ["?"])[-1]
        print(f"mx.metal.is_available(): {metal}", flush=True)
        if metal == "True":
            required.append("mlx")
        else:
            print(f"::notice title=mlx not required::No Metal on this runner (mx.metal.is_available(): {metal}): "
                  "the mlx backend's GPU tests skip with the reason", flush=True)
    return required


def ci(prebuilt: Path | None) -> None:
    """CI: build both (or install ``prebuilt``'s), require the backends (``HELAB_REQUIRE_BACKENDS``
    for the later steps, as the tests read it) and check each against the reference."""
    if prebuilt is not None:
        install_prebuilt(prebuilt)
    else:
        for tool in (["rustc", "--version"], ["cargo", "--version"]):
            run(tool)
        build_cython(force=True)
        build_rust()
    required = ",".join(ci_required())
    print(f"Required converter backends: {required}", flush=True)
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as file:
            file.write(f"HELAB_REQUIRE_BACKENDS={required}\n")
    run([sys.executable, str(HERE / "check_build.py"), "--require", required])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=TARGETS, action="append", help="build only this one (repeatable)")
    parser.add_argument("--force", action="store_true", help="rebuild the cython kernel even when up to date")
    parser.add_argument("--ci", action="store_true",
                        help="CI: build both, set HELAB_REQUIRE_BACKENDS in $GITHUB_ENV, run check_build.py")
    parser.add_argument("--prebuilt", metavar="DIR", type=Path,
                        help="with --ci: install what --out saved in DIR instead of building")
    parser.add_argument("--out", metavar="DIR", type=Path,
                        help="build both and save the cython kernel and the rust wheel in DIR, installing neither")
    args = parser.parse_args()
    if args.prebuilt is not None and not args.ci:
        parser.error("--prebuilt goes with --ci")
    if args.ci:
        ci(args.prebuilt)
        return 0
    if args.out is not None:
        save(args.out)
        return 0
    targets = args.only or list(TARGETS)
    if "cython" in targets:
        build_cython(args.force)
    if "rust" in targets:
        build_rust()  # cargo rebuilds only what changed
    return 0


if __name__ == "__main__":
    sys.exit(main())
